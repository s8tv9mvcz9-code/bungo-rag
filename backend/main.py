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
from typing import List

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

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


class ChatMessage(BaseModel):
    role: str       # "user" | "assistant"
    content: str


class ChatRequest(BaseModel):
    message: str
    history: List[ChatMessage] = []
    top_k: int = 5


@app.get("/health")
def health():
    # BUILD_SHA はデプロイ CI（deploy-backend.yml）が注入する git SHA。
    # 3クライアント共通の SSOT（app/rag.py）がどの版で動いているかの追跡用。
    return {"status": "ok", "version": os.getenv("BUILD_SHA", "dev")}


@app.post("/chat")
def chat(req: ChatRequest):
    """RAG 応答を NDJSON でストリーミングする。"""

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
