# bungo-rag backend API

Android ネイティブアプリ向けに `app/rag.py` を再利用した RAG の HTTP API（FastAPI）。

## エンドポイント

| メソッド | パス | 説明 |
|---|---|---|
| GET | `/health` | ヘルスチェック（`{"status":"ok"}`） |
| POST | `/chat` | RAG 応答を NDJSON ストリーミング |
| GET | `/docs` | Swagger UI |

### POST /chat リクエスト

```json
{
  "message": "今日はいい天気ですね",
  "history": [{"role":"user","content":"..."},{"role":"assistant","content":"..."}],
  "top_k": 5
}
```

### レスポンス（`application/x-ndjson`：1 行 = 1 JSON）

```
{"type":"token","content":"今"}
{"type":"token","content":"日"}
...
{"type":"sources","sources":[{"title":"...","author":"...","style":"...","text":"..."}]}
{"type":"done"}
```
エラー時は `{"type":"error","message":"..."}` を返す。

## ローカル起動

```bash
pip install -r requirements.txt          # RAG コア依存（リポジトリ直下）
pip install -r backend/requirements.txt  # API 依存
# .env を直下に配置（app/rag.py が読み込む）
uvicorn backend.main:app --reload --port 8000
```

## Docker（ビルドコンテキストはリポジトリ直下）

```bash
docker build -f backend/Dockerfile -t bungo-rag-api .
docker run -p 8000:8000 --env-file .env bungo-rag-api
```

## Azure へのデプロイ（既存の Container Apps 構成を流用）

既存の Streamlit デプロイと同じ ACR / リソースグループを使い、別アプリとして公開できる：

```bash
IMAGE=bungoregistry.azurecr.io/bungo-rag-api:latest
docker buildx build --platform linux/amd64 -f backend/Dockerfile -t "$IMAGE" --push .

az containerapp create \
  --name bungo-api \
  --resource-group bungo-rag-rg \
  --environment bungo-env \
  --image "$IMAGE" \
  --target-port 8000 --ingress external \
  --env-vars AZURE_SEARCH_ENDPOINT=... AZURE_SEARCH_ADMIN_KEY=... \
             SEARCH_INDEX_NAME=bungo-chunks \
             AZURE_OPENAI_ENDPOINT=... AZURE_OPENAI_API_KEY=... \
             EMBED_DEPLOYMENT=text-embedding-3-small \
             CHAT_ENDPOINT=... CHAT_API_KEY=... CHAT_DEPLOYMENT=Phi-4-mini
```

> 公開後の FQDN を Android の `BUNGO_BASE_URL`（`https://...`）に設定する。
> HTTPS になれば Android 側の cleartext 許可（network_security_config）は不要。
