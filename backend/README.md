# bungo-rag backend API

iOS / Android ネイティブアプリ向けに `app/rag.py`（SSOT）を再利用した RAG の HTTP API（FastAPI）。

## エンドポイント

| メソッド | パス | 説明 |
|---|---|---|
| GET | `/health` | ヘルスチェック（`{"status":"ok","version":"<git SHA>"}` — version は CD が注入する BUILD_SHA） |
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
{"type":"sources","sources":[{"title":"...","author":"...","style":"...","text":"...","book_id":"..."}]}
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

## Azure へのデプロイ

**通常は何もしなくてよい。** `main` へ push すると `.github/workflows/deploy-backend.yml` が
ghcr.io へビルド＆push → `bungo-api` を更新（**未作成なら bungo-app から環境変数を複製して自動作成**）→
`/health` が新しい git SHA を返すまで待つ疎通ゲート、まで全自動で行う。

手動でやりたい場合（ローカルの `.env` からシークレットを注入して作成/更新）：

```bash
az login
bash backend/deploy-api.sh   # ghcr ログイン→ビルド→push→create/update→URL表示
```

> 本番 URL（`https://bungo-api.gentleground-ba3d7ba2...`）は iOS / Android のビルドに
> 既定値として埋め込み済み。FQDN を変更した場合の更新箇所一覧は STATUS.md 参照。
