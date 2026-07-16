"""
test_security.py — backend/main.py の濫用・コスト対策の回帰テスト。

実行:
    python backend/test_security.py        # 成功で exit 0

外部通信・実モデルには一切触れない（stream_answer をモックし、rag のクライアントは
遅延初期化なのでダミー env でインポートできる）。CI（backend-ci.yml）で自動実行する。
"""
import os
import sys
import itertools
import warnings
import logging

warnings.filterwarnings("ignore")

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, os.path.join(_ROOT, "app"))   # rag / retrieval
sys.path.insert(0, _HERE)                         # main

# rag の import に必要なダミー env（実クライアントは遅延初期化なので通信は発生しない）
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

# テスト固有の guard 設定（main の import 前に確定させる必要がある）
os.environ["TRUSTED_IPS"] = "203.0.113.7,198.51.100.0/24"
os.environ["TRUSTED_KEYS"] = "relative-secret-1,relative-secret-2"
os.environ["MAX_BODY_BYTES"] = "100"

logging.disable(logging.CRITICAL)

import main as m  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

_c = TestClient(m.app)
_seq = itertools.count(1)


def _ok(**_k):
    return (iter(["変", "換"]), [{"title": "x"}], None)


m.stream_answer = _ok


def post(body=None, ip=None, key=None):
    body = body or {"message": "ok"}
    headers = {"x-forwarded-for": ip or f"10.0.0.{next(_seq)}"}
    if key:
        headers["x-api-key"] = key
    return _c.post("/chat", json=body, headers=headers)


def reset(**caps):
    m._ip_hits.clear()
    m._daily.update(day=-1, public=0, trusted=0)
    for k, v in caps.items():
        setattr(m, k, v)


def run():
    # (1) 入力クランプ + 本文サイズ上限
    reset(RATE_MAX_PER_IP=10_000, RATE_MAX_PER_IP_TRUSTED=10_000,
          DAILY_REQUEST_CAP=10_000, DAILY_REQUEST_CAP_TRUSTED=10_000)
    assert post({"message": "x", "top_k": 1000}).status_code == 422
    assert post({"message": "x", "top_k": 0}).status_code == 422
    assert post({"message": ""}).status_code == 422
    assert post({"message": "あ" * 5000}).status_code in (413, 422)   # 本文/文字数どちらかで拒否
    assert post({"message": "あ" * 80}).status_code == 413             # 本文>100B
    print("✓ 入力クランプ: top_k(0/1000)/空message=422、本文>100B=413")

    # (2) 公開枠 per-IP
    reset(RATE_MAX_PER_IP=3, RATE_MAX_PER_IP_TRUSTED=100,
          DAILY_REQUEST_CAP=10_000, DAILY_REQUEST_CAP_TRUSTED=10_000)
    assert [post(ip="9.9.9.9").status_code for _ in range(4)] == [200, 200, 200, 429]
    print("✓ 公開枠: per-IP 3→4件目429")

    # (2) 関係者IP枠（単一IP と CIDR）
    reset(RATE_MAX_PER_IP=3, RATE_MAX_PER_IP_TRUSTED=100,
          DAILY_REQUEST_CAP=10_000, DAILY_REQUEST_CAP_TRUSTED=10_000)
    assert [post(ip="203.0.113.7").status_code for _ in range(6)] == [200] * 6
    assert [post(ip="198.51.100.42").status_code for _ in range(6)] == [200] * 6
    print("✓ 関係者IP枠: 許可IP/CIDRは公開上限(3)超を許容")

    # (2) 共有キー枠（XFF詐称耐性・公開IPからでも昇格）／誤キーは公開枠へ
    reset(RATE_MAX_PER_IP=2, RATE_MAX_PER_IP_TRUSTED=100,
          DAILY_REQUEST_CAP=10_000, DAILY_REQUEST_CAP_TRUSTED=10_000)
    assert [post(ip="9.9.9.9", key="relative-secret-1").status_code for _ in range(5)] == [200] * 5
    assert [post(ip="3.3.3.3", key="wrong-key").status_code for _ in range(3)] == [200, 200, 429]
    print("✓ 共有キー枠: 正キーは昇格・誤キーは公開枠に落ちる")

    # (2) 公開日次枯渇でも関係者は別バジェットで継続
    reset(RATE_MAX_PER_IP=10_000, RATE_MAX_PER_IP_TRUSTED=10_000,
          DAILY_REQUEST_CAP=2, DAILY_REQUEST_CAP_TRUSTED=100)
    assert [post(ip=f"7.7.7.{i}").status_code for i in range(3)] == [200, 200, 429]
    assert post(ip="203.0.113.7").status_code == 200
    assert post(ip="9.9.9.9", key="relative-secret-2").status_code == 200
    print("✓ 公開日次枯渇時も関係者は別バジェットで継続")

    # (4) エラー詳細の非開示
    reset(RATE_MAX_PER_IP=10, RATE_MAX_PER_IP_TRUSTED=10,
          DAILY_REQUEST_CAP=100, DAILY_REQUEST_CAP_TRUSTED=100)

    def boom(**_k):
        raise RuntimeError("SECRET https://foundry.internal/anthropic deployment 'opus' key1=abcdef")

    m.stream_answer = boom
    r = post(ip="1.2.3.4")
    assert r.status_code == 200
    for leak in ("SECRET", "foundry.internal", "key1", "opus"):
        assert leak not in r.text, f"漏洩: {leak}"
    assert "生成中にエラー" in r.text
    m.stream_answer = _ok
    print("✓ エラー非開示: 例外詳細(URL/キー/モデル名)は出さずログのみ")

    # (3) セキュリティヘッダ
    h = _c.get("/health")
    assert h.status_code == 200
    assert h.headers.get("x-content-type-options") == "nosniff"
    assert h.headers.get("referrer-policy") == "no-referrer"
    print("✓ セキュリティヘッダ: nosniff / no-referrer")

    print("✅ backend security 全テスト成功")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
