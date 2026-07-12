"""
rag.py — RAG コア（検索 + ストリーミング生成）
"""
import os
from typing import Iterator, List
from dotenv import load_dotenv
from openai import AzureOpenAI, OpenAI
from anthropic import Anthropic
from azure.search.documents import SearchClient
from azure.search.documents.models import VectorizedQuery
from azure.core.credentials import AzureKeyCredential

# .env を自分のパス基準でロード（app.py より先にインポートされるため）
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

# ── 設定 ────────────────────────────────────────────────
SEARCH_ENDPOINT  = os.environ["AZURE_SEARCH_ENDPOINT"]
SEARCH_KEY       = os.environ["AZURE_SEARCH_ADMIN_KEY"]
INDEX_NAME       = os.environ.get("SEARCH_INDEX_NAME", "bungo-chunks")

EMBED_ENDPOINT   = os.environ["AZURE_OPENAI_ENDPOINT"]
EMBED_KEY        = os.environ["AZURE_OPENAI_API_KEY"]
EMBED_DEPLOYMENT = os.environ.get("EMBED_DEPLOYMENT", "text-embedding-3-small")

CHAT_ENDPOINT    = os.environ.get("CHAT_ENDPOINT", "")
CHAT_KEY         = os.environ.get("CHAT_API_KEY", "")
CHAT_DEPLOYMENT  = os.environ.get("CHAT_DEPLOYMENT", "")

# ── クライアント ─────────────────────────────────────────
embed_client = AzureOpenAI(
    azure_endpoint=EMBED_ENDPOINT,
    api_key=EMBED_KEY,
    api_version="2024-02-01",
)

# チャットのプロバイダを CHAT_ENDPOINT から自動判定する
#   ・"anthropic" を含む   → Azure AI Foundry の Claude（Anthropic Messages API）
#   ・"openai.azure.com"   → Azure OpenAI
#   ・それ以外             → OpenAI 互換（GitHub Models / MaaS 等）
def _chat_provider() -> str:
    ep = CHAT_ENDPOINT.lower()
    if "anthropic" in ep:
        return "anthropic"
    if "openai.azure.com" in ep:
        return "azure_openai"
    return "openai"

def _chat_client():
    """OpenAI 系プロバイダ（Azure OpenAI / OpenAI 互換）用のクライアント"""
    if _chat_provider() == "azure_openai":
        return AzureOpenAI(
            azure_endpoint=CHAT_ENDPOINT,
            api_key=CHAT_KEY,
            api_version="2024-02-01",
        )
    return OpenAI(base_url=CHAT_ENDPOINT, api_key=CHAT_KEY)

search_client = SearchClient(
    endpoint=SEARCH_ENDPOINT,
    index_name=INDEX_NAME,
    credential=AzureKeyCredential(SEARCH_KEY),
)

# ── システムプロンプト ────────────────────────────────────
SYSTEM_PROMPT = """あなたは旧字旧仮名の文語体に変換・作文する専門家です。

【最重要ルール】
- 返答の冒頭から、即座に旧字旧仮名の文語体で書いた「結果」を出力すること
- 「変換します」「以下に示します」などの前置きは一切不要
- 変換・作文した文章そのものから始めよ
- 末尾にのみ【ポイント】として解説を3点以内で添えてよい

【旧字旧仮名のルール（必ず守ること）】
仮名遣い:
  言う→言ふ、思う→思ふ、いる→ゐる、見える→見ゆる
  今日→けふ、そういう→さういふ、ようやく→やうやく
旧字体:
  国→國、学→學、会→會、体→體、気→氣、来→來
  発→發、関→關、様→樣、実→實、声→聲、読→讀
文末:
  〜なり、〜べし、〜たり、〜にて候、〜せり、〜けり
語彙:
  でも→されど、だから→されば、とても→いとも、そして→かくして

【動作別ルール】
・現代文が来たら → その文を旧字旧仮名に全文変換して出力
・テーマ指定が来たら → そのテーマで旧字旧仮名の文章を作文して出力
・添削依頼が来たら → 正しい旧字旧仮名に整えて出力
・質問が来たら → 答えを旧字旧仮名で書いて出力

【文体手本について】
毎回「文体手本」として青空文庫の実文章が提供される。
その語彙・文体・リズムを吸収して出力に活かすこと。転載は禁止。

【出力例】
入力:「今日はいい天気です。散歩に行きたいです。」
出力:「今日はよき御天氣にて候。散歩に出でたき心地のするものなり。
【ポイント】①いい→よき ②行きたい→出でたき ③です→にて候」

入力:「春について短い文章を書いて」
出力:「春はあけぼの。やうやう白くなりゆく山ぎは、霞たなびきて、
をりをりそよぐ風のぬるやかなること、いとをかし。
萬物の芽吹くこの季節、古よりひとびとの心を和らげたるも宜なりと言ふべし。
【ポイント】①「やうやう」は現代語「だんだん」②「をかし」は趣深いの意 ③文末「べし」で確信を表現」"""

# ── 検索 ────────────────────────────────────────────────
# 1作品から採用するチャンク数の上限。特定文献への「引っ張られ」を防ぎ、
# top-K を複数作品に分散させて多様な文体手本を集めるための多様性制約。
MAX_PER_BOOK = 2

def search_chunks(query: str, top: int = 5) -> List[dict]:
    """ハイブリッド検索でコンテキストチャンクを取得。

    候補を多めに取り、1作品あたり MAX_PER_BOOK 件までに間引いてから
    上位 top 件を返す。これにより検索結果が単一作品で占有されるのを防ぐ。"""
    resp = embed_client.embeddings.create(
        input=[query], model=EMBED_DEPLOYMENT
    )
    vec = resp.data[0].embedding

    # 多様性のため多めの候補を取得（間引き後に top 件へ絞る）
    candidate_top = max(top * 3, top)
    results = search_client.search(
        search_text=query,
        vector_queries=[VectorizedQuery(
            vector=vec, k_nearest_neighbors=candidate_top * 2, fields="embedding"
        )],
        select=["text", "title", "author", "style", "book_id"],
        top=candidate_top,
    )

    # 1作品 MAX_PER_BOOK 件までに間引く（Search はスコア降順で返す）
    picked: List[dict] = []
    per_book: dict = {}
    for r in results:
        d = dict(r)
        key = d.get("book_id") or d.get("title")
        if per_book.get(key, 0) >= MAX_PER_BOOK:
            continue
        per_book[key] = per_book.get(key, 0) + 1
        picked.append(d)
        if len(picked) >= top:
            break
    return picked

def format_context(chunks: List[dict]) -> str:
    return "\n\n---\n\n".join(
        f"【{c['title']} / {c['author']} ({c.get('style','')})】\n{c['text']}"
        for c in chunks
    )

# ── ストリーミング生成 ────────────────────────────────────
def stream_answer(
    user_message: str,
    history: List[dict],   # [{"role": "user"|"assistant", "content": str}, ...]
    top: int = 5,
) -> tuple[Iterator[str], List[dict]]:
    """
    Returns:
        (token_stream, source_chunks)
    """
    chunks = search_chunks(user_message, top=top)
    context = format_context(chunks)

    # RAG文脈を「文体手本」として明示し、今すぐ出力するよう命令する
    augmented_user = (
        f"【文体手本（青空文庫より）】\n"
        f"{context}\n\n"
        f"---\n"
        f"上記を文体の手本として参照し、以下をただちに旧字旧仮名の文語体に変換・作文して出力せよ。"
        f"前置きは不要。変換・作文した文章そのものから書き始めよ。\n\n"
        f"{user_message}"
    )

    # 直近4ターンの会話履歴 + 今回のユーザー発話（system は含めない）
    convo = history[-8:] + [{"role": "user", "content": augmented_user}]

    if _chat_provider() == "anthropic":
        token_gen = _stream_anthropic(convo)
    else:
        token_gen = _stream_openai(convo)

    return token_gen, chunks

# ── プロバイダ別ストリーミング ───────────────────────────
def _stream_anthropic(convo: List[dict]) -> Iterator[str]:
    """Azure AI Foundry の Claude（Anthropic Messages API）でストリーミング生成。
    system はトップレベル引数。temperature はこのモデルでは非対応のため送らない。

    Prompt Caching: 固定の SYSTEM_PROMPT（約1,500トークン）に cache_control を付け、
    2回目以降のリクエストでプロンプト前置き部分をキャッシュヒットさせる。
    入力トークンのコストと初回レイテンシを削減する（Foundry ではβ機能のため
    anthropic-beta ヘッダを付与）。"""
    client = Anthropic(base_url=CHAT_ENDPOINT, api_key=CHAT_KEY)
    with client.messages.stream(
        model=CHAT_DEPLOYMENT,
        max_tokens=1200,
        system=[{
            "type": "text",
            "text": SYSTEM_PROMPT,
            "cache_control": {"type": "ephemeral"},
        }],
        messages=convo,
        extra_headers={"anthropic-beta": "prompt-caching-2024-07-31"},
    ) as stream:
        for text in stream.text_stream:
            yield text

def _stream_openai(convo: List[dict]) -> Iterator[str]:
    """OpenAI 互換（Azure OpenAI / GitHub Models / MaaS）でストリーミング生成。"""
    client = _chat_client()
    messages = [{"role": "system", "content": SYSTEM_PROMPT}, *convo]
    stream = client.chat.completions.create(
        model=CHAT_DEPLOYMENT,
        messages=messages,
        temperature=0.75,
        max_tokens=1200,
        stream=True,
    )
    for chunk in stream:
        delta = chunk.choices[0].delta.content if chunk.choices else None
        if delta:
            yield delta
