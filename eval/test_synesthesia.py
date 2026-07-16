"""
test_synesthesia.py — app/synesthesia.py の純関数テスト（依存ゼロ・LLM不使用）。

実行: python eval/test_synesthesia.py
色数学（Oklab 往復・混合）／語彙照合（現代語・旧字旧仮名の双方）／
パレット構造・決定性・弱信号ガード（hint=None）を回帰的に検証する。
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app"))
from synesthesia import (  # noqa: E402
    TRADITIONAL_COLORS, NEUTRAL_HEX, NEUTRAL_NAME,
    hex_to_oklab, oklab_to_hex, mix_colors, nearest_color,
    text_moods, text_color, estimate_palette, HINT_MIN_STRENGTH,
)


def _close(h1: str, h2: str, tol: int = 2) -> bool:
    """hex 同士が各チャネル tol/255 以内か"""
    a = [int(h1.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)]
    b = [int(h2.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)]
    return all(abs(x - y) <= tol for x, y in zip(a, b))


def run():
    # ── 色数学: Oklab 往復（全伝統色でチャネル誤差 ±2 以内）──
    for name, h in TRADITIONAL_COLORS.items():
        rt = oklab_to_hex(hex_to_oklab(h))
        assert _close(h, rt), f"Oklab往復が崩れた: {name} {h} → {rt}"

    # 同色の混合は同色、端点の再現
    assert _close(mix_colors([("#B7282E", 1.0), ("#B7282E", 2.0)]), "#B7282E")
    assert _close(mix_colors([("#B7282E", 1.0), ("#EAF4FC", 0.0)]), "#B7282E")
    assert mix_colors([]) == NEUTRAL_HEX               # 空・全ゼロは中立色
    assert mix_colors([("#B7282E", 0.0)]) == NEUTRAL_HEX

    # 最近傍命名: 表に載っている色はそれ自身に写る
    assert nearest_color("#B7282E")[0] == "茜色"
    assert nearest_color("#EAF4FC")[0] == "月白"
    print("✓ 色数学: Oklab往復・混合・最近傍命名")

    # ── 語彙照合: 現代語 ──
    dist, s = text_moods("悲しい雨の夜、独りで泣いていた")
    assert s > 0 and "aishu" in dist and dist["aishu"] == max(dist.values()), (dist, s)

    dist2, s2 = text_moods("春の桜が咲いて、嬉しくて笑った")
    top2 = sorted(dist2, key=dist2.get, reverse=True)[:2]
    assert "haru" in top2 and s2 > 0, (dist2, s2)

    # ── 語彙照合: 旧字旧仮名（手本側テキストに反応するか）──
    dist3, s3 = text_moods("戀しき人を思ひて淚す。うれひは深く、月影さやかなる夜なりけり")
    assert "koi" in dist3 and "aishu" in dist3 and s3 > 0.5, (dist3, s3)

    # ── 複合語優先（長い語が短い語の誤発火を抑える）──
    d_kagerou, _ = text_moods("春の野に陽炎の立つを見た")   # 陽炎=夢幻。「炎」(情炎)を発火させない
    assert "jou" not in d_kagerou, d_kagerou
    d_chishio, _ = text_moods("血潮のたぎる思ひ")           # 血潮=情炎。「潮」(水邊)を発火させない
    assert "mizu" not in d_chishio and "jou" in d_chishio, d_chishio
    d_gekkou, _ = text_moods("月光の差す部屋")               # 月光=月影。「光」(陽光)を発火させない
    assert "youkou" not in d_gekkou and "tsuki" in d_gekkou, d_gekkou

    # ── 無信号 → 中立・強度0 ──
    hexn, sn, dn = text_color("これはペンです。会議は三時からです。")
    assert sn == 0.0 and dn == {} and hexn == NEUTRAL_HEX

    # ── 決定性 ──
    t = "月光の海辺で、懐かしい故郷を思い出す"
    assert text_color(t) == text_color(t)

    # ── パレット構造と型 ──
    p = estimate_palette(
        "悲しい別れの朝、涙が止まらなかった",
        ["戀しき人の面影を、月影に見て淚す", "これは説明の文章である"],
    )
    for key in ("input", "exemplar", "blend", "stops", "sources", "categories", "hint"):
        assert key in p, key
    assert len(p["stops"]) == 3 and all(x.startswith("#") for x in p["stops"])
    assert len(p["sources"]) == 2
    assert p["input"]["strength"] >= HINT_MIN_STRENGTH
    assert p["hint"] is not None and p["blend"]["name"] in p["hint"]
    assert "最優先" in p["hint"]                       # 実用性ガード文言が入っている
    assert p["categories"] and p["categories"][0] == "哀愁"
    # 手本1件目（戀・淚・月影）は色付き、2件目（説明文）は中立
    assert p["sources"][0]["strength"] > 0
    assert p["sources"][1]["strength"] == 0.0 and p["sources"][1]["name"] == NEUTRAL_NAME

    # ── 弱信号ガード: 情景語なし → hint なし・中立パレット ──
    p2 = estimate_palette("これを変換してください", ["普通の説明文です"])
    assert p2["hint"] is None
    assert p2["input"]["strength"] == 0.0
    assert p2["blend"]["hex"] == NEUTRAL_HEX

    # ── 補間: blend は入力色と手本色の間（入力寄り）──
    p3 = estimate_palette(
        "燃える夕焼けの茜空に怒りが滾る",          # 強い暖色（情炎）
        ["雪の降る寒い冬の朝、氷は冷たく凍てついた"] * 3,  # 強い寒色（雪冽）
    )
    li = hex_to_oklab(p3["input"]["hex"])
    le = hex_to_oklab(p3["exemplar"]["hex"])
    lb = hex_to_oklab(p3["blend"]["hex"])
    # a軸（緑–赤）: blend は両端の間に入る
    lo, hi = min(li[1], le[1]), max(li[1], le[1])
    assert lo - 1e-6 <= lb[1] <= hi + 1e-6, (li, lb, le)
    # 入力重み(0.6)が手本(0.4)より強い → blend は入力側に寄る
    d_in = sum((lb[i] - li[i]) ** 2 for i in range(3))
    d_ex = sum((lb[i] - le[i]) ** 2 for i in range(3))
    assert d_in < d_ex, (d_in, d_ex)

    # ── 手本が空でも壊れない ──
    p4 = estimate_palette("桜の春", [])
    assert p4["sources"] == [] and p4["exemplar"]["hex"] == NEUTRAL_HEX

    # ── hex 形式の妥当性（大文字 #RRGGBB）──
    import re
    for e in (p3["input"], p3["exemplar"], p3["blend"]):
        assert re.fullmatch(r"#[0-9A-F]{6}", e["hex"]), e

    print("✓ 語彙照合（現代語/旧字旧仮名）・パレット構造・弱信号ガード・補間・決定性")
    print("✅ synesthesia 全テスト成功")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
