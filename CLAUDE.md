# bungo-rag — 開発ガイド

## プロジェクト概要

青空文庫をコーパスとした **戦前日本語文体 RAG チャットボット**。
現代語テキストを旧字旧仮名・文語体に変換・作文する Streamlit アプリ。

## アーキテクチャ

```
app/app.py            — Streamlit UI
app/rag.py            — RAGコア（検索 + ストリーミング生成、プロバイダ非依存）
app/vector_store.py   — ローカルハイブリッド検索（numpyコサイン + 文字bigram BM25）
scripts/build_index.py — 青空文庫(GitHubミラー)からコーパス構築
corpus/               — ローカル検索インデックス（index.npz + meta.json）
docs/zero-cost.md     — ゼロコスト構成のセットアップガイド
requirements.txt      — Python依存
Dockerfile            — コンテナ定義
.github/workflows/
  deploy.yml          — Azure向けCI/CD（Azure利用時のみ）
  build-index.yml     — 検索インデックス構築（手動実行、corpus/を自動コミット）
```

## バックエンド構成（2系統・環境変数で切替）

### ゼロコスト構成（推奨・既定）

Azure 不要。詳細は `docs/zero-cost.md`。

| 機能 | 実装 | 設定キー |
|---|---|---|
| 検索 | `corpus/` をローカル検索（`VECTOR_BACKEND=auto`で自動選択） | `CORPUS_DIR`（省略可） |
| Embedding | 任意の OpenAI 互換 API（推奨: Google AI Studio 無料キー） | `EMBED_ENDPOINT`, `EMBED_API_KEY`, `EMBED_DEPLOYMENT`, `EMBED_DIMENSIONS` |
| チャット生成 | 任意の OpenAI 互換 API（同上） | `CHAT_ENDPOINT`, `CHAT_API_KEY`, `CHAT_DEPLOYMENT` |

```env
EMBED_ENDPOINT=https://generativelanguage.googleapis.com/v1beta/openai/
EMBED_API_KEY=xxx
EMBED_DEPLOYMENT=gemini-embedding-001
EMBED_DIMENSIONS=1536
CHAT_ENDPOINT=https://generativelanguage.googleapis.com/v1beta/openai/
CHAT_API_KEY=xxx
CHAT_DEPLOYMENT=gemini-2.0-flash
```

### Azure 構成（後方互換・要PAYGサブスクリプション）

| サービス | 用途 | 設定キー |
|---|---|---|
| Azure AI Search | ベクトル検索 | `AZURE_SEARCH_ENDPOINT`, `AZURE_SEARCH_ADMIN_KEY`, `SEARCH_INDEX_NAME` |
| Azure OpenAI | Embedding | `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_API_KEY` |
| Azure Container Apps / ACR | ホスティング / イメージ | `bungo-app` / `bungoregistry.azurecr.io`（`bungo-rag-rg`） |

`VECTOR_BACKEND=azure` を明示すると Azure 検索を強制。

## ⚠️ 廃止済みサービスに関する注意（2026-07 時点）

- `models.inference.ai.azure.com`（GitHub Models 旧エンドポイント）は **2025-10-17 停止済み**。設定しても動かない。
- GitHub Models 本体（`models.github.ai`）も **2026-07-30 完全廃止**。依存先にしないこと。
- チャット/埋め込みは OpenAI 互換ならどこでも良い（コードはプロバイダ非ハードコード）。

## CI/CD フロー

- Azure 利用時: `main` push → `deploy.yml`（Docker→ACR→Container Apps。Secret `AZURE_CREDENTIALS` 必要）
- インデックス構築: Actions「Build Local Search Index」を手動実行（Secret `EMBED_API_KEY` 必要）

## 開発ブランチ運用

- 開発: 任意の `claude/*` featureブランチ
- 本番デプロイ: `main` へのマージで自動実行（Azure構成時）

## ローカル起動

```bash
pip install -r requirements.txt
# corpus/ を構築（初回のみ、docs/zero-cost.md 参照）し、.env を配置してから
streamlit run app/app.py
```
