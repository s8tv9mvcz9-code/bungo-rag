# Claude（Azure AI Foundry）でチャット生成する

チャット生成を **Claude Opus 4.8 等（Azure AI Foundry 経由）** に切り替えるための設定。
検索・埋め込みは従来どおり（ローカル / OpenAI互換）で、**生成だけ** Foundry の Claude に向ける。

> ⚠️ 前提: Azure AI Foundry は **有効な Azure サブスクリプション（従量課金/PAYG）** が必要。
> 課金は Claude Consumption Unit（CCU）による純粋な**従量制**（固定の維持費なし）。
> Opus 4.8 は標準 $5 / $25 per 1M（入力/出力）。

## 1st ステップ（コード側）— 実装済み

`app/rag.py` に `CHAT_BACKEND=foundry` で有効化される Claude 経路を追加済み。
既定（未設定）は従来の OpenAI 互換経路のままで、挙動は変わらない。

## Azure 側で行うこと（あなたの認証作業）

1. Foundry ポータル（https://ai.azure.com/）で **Foundry リソース**を作成（リソース名を控える）
2. モデルカタログで **claude-opus-4-8** を選び **Deploy**（Hosted on Azure）。デプロイ名を控える（既定はモデルID）
3. デプロイの **Details** で **Target URI** と **Key** を取得

## 環境変数（.env）

```env
CHAT_BACKEND=foundry
ANTHROPIC_FOUNDRY_RESOURCE=<Foundryリソース名>   # 例: example-resource
CHAT_DEPLOYMENT=claude-opus-4-8                   # Foundryのデプロイ名（既定はモデルID）

# 認証（どちらか）
# A) APIキー（手軽）
ANTHROPIC_FOUNDRY_API_KEY=<FoundryのKey>          # 省略時は CHAT_API_KEY を使用
# B) Entra ID（キーレス・本番推奨、要 azure-identity と RBAC ロール）
# FOUNDRY_AUTH=entra
```

`pip install anthropic`（Entra 利用時は `azure-identity` も）。エンドポイントは
`https://{resource}.services.ai.azure.com/anthropic/` がリソース名から自動構築される。

## 注意（Hosted on Azure の制約）

Azure ホストでは構造化出力・サーバーサイドツール・Files API 等は非対応（400）。
本アプリの生成は素の Messages ストリーミングのみ使うため影響なし。
