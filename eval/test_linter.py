"""
test_linter.py — eval/linter.py のユニットテスト（依存ゼロ・LLM不使用）。

実行:
    python eval/test_linter.py         # 直接実行（成功で exit 0）
    python -m pytest eval/             # pytest でも可

各ルールの「正例（違反を検出すべき）」と「負例（本物の旧字旧仮名を誤検出しない）」を
両方置き、精度優先設計（本物を通す）を回帰的に守る。
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from eval.linter import lint, score, check_copy, KYUJI_MAP  # noqa: E402


def _rules(text):
    return {v.rule for v in lint(text)}


def run():
    # ── R1: 新字体漢字 ──────────────────────────────
    assert "R1" in _rules("国の学問")            # 国/学 は新字体
    assert "R1" not in _rules("國の學問")        # 旧字体なら検出しない
    assert "R1" not in _rules("山の花")          # 新旧同形は誤検出しない

    # ── R2: 〜ている ────────────────────────────────
    assert "R2" in _rules("見ている")
    assert "R2" in _rules("咲いています")
    assert "R2" not in _rules("見てゐる")        # 正しい歴史的仮名は通す

    # ── R5: でしょう/ましょう ───────────────────────
    assert "R5" in _rules("さうでしょう")
    assert "R5" in _rules("行きましょう")
    assert "R5" not in _rules("さうでせう")      # 正しい形は通す

    # ── R10: 口語文末 ──────────────────────────────
    assert "R10" in _rules("これは美しいです。")
    assert "R10" in _rules("散歩に行きました。")
    assert "R10" not in _rules("これぞ美しきなり。")   # 文語文末は通す

    # ── R10b: 候文と和文文語の併存（現行few-shotの欠陥） ──
    assert "R10b" in _rules("今日はよき御天氣にて候。散歩に出でたきものなり。")
    assert "R10b" not in _rules("花の咲くを見て、心和むなり。")   # 和文のみは通す

    # ── R11: 口語語彙 ──────────────────────────────
    assert "R11" in _rules("でも、それは違ふ")
    assert "R11" in _rules("とても美し")
    assert "R11" not in _rules("されど、それは違ふ")   # 文語語彙は通す

    # ── R12: 前置き ────────────────────────────────
    assert "R12" in _rules("承知しました。以下に示します。")
    assert "R12" in _rules("変換します。")
    assert "R12" not in _rules("花はうつくしきかな。")  # 即結果は通す

    # ── R14: 記号残骸 ──────────────────────────────
    assert "R14" in _rules("あはれ※なり")
    assert "R14" in _rules("山ぎは《やま》")
    assert "R14" not in _rules("あはれなり")

    # ── R13: 転用（コピー）検査 ─────────────────────
    ex = ["春はあけぼの。やうやう白くなりゆく山ぎは"]
    assert check_copy("春はあけぼの。やうやう白くなりゆく山ぎは、いとをかし", ex, n=10)
    assert not check_copy("花の香ただよふ朝、心は澄みわたるなり", ex, n=10)

    # ── score メトリクス ───────────────────────────
    clean = score("花はうつくしく、月はさやけきなり。")
    assert clean["clean"] is True and clean["errors"] == 0
    dirty = score("これは国の学問です。")
    assert dirty["clean"] is False and dirty["errors"] >= 2   # R1×2 + R10

    # ── KYUJI_MAP 健全性（恒等写像・非日本語混入がないこと） ──
    for k, v in KYUJI_MAP.items():
        assert k != v, f"恒等写像が混入: {k}"
        assert len(k) == 1 and len(v) == 1
        assert "　" <= k <= "鿿" or k >= "一", f"非漢字キー: {k!r}"

    print(f"✅ 全テスト成功（KYUJI_MAP {len(KYUJI_MAP)}字, ルール8種 + copy検査）")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
