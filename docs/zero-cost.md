# ゼロコスト構成ガイド — Azure なしで bungo-rag を動かす

Azure 無料トライアル終了後も**恒久無料**で全機能を動かすための構成。

## 背景（2026-07 時点の事実）

| 従来の依存 | 状態 |
|---|---|
| Azure AI Search / Azure OpenAI / Container Apps / ACR | トライアル終了→**サブスクリプション無効化で全停止**。PAYG移行の猶予は無効化後30日、データは30〜90日で削除 |
| GitHub Models 旧エンドポイント `models.inference.ai.azure.com` | **2025-10-17 に停止済み**（＝チャット生成はトライアルと無関係にずっと壊れていた） |
| GitHub Models 本体 `models.github.ai` | **2026-07-30 に完全廃止**（新規利用は 2026-06-16 から不可） |

→ 移行先は「GitHub Models」ではなく **汎用 OpenAI 互換プロバイダ**＋**ローカル検索**。

## ゼロコスト・アーキテクチャ

```
[Streamlit / FastAPI]
   ├─ 検索: corpus/index.npz をローカルで検索（app/vector_store.py）
   │        numpy コサイン + 文字bigram BM25 の RRF ハイブリッド
   │        → Azure AI Search 不要・API呼び出しゼロ
   ├─ 埋め込み: OpenAI互換API（推奨: Google AI Studio 無料キー）
   └─ チャット: OpenAI互換API（同上。gemini-2.0-flash 等）
[インデックス構築]
   └─ scripts/build_index.py が青空文庫の公式GitHubミラーから取得
      （www.aozora.gr.jp 不要。GitHub Actions 内でも動作）
```

## セットアップ（合計 10 分・カード登録不要）

### 1. 無料 API キーを 1 本取る

[Google AI Studio](https://aistudio.google.com/apikey) で API キーを発行（無料、クレジットカード不要）。
これ 1 本で埋め込みとチャットの両方を賄える。

### 2. インデックスを構築

ローカルで:

```bash
pip install -r requirements.txt
EMBED_ENDPOINT=https://generativelanguage.googleapis.com/v1beta/openai/ \
EMBED_API_KEY=<AI Studioのキー> \
EMBED_DEPLOYMENT=gemini-embedding-001 \
EMBED_DIMENSIONS=1536 \
python scripts/build_index.py --limit 50
# → corpus/index.npz + corpus/meta.json が生成される
```

または GitHub Actions（`Build Local Search Index` ワークフロー）:
Repository secret `EMBED_API_KEY` を設定 → Actions から手動実行 → corpus/ が自動コミットされる。

### 3. アプリの環境変数（.env）

```env
# 検索: corpus/ があれば自動でローカル検索になる（VECTOR_BACKEND=auto）
# 埋め込み（クエリ用。インデックス構築時と同じ設定にすること）
EMBED_ENDPOINT=https://generativelanguage.googleapis.com/v1beta/openai/
EMBED_API_KEY=<AI Studioのキー>
EMBED_DEPLOYMENT=gemini-embedding-001
EMBED_DIMENSIONS=1536
# チャット生成
CHAT_ENDPOINT=https://generativelanguage.googleapis.com/v1beta/openai/
CHAT_API_KEY=<AI Studioのキー>
CHAT_DEPLOYMENT=gemini-2.0-flash
```

```bash
streamlit run app/app.py
```

## 環境変数リファレンス

| 変数 | 意味 | 既定 |
|---|---|---|
| `VECTOR_BACKEND` | `local` / `azure` / `auto` | `auto`（corpus/ があれば local） |
| `CORPUS_DIR` | ローカルインデックスの場所 | `corpus/` |
| `EMBED_ENDPOINT` | OpenAI互換の埋め込みAPI | —（未設定なら AZURE_OPENAI_* に後方互換） |
| `EMBED_API_KEY` | そのキー | — |
| `EMBED_DEPLOYMENT` | モデル名 | `text-embedding-3-small` |
| `EMBED_DIMENSIONS` | 出力次元（インデックスと一致させる） | モデル既定 |
| `CHAT_ENDPOINT` / `CHAT_API_KEY` / `CHAT_DEPLOYMENT` | チャット生成（OpenAI互換 or Azure） | — |

Azure に戻す場合は従来どおり `AZURE_SEARCH_*` / `AZURE_OPENAI_*` を設定し
`VECTOR_BACKEND=azure` にするだけ（後方互換を維持）。

## プロバイダ乗り換え耐性

GitHub Models 廃止の教訓として、コードはプロバイダ名を一切ハードコードしていない。
OpenAI 互換 API なら何でも使える（Groq / OpenRouter / Mistral / ローカル llama.cpp 等）。
乗り換えは環境変数 3 つの差し替えのみ。埋め込みモデルを変えた場合のみ
インデックス再構築（ワークフロー再実行）が必要。

## 無料枠の目安（Google AI Studio, 2026-07 時点）

- チャット（gemini-2.0-flash）: 無料ティアで RPM/RPD 制限内なら $0
- 埋め込み: 同上。インデックス構築（数千チャンク）はレート制限に当たりうるため
  `--sleep 1.0` 付きで実行（ワークフローは設定済み）

レート制限・提供条件は変わりうるので、公式の料金/制限ページを確認のこと。

## 無料ホスティング

公開まで無料で行く場合は `docs/hosting.md` を参照
（Streamlit Community Cloud / Hugging Face Spaces の手順と比較表）。
