# infra — bungo-rag の Azure 構成（Bicep / IaC）

これまで `deploy.sh` / `deploy-api.sh` の命令的な `az` コマンドで作っていた Azure 構成を、
**宣言的な Bicep** に書き起こしたもの。`main.bicep` 1ファイルで全リソースを定義する。

## 何を作るか

| リソース | Bicep内 | 役割 |
|---|---|---|
| Log Analytics | `logAnalytics` | Container Apps のログ集約先 |
| Container Apps 環境 | `environment` | アプリ実行基盤（ログ連携付き） |
| Container Registry | `acr` | イメージ保管（admin有効でpull認証） |
| AI Search | `search` | ベクトル＋全文検索 |
| Azure OpenAI + 埋め込み | `openAi` / `embed` | `text-embedding-3-small`（`deployOpenAi` で切替） |
| Container App（web） | `webApp` | Streamlit :8501 |
| Container App（api） | `apiApp` | FastAPI :8000 |

シークレット（ACRパス・Search鍵・OpenAI鍵・チャット鍵）は `listKeys` 系関数で取得し、
各アプリの `secrets` に格納→環境変数へ `secretRef` 注入する（鍵を平文出力しない）。

## デプロイ（二相）

> 前提: `az login` 済み。RG は既存の `bungo-rag-rg` を使う。
> Bicep が無ければ `az bicep install`。

### 相1: 基盤のみ（ACR/Search/env、必要ならOpenAI）

```bash
az deployment group create \
  -g bungo-rag-rg \
  -f infra/main.bicep \
  -p infra/main.bicepparam \
  -p chatApiKey="$GITHUB_PAT"
```

ACR がまだ空なので `deployApps=false`（既定）。出力の `acrLoginServer` を控える。

### 相2: イメージを push → アプリ作成

```bash
# 相1で出来た ACR にイメージを push
az acr login --name bungoregistry
docker buildx build --platform linux/amd64 -t bungoregistry.azurecr.io/bungo-rag:latest --push .
docker buildx build --platform linux/amd64 -f backend/Dockerfile -t bungoregistry.azurecr.io/bungo-rag-api:latest --push .

# アプリを作成（deployApps=true で再デプロイ）
az deployment group create \
  -g bungo-rag-rg \
  -f infra/main.bicep \
  -p infra/main.bicepparam \
  -p deployApps=true \
  -p chatApiKey="$GITHUB_PAT"
```

出力 `webUrl` / `apiUrl` が公開URL。`apiUrl` を Android の `BUNGO_BASE_URL` に設定。

## フリートライアル向けの切替

`main.bicepparam` の既定は無料枠寄り:

- `deployOpenAi = false` … Azure OpenAI はトライアルで作成不可な場合があるため既定オフ。
  この場合は埋め込みも GitHub Models 等に振り替える前提（`AZURE_OPENAI_ENDPOINT` は空になる）。
- `searchSku = 'free'` … 50MB制限の無料ティア。本番は `'basic'`。

## 既存スクリプトとの関係

- `deploy.sh` / `backend/deploy-api.sh` … **命令的**。素早い手動デプロイ・更新向け。
- `infra/main.bicep` … **宣言的**。構成の正本（source of truth）。環境再現・レビュー・差分確認向け。

`az deployment group what-if` で**適用前に差分**を確認できるのが Bicep の強み:

```bash
az deployment group what-if -g bungo-rag-rg -f infra/main.bicep -p infra/main.bicepparam
```

## デモする Bicep / IaC の概念

- リソース宣言と暗黙の依存解決（`environment` が `logAnalytics` を参照→自動順序付け）
- `@secure()` パラメータと `listKeys` によるシークレットの安全な受け渡し
- 条件付きデプロイ（`if (deployOpenAi)` / `if (deployApps)`）
- `uniqueString()` によるグローバル一意名の生成
- 冪等性（再実行で差分のみ適用）と `what-if` による事前差分
