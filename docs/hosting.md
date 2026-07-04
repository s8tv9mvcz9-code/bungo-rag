# 無料ホスティングガイド（2026-07 調査）

ゼロコスト構成（`docs/zero-cost.md`）のアプリを無料で公開する2つの方法。
どちらも GitHub 連携で自動デプロイでき、クレジットカード不要。

## 比較

| | Streamlit Community Cloud | Hugging Face Spaces（CPU basic） |
|---|---|---|
| 料金 | 無料 | 無料 |
| スペック | 限定的（軽量アプリ向け） | 2 vCPU / 16GB RAM / 50GB disk |
| リポジトリ | **公開 GitHub リポジトリ必須** | Space側で公開/非公開を選択可 |
| スリープ | 非アクティブで休止→アクセスで復帰 | **48時間**非アクティブで休止 |
| デプロイ方式 | GitHub リポジトリを直接リンク | Space の git repo へ push（Action で同期可） |
| シークレット | ダッシュボードの Secrets（env として読める） | Space Settings の Secrets（env として読める） |
| 向き | Streamlit UI（本リポジトリ既定） | Docker なら FastAPI 等も可 |

本アプリは RAM 数百MB・外部API呼び出しのみの軽量構成なので、どちらでも動く。

## A. Streamlit Community Cloud（最短・推奨）

1. リポジトリを **public** にする（必須条件）
2. https://share.streamlit.io → New app → このリポジトリ / ブランチ / `app/app.py` を指定
3. Advanced settings → Secrets に以下を貼る（TOML形式。環境変数として注入される）:

```toml
EMBED_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/openai/"
EMBED_API_KEY = "xxx"
EMBED_DEPLOYMENT = "gemini-embedding-001"
EMBED_DIMENSIONS = "1536"
CHAT_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/openai/"
CHAT_API_KEY = "xxx"
CHAT_DEPLOYMENT = "gemini-2.0-flash"
```

4. Deploy。以後 `main` への push で自動再デプロイ。
   `corpus/` はリポジトリに含まれるため（Actions で構築後）、そのまま検索が動く。

## B. Hugging Face Spaces（非公開リポジトリ / 高スペックが欲しい場合）

1. https://huggingface.co/new-space → SDK は **Docker** を選択
2. Space の README.md 先頭メタデータに `app_port: 8501` を設定:

```yaml
---
title: bungo-rag
sdk: docker
app_port: 8501
---
```

3. このリポジトリの内容を Space の git repo へ push
   （`git remote add space https://huggingface.co/spaces/<user>/bungo-rag && git push space main`）
4. Space Settings → Variables and secrets に上記と同じキーを設定（環境変数として注入される）
5. 既存の `Dockerfile`（:8501 EXPOSE 済み）がそのままビルドされる

GitHub からの自動同期が欲しい場合は、HF_TOKEN を GitHub Secret に置き
`git push space` するだけの Action を追加すればよい。

## 注意

- 無料枠の仕様（スペック・スリープ時間・公開要件）は変わりうる。デプロイ前に公式を確認:
  - https://docs.streamlit.io/deploy/streamlit-community-cloud/status
  - https://huggingface.co/docs/hub/spaces-overview
- どちらもスリープ復帰時に数十秒のコールドスタートがある（Azure Container Apps の scale-to-zero と同様の体験）
- FastAPI バックエンド（Android 用、PR #4）を公開する場合は HF Spaces Docker（`app_port: 8000`）が適する
