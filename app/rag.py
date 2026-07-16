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
# 検索クエリ整形・手本の多様化（rag.py と scripts/query.py の共有純関数）
from retrieval import search_query, diversify
# 共感覚レイヤー: 文 → 情調 → 日本の伝統色（純関数・LLM不使用）
from synesthesia import estimate_palette

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
  ※ 候文（〜にて候）と和文文語（〜なり／〜べし）を一つの文章内で混在させず、文体を統一すること
語彙:
  でも→されど、だから→されば、とても→いとも、そして→かくして

【動作別ルール】
・現代文が来たら → その文を旧字旧仮名に全文変換して出力
・テーマ指定が来たら → そのテーマで旧字旧仮名の文章を作文して出力
・添削依頼が来たら → 正しい旧字旧仮名に整えて出力
・質問が来たら → 答えを旧字旧仮名で書いて出力

【出力例】
入力:「今日はいい天気です。散歩に行きたいです。」
出力:「今日は麗しき天氣なり。散歩に出でむとぞ思ふ。
【ポイント】①いい天気→麗しき天氣 ②行きたい→出でむ ③文末を「なり」で統一（候文と混ぜない）」

入力:「春について短い文章を書いて」
出力:「冬の名殘の風もやうやく和らぎて、梅が枝に鶯の初音を聞くころとなりぬ。
日ごとに光うらうらとして、野山の色づきゆくさま、まことに心樂しきものなり。
【ポイント】①「やうやく」は歴史的仮名遣ひ ②旧字体「殘・氣・樂」を用ゐる ③文末を「なり」で統一」"""

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

    # 旧字旧仮名を優先しつつ 1作品 MAX_PER_BOOK 件までに間引く（共有ロジック）。
    # 旧字新仮名（現代仮名）の手本が仮名遣ひの誤りを教へるのを避ける。
    return diversify([dict(r) for r in results], top=top, max_per_book=MAX_PER_BOOK)

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
    synesthesia: bool = True,
) -> tuple[Iterator[str], List[dict], dict | None]:
    """
    Returns:
        (token_stream, source_chunks, palette)
        palette は共感覚パレット（synesthesia.py 参照）。synesthesia=False なら None。
    """
    # 検索は変換指示語を除いた「内容」で引く（生成には下の augmented_user でフル原文を渡す）
    chunks = search_chunks(search_query(user_message), top=top)
    context = format_context(chunks)

    # 共感覚: 入力文と手本の情調を伝統色に写像。信号が弱ければ hint は None。
    palette = None
    if synesthesia:
        palette = estimate_palette(user_message, [c.get("text", "") for c in chunks])
        # 各手本チャンクに色を付与（sources 表示用。追加キーはクライアント側で無害）
        for c, sc in zip(chunks, palette.pop("sources")):
            c["color"], c["color_name"] = sc["hex"], sc["name"]

    hint_line = f"{palette['hint']}\n" if palette and palette.get("hint") else ""
    augmented_user = (
        f"【文体参照例（語彙・文末・リズムの傾向把握のみに使うこと。内容・フレーズの転用禁止）】\n"
        f"{context}\n\n"
        f"---\n"
        f"上記は文体の傾向を掴むためだけの参考例である。内容はあなた自身の言葉で完全に新たに生成せよ。"
        f"前置きは不要。変換・作文した文章そのものから書き始めよ。\n"
        f"{hint_line}\n"
        f"{user_message}"
    )

    # 直近4ターンの会話履歴 + 今回のユーザー発話（system は含めない）
    convo = history[-8:] + [{"role": "user", "content": augmented_user}]

    if _chat_provider() == "anthropic":
        token_gen = _stream_anthropic(convo)
    else:
        token_gen = _stream_openai(convo)

    return token_gen, chunks, palette

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
        max_tokens=2000,
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
        temperature=0.85,
        max_tokens=2000,
        stream=True,
    )
    for chunk in stream:
        delta = chunk.choices[0].delta.content if chunk.choices else None
        if delta:
            yield delta
