"""
synesthesia.py — 共感覚レイヤー（文 → 情調 → 日本の伝統色）

純関数・依存ゼロ・LLM 不使用。決定的（同じ入力 → 同じ出力）なので机上検証できる。

仕組み（3段）:
  1. 語彙照合   — 文中の情景・情緒語（現代語 + 歴史的仮名 + 旧字の異体を収録）を
                  13 の情調カテゴリに集計する。形態素解析はせず部分文字列照合
                  （日本語の内容語は 2 字以上の表記が多く、風味付け用途には十分）。
  2. 色の合成   — 各カテゴリのアンカー（日本の伝統色）を Oklab 色空間（知覚均等）で
                  重み付き混合。入力文の色・文体手本の色・両者の補間色（連想）を得る。
  3. 命名       — 伝統色表への最近傍照合で「茜色」「月白」等の名を与える。

出力は estimate_palette() のパレット辞書。信号が弱い（情景語が無い）場合は
中立色（白磁）に落ち、生成プロンプトへのヒント（hint）は None になる —
実用性（変換の正確さ）を損なわないためのガードである。

precision/recall とも完全ではない（否定「悲しくない」は拾えない・「観光」の「光」を
拾う等）が、風味付けが目的であり誤差は許容する。厳密な情緒推定は将来の LLM 判定
（quality-roadmap Phase 2 相当）の領域。
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

# ── 日本の伝統色（最近傍命名用。値は慣用的な近似）─────────────────
TRADITIONAL_COLORS: Dict[str, str] = {
    "桜色":   "#FDEFF2", "薄紅":   "#F0908D", "紅梅色": "#F2A0A1",
    "韓紅":   "#E9546B", "茜色":   "#B7282E", "緋色":   "#D3381C",
    "朱色":   "#EB6101", "柿色":   "#ED6D3D", "琥珀色": "#BF783A",
    "黄金":   "#E6B422", "山吹色": "#F8B500", "菜の花色": "#FFEC47",
    "鳥の子色": "#FFF1CF", "若草色": "#C3D825", "萌黄":  "#AACF53",
    "若竹色": "#68BE8D", "常磐色": "#007B43", "青磁色": "#7EBEA5",
    "浅葱色": "#00A3AF", "瑠璃色": "#1E50A2", "群青色": "#4C6CB3",
    "紺青":   "#192F60", "藍色":   "#165E83", "勿忘草色": "#89C3EB",
    "空色":   "#A0D8EF", "月白":   "#EAF4FC", "藍白":   "#EBF6F7",
    "白磁":   "#F8FBF8", "藤色":   "#BBA1CB", "藤紫":   "#A59ACA",
    "菫色":   "#7058A3", "江戸紫": "#745399", "桔梗色": "#5654A2",
    "鈍色":   "#727171", "藍鼠":   "#6C848D", "利休鼠": "#888E7E",
    "銀鼠":   "#AFAFB0", "朽葉色": "#917347", "煤竹色": "#6F514C",
    "焦茶":   "#6F4B3E", "墨":     "#595857", "桧皮色": "#965042",
    "小豆色": "#96514D", "朱鷺色": "#F4B3C2", "撫子色": "#EEBBCB",
    "灰桜":   "#E8D3D1", "向日葵色": "#FCC800", "蜜柑色": "#F08300",
}

NEUTRAL_NAME = "白磁"
NEUTRAL_HEX = TRADITIONAL_COLORS[NEUTRAL_NAME]

# ── 情調カテゴリ（ラベル・アンカー伝統色・語彙）───────────────────
# 語彙は (語, 重み)。現代語と歴史的仮名遣ひ・旧字の異体を並記する
# （入力は現代語・手本は旧字旧仮名の双方に反応させるため）。
# 1 字語は誤照合（例: 月曜の「月」）があるため低重みに抑え、複合語を高重みにする。
_CATEGORIES: List[Tuple[str, str, str, List[Tuple[str, float]]]] = [
    ("haru", "春光", "桜色", [
        ("春", 1.0), ("桜", 1.2), ("櫻", 1.2), ("花見", 1.2), ("梅", 0.8),
        ("鶯", 1.0), ("うぐひす", 1.0), ("芽吹", 1.2), ("蝶", 0.8),
        ("麗らか", 1.2), ("うらら", 1.0), ("長閑", 1.0), ("のどか", 1.0),
        ("春風", 1.5), ("花びら", 1.0), ("花片", 1.0), ("菜の花", 1.2), ("若菜", 1.0),
    ]),
    ("wakaba", "若葉", "若竹色", [
        ("新緑", 1.5), ("若葉", 1.5), ("青葉", 1.2), ("緑", 0.8), ("みどり", 0.8),
        ("草原", 1.0), ("苔", 0.8), ("森", 0.8), ("木立", 0.8), ("竹", 0.6),
        ("野原", 0.8), ("薫風", 1.5), ("息吹", 1.0), ("木漏れ日", 1.2), ("若芽", 1.2),
    ]),
    ("youkou", "陽光", "山吹色", [
        ("太陽", 1.0), ("日差し", 1.2), ("日ざし", 1.2), ("陽射", 1.2),
        ("光", 0.5), ("ひかり", 0.6), ("輝", 0.8), ("かがや", 0.8),
        ("眩し", 1.0), ("まぶし", 1.0), ("晴れ", 1.0), ("向日葵", 1.5),
        ("ひまわり", 1.5), ("真夏", 1.2), ("炎天", 1.2), ("嬉し", 1.0),
        ("うれし", 1.0), ("喜び", 1.0), ("喜ば", 1.0), ("楽し", 1.0),
        ("たのし", 1.0), ("笑", 0.8), ("明るい", 1.0), ("希望", 1.0), ("朗らか", 1.2),
    ]),
    ("mizu", "水邊", "浅葱色", [
        ("海", 1.0), ("波", 1.0), ("浪", 1.0), ("川", 0.8), ("河", 0.6),
        ("湖", 1.0), ("水面", 1.2), ("みなも", 1.2), ("泉", 1.0),
        ("雫", 1.0), ("しづく", 1.0), ("潮", 1.0), ("舟", 0.8),
        ("涼し", 1.0), ("すずし", 1.0), ("清流", 1.5), ("渚", 1.2),
        ("磯", 1.0), ("せせらぎ", 1.5), ("流れ", 0.6),
    ]),
    ("tsuki", "月影", "月白", [
        ("月", 0.4), ("月夜", 1.5), ("月光", 1.5), ("月影", 1.5), ("名月", 1.5),
        ("満月", 1.2), ("三日月", 1.2), ("朧", 1.2), ("おぼろ", 1.2),
        ("静か", 0.8), ("しづか", 0.8), ("静寂", 1.2), ("冴え", 1.0),
        ("さやか", 1.0), ("星", 0.8), ("澄み", 0.8), ("澄んだ", 0.8),
    ]),
    ("yoru", "夜陰", "紺青", [
        ("夜", 0.8), ("闇", 1.2), ("やみ", 1.0), ("宵", 1.0), ("よひ", 1.0),
        ("夜更け", 1.2), ("深夜", 1.0), ("真夜中", 1.2), ("灯", 0.8),
        ("ともしび", 1.0), ("燈", 0.8), ("蝋燭", 1.0), ("蠟燭", 1.0),
        ("梟", 1.0), ("幽", 0.8), ("眠り", 0.6),
    ]),
    ("yume", "夢幻", "藤色", [
        ("夢", 1.0), ("幻", 1.2), ("まぼろし", 1.2), ("霞", 1.0), ("かすみ", 1.0),
        ("霧", 1.0), ("朝霧", 1.2), ("靄", 1.2), ("もや", 0.6), ("陽炎", 1.0),
        ("うつつ", 1.0), ("面影", 1.0), ("おもかげ", 1.0), ("ほのか", 0.8),
        ("たゆた", 1.2), ("揺らめ", 1.0), ("ゆらめ", 1.0),
    ]),
    ("koi", "戀情", "韓紅", [
        ("恋", 1.2), ("戀", 1.2), ("こひ", 0.8), ("恋し", 1.5), ("戀し", 1.5),
        ("慕", 1.2), ("愛し", 1.2), ("いとし", 1.2), ("逢瀬", 1.5),
        ("契り", 1.0), ("想い人", 1.5), ("思ひ人", 1.5), ("口づけ", 1.5),
        ("くちづけ", 1.5), ("ときめ", 1.2), ("焦がれ", 1.5), ("こがれ", 1.2),
        ("頬", 0.6), ("紅", 0.6),
    ]),
    ("jou", "情炎", "茜色", [
        ("夕焼", 1.5), ("夕燒", 1.5), ("茜", 1.5), ("夕日", 1.2), ("夕陽", 1.2),
        ("落日", 1.2), ("燃え", 1.0), ("燃ゆ", 1.2), ("炎", 1.2), ("ほのほ", 1.2),
        ("焔", 1.2), ("血潮", 1.2), ("熱い", 0.8), ("熱き", 1.0),
        ("怒り", 1.2), ("怒れ", 1.2), ("激し", 1.0), ("はげし", 1.0),
        ("叫び", 1.0), ("滾", 1.2), ("たぎ", 1.0),
    ]),
    ("aishu", "哀愁", "藍鼠", [
        ("悲し", 1.5), ("かなし", 1.2), ("哀", 1.2), ("淋し", 1.5), ("寂し", 1.5),
        ("さびし", 1.2), ("さみし", 1.2), ("涙", 1.2), ("淚", 1.2), ("なみだ", 1.2),
        ("泣", 1.0), ("嘆", 1.2), ("なげき", 1.2), ("憂", 1.2), ("うれひ", 1.2),
        ("愁", 1.2), ("切な", 1.2), ("せつな", 1.2), ("別れ", 1.2), ("わかれ", 1.0),
        ("侘し", 1.2), ("儚", 1.2), ("はかな", 1.2), ("雨", 0.8), ("時雨", 1.2),
        ("しぐれ", 1.2), ("曇", 0.8), ("くもり", 0.8), ("秋雨", 1.2),
        ("独り", 1.0), ("ひとり", 0.6), ("孤独", 1.2),
    ]),
    ("kaikyu", "懷舊", "朽葉色", [
        ("懐かし", 1.5), ("なつかし", 1.5), ("懷かし", 1.5), ("昔", 1.0),
        ("むかし", 1.0), ("故郷", 1.5), ("ふるさと", 1.5), ("いにしへ", 1.2),
        ("思ひ出", 1.2), ("思い出", 1.2), ("落葉", 1.2), ("落ち葉", 1.2),
        ("枯れ", 1.0), ("枯る", 1.0), ("朽ち", 1.2), ("錆", 1.0),
        ("廃", 0.8), ("名残", 1.2), ("なごり", 1.2), ("蔦", 0.8), ("苔むす", 1.2),
    ]),
    ("yuki", "雪冽", "藍白", [
        ("雪", 1.2), ("吹雪", 1.5), ("霜", 1.2), ("氷", 1.2), ("こほり", 1.2),
        ("凍", 1.2), ("冬", 1.0), ("寒", 1.0), ("冷た", 1.0), ("つめた", 1.0),
        ("白妙", 1.5), ("木枯", 1.2), ("こがらし", 1.2), ("凩", 1.2),
        ("清らか", 1.0), ("きよらか", 1.0),
    ]),
    ("aki", "秋思", "琥珀色", [
        ("秋", 1.0), ("紅葉", 1.5), ("もみぢ", 1.5), ("もみじ", 1.2),
        ("稲穂", 1.2), ("芒", 1.2), ("すすき", 1.2), ("虫の音", 1.5),
        ("鈴虫", 1.2), ("蜩", 1.2), ("ひぐらし", 1.0), ("黄昏", 1.2),
        ("たそがれ", 1.2), ("実り", 1.0), ("銀杏", 1.2), ("葡萄", 0.8),
    ]),
]

_LABELS = {cid: label for cid, label, _, _ in _CATEGORIES}
_ANCHORS = {cid: TRADITIONAL_COLORS[anchor] for cid, _, anchor, _ in _CATEGORIES}

# 生成プロンプトへヒントを入れる入力信号の下限（弱い連想で変換を歪めない）
HINT_MIN_STRENGTH = 0.4
# strength 正規化: おおよそ通常語 3 語相当の照合で 1.0 に飽和
_STRENGTH_SATURATION = 3.0
# 同一語の照合回数上限（1 語の反復で分布が偏り過ぎないように）
_MAX_TERM_COUNT = 3


# ── Oklab 色空間（Björn Ottosson の定義。知覚的に自然な混合のため）──
def _hex_to_rgb(h: str) -> Tuple[float, float, float]:
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))  # type: ignore[return-value]


def _rgb_to_hex(rgb: Tuple[float, float, float]) -> str:
    return "#%02X%02X%02X" % tuple(
        max(0, min(255, round(c * 255))) for c in rgb
    )


def _srgb_to_linear(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _linear_to_srgb(c: float) -> float:
    c = max(0.0, min(1.0, c))
    return 12.92 * c if c <= 0.0031308 else 1.055 * (c ** (1 / 2.4)) - 0.055


def _cbrt(x: float) -> float:
    return x ** (1 / 3) if x >= 0 else -((-x) ** (1 / 3))


def hex_to_oklab(h: str) -> Tuple[float, float, float]:
    r, g, b = (_srgb_to_linear(c) for c in _hex_to_rgb(h))
    l = 0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b
    m = 0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b
    s = 0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b
    l_, m_, s_ = _cbrt(l), _cbrt(m), _cbrt(s)
    return (
        0.2104542553 * l_ + 0.7936177850 * m_ - 0.0040720468 * s_,
        1.9779984951 * l_ - 2.4285922050 * m_ + 0.4505937099 * s_,
        0.0259040371 * l_ + 0.7827717662 * m_ - 0.8086757660 * s_,
    )


def oklab_to_hex(lab: Tuple[float, float, float]) -> str:
    L, a, b = lab
    l_ = L + 0.3963377774 * a + 0.2158037573 * b
    m_ = L - 0.1055613458 * a - 0.0638541728 * b
    s_ = L - 0.0894841775 * a - 1.2914855480 * b
    l, m, s = l_ ** 3, m_ ** 3, s_ ** 3
    r = +4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s
    g = -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s
    bb = -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s
    return _rgb_to_hex(tuple(_linear_to_srgb(c) for c in (r, g, bb)))  # type: ignore[arg-type]


def mix_colors(weighted: List[Tuple[str, float]]) -> str:
    """(hex, weight) の列を Oklab で重み付き平均して hex を返す。全重み 0 は中立色。"""
    total = sum(w for _, w in weighted if w > 0)
    if total <= 0:
        return NEUTRAL_HEX
    acc = [0.0, 0.0, 0.0]
    for h, w in weighted:
        if w <= 0:
            continue
        lab = hex_to_oklab(h)
        for i in range(3):
            acc[i] += lab[i] * (w / total)
    return oklab_to_hex((acc[0], acc[1], acc[2]))


def nearest_color(h: str) -> Tuple[str, str]:
    """伝統色表から Oklab 距離最小の (名, hex) を返す。"""
    lab = hex_to_oklab(h)
    best = (float("inf"), NEUTRAL_NAME, NEUTRAL_HEX)
    for name, chex in TRADITIONAL_COLORS.items():
        cl = hex_to_oklab(chex)
        d = sum((lab[i] - cl[i]) ** 2 for i in range(3))
        if d < best[0]:
            best = (d, name, chex)
    return best[1], best[2]


# ── 情調推定 ─────────────────────────────────────────────
def _match_spans(text: str) -> List[Tuple[int, int, str, str, float]]:
    """全語彙の出現位置 (start, end, term, cid, weight) を列挙し、
    別語の内部に完全に含まれる照合を除外する（長い語＝複合語を優先）。
    例:「陽炎」が「炎」(情炎) を、「血潮」が「潮」(水邊) を誤発火させない。"""
    occ: List[Tuple[int, int, str, str, float]] = []
    for cid, _label, _anchor, terms in _CATEGORIES:
        for term, weight in terms:
            start = 0
            while True:
                i = text.find(term, start)
                if i < 0:
                    break
                occ.append((i, i + len(term), term, cid, weight))
                start = i + 1
    # 長い照合から確定し、別語の確定済み範囲に含まれるものは棄却
    occ.sort(key=lambda o: (-(o[1] - o[0]), o[0]))
    kept: List[Tuple[int, int, str, str, float]] = []
    for o in occ:
        if any(k[0] <= o[0] and o[1] <= k[1] and k[2] != o[2] for k in kept):
            continue
        kept.append(o)
    return kept


def text_moods(text: str) -> Tuple[Dict[str, float], float]:
    """文 → (カテゴリ分布(和=1 or 空), 信号強度 0..1)。照合ゼロなら ({}, 0.0)。"""
    counts: Dict[Tuple[str, str], int] = {}
    weights: Dict[Tuple[str, str], float] = {}
    for _s, _e, term, cid, weight in _match_spans(text):
        key = (cid, term)
        counts[key] = counts.get(key, 0) + 1
        weights[key] = weight
    raw: Dict[str, float] = {}
    for (cid, _term), n in counts.items():
        raw[cid] = raw.get(cid, 0.0) + weights[(cid, _term)] * min(n, _MAX_TERM_COUNT)
    total = sum(raw.values())
    if total <= 0:
        return {}, 0.0
    dist = {cid: v / total for cid, v in raw.items()}
    strength = min(1.0, total / _STRENGTH_SATURATION)
    return dist, strength


def text_color(text: str) -> Tuple[str, float, Dict[str, float]]:
    """文 → (hex, 信号強度, カテゴリ分布)。無信号なら中立色・強度 0。"""
    dist, strength = text_moods(text)
    if not dist:
        return NEUTRAL_HEX, 0.0, {}
    hexv = mix_colors([(_ANCHORS[cid], p) for cid, p in dist.items()])
    return hexv, strength, dist


def _color_entry(hexv: str, strength: Optional[float] = None) -> Dict:
    name, _ = nearest_color(hexv)
    entry: Dict = {"hex": hexv, "name": name}
    if strength is not None:
        entry["strength"] = round(strength, 3)
    return entry


def estimate_palette(input_text: str, exemplar_texts: List[str]) -> Dict:
    """入力文と文体手本群から共感覚パレットを推定する。

    Returns dict:
      input    — 入力文の色 {hex, name, strength}
      exemplar — 手本群の合成色 {hex, name, strength}（各手本の強度で重み付け）
      blend    — 両者の補間色（連想の中心）{hex, name}
      stops    — 表示用グラデーション [input, blend, exemplar]
      sources  — 各手本の色 [{hex, name, strength}, ...]（呼び出し側でチャンクに付与）
      categories — 支配的な情調ラベル（最大 2、例 ["哀愁", "月影"]）
      hint     — 生成プロンプトへ添える一文。入力信号が弱ければ None
    """
    in_hex, in_str, in_dist = text_color(input_text)

    src_entries: List[Dict] = []
    src_pairs: List[Tuple[str, float]] = []
    ex_dist_acc: Dict[str, float] = {}
    for t in exemplar_texts:
        h, s, d = text_color(t or "")
        src_entries.append(_color_entry(h, s))
        src_pairs.append((h, s))
        for cid, p in d.items():
            ex_dist_acc[cid] = ex_dist_acc.get(cid, 0.0) + p * s
    # 手本の合成色: 各手本を強度で重み付け（無信号の手本が色を薄めない）
    ex_hex = mix_colors(src_pairs)
    ex_str = min(1.0, sum(s for _, s in src_pairs) / max(1, len(src_pairs)))

    # 連想（補間）: 入力を主、手本を従として Oklab で混合。
    # 微小の基礎重みにより双方無信号でも中立色に定まる。
    blend_hex = mix_colors([
        (in_hex, 0.6 * in_str + 0.05),
        (ex_hex, 0.4 * ex_str + 0.05),
    ])

    # 支配的な情調ラベル（入力 0.6 : 手本 0.4）
    combined: Dict[str, float] = {}
    for cid, p in in_dist.items():
        combined[cid] = combined.get(cid, 0.0) + 0.6 * p * in_str
    ex_total = sum(ex_dist_acc.values())
    if ex_total > 0:
        for cid, v in ex_dist_acc.items():
            combined[cid] = combined.get(cid, 0.0) + 0.4 * (v / ex_total) * ex_str
    labels = [
        _LABELS[cid]
        for cid, _ in sorted(combined.items(), key=lambda kv: -kv[1])[:2]
        if combined[cid] > 0
    ]

    blend = _color_entry(blend_hex)
    hint: Optional[str] = None
    if in_str >= HINT_MIN_STRENGTH and labels:
        hint = (
            f"なほ、この依頼文の帯びる色合ひは「{blend['name']}」——"
            f"{'・'.join(labels)}の氣配なり。語彙と情景の選び方にこの色調を"
            f"ほのかに滲ませよ（ただし意味の正確な変換・作文を常に最優先し、"
            f"色名そのものを文中に書き込む必要はない）。"
        )

    return {
        "input": _color_entry(in_hex, in_str),
        "exemplar": _color_entry(ex_hex, ex_str),
        "blend": blend,
        "stops": [in_hex, blend_hex, ex_hex],
        "sources": src_entries,
        "categories": labels,
        "hint": hint,
    }
