"""
rag.py — RAG コア（検索 + ストリーミング生成）

プロバイダ非依存:
  埋め込み   … EMBED_ENDPOINT(OpenAI互換; GitHub Models等) または AZURE_OPENAI_*（後方互換）
  ベクトル検索 … VECTOR_BACKEND=local|azure|auto
                local: corpus/index.npz（ゼロコスト・Azure不要）
                azure: Azure AI Search（従来動作）
                auto(既定): ローカルインデックスがあれば local、なければ azure
  チャット生成 … CHAT_ENDPOINT(OpenAI互換; GitHub Models等) / Azure OpenAI 自動判別
"""
import os
from typing import Iterator, List
from dotenv import load_dotenv
from openai import AzureOpenAI, OpenAI

# .env を自分のパス基準でロード（app.py より先にインポートされるため）
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

# ── 設定（すべて遅延評価。ここでは KeyError を起こさない）──────
EMBED_DEPLOYMENT = os.environ.get("EMBED_DEPLOYMENT", "text-embedding-3-small")

CHAT_ENDPOINT    = os.environ.get("CHAT_ENDPOINT", "")
CHAT_KEY         = os.environ.get("CHAT_API_KEY", "")
CHAT_DEPLOYMENT  = os.environ.get("CHAT_DEPLOYMENT", "")

# ── クライアント（遅延初期化）────────────────────────────
_embed_client = None
_search_client = None


def _get_embed_client():
    """OpenAI互換(GitHub Models等) を優先し、Azure OpenAI に後方互換。"""
    global _embed_client
    if _embed_client is not None:
        return _embed_client
    generic_endpoint = os.environ.get("EMBED_ENDPOINT", "")
    if generic_endpoint:
        _embed_client = OpenAI(
            base_url=generic_endpoint,
            api_key=os.environ.get("EMBED_API_KEY")
            or os.environ.get("GITHUB_TOKEN", ""),
        )
    elif os.environ.get("AZURE_OPENAI_ENDPOINT"):
        _embed_client = AzureOpenAI(
            azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
            api_key=os.environ["AZURE_OPENAI_API_KEY"],
            api_version="2024-02-01",
        )
    else:
        raise RuntimeError(
            "埋め込みプロバイダ未設定: EMBED_ENDPOINT(+EMBED_API_KEY) か "
            "AZURE_OPENAI_ENDPOINT(+AZURE_OPENAI_API_KEY) を設定してください。"
        )
    return _embed_client


def _vector_backend() -> str:
    """local / azure を決定。auto はローカルインデックスの有無で判定。"""
    backend = os.environ.get("VECTOR_BACKEND", "auto").lower()
    if backend in ("local", "azure"):
        return backend
    from vector_store import index_exists
    if index_exists():
        return "local"
    if os.environ.get("AZURE_SEARCH_ENDPOINT"):
        return "azure"
    raise RuntimeError(
        "検索バックエンド未設定: corpus/index.npz を構築する"
        "（scripts/build_index.py）か、AZURE_SEARCH_ENDPOINT を設定してください。"
    )


def _get_search_client():
    """Azure AI Search クライアント（azure バックエンド時のみ生成・import）。"""
    global _search_client
    if _search_client is None:
        from azure.search.documents import SearchClient
        from azure.core.credentials import AzureKeyCredential
        _search_client = SearchClient(
            endpoint=os.environ["AZURE_SEARCH_ENDPOINT"],
            index_name=os.environ.get("SEARCH_INDEX_NAME", "bungo-chunks"),
            credential=AzureKeyCredential(os.environ["AZURE_SEARCH_ADMIN_KEY"]),
        )
    return _search_client


def _chat_client():
    if "openai.azure.com" in CHAT_ENDPOINT:
        return AzureOpenAI(
            azure_endpoint=CHAT_ENDPOINT,
            api_key=CHAT_KEY,
            api_version="2024-02-01",
        )
    return OpenAI(base_url=CHAT_ENDPOINT, api_key=CHAT_KEY)


_foundry_client_cached = None


def _chat_backend() -> str:
    """chat 生成のバックエンド: 'foundry'（Azure AI Foundry の Claude）/ 'openai'（OpenAI互換）。

    CHAT_BACKEND 未指定なら、Foundry リソースが設定されていれば foundry、なければ openai。
    """
    backend = os.environ.get("CHAT_BACKEND", "").lower()
    if backend in ("foundry", "anthropic", "claude"):
        return "foundry"
    if backend in ("openai", "azure", "compat"):
        return "openai"
    if os.environ.get("ANTHROPIC_FOUNDRY_RESOURCE") or os.environ.get("FOUNDRY_RESOURCE"):
        return "foundry"
    return "openai"


def _foundry_client():
    """Azure AI Foundry の Claude を叩く AnthropicFoundry クライアント（遅延生成）。

    認証:
      - 既定は API キー（ANTHROPIC_FOUNDRY_API_KEY または CHAT_API_KEY）
      - FOUNDRY_AUTH=entra で Microsoft Entra ID（キーレス、要 azure-identity）
    エンドポイントは resource から https://{resource}.services.ai.azure.com/anthropic/ が構築される。
    """
    global _foundry_client_cached
    if _foundry_client_cached is not None:
        return _foundry_client_cached
    from anthropic import AnthropicFoundry  # 遅延import（ゼロコスト経路に不要な依存を避ける）

    resource = os.environ.get("ANTHROPIC_FOUNDRY_RESOURCE") or os.environ.get("FOUNDRY_RESOURCE")
    if not resource:
        raise RuntimeError(
            "Foundry バックエンドには ANTHROPIC_FOUNDRY_RESOURCE（Foundry リソース名）が必要です。"
        )

    if os.environ.get("FOUNDRY_AUTH", "").lower() == "entra":
        from azure.identity import DefaultAzureCredential, get_bearer_token_provider
        token_provider = get_bearer_token_provider(
            DefaultAzureCredential(), "https://ai.azure.com/.default"
        )
        _foundry_client_cached = AnthropicFoundry(
            resource=resource, azure_ad_token_provider=token_provider
        )
    else:
        api_key = os.environ.get("ANTHROPIC_FOUNDRY_API_KEY") or CHAT_KEY
        if not api_key:
            raise RuntimeError(
                "Foundry の API キー未設定: ANTHROPIC_FOUNDRY_API_KEY か CHAT_API_KEY を設定"
                "（または FOUNDRY_AUTH=entra でキーレス認証）。"
            )
        _foundry_client_cached = AnthropicFoundry(api_key=api_key, resource=resource)
    return _foundry_client_cached


def _stream_foundry(augmented_user: str, history: List[dict]) -> Iterator[str]:
    """Claude（Azure AI Foundry）で Messages API ストリーミング生成。

    - Opus 4.8 は temperature/top_p を受け付けない（送ると 400）ため指定しない。
    - thinking は省略（この創作タスクでは不要。低レイテンシ・低コスト優先）。
    - system はトップレベル引数、messages は user/assistant のみ。
    """
    model = CHAT_DEPLOYMENT or "claude-opus-4-8"  # Foundry のデプロイ名（既定はモデルID）
    messages = [
        {"role": m["role"], "content": m["content"]}
        for m in history[-8:]
        if m.get("role") in ("user", "assistant")
    ]
    messages.append({"role": "user", "content": augmented_user})

    stream = _foundry_client().messages.create(
        model=model,
        max_tokens=1500,
        system=SYSTEM_PROMPT,
        messages=messages,
        stream=True,
    )
    for event in stream:
        if event.type == "content_block_delta" and getattr(event.delta, "type", None) == "text_delta":
            yield event.delta.text


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
def embed_text(text: str) -> List[float]:
    """クエリ/チャンクの埋め込みベクトルを取得（プロバイダ非依存）。

    EMBED_DIMENSIONS を設定すると出力次元を指定する（Gemini の
    gemini-embedding-001 など既定次元がインデックスと異なるモデル向け）。
    """
    kwargs = {}
    dims = os.environ.get("EMBED_DIMENSIONS")
    if dims:
        kwargs["dimensions"] = int(dims)
    resp = _get_embed_client().embeddings.create(
        input=[text], model=EMBED_DEPLOYMENT, **kwargs
    )
    return resp.data[0].embedding


def search_chunks(query: str, top: int = 5) -> List[dict]:
    """ハイブリッド検索でコンテキストチャンクを取得（local / azure 自動切替）"""
    vec = embed_text(query)

    if _vector_backend() == "local":
        from vector_store import get_store
        return get_store().search(query, vec, top=top)

    from azure.search.documents.models import VectorizedQuery
    results = _get_search_client().search(
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

    # Claude（Azure AI Foundry）バックエンドは Messages API 経路へ分岐
    if _chat_backend() == "foundry":
        return _stream_foundry(augmented_user, history), chunks

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
