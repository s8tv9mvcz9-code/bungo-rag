# ロードマップ：② モバイルバックエンドの手直し ＋ iOS版の新規実装

> 対象読者：**実装を担う安価エージェント**と人間レビュア。
> 方針：**main が唯一の基軸**。本書は main（`origin/main`）から派生した `claude/ios-app` を前提に、
> 各フェーズを「安価エージェントが1タスクで完了できる粒度」に分解し、**受け入れ基準と検証コマンド**を付す。
> 設計判断はすべて末尾『調査の裏付け』に出典を明記。最終更新のコード事実は 2026-07 の `origin/main`。

---

## 0. 現状分析（調査で確定した事実）

### 0.1 main の本番構成（`STATUS.md` ＋ 実コード）
- 稼働URL: `https://bungo-app.gentleground-ba3d7ba2.japaneast.azurecontainerapps.io`（Streamlit, scale-to-zero）
- チャット生成: **Azure AI Foundry の Claude Opus 4.8**（`app/rag.py` の `_chat_provider()` が `CHAT_ENDPOINT` に `anthropic` を含むと Anthropic Messages API 経路へ。Prompt Caching β 使用）
- 埋め込み: Azure OpenAI `text-embedding-3-small`／検索: Azure AI Search `bungo-chunks`（free tier）
- レジストリ: **ghcr.io/s8tv9mvcz9-code/bungo-rag**（ACR は削除済み）
- CI: `main` push → `.github/workflows/deploy.yml` が ghcr build → `az containerapp update`

### 0.2 RAG コアの契約（`app/rag.py`、変更不可の前提として扱う）
```
stream_answer(user_message: str, history: [{"role","content"}], top: int)
    -> (token_stream: Iterator[str], source_chunks: List[dict])
source_chunk = {"text","title","author","style","book_id"}
```
`backend/` はこの契約に**プロバイダ非依存**で乗る（`from rag import stream_answer` を呼ぶだけ）。
→ **main に backend を載せれば、backend は自動的に main の Foundry Claude を使う。プロバイダ改修は不要。**

### 0.3 既存の資産（`origin/claude/android-native`）
- `backend/main.py`：FastAPI。`POST /chat` が **NDJSON** ストリーム、`GET /health`。
  1行1 JSON、`type` で判別：`token`／`sources`／`done`／`error`（下記 §2.1 が正式契約）。
- `android/`：Kotlin + Jetpack Compose の Android ネイティブ（この NDJSON を Ktor で消費）。**iOS 実装の参照実装**。
- 付随デプロイ（`backend/deploy-api.sh`, `.github/workflows/deploy-backend.yml`）：**ACR 前提＝main の ghcr 移行と不整合**（要手直し）。

### 0.4 マージ可能性（実測）
- `origin/claude/android-native` → `main` は **コンフリクト 0**（android は `app/rag.py` を改変せず `backend/`・`android/` を追加するのみ）。
  → 統合すると **main の rag.py が維持され**、backend/android がそこに乗る（理想形）。

### 0.5 iOS ビルドの物理制約（実測）
- 本開発コンテナ（**Linux x86_64、Xcode 不在**）では **iOS アプリはビルド・テスト不可**。
  → **ビルド/テストは macOS 必須**：GitHub Actions の `macos-14` runner か、ユーザーの Mac／Xcode Cloud。
  → 逆に **Swift ソース・yaml の「執筆」は本コンテナで可能**（＝安価エージェントがファイル生成でき、検証だけ CI に委ねる）。

---

## 1. スコープ / 非目標

**やる**：(A) backend を main に統合し ghcr で `bungo-api` としてデプロイ可能にする。(B) 既存 NDJSON 契約を消費する **iOS ネイティブ（SwiftUI）** を新規実装し、**XcodeGen で再現可能**・**macOS CI で自動ビルド**する。
**やらない**：main の rag.py／本番 Streamlit の挙動変更、Android 側の作り直し（BASE_URL 差し替え以外）、App Store 配布（署名・審査は別途）。

---

## 2. パートA — backend「②」の手直し（main 統合＋ghcr デプロイ）

### 2.1 API 契約（正式・iOS/Android 共通。**変更禁止**）
`POST /chat`  request:
```json
{ "message": "…", "history": [{"role":"user|assistant","content":"…"}], "top_k": 5 }
```
response: `application/x-ndjson`（1行1オブジェクト、到着順）:
```
{"type":"token","content":"…"}      // 生成トークン（複数回）
{"type":"sources","sources":[{"title","author","style","text","book_id"}]}
{"type":"done"}
{"type":"error","message":"…"}
```
`GET /health` → `{"status":"ok"}`。
> 注：main は Source に `book_id` を追加した。クライアントの Source モデルは**未知キーを無視**する実装にする（Android は既に対応、iOS も §3.2 で同様）。

### 2.2 手直し内容（最小）
1. `origin/claude/android-native` の **`backend/` ディレクトリを main（=このブランチ）へ取り込む**（`app/rag.py` は main のものを使う）。
2. `backend/main.py` は**無改修**（`from rag import stream_answer` で main の Foundry Claude を自動利用）。
3. **デプロイを ACR→ghcr へ書き換え**（下記ワークフローで置換。`deploy-api.sh` も ghcr 化）。
4. `bungo-api` を **2つ目の Container App** として同一 env `bungo-env`・同一シークレット（Azure Search / Azure OpenAI / Foundry）で公開。

`.github/workflows/deploy-backend.yml`（ghcr 版・置換後の正）:
```yaml
name: Deploy Backend API
on:
  push:
    branches: [main]
    paths: ["backend/**", "app/rag.py", "requirements.txt"]
jobs:
  deploy:
    runs-on: ubuntu-latest
    permissions: { contents: read, packages: write }
    steps:
      - uses: actions/checkout@v4
      - uses: docker/login-action@v3
        with: { registry: ghcr.io, username: ${{ github.actor }}, password: ${{ secrets.GITHUB_TOKEN }} }
      - name: Build & push
        run: |
          IMG=ghcr.io/s8tv9mvcz9-code/bungo-rag-api
          docker build -f backend/Dockerfile -t $IMG:${{ github.sha }} -t $IMG:latest .
          docker push $IMG:${{ github.sha }}; docker push $IMG:latest
      - uses: azure/login@v2
        with: { creds: ${{ secrets.AZURE_CREDENTIALS }} }
      - name: Deploy (update if exists)
        run: |
          az extension add --name containerapp --yes --only-show-errors
          IMG=ghcr.io/s8tv9mvcz9-code/bungo-rag-api:${{ github.sha }}
          if az containerapp show -n bungo-api -g bungo-rag-rg >/dev/null 2>&1; then
            az containerapp update -n bungo-api -g bungo-rag-rg --image "$IMG"
          else
            echo "::warning::bungo-api 未作成。初回のみ backend/deploy-api.sh をローカル実行（シークレット注入のため）。"
          fi
```
> 初回作成（`bungo-api`）はシークレット注入が要るためポータル/CLI 手動。`backend/deploy-api.sh` を ghcr＋`--registry-server ghcr.io --registry-username <gh> --registry-password <PAT(write:packages,read:packages)>` に修正して1回実行。ghcr パッケージは public 運用（main の方針に合わせる）。

### 2.3 受け入れ基準（A）
- [ ] main（このブランチ）に `backend/` が存在し、`git show HEAD:app/rag.py | grep _chat_provider` がヒット（main の rag を使用）。
- [ ] `python -c "import sys;sys.path.insert(0,'app');import backend.main"` が **.env 実値ありで** import 成功（構文・契約）。
- [ ] `curl -s localhost:8000/health` → `{"status":"ok"}`（ローカル or CI で backend 起動時）。
- [ ] `deploy-backend.yml` に **ACR 参照（`azurecr.io`）が残っていない**こと（`grep -r azurecr .github/workflows backend` が空）。

---

## 3. パートB — iOS 版設計（SwiftUI + URLSession streaming）

### 3.1 アーキテクチャ（MVVM・単方向）
```
ios/
  project.yml                       # XcodeGen 定義（.xcodeproj はコミットしない）
  Sources/
    BungoRagApp.swift               # @main App
    Config.swift                    # BASE_URL（Info.plist 由来）
    Model/
      Models.swift                  # ChatMessage/ChatRequest/Source/StreamEvent
    Net/
      BungoAPI.swift                # URLSession.bytes による NDJSON ストリーム
    ViewModel/
      ChatViewModel.swift           # @MainActor ObservableObject
    View/
      ChatView.swift                # チャットUI（履歴・入力・参照元）
    Info.plist
  .github/workflows/ios-ci.yml      # macOS runner ビルド（署名なし）
```
データフロー：`ChatView` → `ChatViewModel.send()` → `BungoAPI.streamChat` が `StreamEvent` を逐次コールバック → `@Published` 更新 → UI 再描画。**Android の `BungoApi.kt`/`Models.kt` が1:1の参照実装**。

### 3.2 ファイル別仕様（安価エージェント向け・実装粒度）

**`Model/Models.swift`**（契約は §2.1 と厳密一致）
- `struct ChatMessage: Codable { let role: String; let content: String }`
- `struct ChatRequest: Encodable { let message: String; let history: [ChatMessage]; let topK: Int }` — `CodingKeys` で `topK = "top_k"`。
- `struct Source: Decodable, Identifiable { let id = UUID(); let title,author,style,text: String; CodingKeys で id を除外（title/author/style/text のみ） }` — **未知キー（book_id 等）は Codable が自動で無視**。
- `enum StreamEvent { case token(String); case sources([Source]); case done; case error(String) }`
- デコード補助 `private struct RawEvent: Decodable { let type: String; let content: String?; let sources: [Source]?; let message: String? }`。

**`Net/BungoAPI.swift`**（§調査1 の URLSession.bytes.lines を採用）
```swift
final class BungoAPI {
    private let base: URL
    private let session: URLSession
    init(baseURL: URL) {
        self.base = baseURL
        let c = URLSessionConfiguration.default
        c.timeoutIntervalForRequest = 200   // scale-to-zero コールドスタート(最大1〜2分)対応
        c.timeoutIntervalForResource = 600
        self.session = URLSession(configuration: c)
    }
    func streamChat(_ req: ChatRequest, onEvent: @escaping (StreamEvent) -> Void) async throws {
        var r = URLRequest(url: base.appendingPathComponent("chat"))
        r.httpMethod = "POST"
        r.setValue("application/json", forHTTPHeaderField: "Content-Type")
        r.setValue("application/x-ndjson", forHTTPHeaderField: "Accept")
        r.httpBody = try JSONEncoder().encode(req)
        let (bytes, resp) = try await session.bytes(for: r)
        guard let h = resp as? HTTPURLResponse, 200..<300 ~= h.statusCode else { throw URLError(.badServerResponse) }
        for try await line in bytes.lines {
            guard let data = line.data(using: .utf8),
                  let raw = try? JSONDecoder().decode(RawEvent.self, from: data) else { continue }
            switch raw.type {
            case "token":   if let c = raw.content { onEvent(.token(c)) }
            case "sources": onEvent(.sources(raw.sources ?? []))
            case "done":    onEvent(.done)
            case "error":   onEvent(.error(raw.message ?? "unknown"))
            default: break
            }
        }
    }
}
```

**`ViewModel/ChatViewModel.swift`**：`@MainActor final class ChatViewModel: ObservableObject`。
- `@Published var messages: [ChatMessage]`、`@Published var streaming: String?`、`@Published var sources: [Source]`、`@Published var isLoading: Bool`、`@Published var errorText: String?`。
- `func send(_ text: String)`：user を messages に追加 → `Task { try await api.streamChat(...) { event in … } }`。token は streaming に連結、done で streaming を assistant メッセージへ確定、error は errorText。
- 更新は `@MainActor` なので UI スレッド安全（§調査1）。

**`View/ChatView.swift`**：`List` に messages（＋streaming 中の仮バブル・末尾に "▌"）、下部に `TextField`＋送信ボタン、参照元は `DisclosureGroup` で `sources` 表示。ウェルカム例文4件は Android と同一文言。

**`Config.swift`**：`BASE_URL` は `Info.plist` の `BUNGO_BASE_URL`（XcodeGen で注入）から読む。既定は `bungo-api` の本番URL（§5でデプロイ後に確定）。

**`BungoRagApp.swift`**：`@main struct BungoRagApp: App { var body: some Scene { WindowGroup { ChatView() } } }`。

### 3.3 再現可能プロジェクト `ios/project.yml`（XcodeGen・§調査3）
```yaml
name: BungoRag
options:
  bundleIdPrefix: com.bungo
  deploymentTarget: { iOS: "16.0" }
settings:
  base: { MARKETING_VERSION: "1.0", CURRENT_PROJECT_VERSION: "1", GENERATE_INFOPLIST_FILE: NO }
targets:
  BungoRag:
    type: application
    platform: iOS
    sources: [Sources]
    info:
      path: Sources/Info.plist
      properties:
        CFBundleDisplayName: 文語作文支援
        UILaunchScreen: {}
        BUNGO_BASE_URL: https://bungo-api.gentleground-ba3d7ba2.japaneast.azurecontainerapps.io
```
> `.xcodeproj` は **コミットしない**（`ios/.gitignore` に `*.xcodeproj`）。CI/開発では `xcodegen generate` で再生成（§調査3）。Azure は HTTPS なので ATS 例外は不要。

### 3.4 macOS CI `.github/workflows/ios-ci.yml`（§調査2）
```yaml
name: iOS CI
on:
  push: { paths: ["ios/**", ".github/workflows/ios-ci.yml"] }
  pull_request: { paths: ["ios/**"] }
jobs:
  build:
    runs-on: macos-14
    steps:
      - uses: actions/checkout@v4
      - run: brew install xcodegen
      - working-directory: ios
        run: xcodegen generate
      - working-directory: ios
        run: >
          xcodebuild build
          -project BungoRag.xcodeproj -scheme BungoRag
          -sdk iphonesimulator
          -destination 'platform=iOS Simulator,name=iPhone 15,OS=latest'
          CODE_SIGNING_ALLOWED=NO
```
> **シークレット不使用**。fork PR が走っても機密に触れないため安全（本リポの CI セキュリティ方針と整合）。

### 3.5 受け入れ基準（B）
- [ ] `ios/project.yml` から `xcodegen generate` が成功（macOS）。
- [ ] `ios-ci.yml` が `macos-14` で **署名なしビルド成功**（Actions 緑）。
- [ ] シミュレータ起動 → 例文タップ → **トークンが逐次表示**され、参照元が出る（§5 の実 backend 接続後）。
- [ ] Source の `book_id` 等の未知キーでデコードが壊れないこと。

---

## 4. フェーズ分割ロードマップ（各フェーズ＝安価エージェント1タスク）

| # | フェーズ | 成果物 | 検証（受け入れ） | 実行環境 |
|---|---|---|---|---|
| P0 | 起点 | `claude/ios-app`（main 基軸） | `git merge-base --is-ancestor origin/main HEAD` | ✅済(このコンテナ) |
| P1 | backend 統合＋ghcr化 | `backend/` を main へ、`deploy-backend.yml`(ghcr)、`deploy-api.sh`(ghcr) | §2.3、`grep -r azurecr` 空、`import backend.main` 成功 | コンテナ（コード）＋Azure(デプロイは人/CI) |
| P2 | iOS scaffold | `ios/project.yml`・`ios/.gitignore`・`ios/Sources/`(空App)・`ios-ci.yml` | CI で `xcodegen generate`＋空アプリビルド緑 | コンテナ(執筆)＋macOS CI(検証) |
| P3 | iOS ネットワーク層 | `Models.swift`・`BungoAPI.swift` | ビルド緑、`RawEvent` デコード単体（可能なら XCTest） | 同上 |
| P4 | iOS UI | `ChatViewModel.swift`・`ChatView.swift`・`Config.swift`・`BungoRagApp.swift` | ビルド緑、シミュレータ起動（UIテスト任意） | 同上 |
| P5 | 結線・E2E | `Config` の BASE_URL＝本番`bungo-api`、Android の `BUNGO_BASE_URL` も更新 | 実機/シミュレータで §3.5 の逐次表示、Android も疎通 | 端末/Mac（本番接続） |

**依存**：P1 は P2〜 と独立（並行可）。iOS の E2E（P5）は P1（backend デプロイ）完了が前提。

---

## 5. 実行順・分担
1. **本コンテナ（安価エージェント）でできる**：P1 のコード改修、P2〜P4 の Swift/yaml **執筆＋コミット**。ビルド検証は CI（macOS）に委譲。
2. **人/CI が担う**：`bungo-api` の初回作成（シークレット注入）、iOS の macOS ビルド確認（Actions 緑を見る）、実機テスト。
3. **Azure 通信は本コンテナから不可**（プロキシ遮断）。実疎通は CI/端末側。

---

## 6. 実装エージェントへの指示テンプレ（各フェーズ）
> 安価エージェントに渡すプロンプトの雛形。**本書のファイル別仕様に厳密に従い、契約(§2.1)を変更しないこと**を必ず含める。

- P1: 「`origin/claude/android-native:backend/` を現ブランチに取り込み、`deploy-backend.yml`/`deploy-api.sh` を本書§2.2 の ghcr 版へ置換。`app/rag.py` は改変しない。`grep -r azurecr` が空になるまで。」
- P2: 「本書§3.3 の `ios/project.yml`、`ios/.gitignore`（`*.xcodeproj`）、`ios/Sources/BungoRagApp.swift`(最小)、`ios/Sources/Info.plist`、§3.4 の `ios-ci.yml` を作成。」
- P3: 「本書§3.2 の `Models.swift`・`BungoAPI.swift` を作成。契約(§2.1)厳守、未知キー無視。」
- P4: 「本書§3.2 の ViewModel/View/Config/App を作成。Android の文言・挙動に合わせる。」

---

## 7. リスクと対策
| リスク | 対策 |
|---|---|
| iOS を Linux コンテナでビルド不可 | 執筆はコンテナ、ビルド/テストは `macos-14` CI（署名なし）に委譲（§3.4） |
| scale-to-zero コールドスタート(1〜2分) | `timeoutIntervalForRequest=200`（§3.2）。UI に「起動中」表示 |
| main が並行分岐（STATUS.md 警告） | 各フェーズ push 前に `git fetch origin && git rebase origin/main` |
| Source 契約に `book_id` 追加 | クライアントは未知キー無視（Codable 既定・Ktor `ignoreUnknownKeys`） |
| Foundry の temperature 非対応 | backend は rag.py 経由なので既に対応済み（クライアントは無関係） |
| App Store 配布の署名 | 本ロードマップ外。CI は simulator ビルドのみ（署名不要）。配布時に別途証明書 |
| **【実測・既知の落とし穴】`macos-14` 既定Xcode(15.4)がxcodegen生成プロジェクトを読めない** | `xcodegen` が生成する `.pbxproj` の `objectVersion` が Xcode 15.4 の対応範囲を超え「future Xcode project file format」で失敗（P2実装時に実際に発生）。`ios-ci.yml` に **ランナー上の最新 Xcode を動的選択する** ステップ（`ls /Applications/Xcode_*.app \| sort -V \| tail -1` → `xcode-select -s`）を追加して解消。特定バージョンをハードコードせずランナーイメージ更新に強くする。 |

---

## 8. 調査の裏付け（出典）
1. **iOS ストリーミング**：`URLSession.bytes(for:)` は本文を `AsyncBytes`（`AsyncSequence`）で返し、`.lines` で行単位に `for try await` 消費できる。UI 更新は MainActor。→ NDJSON を1行=1イベントで逐次処理可能。
   [WWDC21 async/await URLSession](https://developer.apple.com/videos/play/wwdc2021/10095/) ／ [URLSession.AsyncBytes](https://developer.apple.com/documentation/foundation/urlsession/asyncbytes)
2. **署名なし macOS CI**：`xcodebuild ... -sdk iphonesimulator CODE_SIGNING_ALLOWED=NO`（または `CODE_SIGNING_REQUIRED=NO CODE_SIGN_IDENTITY=""`）でシミュレータビルド/テストは証明書不要。GitHub Actions `macos` runner で再現可能。
   [installing-an-apple-certificate（署名要否の公式）](https://docs.github.com/actions/deployment/deploying-xcode-applications/installing-an-apple-certificate-on-macos-runners-for-xcode-development) ／ [Quality Coding: GitHub Actions CI with Xcode](https://qualitycoding.org/github-actions-ci-xcode/)
3. **再現可能プロジェクト**：XcodeGen は `project.yml`（YAML）から `.xcodeproj` を生成。`.xcodeproj` はコミットせず CI で `xcodegen generate` する運用が推奨。
   [XcodeGen 公式](https://xcodegen.com/) ／ [yonaskolb/XcodeGen](https://github.com/yonaskolb/XcodeGen)
