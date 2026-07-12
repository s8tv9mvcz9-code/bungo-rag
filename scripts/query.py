"""
query.py
========
青空文庫 RAG — クエリ実行スクリプト

使い方:
  python scripts/query.py "月の描写が美しい文章を教えてください"
  python scripts/query.py --top 5 --search-only "自然の描写"

環境変数 (.env):
  AZURE_SEARCH_ENDPOINT     Azure AI Search エンドポイント
  AZURE_SEARCH_ADMIN_KEY    Azure AI Search 管理キー
  SEARCH_INDEX_NAME         インデックス名（デフォルト: bungo-chunks）
  AZURE_OPENAI_ENDPOINT     Azure OpenAI エンドポイント（Embedding 用）
  AZURE_OPENAI_API_KEY      Azure OpenAI APIキー
  EMBED_DEPLOYMENT          Embedding デプロイ名
  CHAT_ENDPOINT             チャットモデルのエンドポイント（MaaS / Azure OpenAI）
  CHAT_API_KEY              チャットモデルの APIキー
  CHAT_DEPLOYMENT           チャットモデルのデプロイ名
"""

import os
import argparse
from typing import List
from dotenv import load_dotenv
from openai import AzureOpenAI, OpenAI
from anthropic import Anthropic
from azure.search.documents import SearchClient
from azure.search.documents.models import VectorizedQuery
from azure.core.credentials import AzureKeyCredential

load_dotenv()

# ── 設定 ────────────────────────────────────────────────
SEARCH_ENDPOINT = os.environ["AZURE_SEARCH_ENDPOINT"]
SEARCH_KEY      = os.environ["AZURE_SEARCH_ADMIN_KEY"]
INDEX_NAME      = os.environ.get("SEARCH_INDEX_NAME", "bungo-chunks")

# Embedding: Azure OpenAI（既存）
EMBED_ENDPOINT   = os.environ["AZURE_OPENAI_ENDPOINT"]
EMBED_KEY        = os.environ["AZURE_OPENAI_API_KEY"]
EMBED_DEPLOYMENT = os.environ.get("EMBED_DEPLOYMENT", "text-embedding-3-small")

# Chat: MaaS エンドポイント（Phi-3）または Azure OpenAI にフォールバック
CHAT_ENDPOINT   = os.environ.get("CHAT_ENDPOINT", os.environ.get("AZURE_OPENAI_ENDPOINT", ""))
CHAT_KEY        = os.environ.get("CHAT_API_KEY",  os.environ.get("AZURE_OPENAI_API_KEY", ""))
CHAT_DEPLOYMENT = os.environ.get("CHAT_DEPLOYMENT", "")

# ── クライアント初期化 ───────────────────────────────────
embed_client = AzureOpenAI(
    azure_endpoint=EMBED_ENDPOINT,
    api_key=EMBED_KEY,
    api_version="2024-02-01",
)

# CHAT_ENDPOINT からプロバイダを判定してクライアントを構築する:
#   "anthropic" を含む     → Azure AI Foundry の Claude（Anthropic Messages API）
#   "openai.azure.com"     → Azure OpenAI
#   それ以外               → OpenAI 互換（GitHub Models / MaaS）
def _chat_provider() -> str:
    ep = CHAT_ENDPOINT.lower()
    if "anthropic" in ep:
        return "anthropic"
    if "openai.azure.com" in ep:
        return "azure_openai"
    return "openai"

def _build_chat_client():
    if not CHAT_ENDPOINT or not CHAT_KEY:
        return None
    provider = _chat_provider()
    if provider == "anthropic":
        return Anthropic(base_url=CHAT_ENDPOINT, api_key=CHAT_KEY)
    if provider == "azure_openai":
        return AzureOpenAI(
            azure_endpoint=CHAT_ENDPOINT,
            api_key=CHAT_KEY,
            api_version="2024-02-01",
        )
    # OpenAI 互換（inference.ai.azure.com 等）: base_url を指定
    return OpenAI(base_url=CHAT_ENDPOINT, api_key=CHAT_KEY)

chat_client = _build_chat_client()

search_client = SearchClient(
    endpoint=SEARCH_ENDPOINT,
    index_name=INDEX_NAME,
    credential=AzureKeyCredential(SEARCH_KEY),
)


# ── 検索 ────────────────────────────────────────────────
# 1作品から採用するチャンク数の上限（特定文献への引っ張られ防止・多様性確保）
MAX_PER_BOOK = 2

def search(query: str, top: int = 5) -> List[dict]:
    """ハイブリッド検索（ベクター + 全文）。
    候補を多めに取り、1作品 MAX_PER_BOOK 件までに間引いてから上位 top 件を返す。"""
    # クエリを Embedding
    resp = embed_client.embeddings.create(input=[query], model=EMBED_DEPLOYMENT)
    query_vector = resp.data[0].embedding

    candidate_top = max(top * 3, top)
    vector_query = VectorizedQuery(
        vector=query_vector,
        k_nearest_neighbors=candidate_top * 2,
        fields="embedding",
    )
    results = search_client.search(
        search_text=query,
        vector_queries=[vector_query],
        select=["id", "text", "title", "author", "style", "chunk_idx", "book_id"],
        top=candidate_top,
    )

    # 1作品 MAX_PER_BOOK 件までに間引く
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


# ── 生成 ────────────────────────────────────────────────
SYSTEM_PROMPT = """あなたは日本の近代文学の専門家です。
青空文庫の戦前作品から取得した文章を参考に、質問に丁寧に答えてください。
旧字旧仮名・旧字新仮名の文体的特徴についても解説できます。
参考文章に書かれていないことは作り上げないでください。"""


def generate(query: str, contexts: List[dict]) -> str:
    """取得したコンテキストを元に回答を生成"""
    if not chat_client:
        return "（チャットモデル未設定。--search-only モードを使用してください）"

    context_text = "\n\n---\n\n".join(
        f"【{c['title']} / {c['author']} ({c.get('style','')})】\n{c['text']}"
        for c in contexts
    )
    user_prompt = f"## 参考文章\n{context_text}\n\n## 質問\n{query}"

    if _chat_provider() == "anthropic":
        # Anthropic Messages API: system はトップレベル、temperature は非対応
        # Prompt Caching: 固定 SYSTEM_PROMPT に cache_control を付与（Foundry はβ）
        resp = chat_client.messages.create(
            model=CHAT_DEPLOYMENT,
            max_tokens=800,
            system=[{
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }],
            messages=[{"role": "user", "content": user_prompt}],
            extra_headers={"anthropic-beta": "prompt-caching-2024-07-31"},
        )
        return "".join(b.text for b in resp.content if b.type == "text")

    resp = chat_client.chat.completions.create(
        model=CHAT_DEPLOYMENT,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": user_prompt},
        ],
        temperature=0.3,
        max_tokens=800,
    )
    return resp.choices[0].message.content


# ── メイン ───────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="青空文庫 RAG クエリ")
    parser.add_argument("query", help="検索クエリ")
    parser.add_argument("--top",  type=int, default=5, help="取得チャンク数（デフォルト: 5）")
    parser.add_argument("--search-only", action="store_true",
                        help="検索結果のみ表示（生成なし）")
    args = parser.parse_args()

    print(f"\n🔍 クエリ: 「{args.query}」\n")

    # 検索
    results = search(args.query, top=args.top)
    if not results:
        print("検索結果が見つかりませんでした。")
        return

    print(f"📚 関連チャンク（{len(results)} 件）:")
    print("─" * 60)
    for i, r in enumerate(results, 1):
        print(f"\n[{i}] {r['title']} / {r['author']}  （{r.get('style','')}）")
        print(r["text"][:200] + ("…" if len(r["text"]) > 200 else ""))

    if args.search_only:
        print("\n（--search-only モード: 生成をスキップ）")
        return

    # 生成
    print("\n" + "=" * 60)
    print("🤖 回答:")
    print("=" * 60)
    print(generate(args.query, results))


if __name__ == "__main__":
    main()
