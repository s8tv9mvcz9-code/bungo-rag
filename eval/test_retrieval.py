"""test_retrieval.py — app/retrieval.py の純関数テスト（依存ゼロ）。

実行: python eval/test_retrieval.py
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app"))
from retrieval import search_query, diversify, PREFER_STYLE  # noqa: E402


def run():
    # ── search_query: 変換指示語の除去 ─────────────────
    # 変換依頼: 指示語が落ち、内容が残る
    q = search_query("今日はいい天気です。散歩に行きたいです。旧字旧仮名にして")
    assert "旧字旧仮名" not in q and "天気" in q, q

    # テーマ作文（十分な長さ）: 指示語が落ちテーマが残る
    q2 = search_query("春の野辺の情景について短い文章を書いて")
    assert "書いて" not in q2 and "春の野辺" in q2, q2

    # 過剰除去はフォールバック（テーマ1語だけ→原文のまま検索）
    q3 = search_query("春について文章を書いて")
    assert q3 == "春について文章を書いて", q3

    # 指示語なしの素のクエリ: 変化しない
    q4 = search_query("月の描写が美しい文章")
    assert q4 == "月の描写が美しい文章", q4

    # ── diversify: 旧字旧仮名の優先充填 + 1作品上限 ────
    cands = [
        {"book_id": "A", "style": "旧字新仮名", "text": "a1"},  # 新仮名（後回し）
        {"book_id": "B", "style": "旧字旧仮名", "text": "b1"},  # 旧仮名（優先）
        {"book_id": "B", "style": "旧字旧仮名", "text": "b2"},
        {"book_id": "B", "style": "旧字旧仮名", "text": "b3"},  # 1作品上限で弾く
        {"book_id": "C", "style": "旧字旧仮名", "text": "c1"},
    ]
    picked = diversify(cands, top=3, max_per_book=2, prefer_style=PREFER_STYLE)
    styles = [p["style"] for p in picked]
    texts = [p["text"] for p in picked]
    assert len(picked) == 3, picked
    assert styles == ["旧字旧仮名"] * 3, styles          # 旧仮名が優先
    assert texts == ["b1", "b2", "c1"], texts             # B は2件まで、Cで補完

    # 旧仮名が足りなければ新仮名で補完（枯渇を防ぐ）
    few = [
        {"book_id": "B", "style": "旧字旧仮名", "text": "b1"},
        {"book_id": "A", "style": "旧字新仮名", "text": "a1"},
        {"book_id": "A", "style": "旧字新仮名", "text": "a2"},
    ]
    picked2 = diversify(few, top=3, max_per_book=2)
    assert [p["text"] for p in picked2] == ["b1", "a1", "a2"], picked2  # 旧仮名優先→新仮名補完

    print("✅ retrieval 全テスト成功（search_query 4例 / diversify 2例）")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
