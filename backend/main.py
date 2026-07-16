"""
main.py — bungo-rag バックエンド API（FastAPI）

Android/iOS ネイティブアプリ向けに app/rag.py を再利用して
RAG（検索 + ストリーミング生成）を HTTP API として公開する。

レスポンスは NDJSON（application/x-ndjson）ストリーム。1 行 = 1 JSON:
  {"type":"token","content":"…"} / {"type":"sources","sources":[…]}
  {"type":"done"}                 / {"type":"error","message":"…"}

セキュリティ/コスト対策（/chat は無認証・--ingress external・高単価LLM）:
  1) 入力クランプ（ChatRequest の Field）  … 1 リクエストの増幅を有界化
  2) 階層レート制限（rate_limit 依存）      … 不特定多数=控えめ枠／関係者=追加枠
  3) 本文サイズ上限・セキュリティヘッダ（middleware）
  4) エラー詳細の非開示（str(e) を返さずサーバログのみ）
限界と運用（TRUSTED_* の設定先、Foundry TPM クォータが真の $ 上限）は
CLAUDE.md「Abuse / cost guards」を参照。全ての閾値は env で調整可能。
"""
import os
import sys
import json
import time
import hmac
import logging
import ipaddress
from collections import deque, defaultdict
from typing import List

from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# app/rag.py を単一の RAG ロジックとして再利用する
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
from rag import stream_answer  # noqa: E402

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("bungo-api")

app = FastAPI(title="bungo-rag API", version="1.0.0")


# ── 設定（全て env で調整可能）──────────────────────────────
def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


# 入力クランプ（1 リクエストの増幅を有界化）
MAX_MESSAGE_CHARS = _int("MAX_MESSAGE_CHARS", 4000)   # 1 発話の上限
MAX_CONTENT_CHARS = _int("MAX_CONTENT_CHARS", 4000)   # 履歴 1 件の上限
MAX_HISTORY_ITEMS = _int("MAX_HISTORY_ITEMS", 16)     # =8 往復（rag は [-8:]）
MAX_TOP_K         = _int("MAX_TOP_K", 10)             # 製品が露出する最大値
MAX_BODY_BYTES    = _int("MAX_BODY_BYTES", 65536)     # 本文サイズ上限（64KB）

# 階層レート制限（インメモリ・レプリカ毎・scale-to-zero で消滅するソフト上限）。
# 真の $/時 ハード上限は Foundry デプロイの TPM クォータ（Azure 側）が担う。
RATE_WINDOW_SEC           = _int("RATE_WINDOW_SEC", 60)
RATE_MAX_PER_IP           = _int("RATE_MAX_PER_IP", 15)            # 不特定多数
RATE_MAX_PER_IP_TRUSTED   = _int("RATE_MAX_PER_IP_TRUSTED", 120)   # 関係者
DAILY_REQUEST_CAP         = _int("DAILY_REQUEST_CAP", 500)         # 公開の総量/24h
DAILY_REQUEST_CAP_TRUSTED = _int("DAILY_REQUEST_CAP_TRUSTED", 5000)

# 関係者(trusted)の識別:
#   ・IP 許可リスト TRUSTED_IPS（カンマ区切り・CIDR 可）… XFF は詐称可のため
#     ベストエフォート。設置場所固定の関係者向けの簡便策。
#   ・共有キー TRUSTED_KEYS（カンマ区切り・X-API-Key ヘッダで送る）… 詐称耐性あり・推奨。
#   どちらか一致で「関係者」枠。公開/関係者は別々の日次バジェットを持ち双方に上限が
#   あるため、キー漏洩や IP 詐称があっても総コストは有界。
#   ⚠ TRUSTED_IPS/TRUSTED_KEYS は Container App の env に設定すること。公開リポジトリに
#     コミットしてはならない（関係者の自宅 IP 露出・秘密漏洩になる）。
def _parse_nets(spec: str):
    nets = []
    for part in (spec or "").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            nets.append(ipaddress.ip_network(part, strict=False))
        except ValueError:
            log.warning("TRUSTED_IPS の不正なエントリを無視: %s", part)
    return nets


TRUSTED_NETS = _parse_nets(os.getenv("TRUSTED_IPS", ""))
TRUSTED_KEYS = tuple(k.strip() for k in os.getenv("TRUSTED_KEYS", "").split(",") if k.strip())

# CORS（既定 * は無認証 API では低リスク。必要なら ALLOWED_ORIGINS で絞る）
ALLOWED_ORIGINS = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", "*").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

# ── レート制限の状態（インメモリ）───────────────────────────
_ip_hits: "defaultdict[str, deque]" = defaultdict(deque)   # ip -> 直近リクエスト時刻
_daily = {"day": -1, "public": 0, "trusted": 0}            # UTC 暦日ごとの件数


def _client_ip(request: Request) -> str:
    """Container Apps(Envoy) 経由の推定クライアント IP（左端 XFF）。
    XFF は詐称可能なため識別はベストエフォート（総量の砦は日次上限）。"""
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _ip_trusted(ip_str: str) -> bool:
    if not TRUSTED_NETS:
        return False
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    return any(ip in n for n in TRUSTED_NETS)


def _key_trusted(request: Request) -> bool:
    if not TRUSTED_KEYS:
        return False
    key = request.headers.get("x-api-key", "")
    # 定数時間比較（タイミング攻撃対策）
    return bool(key) and any(hmac.compare_digest(key, t) for t in TRUSTED_KEYS)


def _is_trusted(ip: str, request: Request) -> bool:
    # キー一致（詐称耐性）を優先、無ければ IP 許可リスト（ベストエフォート）
    return _key_trusted(request) or _ip_trusted(ip)


def rate_limit(request: Request) -> None:
    """階層レート制限。関係者(trusted)は per-IP・日次とも追加枠。
    公開と関係者で別々の日次バジェットを持ち双方に上限があるため、キー漏洩や
    IP 詐称があっても総コストは有界（＋Foundry TPM が最終的なハード上限）。"""
    now = time.time()
    ip = _client_ip(request)
    trusted = _is_trusted(ip, request)
    bucket = "trusted" if trusted else "public"

    # グローバル日次上限（UTC 暦日でリセット）— スプーフ耐性のある砦
    day = int(now // 86400)
    if _daily["day"] != day:
        _daily.update(day=day, public=0, trusted=0)
    daily_cap = DAILY_REQUEST_CAP_TRUSTED if trusted else DAILY_REQUEST_CAP
    if _daily[bucket] >= daily_cap:
        log.warning("daily cap 到達 bucket=%s ip=%s", bucket, ip)
        raise HTTPException(429, "daily request cap reached",
                            headers={"Retry-After": "3600"})

    # per-IP 固定ウィンドウ（層別上限・ベストエフォート）
    per_ip_max = RATE_MAX_PER_IP_TRUSTED if trusted else RATE_MAX_PER_IP
    dq = _ip_hits[ip]
    cutoff = now - RATE_WINDOW_SEC
    while dq and dq[0] <= cutoff:
        dq.popleft()
    if len(dq) >= per_ip_max:
        log.warning("rate limit 到達 ip=%s trusted=%s", ip, trusted)
        raise HTTPException(429, "rate limit exceeded",
                            headers={"Retry-After": str(RATE_WINDOW_SEC)})
    dq.append(now)
    _daily[bucket] += 1

    # XFF 詐称でマップが肥大しないよう空 deque を間引く
    if len(_ip_hits) > 10000:
        for k in [k for k, v in _ip_hits.items() if not v]:
            del _ip_hits[k]


@app.middleware("http")
async def _guard(request: Request, call_next):
    """本文サイズ上限（Content-Length ベース）＋セキュリティヘッダ。
    chunked 送信で Content-Length が無い場合も、本文中の文字列は後段の
    pydantic char クランプで有界化される。"""
    cl = request.headers.get("content-length")
    if cl and cl.isdigit() and int(cl) > MAX_BODY_BYTES:
        return JSONResponse({"detail": "request body too large"}, status_code=413)
    resp = await call_next(request)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Referrer-Policy"] = "no-referrer"
    return resp


class ChatMessage(BaseModel):
    role: str       # "user" | "assistant"
    content: str = Field(max_length=MAX_CONTENT_CHARS)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=MAX_MESSAGE_CHARS)
    history: List[ChatMessage] = Field(default_factory=list, max_length=MAX_HISTORY_ITEMS)
    top_k: int = Field(default=5, ge=1, le=MAX_TOP_K)
    # 共感覚レイヤー（情調→伝統色）。省略時 ON。旧クライアントは送らない→既定で有効。
    synesthesia: bool = True


@app.get("/health")
def health():
    # BUILD_SHA はデプロイ CI（deploy-backend.yml）が注入する git SHA。
    # 3クライアント共通の SSOT（app/rag.py）がどの版で動いているかの追跡用。
    return {"status": "ok", "version": os.getenv("BUILD_SHA", "dev")}


@app.post("/chat")
def chat(req: ChatRequest, _rl: None = Depends(rate_limit)):
    """RAG 応答を NDJSON でストリーミングする。入力上限・レート制限は上記参照。"""

    def gen():
        try:
            token_stream, sources, palette = stream_answer(
                user_message=req.message,
                history=[m.model_dump() for m in req.history],
                top=req.top_k,
                synesthesia=req.synesthesia,
            )
            for token in token_stream:
                yield json.dumps(
                    {"type": "token", "content": token}, ensure_ascii=False
                ) + "\n"
            # 共感覚パレットは sources イベントの追加キーとして返す。
            # 新イベント型を増やすと旧 Android が落ちる（未知 type は throw）ため、
            # 既知イベントへの追加キー（両クライアントとも無視できる）に限定する。
            sources_event = {"type": "sources", "sources": sources}
            if palette is not None:
                sources_event["palette"] = palette
            yield json.dumps(sources_event, ensure_ascii=False) + "\n"
            yield json.dumps({"type": "done"}, ensure_ascii=False) + "\n"
        except Exception:  # noqa: BLE001 — クライアントに必ずエラーイベントを返す
            # 詳細（エンドポイント URL・モデル名・Azure エラー等）はサーバログのみに残し、
            # クライアントには一般化メッセージを返して情報漏洩を防ぐ。
            log.exception("chat generation failed")
            yield json.dumps(
                {"type": "error",
                 "message": "生成中にエラーが発生しました。時間をおいて再度お試しください。"},
                ensure_ascii=False,
            ) + "\n"

    return StreamingResponse(gen(), media_type="application/x-ndjson")


log.info(
    "bungo-api guards: per_ip(pub=%d/trusted=%d)/%ds daily(pub=%d/trusted=%d) "
    "trusted_nets=%d trusted_keys=%d max_body=%dB max_top_k=%d",
    RATE_MAX_PER_IP, RATE_MAX_PER_IP_TRUSTED, RATE_WINDOW_SEC,
    DAILY_REQUEST_CAP, DAILY_REQUEST_CAP_TRUSTED,
    len(TRUSTED_NETS), len(TRUSTED_KEYS), MAX_BODY_BYTES, MAX_TOP_K,
)
