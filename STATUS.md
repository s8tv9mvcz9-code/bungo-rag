# 📌 プロジェクト現況・引き継ぎメモ（bungo-rag）

> **これは人間＋次のClaudeセッション向けの全体像です。iPhone版 Claude Code で続きを行う際、まずここを読めば迷いません。**
> 技術的な設計詳細は [`CLAUDE.md`](./CLAUDE.md) を参照。最終更新: 2026-07-12

---

## 🎯 このアプリは何か

青空文庫をコーパスにした **現代語→戦前文体（旧字旧仮名・文語体）変換 RAG チャットボット**（Streamlit）。
LLM が生成の主体、RAG は「文体参照」用（内容の転用は禁止）。

## 🌐 ライブ環境（稼働中・無停止）

- **URL**: https://bungo-app.gentleground-ba3d7ba2.japaneast.azurecontainerapps.io
- **チャット**: Azure AI Foundry の **Claude Opus 4.8**（Anthropic Messages API 経由）
- **Embedding**: Azure OpenAI `text-embedding-3-small`
- **検索**: Azure AI Search `bungo-chunks`（**free tier = $0**、現在 300作品 / 約7千チャンク）

## 💰 コスト（2026-07-12 時点）

- **固定費: $0**（ACR は削除済み。Search=free、Container Apps=scale-to-zero で無償枠内）
- **変動費**: Opus トークンのみ（〜$0.02〜0.04/メッセージ、Prompt Caching で連続対話は軽減）＋Embedding は無視できる額
- **未使用時: 完全に $0**

## 🚀 デプロイの仕組み（重要）

- **本番CI**: `main` へ push（変更が `app/**` `requirements.txt` `Dockerfile` を含むとき）→ `.github/workflows/deploy.yml` が
  **ghcr.io/s8tv9mvcz9-code/bungo-rag（public パッケージ）** にビルド＆push → `az containerapp update`。**完全自動**。
- **ローカル**: `./deploy.sh`（env変数注入付き。ghcr push には `gh auth refresh -s write:packages` が一度必要）
- **ACR は廃止・削除済み**（$5/月撤廃）。もう `bungoregistry.azurecr.io` は存在しない。

## ✅ 直近セッションで完了したこと（2026-07-12）

1. **著者メタデータ修正** — 旧コードは存在しない「姓名」列を参照し全著者が `不明` だったのを、「姓」+「名」で復元。**再インデックス反映済**（不明=0）。
2. **検索の多様性制約** — 1作品あたり最大2件に間引き（`MAX_PER_BOOK`）、「特定文献への引っ張られ」を緩和。
3. **反コピー設計の統合** — 文体参照例を120字に短縮＋システムプロンプトで転用禁止（別セッションのリファクタを取り込み）。
4. **Prompt Caching** — 固定 SYSTEM_PROMPT に `cache_control` ＋ `anthropic-beta` ヘッダ（Foundryで cache_read 検証済）。
5. **コーパス 200→300作品**、**ghcr.io 移行**、**ACR 削除**。

## ⚠️ ハマりどころ・次セッションへの注意

- **⚠️ 並行セッションで `main` が分岐しやすい**（iPhone cloud / 各種 `claude/*` ブランチ）。
  **push 前に必ず `git fetch origin` して origin/main との差分を確認**すること。過去に Claude 非対応版へ巻き戻る分岐が発生済み。
- **`.env` は本番シークレット**（Azure Search 管理キー / Azure OpenAI キー / Foundry key1 など）。**gitignore 維持・絶対にコミットしない**。
- **Foundry の Claude 制約**: `temperature` は 400 で拒否（送らない）／ `system` はトップレベル引数／ Prompt Caching は β（`anthropic-beta` ヘッダ必須）。
- **再インデックス**（`python3 scripts/build_index.py`）は**ライブの検索インデックスを上書き**する。著者は「姓」+「名」、`MAX_BOOKS` は現在 300。
- **provider 判定は2ファイル**（`app/rag.py` と `scripts/query.py`）に重複。**必ず両方同時に変更**。

## 🔜 未着手・候補（必要なら）

- **B: Citations** — 今回スキップ（文体変換は原文を引用しないため構造的に非整合）。学習目的でやるなら document ブロック化が必要。
- **`.env` の GitHub PAT ローテーション**（推奨）。
- さらなるコーパス拡充（free tier の実上限に注意。現在 260MB 超で稼働中）。

## 🗂 主要リソース名

| 種別 | 名前 |
|---|---|
| Resource Group | `bungo-rag-rg` |
| Container App | `bungo-app` / env `bungo-env`（japaneast） |
| Search サービス | `bungo-search`（free）/ index `bungo-chunks` |
| コンテナレジストリ | `ghcr.io/s8tv9mvcz9-code/bungo-rag`（public） |
| GitHub リポジトリ | `s8tv9mvcz9-code/bungo-rag` |
