"""
build_index.py
==============
青空文庫 RAG — Phase 1 インデックス構築スクリプト

処理フロー:
  1. 青空文庫公式カタログ CSV をダウンロード（ZORAPI 不使用）
  2. 旧字旧仮名 / 旧字新仮名 かつ著作権フリーの作品を抽出
  3. 各作品の ZIP テキストをダウンロード・Shift-JIS デコード
  4. 青空文庫注記（ルビ、入力者情報等）を除去
  5. 段落単位でチャンク分割
  6. Azure OpenAI Embeddings でベクター生成
  7. Azure AI Search にドキュメントとして登録

カタログ URL:
  https://www.aozora.gr.jp/index_pages/list_person_all_extended_utf8.zip

前提:
  pip install requests openai azure-search-documents python-dotenv
"""

import os
import re
import io
import csv
import time
import zipfile
import requests
from typing import Optional, List
from dotenv import load_dotenv
from openai import AzureOpenAI
from azure.search.documents import SearchClient
from azure.search.documents.indexes import SearchIndexClient
from azure.search.documents.indexes.models import (
    SearchIndex, SimpleField, SearchFieldDataType,
    SearchableField, SearchField, VectorSearch,
    HnswAlgorithmConfiguration, VectorSearchProfile,
)
from azure.core.credentials import AzureKeyCredential

load_dotenv()

# ── 設定 ────────────────────────────────────────────────
CATALOG_URL        = "https://www.aozora.gr.jp/index_pages/list_person_all_extended_utf8.zip"
AZURE_OAI_ENDPOINT = os.environ["AZURE_OPENAI_ENDPOINT"]
AZURE_OAI_KEY      = os.environ["AZURE_OPENAI_API_KEY"]
EMBED_DEPLOY       = os.environ.get("EMBED_DEPLOYMENT", "text-embedding-3-small")
SEARCH_ENDPOINT    = os.environ["AZURE_SEARCH_ENDPOINT"]
SEARCH_KEY         = os.environ["AZURE_SEARCH_ADMIN_KEY"]
INDEX_NAME         = os.environ.get("SEARCH_INDEX_NAME", "bungo-chunks")

# 取得対象：旧字旧仮名 と 旧字新仮名（戦前文体が多い）
TARGET_STYLES = {"旧字旧仮名", "旧字新仮名"}
MAX_BOOKS     = 300   # 対象作品数の上限（著者メタデータ修正の再構築に合わせ 200→300 へ微増）
CHUNK_SIZE    = 300   # 1チャンクの目安文字数
EMBED_BATCH   = 16    # Embedding API への1バッチサイズ
SLEEP_SEC     = 0.5   # API レート制限対策

# ── Azure クライアント初期化 ─────────────────────────────
oai_client = AzureOpenAI(
    azure_endpoint=AZURE_OAI_ENDPOINT,
    api_key=AZURE_OAI_KEY,
    api_version="2024-02-01",
)
search_index_client = SearchIndexClient(
    endpoint=SEARCH_ENDPOINT,
    credential=AzureKeyCredential(SEARCH_KEY),
)
search_client = SearchClient(
    endpoint=SEARCH_ENDPOINT,
    index_name=INDEX_NAME,
    credential=AzureKeyCredential(SEARCH_KEY),
)


# ── インデックス作成 ─────────────────────────────────────
def create_index_if_not_exists():
    """ベクター検索対応インデックスを作成（既存ならスキップ）"""
    existing = [i.name for i in search_index_client.list_indexes()]
    if INDEX_NAME in existing:
        print(f"[index] '{INDEX_NAME}' は既に存在します。スキップ。")
        return

    fields = [
        SimpleField(name="id",        type=SearchFieldDataType.String, key=True),
        SimpleField(name="book_id",   type=SearchFieldDataType.String, filterable=True),
        SimpleField(name="author",    type=SearchFieldDataType.String, filterable=True),
        SimpleField(name="title",     type=SearchFieldDataType.String, filterable=True),
        SimpleField(name="style",     type=SearchFieldDataType.String, filterable=True),
        SimpleField(name="chunk_idx", type=SearchFieldDataType.Int32),
        SearchableField(name="text",  type=SearchFieldDataType.String, analyzer_name="ja.microsoft"),
        SearchField(
            name="embedding",
            type=SearchFieldDataType.Collection(SearchFieldDataType.Single),
            searchable=True,
            vector_search_dimensions=1536,
            vector_search_profile_name="bungo-profile",
        ),
    ]
    vector_search = VectorSearch(
        algorithms=[HnswAlgorithmConfiguration(name="bungo-hnsw")],
        profiles=[VectorSearchProfile(name="bungo-profile", algorithm_configuration_name="bungo-hnsw")],
    )
    index = SearchIndex(name=INDEX_NAME, fields=fields, vector_search=vector_search)
    search_index_client.create_index(index)
    print(f"[index] '{INDEX_NAME}' を作成しました。")


# ── カタログ取得 ─────────────────────────────────────────
def load_catalog(max_books: int = MAX_BOOKS) -> List[dict]:
    """
    青空文庫公式カタログ ZIP を取得し、対象作品リストを返す。
    フィルタ条件:
      - 文字遣い種別 が TARGET_STYLES に含まれる
      - 作品著作権フラグ == なし
      - 人物著作権フラグ == なし
      - テキストファイルURL が存在する
    """
    print(f"[catalog] カタログをダウンロード中: {CATALOG_URL}")
    resp = requests.get(CATALOG_URL, timeout=60)
    resp.raise_for_status()

    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        csv_name = next(n for n in zf.namelist() if n.endswith(".csv"))
        raw_csv = zf.read(csv_name).decode("utf-8-sig")

    reader = csv.DictReader(io.StringIO(raw_csv))
    books = []
    seen_ids = set()

    for row in reader:
        if row.get("文字遣い種別") not in TARGET_STYLES:
            continue
        if row.get("作品著作権フラグ") != "なし":
            continue
        if row.get("人物著作権フラグ") != "なし":
            continue
        if not row.get("テキストファイルURL"):
            continue

        book_id = row.get("作品ID", "")
        if book_id in seen_ids:   # 同一作品の複数著者行を除重
            continue
        seen_ids.add(book_id)
        books.append(row)

        if len(books) >= max_books:
            break

    print(f"[catalog] 対象作品: {len(books)} 件（上限 {max_books}）")
    return books


# ── 著者名の組み立て ─────────────────────────────────────
def _author_name(book: dict) -> str:
    """拡張カタログは著者を「姓」「名」の2列で持つ（「姓名」列は存在しない）。
    両者を結合して姓名を復元する。片方しか無い場合や欠損時も安全に処理する。"""
    sei = (book.get("姓") or "").strip()
    mei = (book.get("名") or "").strip()
    name = (sei + mei).strip()
    return name or "不明"


# ── テキスト取得・クリーニング ──────────────────────────
AOZORA_NOISE = re.compile(
    r"(?:"
    r"《[^》]*》"        # ルビ（親文字の読み）
    r"|［＃[^］]*］"      # 注記 ［＃〜］
    r"|｜"               # ルビ開始記号
    r"|〔[^〕]*〕"        # 底本注
    r")",
    re.UNICODE,
)
HEADER_FOOTER = re.compile(r"-{5,}.*?-{5,}", re.DOTALL)


def fetch_text(book: dict) -> Optional[str]:
    """ZIP から本文テキストを取得し、クリーニングして返す"""
    zip_url = book.get("テキストファイルURL", "")
    if not zip_url:
        return None
    try:
        resp = requests.get(zip_url, timeout=30)
        resp.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            txt_name = next((n for n in zf.namelist() if n.endswith(".txt")), None)
            if not txt_name:
                return None
            raw = zf.read(txt_name).decode("shift_jis", errors="replace")

        raw = HEADER_FOOTER.sub("", raw)   # ヘッダー・フッター除去
        raw = AOZORA_NOISE.sub("", raw)    # 青空注記除去
        raw = re.sub(r"\n{3,}", "\n\n", raw).strip()
        return raw
    except Exception as e:
        print(f"    [warn] テキスト取得失敗: {book.get('作品名')} — {e}")
        return None


# ── チャンク分割 ────────────────────────────────────────
def split_chunks(text: str, author: str, title: str) -> List[str]:
    """
    段落単位を優先しつつ、CHUNK_SIZE を超えたら句点で切る。
    著者名・作品名をチャンク先頭に付与し、検索精度を高める。
    """
    prefix = f"【{author}「{title}」より】\n"
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks: List[str] = []
    buf = ""

    for para in paragraphs:
        if len(buf) + len(para) <= CHUNK_SIZE:
            buf += para + "\n"
        else:
            if buf:
                chunks.append(prefix + buf.strip())
            if len(para) > CHUNK_SIZE:
                sentences = re.split(r"(?<=[。！？])", para)
                sbuf = ""
                for s in sentences:
                    if len(sbuf) + len(s) <= CHUNK_SIZE:
                        sbuf += s
                    else:
                        if sbuf:
                            chunks.append(prefix + sbuf.strip())
                        sbuf = s
                buf = sbuf + "\n" if sbuf else ""
            else:
                buf = para + "\n"

    if buf:
        chunks.append(prefix + buf.strip())

    return chunks


# ── Embedding ────────────────────────────────────────────
def embed_batch(texts: List[str]) -> List[List[float]]:
    """text-embedding-3-small でベクターを生成"""
    resp = oai_client.embeddings.create(model=EMBED_DEPLOY, input=texts)
    return [item.embedding for item in resp.data]


# ── メイン処理 ───────────────────────────────────────────
def main():
    print("=== 青空文庫 RAG インデックス構築 ===\n")
    create_index_if_not_exists()

    # 1. カタログから作品リスト取得
    all_books = load_catalog(max_books=MAX_BOOKS)
    if not all_books:
        print("対象作品が見つかりませんでした。")
        return

    print(f"\n合計 {len(all_books)} 作品を処理します。\n")

    # 2. 本文取得 → チャンク化 → Embedding → 登録
    doc_buffer: List[dict] = []

    for i, book in enumerate(all_books, 1):
        book_id = book.get("作品ID", f"unknown-{i}")
        author  = _author_name(book)
        title   = book.get("作品名", "不明")
        style   = book.get("文字遣い種別", "不明")
        print(f"[{i:03}/{len(all_books)}] {author}「{title}」({style})")

        text = fetch_text(book)
        if not text:
            continue

        chunks = split_chunks(text, author, title)
        print(f"  → {len(chunks)} チャンク")

        for b_start in range(0, len(chunks), EMBED_BATCH):
            batch_texts = chunks[b_start:b_start + EMBED_BATCH]
            try:
                vectors = embed_batch(batch_texts)
            except Exception as e:
                print(f"  [warn] Embedding 失敗: {e}")
                time.sleep(2)
                continue

            for j, (chunk_text, vector) in enumerate(zip(batch_texts, vectors)):
                doc_buffer.append({
                    "id":        f"{book_id}-{b_start + j}",
                    "book_id":   book_id,
                    "author":    author,
                    "title":     title,
                    "style":     style,
                    "chunk_idx": b_start + j,
                    "text":      chunk_text,
                    "embedding": vector,
                })

            time.sleep(SLEEP_SEC)

        # AI Search へバッチ登録（1000件ごと）
        if len(doc_buffer) >= 1000:
            search_client.upload_documents(documents=doc_buffer)
            print(f"  [search] {len(doc_buffer)} ドキュメントを登録")
            doc_buffer = []

        time.sleep(SLEEP_SEC)

    # 残りを登録
    if doc_buffer:
        search_client.upload_documents(documents=doc_buffer)
        print(f"\n[search] 残り {len(doc_buffer)} ドキュメントを登録")

    print("\n✅ インデックス構築完了！")


if __name__ == "__main__":
    main()
