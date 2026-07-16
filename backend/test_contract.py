"""
test_contract.py — 共感覚レイヤーの配線と NDJSON 契約の回帰テスト。

実行: python backend/test_contract.py
外部通信・実モデルには一切触れない（search/生成をモック、ダミー env でインポート）。
検証対象:
  1. rag.stream_answer — 3値返し・チャンクへの色付与・強信号時のみプロンプトへヒント注入
  2. backend /chat     — sources イベントへの palette 追加キー（後方互換）・イベント順
"""
import os
import sys
import json
import warnings

warnings.filterwarnings("ignore")

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, os.path.join(_ROOT, "app"))
sys.path.insert(0, _HERE)

for _k, _v in {
    "AZURE_SEARCH_ENDPOINT": "https://d.search.windows.net",
    "AZURE_SEARCH_ADMIN_KEY": "k",
    "AZURE_OPENAI_ENDPOINT": "https://d.openai.azure.com",
    "AZURE_OPENAI_API_KEY": "k",
    "CHAT_ENDPOINT": "https://d/anthropic",
    "CHAT_API_KEY": "k",
    "CHAT_DEPLOYMENT": "x",
}.items():
    os.environ.setdefault(_k, _v)

import logging  # noqa: E402
logging.disable(logging.CRITICAL)

import rag  # noqa: E402
import main as m  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

FAKE_CHUNKS = [
    {"title": "海のほとり", "author": "某", "style": "旧字旧仮名", "book_id": "1",
     "text": "月影さやかに、浪の音しづかなる磯邊なりけり"},
    {"title": "雑記", "author": "某", "style": "旧字新仮名", "book_id": "2",
     "text": "これは何の変哲もない説明の文章である"},
]


def _fresh_chunks():
    return [dict(c) for c in FAKE_CHUNKS]


def run():
    # ── 1. rag.stream_answer の配線 ─────────────────────────
    captured = {}

    def fake_search(query, top=5):
        return _fresh_chunks()

    def fake_anthropic(convo):
        captured["convo"] = convo
        return iter(["變", "換"])

    rag.search_chunks = fake_search
    rag._stream_anthropic = fake_anthropic

    # 強い情景語を含む入力 → palette あり・hint がプロンプトに入る
    gen, chunks, palette = rag.stream_answer("悲しい別れの涙が止まらない", [], top=2)
    assert palette is not None and palette["hint"], palette
    assert "sources" not in palette, "sources はチャンク付与後に除去される"
    assert all("color" in c and "color_name" in c for c in chunks), chunks
    user_msg = captured["convo"][-1]["content"]
    assert palette["hint"] in user_msg, "hint が拡張プロンプトに入っていない"
    assert "悲しい別れの涙が止まらない" in user_msg
    assert list(gen) == ["變", "換"]
    print("✓ rag: 3値返し・チャンク色付与・強信号でヒント注入")

    # 情景語なし → palette はあるが hint なし（プロンプト無汚染）
    gen2, _c2, p2 = rag.stream_answer("これを変換して下さい", [], top=2)
    assert p2 is not None and p2["hint"] is None
    assert "色合ひ" not in captured["convo"][-1]["content"]
    list(gen2)
    print("✓ rag: 弱信号ではプロンプトを汚さない")

    # synesthesia=False → palette None・色付与なし・ヒントなし
    _g3, c3, p3 = rag.stream_answer("悲しい別れの涙", [], top=2, synesthesia=False)
    assert p3 is None and all("color" not in c for c in c3)
    assert "色合ひ" not in captured["convo"][-1]["content"]
    print("✓ rag: synesthesia=False で完全に素通り")

    # ── 2. backend /chat の NDJSON 契約 ────────────────────
    def stub_stream_answer(**kw):
        captured["kw"] = kw
        pal = {"stops": ["#111111", "#222222", "#333333"],
               "blend": {"hex": "#222222", "name": "試"}} if kw.get("synesthesia", True) else None
        return (iter(["あ", "い"]),
                [{"title": "t", "color": "#111111", "color_name": "試"}],
                pal)

    m.stream_answer = stub_stream_answer
    m.RATE_MAX_PER_IP, m.DAILY_REQUEST_CAP = 10_000, 10_000
    m._ip_hits.clear(); m._daily.update(day=-1, public=0, trusted=0)
    c = TestClient(m.app)

    def post(body):
        r = c.post("/chat", json=body, headers={"x-forwarded-for": "10.9.9.9"})
        assert r.status_code == 200, r.status_code
        return [json.loads(line) for line in r.text.strip().splitlines()]

    # 既定（synesthesia 未指定 = True）: sources イベントに palette キー
    events = post({"message": "悲しい別れ"})
    types = [e["type"] for e in events]
    assert types == ["token", "token", "sources", "done"], types  # 順序契約は不変
    src = events[2]
    assert src["palette"]["blend"]["name"] == "試"
    assert src["sources"][0]["color"] == "#111111"       # 出典の追加キー
    assert captured["kw"]["synesthesia"] is True
    print("✓ backend: sources イベントに palette / 出典色（順序契約は不変）")

    # synesthesia=false 指定: palette キーが現れない（旧形と同一形）
    events2 = post({"message": "悲しい別れ", "synesthesia": False})
    assert captured["kw"]["synesthesia"] is False
    src2 = [e for e in events2 if e["type"] == "sources"][0]
    assert "palette" not in src2
    print("✓ backend: synesthesia=false で旧来と同一のイベント形")

    # 旧クライアント形のリクエスト（余計なフィールドなし）が従来どおり通る
    events3 = post({"message": "x", "history": [], "top_k": 3})
    assert [e["type"] for e in events3] == ["token", "token", "sources", "done"]
    print("✓ backend: 旧クライアントのリクエスト形も不変で受理")

    print("✅ contract 全テスト成功")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
