// ============================================================================
// main.bicep — bungo-rag の Azure 構成を IaC 化（Infrastructure as Code）
//
// スコープ: resourceGroup（既存の bungo-rag-rg に流す想定）
// デプロイ:
//   az deployment group create -g bungo-rag-rg -f infra/main.bicep \
//      -p infra/main.bicepparam
//
// 二相デプロイ（鶏卵問題の回避）:
//   [相1] deployApps=false … 基盤のみ（ACR/Search/OpenAI/env）を作成
//         → 新しい ACR にイメージを build & push
//   [相2] deployApps=true webImage=... apiImage=... … コンテナアプリを作成
// ============================================================================

@description('リソースの配置リージョン（既定: RG と同じ）')
param location string = resourceGroup().location

@description('共通の接頭辞。グローバル一意が必要な名前の素として使う')
param namePrefix string = 'bungo'

// ── レジストリ / ログ / 環境 ────────────────────────────────
@description('Container Registry 名（英数字のみ・グローバル一意）')
param acrName string = 'bungoregistry'

@description('Log Analytics ワークスペース名')
param logAnalyticsName string = '${namePrefix}-logs'

@description('Container Apps 環境名')
param environmentName string = '${namePrefix}-env'

// ── AI Search ───────────────────────────────────────────────
@description('Azure AI Search サービス名（グローバル一意）')
param searchName string = '${namePrefix}-search-${uniqueString(resourceGroup().id)}'

@description('AI Search の SKU。フリートライアルは free（50MB制限）も可')
@allowed([ 'free', 'basic', 'standard' ])
param searchSku string = 'basic'

@description('検索インデックス名（rag.py の既定と一致させる）')
param searchIndexName string = 'bungo-chunks'

// ── Azure OpenAI（フリートライアルでは作成不可な場合あり）──────
@description('Azure OpenAI を作成するか。フリートライアルでは false 推奨')
param deployOpenAi bool = true

@description('Azure OpenAI アカウント名（グローバル一意）')
param openAiName string = '${namePrefix}-openai-${uniqueString(resourceGroup().id)}'

@description('埋め込みモデルのデプロイ名')
param embedDeployment string = 'text-embedding-3-small'

@description('埋め込みデプロイの容量（千TPM単位）')
param embedCapacity int = 50

// ── チャット生成（GitHub Models／Azure外。キーは PAT）───────────
@description('チャット生成エンドポイント（GitHub Models など）')
param chatEndpoint string = 'https://models.inference.ai.azure.com'

@description('チャット生成のデプロイ/モデル名')
param chatDeployment string = 'Phi-4-mini'

@description('チャット生成 APIキー（GitHub PAT）。CLI の -p で渡すこと')
@secure()
param chatApiKey string = ''

// ── コンテナアプリ ──────────────────────────────────────────
@description('コンテナアプリ（web/api）を作成するか。初回は false で基盤のみ')
param deployApps bool = false

param webAppName string = '${namePrefix}-app'
param apiAppName string = '${namePrefix}-api'

@description('Streamlit(web) イメージ。相2 で実イメージを指定')
param webImage string = '${acrName}.azurecr.io/bungo-rag:latest'

@description('FastAPI(api) イメージ。相2 で実イメージを指定')
param apiImage string = '${acrName}.azurecr.io/bungo-rag-api:latest'

// ============================================================================
// 1) 監視: Log Analytics ワークスペース
// ============================================================================
resource logAnalytics 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: logAnalyticsName
  location: location
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
  }
}

// ============================================================================
// 2) Container Apps 環境（ログ送信先に Log Analytics を接続）
// ============================================================================
resource environment 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: environmentName
  location: location
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logAnalytics.properties.customerId
        sharedKey: logAnalytics.listKeys().primarySharedKey
      }
    }
  }
}

// ============================================================================
// 3) Container Registry（admin ユーザー有効＝コンテナアプリの pull 認証に使用）
// ============================================================================
resource acr 'Microsoft.ContainerRegistry/registries@2023-11-01-preview' = {
  name: acrName
  location: location
  sku: { name: 'Basic' }
  properties: {
    adminUserEnabled: true
  }
}

// ============================================================================
// 4) Azure AI Search
// ============================================================================
resource search 'Microsoft.Search/searchServices@2024-03-01-preview' = {
  name: searchName
  location: location
  sku: { name: searchSku }
  properties: {
    replicaCount: 1
    partitionCount: 1
    hostingMode: 'default'
  }
}

// ============================================================================
// 5) Azure OpenAI + 埋め込みデプロイ（deployOpenAi=true のときのみ）
// ============================================================================
resource openAi 'Microsoft.CognitiveServices/accounts@2024-10-01' = if (deployOpenAi) {
  name: openAiName
  location: location
  kind: 'OpenAI'
  sku: { name: 'S0' }
  properties: {
    customSubDomainName: openAiName
    publicNetworkAccess: 'Enabled'
  }
}

resource embed 'Microsoft.CognitiveServices/accounts/deployments@2024-10-01' = if (deployOpenAi) {
  parent: openAi
  name: embedDeployment
  sku: {
    name: 'Standard'
    capacity: embedCapacity
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: 'text-embedding-3-small'
      version: '1'
    }
  }
}

// ── 実行時に各アプリへ渡す環境変数（rag.py が参照）────────────
// deployOpenAi=false のとき openAi は未作成。三項でショートサーキットされるため安全。
#disable-next-line BCP318
var openAiEndpoint = deployOpenAi ? openAi.properties.endpoint : ''

var sharedEnv = [
  { name: 'AZURE_SEARCH_ENDPOINT', value: 'https://${search.name}.search.windows.net' }
  { name: 'AZURE_SEARCH_ADMIN_KEY', secretRef: 'search-key' }
  { name: 'SEARCH_INDEX_NAME', value: searchIndexName }
  { name: 'AZURE_OPENAI_ENDPOINT', value: openAiEndpoint }
  { name: 'AZURE_OPENAI_API_KEY', secretRef: 'openai-key' }
  { name: 'EMBED_DEPLOYMENT', value: embedDeployment }
  { name: 'CHAT_ENDPOINT', value: chatEndpoint }
  { name: 'CHAT_API_KEY', secretRef: 'chat-key' }
  { name: 'CHAT_DEPLOYMENT', value: chatDeployment }
]

// ── 各アプリの secrets（ACR pass・Search key・OpenAI key・chat key）──
var sharedSecrets = [
  { name: 'acr-password', value: acr.listCredentials().passwords[0].value }
  { name: 'search-key', value: search.listAdminKeys().primaryKey }
  // openAi 未作成時は 'unused'。三項でショートサーキット。
  #disable-next-line BCP422
  { name: 'openai-key', value: deployOpenAi ? openAi.listKeys().key1 : 'unused' }
  { name: 'chat-key', value: empty(chatApiKey) ? 'unused' : chatApiKey }
]

var registries = [
  {
    server: acr.properties.loginServer
    username: acr.name
    passwordSecretRef: 'acr-password'
  }
]

// ============================================================================
// 6) Container App: Streamlit（Web版, :8501）
// ============================================================================
resource webApp 'Microsoft.App/containerApps@2024-03-01' = if (deployApps) {
  name: webAppName
  location: location
  properties: {
    managedEnvironmentId: environment.id
    configuration: {
      ingress: {
        external: true
        targetPort: 8501
        transport: 'auto'
      }
      registries: registries
      secrets: sharedSecrets
    }
    template: {
      containers: [
        {
          name: webAppName
          image: webImage
          resources: { cpu: json('0.5'), memory: '1Gi' }
          env: sharedEnv
        }
      ]
      scale: { minReplicas: 0, maxReplicas: 2 }
    }
  }
}

// ============================================================================
// 7) Container App: FastAPI（API版, :8000 / Android用）
// ============================================================================
resource apiApp 'Microsoft.App/containerApps@2024-03-01' = if (deployApps) {
  name: apiAppName
  location: location
  properties: {
    managedEnvironmentId: environment.id
    configuration: {
      ingress: {
        external: true
        targetPort: 8000
        transport: 'auto'
      }
      registries: registries
      secrets: sharedSecrets
    }
    template: {
      containers: [
        {
          name: apiAppName
          image: apiImage
          resources: { cpu: json('0.5'), memory: '1Gi' }
          env: sharedEnv
        }
      ]
      scale: { minReplicas: 0, maxReplicas: 2 }
    }
  }
}

// ============================================================================
// 出力
// ============================================================================
output acrLoginServer string = acr.properties.loginServer
output searchEndpoint string = 'https://${search.name}.search.windows.net'
output openAiEndpoint string = openAiEndpoint
// deployApps=false のとき webApp/apiApp は未作成。三項でショートサーキット。
#disable-next-line BCP318
output webUrl string = deployApps ? 'https://${webApp.properties.configuration.ingress.fqdn}' : '(deployApps=false)'
#disable-next-line BCP318
output apiUrl string = deployApps ? 'https://${apiApp.properties.configuration.ingress.fqdn}' : '(deployApps=false)'
