#!/bin/bash
# bungo-rag デプロイスクリプト
# ローカル実行: .env が自動で読み込まれます
# GitHub Actions: リポジトリの Secrets から環境変数が注入されます
set -e

# Docker Desktop の PATH を通す（ローカル Mac 用）
export PATH="/Applications/Docker.app/Contents/Resources/bin:$PATH"

# ローカル実行時は .env から変数を読み込む
if [ -f "$(dirname "$0")/.env" ]; then
  set -a
  source "$(dirname "$0")/.env"
  set +a
fi

# イメージは GitHub Container Registry（ghcr.io, public）。ACR Basic($5/月)は廃止済み。
REGISTRY="ghcr.io/s8tv9mvcz9-code"
IMAGE="${REGISTRY}/bungo-rag:latest"
RG="bungo-rag-rg"
APP_NAME="bungo-app"
ENV_NAME="bungo-env"

echo "=== [1/4] ghcr.io ログイン ==="
# gh CLI のトークンで docker ログイン。push には write:packages スコープが必要
#   （不足時は once:  gh auth refresh -s write:packages,read:packages ）
gh auth token | docker login ghcr.io -u s8tv9mvcz9-code --password-stdin

echo "=== [2/4] Docker ビルド (linux/amd64) ==="
docker buildx build --platform linux/amd64 -t "${IMAGE}" .

echo "=== [3/4] ghcr.io へプッシュ ==="
docker push "${IMAGE}"

echo "=== [4/4] Container App 更新 ==="
# パッケージは public のため pull 認証情報は不要（--registry-* 不要）
az containerapp update \
  --name "${APP_NAME}" \
  --resource-group "${RG}" \
  --image "${IMAGE}" \
  --set-env-vars \
    AZURE_SEARCH_ENDPOINT="${AZURE_SEARCH_ENDPOINT}" \
    AZURE_SEARCH_ADMIN_KEY="${AZURE_SEARCH_ADMIN_KEY}" \
    SEARCH_INDEX_NAME="${SEARCH_INDEX_NAME}" \
    AZURE_OPENAI_ENDPOINT="${AZURE_OPENAI_ENDPOINT}" \
    AZURE_OPENAI_API_KEY="${AZURE_OPENAI_API_KEY}" \
    EMBED_DEPLOYMENT="${EMBED_DEPLOYMENT}" \
    CHAT_ENDPOINT="${CHAT_ENDPOINT}" \
    CHAT_API_KEY="${CHAT_API_KEY}" \
    CHAT_DEPLOYMENT="${CHAT_DEPLOYMENT}"

echo ""
echo "=== デプロイ完了 ==="
az containerapp show \
  --name "${APP_NAME}" \
  --resource-group "${RG}" \
  --query "properties.configuration.ingress.fqdn" -o tsv | xargs -I{} echo "URL: https://{}"
