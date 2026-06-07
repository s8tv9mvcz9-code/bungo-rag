"""
rag.py — RAG コア（検索 + ストリーミング生成）
"""
import os
from typing import Iterator, List
from dotenv import load_dotenv
from openai import AzureOpenAI, OpenAI
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

def _chat_client():
    if "openai.azure.com" in CHAT_ENDPOINT:
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
SYSTEM_PROMPT = """あなたは旧字旧仮名の文語体で作文・変換する専門家です。
あなた自身の知識と能力が生成の主体であり、参照例はあくまで文体調整のヒントにすぎません。

【最重要ルール】
- 返答の冒頭から、即座に旧字旧仮名の文語体で書いた「結果」を出力すること
- 「変換します」「以下に示します」などの前置きは一切不要
- 変換・作文した文章そのものから始めよ
- 末尾にのみ【ポイント】として解説を3点以内で添えてよい

【生成の主体はあなた自身】
- ユーザーの依頼に対する回答はすべてあなた自身の言葉で独自に生成すること
- 参照例として青空文庫の断片が提示されるが、それは語彙・文末表現・リズムの傾向を掴むためだけに使う
- 参照例の文・フレーズ・内容を転用・引用・再構成してはならない
- 参照例に似た内容であっても、表現は完全に自分で作ること

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
def search_chunks(query: str, top: int = 5) -> List[dict]:
    """ハイブリッド検索でコンテキストチャンクを取得"""
    resp = embed_client.embeddings.create(
        input=[query], model=EMBED_DEPLOYMENT
    )
    vec = resp.data[0].embedding

    results = search_client.search(
        search_text=query,
        vector_queries=[VectorizedQuery(
            vector=vec, k_nearest_neighbors=top * 2, fields="embedding"
        )],
        select=["text", "title", "author", "style"],
        top=top,
    )
    return [dict(r) for r in results]

def format_context(chunks: List[dict]) -> str:
    # 文体パターン把握には冒頭120字で十分。全文渡しはコピー誘発の原因になるため短縮する
    return "\n\n".join(
        f"▷ {c['title']} / {c['author']}（{c.get('style','')}）\n"
        f"{c['text'][:120]}{'…' if len(c['text']) > 120 else ''}"
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

    augmented_user = (
        f"【文体参照例（語彙・文末・リズムの傾向把握のみに使うこと。内容・フレーズの転用禁止）】\n"
        f"{context}\n\n"
        f"---\n"
        f"上記は文体の傾向を掴むためだけの参考例である。内容はあなた自身の言葉で完全に新たに生成せよ。"
        f"前置きは不要。変換・作文した文章そのものから書き始めよ。\n\n"
        f"{user_message}"
    )

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    # 直近4ターンの会話履歴を追加（コンテキスト節約）
    messages.extend(history[-8:])
    messages.append({"role": "user", "content": augmented_user})

    client = _chat_client()
    stream = client.chat.completions.create(
        model=CHAT_DEPLOYMENT,
        messages=messages,
        temperature=0.85,
        max_tokens=1200,
        stream=True,
    )

    def token_gen():
        for chunk in stream:
            delta = chunk.choices[0].delta.content if chunk.choices else None
            if delta:
                yield delta

    return token_gen(), chunks
