using './main.bicep'

// ── 相1（基盤のみ）の例。まずこれで ACR/Search/env を作る ──────
// フリートライアルでは Azure OpenAI を切り離す:
param deployOpenAi = false
param deployApps = false

// 命名（グローバル一意が必要なものは既定で uniqueString が付く）
param acrName = 'bungoregistry'
param searchSku = 'free' // フリートライアルは free（50MB）。本番は basic

// チャット生成（GitHub Models）。キーはここに書かず CLI で渡す:
//   az deployment group create ... -p chatApiKey=<GitHub PAT>
param chatEndpoint = 'https://models.inference.ai.azure.com'
param chatDeployment = 'Phi-4-mini'

// ── 相2（アプリ作成）に進むときは上書きして再デプロイ ──────────
// param deployApps = true
// param webImage = 'bungoregistry.azurecr.io/bungo-rag:latest'
// param apiImage = 'bungoregistry.azurecr.io/bungo-rag-api:latest'
