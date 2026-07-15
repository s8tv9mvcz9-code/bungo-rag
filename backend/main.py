"""
main.py — bungo-rag バックエンド API（FastAPI）

Android ネイティブアプリ向けに app/rag.py を再利用して
RAG（検索 + ストリーミング生成）を HTTP API として公開する。

レスポンスは NDJSON（application/x-ndjson）ストリーム。
1 行 = 1 JSON オブジェクトで、type により種別を区別する:
  {"type":"token","content":"…"}   生成トークン（逐次）
  {"type":"sources","sources":[…]} 参照した青空文庫チャンク
  {"type":"done"}                   正常終了
  {"type":"error","message":"…"}   エラー
"""
import os
import sys
import json
import time
from collections import deque, defaultdict
from typing import List

from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# app/rag.py を単一の RAG ロジックとして再利用する
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
from rag import stream_answer  # noqa: E402

app = FastAPI(title="bungo-rag API", version="1.0.0")

# ネイティブアプリ自体は CORS 不要だが、開発用 Web クライアントのために許可
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── 濫用・コスト対策 ─────────────────────────────────────────
# /chat は無認証の公開エンドポイント（--ingress external）で、モデルは高単価の
# claude-opus-4-8。防御は 2 層:
#   (1) 入力クランプ … 1 リクエストの増幅（top_k / message 長）を有界化（下の Field）
#   (2) レート制限   … 総量を抑える（下の rate_limit 依存）
# ※ 真の $/時 のハード上限は Foundry デプロイの TPM クォータ（Azure 側）が担う。
#   本レート制限はインメモリ（レプリカ毎・scale-to-zero で消滅）のソフト上限で、
#   X-Forwarded-For は詐称可能なため per-IP はベストエフォート。総量の砦は
#   グローバル日次上限で、これはスプーフ耐性がある。
MAX_MESSAGE_CHARS = int(os.getenv("MAX_MESSAGE_CHARS", "4000"))   # 1 発話の上限
MAX_CONTENT_CHARS = int(os.getenv("MAX_CONTENT_CHARS", "4000"))   # 履歴 1 件の上限
MAX_HISTORY_ITEMS = int(os.getenv("MAX_HISTORY_ITEMS", "16"))     # =8 往復（rag は [-8:]）
MAX_TOP_K         = int(os.getenv("MAX_TOP_K", "10"))             # 製品が露出する最大値
RATE_WINDOW_SEC   = int(os.getenv("RATE_WINDOW_SEC", "60"))
RATE_MAX_PER_IP   = int(os.getenv("RATE_MAX_PER_IP", "20"))       # ウィンドウ毎 / IP
DAILY_REQUEST_CAP = int(os.getenv("DAILY_REQUEST_CAP", "1000"))   # 24h グローバル上限

_ip_hits: "defaultdict[str, deque]" = defaultdict(deque)  # ip -> 直近リクエスト時刻
_daily = {"day": -1, "count": 0}


def _client_ip(request: Request) -> str:
    """Container Apps(Envoy) 経由の推定クライアント IP。左端の XFF を使う。
    XFF は詐称可能なため識別はベストエフォート（総量の砦は日次上限）。"""
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def rate_limit(request: Request) -> None:
    now = time.time()
    # グローバル日次上限（UTC 暦日でリセット）— スプーフ耐性のある砦
    day = int(now // 86400)
    if _daily["day"] != day:
        _daily["day"], _daily["count"] = day, 0
    if _daily["count"] >= DAILY_REQUEST_CAP:
        raise HTTPException(429, "daily request cap reached",
                            headers={"Retry-After": "3600"})
    # per-IP 固定ウィンドウ（ベストエフォート）
    ip = _client_ip(request)
    dq = _ip_hits[ip]
    cutoff = now - RATE_WINDOW_SEC
    while dq and dq[0] <= cutoff:
        dq.popleft()
    if len(dq) >= RATE_MAX_PER_IP:
        raise HTTPException(429, "rate limit exceeded",
                            headers={"Retry-After": str(RATE_WINDOW_SEC)})
    dq.append(now)
    _daily["count"] += 1
    # XFF 詐称でマップが肥大しないよう、空 deque を間引く（軽量プルーニング）
    if len(_ip_hits) > 10000:
        for k in [k for k, v in _ip_hits.items() if not v]:
            del _ip_hits[k]


class ChatMessage(BaseModel):
    role: str       # "user" | "assistant"
    content: str = Field(max_length=MAX_CONTENT_CHARS)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=MAX_MESSAGE_CHARS)
    history: List[ChatMessage] = Field(default_factory=list, max_length=MAX_HISTORY_ITEMS)
    top_k: int = Field(default=5, ge=1, le=MAX_TOP_K)


@app.get("/health")
def health():
    # BUILD_SHA はデプロイ CI（deploy-backend.yml）が注入する git SHA。
    # 3クライアント共通の SSOT（app/rag.py）がどの版で動いているかの追跡用。
    return {"status": "ok", "version": os.getenv("BUILD_SHA", "dev")}


@app.post("/chat")
def chat(req: ChatRequest, _rl: None = Depends(rate_limit)):
    """RAG 応答を NDJSON でストリーミングする。レート制限・入力上限は上記参照。"""

    def gen():
        try:
            token_stream, sources = stream_answer(
                user_message=req.message,
                history=[m.model_dump() for m in req.history],
                top=req.top_k,
            )
            for token in token_stream:
                yield json.dumps(
                    {"type": "token", "content": token}, ensure_ascii=False
                ) + "\n"
            yield json.dumps(
                {"type": "sources", "sources": sources}, ensure_ascii=False
            ) + "\n"
            yield json.dumps({"type": "done"}, ensure_ascii=False) + "\n"
        except Exception as e:  # noqa: BLE001 — クライアントに必ずエラーを返す
            yield json.dumps(
                {"type": "error", "message": str(e)}, ensure_ascii=False
            ) + "\n"

    return StreamingResponse(gen(), media_type="application/x-ndjson")
