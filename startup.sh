#!/bin/bash
# Azure App Service (Linux) 起動スクリプト
# PORT 環境変数は App Service が自動で設定する（デフォルト 8000）
streamlit run app/app.py \
  --server.port="${PORT:-8000}" \
  --server.address=0.0.0.0 \
  --server.headless=true \
  --server.enableWebsocketCompression=false
