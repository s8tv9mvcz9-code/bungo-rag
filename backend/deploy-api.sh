#!/bin/bash
# backend/deploy-api.sh
# bungo-rag バックエンドAPI を Azure Container Apps へ初回作成 or 更新する。
#
# 使い方:
#   az login            # 認証はあなたが行う
#   bash backend/deploy-api.sh
#
# - リポジトリ直下に .env（既存の Streamlit 用と同じ値）を置いておくこと
# - 既存の ACR / Container Apps Environment（bungo-env）を流用する
# - 初回は create（env注入）、2回目以降は update（imageとenv更新）
set -e

# リポジトリ直下へ移動（このスクリプトは backend/ 配下にある想定）
cd "$(dirname "$0")/.."

# .env を読み込む
if [ -f ".env" ]; then
  set -a
  source ".env"
  set +a
else
  echo "⚠️  .env が見つかりません。環境変数が設定済みであることを確認してください。"
fi

REGISTRY="bungoregistry.azurecr.io"
IMAGE="${REGISTRY}/bungo-rag-api:latest"
RG="bungo-rag-rg"
ENV_NAME="bungo-env"
APP_NAME="bungo-api"
PORT=8000

echo "=== [1/4] ACR ログイン ==="
az acr login --name bungoregistry

echo "=== [2/4] Docker ビルド (linux/amd64, backend/Dockerfile) ==="
docker buildx build --platform linux/amd64 -f backend/Dockerfile -t "${IMAGE}" --push .

echo "=== [3/4] Container App 作成 or 更新 ==="
ENV_VARS=(
  "AZURE_SEARCH_ENDPOINT=${AZURE_SEARCH_ENDPOINT}"
  "AZURE_SEARCH_ADMIN_KEY=${AZURE_SEARCH_ADMIN_KEY}"
  "SEARCH_INDEX_NAME=${SEARCH_INDEX_NAME:-bungo-chunks}"
  "AZURE_OPENAI_ENDPOINT=${AZURE_OPENAI_ENDPOINT}"
  "AZURE_OPENAI_API_KEY=${AZURE_OPENAI_API_KEY}"
  "EMBED_DEPLOYMENT=${EMBED_DEPLOYMENT:-text-embedding-3-small}"
  "CHAT_ENDPOINT=${CHAT_ENDPOINT}"
  "CHAT_API_KEY=${CHAT_API_KEY}"
  "CHAT_DEPLOYMENT=${CHAT_DEPLOYMENT}"
)

if az containerapp show --name "${APP_NAME}" --resource-group "${RG}" >/dev/null 2>&1; then
  echo "→ 既存アプリを更新します"
  az containerapp update \
    --name "${APP_NAME}" \
    --resource-group "${RG}" \
    --image "${IMAGE}" \
    --set-env-vars "${ENV_VARS[@]}"
else
  echo "→ 新規アプリを作成します"
  ACR_USER=$(az acr credential show --name bungoregistry --query username -o tsv)
  ACR_PASS=$(az acr credential show --name bungoregistry --query "passwords[0].value" -o tsv)
  az containerapp create \
    --name "${APP_NAME}" \
    --resource-group "${RG}" \
    --environment "${ENV_NAME}" \
    --image "${IMAGE}" \
    --target-port "${PORT}" \
    --ingress external \
    --registry-server "${REGISTRY}" \
    --registry-username "${ACR_USER}" \
    --registry-password "${ACR_PASS}" \
    --min-replicas 0 \
    --max-replicas 2 \
    --env-vars "${ENV_VARS[@]}"
fi

echo ""
echo "=== [4/4] 完了。API の URL ==="
az containerapp show \
  --name "${APP_NAME}" \
  --resource-group "${RG}" \
  --query "properties.configuration.ingress.fqdn" -o tsv | xargs -I{} echo "BUNGO_BASE_URL=https://{}"
