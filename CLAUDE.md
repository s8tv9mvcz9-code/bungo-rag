# bungo-rag — 開発ガイド

## プロジェクト概要

青空文庫をコーパスとした **戦前日本語文体 RAG チャットボット**。
現代語テキストを旧字旧仮名・文語体に変換・作文する Streamlit アプリ。

## アーキテクチャ

```
app/app.py       — Streamlit UI
app/rag.py       — RAGコア（検索 + ストリーミング生成）
requirements.txt — Python依存
Dockerfile       — コンテナ定義
.github/workflows/deploy.yml — CI/CDパイプライン
```

### 外部サービス

| サービス | 用途 | 設定キー |
|---|---|---|
| Azure AI Search | ベクトル検索（青空文庫チャンク） | `AZURE_SEARCH_ENDPOINT`, `AZURE_SEARCH_ADMIN_KEY` |
| Azure OpenAI | Embedding生成（text-embedding-3-small） | `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_API_KEY` |
| GitHub Models / Azure OpenAI | チャット生成 | `CHAT_ENDPOINT`, `CHAT_API_KEY`, `CHAT_DEPLOYMENT` |
| Azure Container Registry | Dockerイメージ保管 | `bungoregistry.azurecr.io` |
| Azure Container Apps | アプリホスティング | `bungo-app`（`bungo-rag-rg`） |

### 環境変数（.env または Azure Container Apps シークレット）

```env
AZURE_SEARCH_ENDPOINT=https://xxx.search.windows.net
AZURE_SEARCH_ADMIN_KEY=xxx
SEARCH_INDEX_NAME=bungo-chunks
AZURE_OPENAI_ENDPOINT=https://xxx.openai.azure.com
AZURE_OPENAI_API_KEY=xxx
EMBED_DEPLOYMENT=text-embedding-3-small
CHAT_ENDPOINT=https://models.inference.ai.azure.com
CHAT_API_KEY=xxx
CHAT_DEPLOYMENT=Phi-4-mini
```

## CI/CD フロー

1. `main` ブランチに push
2. GitHub Actions が Docker ビルド → ACR プッシュ → Container Apps デプロイ
3. GitHub Secret `AZURE_CREDENTIALS` が必要（手動設定）

## 開発ブランチ運用

- 開発: `claude/iphone-claude-code-setup-d2w3m`（または任意のfeatureブランチ）
- 本番デプロイ: `main` へのマージで自動実行

## ローカル起動（参考）

```bash
pip install -r requirements.txt
# .env を配置してから
streamlit run app/app.py
```
