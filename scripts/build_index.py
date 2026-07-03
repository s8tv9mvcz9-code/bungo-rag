"""
build_index.py — 青空文庫からローカル検索インデックスを構築する

Azure AI Search を使わないゼロコスト構成のためのパイプライン:
  1. 青空文庫の公式 GitHub ミラーからカタログ CSV を取得
  2. パブリックドメイン & 指定の文字遣い（既定: 旧字旧仮名）の作品を選定
  3. テキストを取得し、ルビ・注記・ヘッダ/フッタを除去
  4. 約 CHUNK_CHARS 文字でチャンク化
  5. OpenAI 互換 API（GitHub Models 等）で埋め込みを生成
  6. corpus/index.npz + corpus/meta.json に保存

使い方:
  # GitHub Models で埋め込み（GITHUB_TOKEN か EMBED_API_KEY が必要）
  python scripts/build_index.py --limit 50

  # 埋め込みなしのドライラン（チャンク化まで確認）
  python scripts/build_index.py --limit 5 --mock-embeddings

青空文庫本家ではなく GitHub ミラー（raw.githubusercontent.com）を使うため、
GitHub Actions 内でも追加設定なしで動作する。
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import sys
import time
import zipfile
from urllib.request import urlopen, Request

import numpy as np

CATALOG_URL = (
    "https://raw.githubusercontent.com/aozorabunko/aozorabunko/master/"
    "index_pages/list_person_all_extended_utf8.zip"
)
MIRROR_PREFIX = "https://raw.githubusercontent.com/aozorabunko/aozorabunko/master/"
AOZORA_PREFIX = "https://www.aozora.gr.jp/"

UA = {"User-Agent": "bungo-rag-index-builder/1.0"}

# ── テキスト整形 ─────────────────────────────────────────
RUBY_RE = re.compile(r"《[^》]*》")
NOTE_RE = re.compile(r"［＃[^］]*］")
BAR_RE = re.compile(r"｜")
HEADER_SEP = "-------------------------------------------------------"


def fetch(url: str, retries: int = 3) -> bytes:
    for i in range(retries):
        try:
            with urlopen(Request(url, headers=UA), timeout=60) as r:
                return r.read()
        except Exception:
            if i == retries - 1:
                raise
            time.sleep(2 ** (i + 1))
    raise RuntimeError("unreachable")


def load_catalog() -> list[dict]:
    raw = fetch(CATALOG_URL)
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        name = z.namelist()[0]
        text = z.read(name).decode("utf-8-sig")
    return list(csv.DictReader(io.StringIO(text)))


def select_works(rows: list[dict], styles: list[str], limit: int) -> list[dict]:
    """PD作品のみ、翻訳（役割フラグ≠著者）を除き、作品IDで決定的に選ぶ。"""
    seen: set[str] = set()
    out: list[dict] = []
    for r in sorted(rows, key=lambda r: r["作品ID"]):
        if r["作品ID"] in seen:
            continue
        if r["文字遣い種別"] not in styles:
            continue
        if r["作品著作権フラグ"] != "なし" or r["人物著作権フラグ"] != "なし":
            continue
        if r["役割フラグ"] != "著者":
            continue
        if not r["テキストファイルURL"].startswith(AOZORA_PREFIX):
            continue
        seen.add(r["作品ID"])
        out.append(r)
        if len(out) >= limit:
            break
    return out


def clean_text(raw: str) -> str:
    """青空文庫テキストからルビ・注記・ヘッダ/フッタを除去する。"""
    # ヘッダ（【テキスト中に現れる記号について】ブロック）を除去
    parts = raw.split(HEADER_SEP)
    if len(parts) >= 3:
        raw = parts[0] + parts[2]
    # フッタ（底本情報以降）を除去
    for marker in ("底本：", "底本:"):
        idx = raw.find(marker)
        if idx > 0:
            raw = raw[:idx]
            break
    raw = RUBY_RE.sub("", raw)
    raw = NOTE_RE.sub("", raw)
    raw = BAR_RE.sub("", raw)
    return raw.strip()


def chunk_text(text: str, chunk_chars: int = 400, min_chars: int = 80) -> list[str]:
    """文境界（。）を優先して約 chunk_chars 文字ずつに分割。"""
    sentences = re.split(r"(?<=。)", text.replace("\r", ""))
    chunks: list[str] = []
    buf = ""
    for s in sentences:
        s = s.strip("　 \n\t")
        if not s:
            continue
        if len(buf) + len(s) > chunk_chars and buf:
            chunks.append(buf)
            buf = s
        else:
            buf += s
    if buf:
        chunks.append(buf)
    return [c for c in chunks if len(c) >= min_chars]


def download_work(row: dict) -> str | None:
    """テキスト zip をミラーから取得し、整形済み本文を返す。"""
    url = row["テキストファイルURL"].replace(AOZORA_PREFIX, MIRROR_PREFIX)
    try:
        raw = fetch(url)
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            txt_names = [n for n in z.namelist() if n.lower().endswith(".txt")]
            if not txt_names:
                return None
            body = z.read(txt_names[0]).decode(
                "shift_jis" if "ShiftJIS" in row["テキストファイル符号化方式"] else "utf-8",
                errors="replace",
            )
        return clean_text(body)
    except Exception as e:
        print(f"  ⚠️ 取得失敗 {row['作品名']}: {e}", file=sys.stderr)
        return None


def embed_batches(
    texts: list[str], model: str, batch: int, sleep: float, mock: bool
) -> np.ndarray:
    if mock:
        rng = np.random.default_rng(42)
        v = rng.standard_normal((len(texts), 1536)).astype(np.float32)
        return v / np.linalg.norm(v, axis=1, keepdims=True)

    from openai import OpenAI

    endpoint = os.environ.get("EMBED_ENDPOINT", "")
    api_key = os.environ.get("EMBED_API_KEY", "")
    if not (endpoint and api_key):
        sys.exit(
            "EMBED_ENDPOINT と EMBED_API_KEY を設定してください"
            "（OpenAI互換の埋め込みAPI。例: Gemini の OpenAI 互換エンドポイント）"
        )
    client = OpenAI(base_url=endpoint, api_key=api_key)

    kwargs = {}
    dims = os.environ.get("EMBED_DIMENSIONS")
    if dims:
        kwargs["dimensions"] = int(dims)

    out: list[list[float]] = []
    for i in range(0, len(texts), batch):
        chunk = texts[i : i + batch]
        for attempt in range(5):
            try:
                resp = client.embeddings.create(input=chunk, model=model, **kwargs)
                out.extend(d.embedding for d in resp.data)
                break
            except Exception as e:
                wait = 15 * (attempt + 1)
                print(f"  ⚠️ embed retry {attempt+1}/5 in {wait}s: {e}", file=sys.stderr)
                time.sleep(wait)
        else:
            sys.exit("埋め込み API のリトライ上限に達しました（レート制限を確認）")
        done = min(i + batch, len(texts))
        print(f"  embedded {done}/{len(texts)}")
        if sleep:
            time.sleep(sleep)
    return np.asarray(out, dtype=np.float32)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, default=50, help="対象作品数（既定50）")
    ap.add_argument(
        "--styles",
        default="旧字旧仮名",
        help="対象の文字遣い（カンマ区切り。例: 旧字旧仮名,新字旧仮名）",
    )
    ap.add_argument("--chunk-chars", type=int, default=400)
    ap.add_argument("--embed-model", default=os.environ.get(
        "EMBED_DEPLOYMENT", "text-embedding-3-small"),
        help="埋め込みモデル名（EMBED_ENDPOINT のプロバイダに合わせる）")
    ap.add_argument("--batch", type=int, default=16, help="埋め込みバッチサイズ")
    ap.add_argument("--sleep", type=float, default=0.0, help="バッチ間スリープ秒")
    ap.add_argument("--mock-embeddings", action="store_true",
                    help="APIを呼ばず乱数埋め込み（パイプライン検証用）")
    ap.add_argument("--out-dir", default=os.path.join(
        os.path.dirname(__file__), "..", "corpus"))
    args = ap.parse_args()

    print("=== 1/4 カタログ取得 ===")
    rows = load_catalog()
    works = select_works(rows, args.styles.split(","), args.limit)
    print(f"対象作品: {len(works)} 件（styles={args.styles}, PD のみ）")

    print("=== 2/4 テキスト取得 & チャンク化 ===")
    meta: list[dict] = []
    for i, w in enumerate(works, 1):
        body = download_work(w)
        if not body:
            continue
        for c in chunk_text(body, args.chunk_chars):
            meta.append({
                "text": c,
                "title": w["作品名"],
                "author": f"{w['姓']}{w['名']}",
                "style": w["文字遣い種別"],
            })
        print(f"  [{i}/{len(works)}] {w['作品名']} / {w['姓']}{w['名']} → 累計 {len(meta)} chunks")

    if not meta:
        sys.exit("チャンクが 0 件です。ネットワーク/フィルタ条件を確認してください。")

    print(f"=== 3/4 埋め込み生成（{len(meta)} chunks, model={args.embed_model}）===")
    embeddings = embed_batches(
        [m["text"] for m in meta], args.embed_model,
        args.batch, args.sleep, args.mock_embeddings,
    )

    print("=== 4/4 保存 ===")
    os.makedirs(args.out_dir, exist_ok=True)
    npz_path = os.path.join(args.out_dir, "index.npz")
    meta_path = os.path.join(args.out_dir, "meta.json")
    np.savez_compressed(npz_path, embeddings=embeddings)
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False)
    size_mb = os.path.getsize(npz_path) / 1e6
    print(f"✅ 完了: {npz_path} ({size_mb:.1f} MB) / {meta_path} ({len(meta)} chunks)")
    if args.mock_embeddings:
        print("⚠️ mock embeddings（乱数）です。本番検索には使わないでください。")


if __name__ == "__main__":
    main()
