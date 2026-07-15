"""
linter.py — 旧字旧仮名・文語体の決定的リンタ（依存ゼロ・LLM不使用・$0）

品質ロードマップ（docs/quality-roadmap.md）Phase 1 の要石。
生成物の「旧字体の徹底」「歴史的仮名遣い」「文語文体」の破れを、正規表現と
対応表だけで機械判定する。完全な仮名遣い判定は語の同定（形態素・語源）を
要するため、本リンタは **精度優先・再現率不完全** の設計。取りこぼしは
Phase 2 の LLM-as-judge が受け持つ。

使い方:
    python -m eval.linter <file>        # ファイルを検査
    echo "..." | python -m eval.linter  # 標準入力を検査
    from eval.linter import lint, score, check_copy

各違反は Violation(rule, severity, pos, found, expected, message)。
severity は "error"（規範違反が確定的）/ "warning"（文脈依存・規範選択の余地）。
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass, asdict
from typing import List, Optional

# ── 新字体 → 旧字体 対応表（R1 / 旧字徹底率で共用） ──────────────
# 確実に「新字体（当用/常用漢字体）」であり、旧字旧仮名文では旧字体を使うべき字のみ。
# 新旧同形（例: 花・山）や一対多で自動判定できない字（弁/予/余 等）は入れない。
KYUJI_MAP = {
    "亜": "亞", "悪": "惡", "圧": "壓", "囲": "圍", "医": "醫", "為": "爲",
    "壱": "壹", "隠": "隱", "栄": "榮", "営": "營", "衛": "衞", "駅": "驛",
    "円": "圓", "塩": "鹽", "応": "應", "欧": "歐", "黄": "黃", "温": "溫",
    "仮": "假", "価": "價", "画": "畫", "会": "會", "回": "囘", "壊": "壞",
    "懐": "懷", "絵": "繪", "拡": "擴", "覚": "覺", "学": "學", "岳": "嶽",
    "楽": "樂", "缶": "罐", "巻": "卷", "陥": "陷", "関": "關", "歓": "歡",
    "観": "觀", "気": "氣", "帰": "歸", "旧": "舊", "拠": "據", "挙": "擧",
    "虚": "虛", "峡": "峽", "挟": "挾", "郷": "鄕", "暁": "曉", "区": "區",
    "駆": "驅", "径": "徑", "恵": "惠", "経": "經", "継": "繼", "茎": "莖",
    "渓": "溪", "剣": "劍", "険": "險", "圏": "圈", "検": "檢", "権": "權",
    "献": "獻", "県": "縣", "戸": "戶", "呉": "吳", "娯": "娛", "広": "廣",
    "鉱": "鑛", "号": "號", "国": "國", "黒": "黑", "済": "濟", "斎": "齋",
    "剤": "劑", "雑": "雜", "参": "參", "桟": "棧", "蚕": "蠶", "惨": "慘",
    "賛": "贊", "残": "殘", "糸": "絲", "歯": "齒", "児": "兒", "辞": "辭",
    "湿": "濕", "実": "實", "写": "寫", "釈": "釋", "寿": "壽", "収": "收",
    "従": "從", "渋": "澀", "獣": "獸", "縦": "縱", "粛": "肅", "処": "處",
    "叙": "敍", "尚": "尙", "奨": "奬", "将": "將", "称": "稱", "焼": "燒",
    "証": "證", "乗": "乘", "浄": "淨", "剰": "剩", "壌": "壤", "嬢": "孃",
    "譲": "讓", "醸": "釀", "触": "觸", "嘱": "囑", "真": "眞", "寝": "寢",
    "慎": "愼", "尽": "盡", "図": "圖", "粋": "粹", "酔": "醉", "穂": "穗",
    "随": "隨", "髄": "髓", "枢": "樞", "数": "數", "瀬": "瀨", "声": "聲",
    "斉": "齊", "静": "靜", "窃": "竊", "摂": "攝", "説": "說", "専": "專",
    "浅": "淺", "戦": "戰", "践": "踐", "銭": "錢", "潜": "潛", "繊": "纖",
    "禅": "禪", "双": "雙", "壮": "壯", "争": "爭", "荘": "莊", "捜": "搜",
    "挿": "插", "巣": "巢", "総": "總", "騒": "騷", "増": "增", "臓": "臟",
    "蔵": "藏", "属": "屬", "続": "續", "堕": "墮", "対": "對", "体": "體",
    "帯": "帶", "滞": "滯", "台": "臺", "滝": "瀧", "択": "擇", "沢": "澤",
    "担": "擔", "単": "單", "胆": "膽", "団": "團", "断": "斷", "弾": "彈",
    "遅": "遲", "虫": "蟲", "昼": "晝", "鋳": "鑄", "庁": "廳", "徴": "徵",
    "聴": "聽", "鎮": "鎭", "逓": "遞", "鉄": "鐵", "点": "點", "転": "轉",
    "伝": "傳", "灯": "燈", "当": "當", "党": "黨", "盗": "盜", "稲": "稻",
    "闘": "鬪", "徳": "德", "独": "獨", "読": "讀", "届": "屆",
    "弐": "貳", "悩": "惱", "脳": "腦", "覇": "霸", "拝": "拜", "廃": "廢",
    "売": "賣", "麦": "麥", "発": "發", "髪": "髮", "抜": "拔", "蛮": "蠻",
    "秘": "祕", "浜": "濱", "瓶": "甁", "払": "拂", "仏": "佛", "併": "倂",
    "並": "竝", "餅": "餠", "辺": "邊", "変": "變", "宝": "寶", "褒": "襃",
    "豊": "豐", "翻": "飜", "毎": "每", "万": "萬", "満": "滿", "訳": "譯",
    "薬": "藥", "誉": "譽", "様": "樣", "謡": "謠", "来": "來", "頼": "賴",
    "乱": "亂", "覧": "覽", "竜": "龍", "両": "兩", "猟": "獵", "緑": "綠",
    "塁": "壘", "涙": "淚", "励": "勵", "礼": "禮", "齢": "齡", "暦": "曆",
    "歴": "歷", "恋": "戀", "錬": "鍊", "炉": "爐", "労": "勞", "郎": "郞",
    "楼": "樓", "録": "錄", "湾": "灣",
}
# 一対多・文脈依存で自動修正が危険な字（弁→辨/瓣/辯、予→豫/予 等）は
# 誤検出を避けるため KYUJI_MAP に含めない。将来 warning 化する場合の候補。
AMBIGUOUS_SHINJI = set("弁予余欠芸従")


@dataclass
class Violation:
    rule: str
    severity: str        # "error" | "warning"
    pos: int             # 文字オフセット（0始まり）
    found: str
    message: str
    expected: Optional[str] = None


# ── ルール定義 ──────────────────────────────────────────────
# 各ルールは text を受けて Violation のリストを返す関数。

def _r1_shinjitai(text: str) -> List[Violation]:
    """R1: 新字体漢字の出現（旧字旧仮名では旧字体を使うべき）。severity=error。"""
    out = []
    for i, ch in enumerate(text):
        exp = KYUJI_MAP.get(ch)
        if exp and exp != ch:
            out.append(Violation("R1", "error", i, ch,
                                 f"新字体「{ch}」→ 旧字体「{exp}」", exp))
    return out


_R2 = re.compile(r"てい(る|た|て|ます|ました|ません|ない|なく|よう|れ)")
def _r2_teiru(text: str) -> List[Violation]:
    """R2: 補助動詞「〜ている」系（歴史的仮名では「〜てゐる」）。severity=error。"""
    return [Violation("R2", "error", m.start(), m.group(),
                      f"「{m.group()}」→「{m.group().replace('てい','てゐ',1)}」")
            for m in _R2.finditer(text)]


_R5 = re.compile(r"でしょう|ましょう|でしたら|ましたら")
def _r5_modern_aux(text: str) -> List[Violation]:
    """R5: 「でしょう/ましょう」等の現代助動詞（→でせう/ませう）。severity=error。"""
    sub = {"でしょう": "でせう", "ましょう": "ませう"}
    return [Violation("R5", "error", m.start(), m.group(),
                      f"「{m.group()}」は現代仮名遣い", sub.get(m.group()))
            for m in _R5.finditer(text)]


# 口語の丁寧体・断定が「。」「、」「」で終わる（文語体に対する register 違反）
_R10 = re.compile(r"(です|ます|ました|でした|ません|でしょう|だった|ではない|ている)(。|、|」|\n|$)")
def _r10_colloquial_end(text: str) -> List[Violation]:
    """R10: 口語文末の混在（文語体では なり/べし/けり 等を用いる）。severity=error。"""
    return [Violation("R10", "error", m.start(1), m.group(1),
                      f"口語文末「{m.group(1)}」が文語体に混在")
            for m in _R10.finditer(text)]


def _r10b_register_mix(text: str) -> List[Violation]:
    """R10b: 候文（〜候）と和文文語（なり/べし/けり）が1応答内に併存（文体不統一）。
    severity=warning。現行 SYSTEM_PROMPT の few-shot がこれを犯している。"""
    has_sourou = bool(re.search(r"候(。|、|ふ|なり|$)", text)) or "にて候" in text
    m_wabun = re.search(r"(なり|べし|けり|たり)(。|、|」|$)", text)
    if has_sourou and m_wabun:
        return [Violation("R10b", "warning", m_wabun.start(),
                          m_wabun.group(1),
                          "候文と和文文語が併存（文体不統一）")]
    return []


_R11 = re.compile(r"(でも|だから|それで|とても|やっぱり|すごく|ちゃんと|きっと|ちょっと)")
def _r11_colloquial_lex(text: str) -> List[Violation]:
    """R11: 口語の接続詞・副詞（→されど/されば/いと 等）。severity=warning。"""
    return [Violation("R11", "warning", m.start(), m.group(),
                      f"口語語彙「{m.group()}」")
            for m in _R11.finditer(text)]


_R12 = re.compile(r"^\s*(はい[、。]?|承知|かしこまり|以下(に|の)|了解|わかりました|"
                  r"変換(します|いたします)|作文します|次のように)")
def _r12_preamble(text: str) -> List[Violation]:
    """R12: 前置き（「変換します」等）。冒頭から結果を出す規則に反する。severity=error。"""
    m = _R12.match(text)
    return [Violation("R12", "error", 0, m.group().strip(),
                      "前置きは禁止（冒頭から結果を出力する規則）")] if m else []


_R14 = re.compile(r"[※〓�]|《|》|［＃|〔＃")
def _r14_garbage(text: str) -> List[Violation]:
    """R14: 記号残骸・文字化け（青空文庫マークアップの除去漏れ等）。severity=error。"""
    return [Violation("R14", "error", m.start(), m.group(),
                      "記号残骸・文字化け")
            for m in _R14.finditer(text)]


RULES = [
    _r1_shinjitai, _r2_teiru, _r5_modern_aux,
    _r10_colloquial_end, _r10b_register_mix,
    _r11_colloquial_lex, _r12_preamble, _r14_garbage,
]


def lint(text: str) -> List[Violation]:
    """全ルールを適用し、違反を位置順に返す。"""
    out: List[Violation] = []
    for rule in RULES:
        out.extend(rule(text))
    out.sort(key=lambda v: (v.pos, v.rule))
    return out


def check_copy(output: str, exemplars: List[str], n: int = 10) -> List[str]:
    """R13: 出力が参照例から n 文字以上を連続転用していないか検査。
    句読点・空白を除いた上で共通部分文字列を探す。転用断片のリストを返す。"""
    def norm(s: str) -> str:
        return re.sub(r"[\s、。「」『』（）　]", "", s)
    o = norm(output)
    hits = []
    for ex in exemplars:
        e = norm(ex)
        # 長さ n の窓を総当り（コーパス断片は短いので実用上十分）
        seen = set()
        for i in range(len(e) - n + 1):
            frag = e[i:i + n]
            if frag in o and frag not in seen:
                seen.add(frag)
                hits.append(frag)
    return hits


def score(text: str) -> dict:
    """要約メトリクス。回帰監視に使う。"""
    vs = lint(text)
    errors = [v for v in vs if v.severity == "error"]
    warnings = [v for v in vs if v.severity == "warning"]
    # 旧字徹底率: KYUJI_MAP 対象字の全出現のうち旧字体で書かれた割合
    kyuji = sum(1 for ch in text if ch in KYUJI_MAP.values())
    shinji = sum(1 for ch in text if ch in KYUJI_MAP and KYUJI_MAP[ch] != ch)
    denom = kyuji + shinji
    kanji_ratio = (kyuji / denom) if denom else 1.0
    n = max(len(text), 1)
    return {
        "chars": len(text),
        "errors": len(errors),
        "warnings": len(warnings),
        "kana_violation_per_100": round(100 * len(errors) / n, 2),
        "kyuji_ratio": round(kanji_ratio, 3),
        "clean": len(errors) == 0,
    }


def _format(text: str) -> str:
    vs = lint(text)
    lines = []
    for v in vs:
        ctx = text[max(0, v.pos - 6):v.pos + 6].replace("\n", "⏎")
        lines.append(f"  [{v.severity:7}] {v.rule}: 「{v.found}」 …{ctx}…  {v.message}")
    s = score(text)
    head = (f"score: errors={s['errors']} warnings={s['warnings']} "
            f"kyuji_ratio={s['kyuji_ratio']} clean={s['clean']}")
    return head + ("\n" + "\n".join(lines) if lines else "\n  （違反なし）")


def main(argv: List[str]) -> int:
    text = (open(argv[1], encoding="utf-8").read() if len(argv) > 1
            else sys.stdin.read())
    print(_format(text))
    return 0 if score(text)["clean"] else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
