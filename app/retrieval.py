"""
retrieval.py — 検索クエリ整形と文体手本の多様化（純関数・副作用なし）

app/rag.py と scripts/query.py の双方から使う共有ロジック。
両ファイルに重複していた検索後処理を一本化する一歩（docs/quality-roadmap.md 3-1）。
Azure/OpenAI SDK に依存しないため単体テスト可能（eval/test_retrieval.py）。
"""
from __future__ import annotations

import re
from typing import List

# 文体手本として優先する文字遣ひ。旧字新仮名（＝現代仮名遣い）の手本は
# 「〜してゐる」等の変換漏れをむしろ助長するため、旧字旧仮名を先に充填する。
PREFER_STYLE = "旧字旧仮名"

# 検索クエリから取り除く「変換指示」語。手本は依頼文言ではなく内容で引きたい。
# 生成モデルには別途フルの原文を渡すため、ここでの除去は検索精度のためだけに効く。
_INSTRUCTION_PATTERNS = [
    re.compile(r"(を|に|へ)?(旧字旧仮名|旧仮名|旧字|文語体?|歴史的仮名遣[いひ]?)"
               r"(に|へ|で)?(変換|翻訳|直し?|書き?)?(して|しろ|せよ|ください|下さい|て)?"),
    re.compile(r"(に|へ)?(変換|翻訳)(して|しろ|せよ|ください|下さい)"),
    re.compile(r"次の(文章|文|テキスト)を?"),
    re.compile(r"^以下を?[:：]?"),
    re.compile(r"について(の)?(短[いく])?(文章|文|作文)(を)?(書[いく]て?(ください|下さい)?)?"),
]


def search_query(message: str) -> str:
    """検索用にユーザー発話から変換指示語を除去する。
    過剰除去で内容が消える場合は原文にフォールバックする（安全側）。"""
    q = message
    for p in _INSTRUCTION_PATTERNS:
        q = p.sub(" ", q)
    q = re.sub(r"[\s、。「」　]+", " ", q).strip()
    # 4文字未満まで削れたら情報が失われすぎ → 原文で検索する
    return q if len(q) >= 4 else message


def diversify(
    candidates: List[dict],
    top: int,
    max_per_book: int,
    prefer_style: str = PREFER_STYLE,
) -> List[dict]:
    """検索候補（スコア降順）を、1作品 max_per_book 件までに間引きつつ返す。
    prefer_style のチャンクを先に充填し、不足分のみ他 style で補完する。
    これにより手本の「文字遣ひ純度」を上げつつ、件数不足（枯渇）を避ける。"""
    picked: List[dict] = []
    per_book: dict = {}

    def _fill(items: List[dict]) -> None:
        for d in items:
            if len(picked) >= top:
                return
            key = d.get("book_id") or d.get("title")
            if per_book.get(key, 0) >= max_per_book:
                continue
            per_book[key] = per_book.get(key, 0) + 1
            picked.append(d)

    _fill([c for c in candidates if c.get("style") == prefer_style])
    _fill([c for c in candidates if c.get("style") != prefer_style])
    return picked
