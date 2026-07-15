# 実機テストガイド（iPhone / Android）

手持ちのスマートフォンで bungo-rag のネイティブアプリを動かして試すための手順。
**人間の作業が必要なのは「端末へのインストール」だけ**で、ビルド成果物は CI が自動生成する。

```
main へ push
  ├─ Android CI → debug APK を Releases「android-latest」に自動添付（そのままインストール可）
  ├─ iOS CI    → 未署名 IPA を Releases「ios-latest」に自動添付（署名だけ手元で行う）
  └─ Deploy Backend API → bungo-api を自動デプロイ（/health で疎通ゲート）
```

---

## 0. 前提：バックエンドの確認

アプリは共通バックエンド `bungo-api` と通信する。まず生存確認：

```bash
curl -s https://bungo-api.gentleground-ba3d7ba2.japaneast.azurecontainerapps.io/health
# → {"status":"ok","version":"<git SHA>"} が返ればOK
```

- `version` は **デプロイされている SSOT（`app/rag.py`）の git SHA**。main の HEAD と一致していれば最新。
- scale-to-zero 構成のため、**初回アクセスは起動に1〜2分**かかることがある（異常ではない）。
- 返らない場合は GitHub Actions の「Deploy Backend API」の最新実行を確認。`backend/**` か `app/rag.py` を touch して main に push すれば再デプロイが走る。

---

## 1. Android 実機

### 方法A（推奨・最短）: Releases から APK をダウンロード

1. スマホのブラウザで GitHub にログインし、リポジトリの **Releases → `android-latest`** を開く
   （プライベートリポジトリのため要ログイン）
2. **`bungo-rag-debug.apk`** をダウンロード
3. 開こうとすると「提供元不明のアプリ」の許可を求められる → ブラウザ（またはファイルアプリ）に**インストール許可**を与える
4. インストール → 「文語作文支援」アプリを起動

APK は main への push ごとに自動更新される（リリースノートに commit SHA が記載される）。
接続先は本番 `bungo-api` がビルド時に埋め込まれており、設定不要。

### 方法B: ローカルビルド（開発時）

```bash
cd android
./gradlew installDebug                # USB接続した実機/エミュレータへ直接インストール（接続先=本番）
./gradlew installDebug -PBUNGO_BASE_URL=http://10.0.2.2:8000   # ローカルbackendに向ける場合
```

前提: Android SDK + JDK 17（または Android Studio）。詳細は [`android/README.md`](../android/README.md)。

---

## 2. iPhone 実機

iOS はプラットフォーム制約上、**自分の Apple ID（無料でよい）による署名**が必ず手元で必要になる。
有料の Apple Developer Program（$99/年）は不要。無料 Apple ID の制約として**7日ごとに再署名**が必要。

### 方法A（推奨）: Mac + Xcode でビルド＆インストール

1. **コードを取得してプロジェクト生成**
   ```bash
   git clone https://github.com/s8tv9mvcz9-code/bungo-rag.git
   cd bungo-rag/ios
   brew install xcodegen   # 未インストールなら
   xcodegen generate
   open BungoRag.xcodeproj
   ```
2. **無料 Apple ID で署名設定**
   - Xcode → Settings（⌘,）→ Accounts → **+** → Apple ID でサインイン
   - プロジェクト → TARGETS **BungoRag** → **Signing & Capabilities**
   - **Automatically manage signing** をチェック → Team に「(Personal Team)」を選択
   - Bundle ID 重複エラーが出たら `ios/project.yml` の `bundleIdPrefix` を自分だけの値に変えて `xcodegen generate` を再実行
3. **iPhone を接続して信頼**
   - ケーブル接続 →「このコンピュータを信頼しますか？」→ 信頼
   - Xcode のデバイス選択で自分の iPhone を選ぶ
   - 初回起動時に「開発者を信頼していません」→ iPhone の **設定 → 一般 → VPNとデバイス管理** → 自分の Apple ID を信頼
4. **⌘R でビルド＆実行**（初回は数分）。以後はホーム画面から起動できる。

### 方法B: CI の未署名 IPA + Sideloadly（Windows でも可）

Mac で Xcode を開きたくない場合、CI が生成する未署名 IPA に手元で署名する：

1. GitHub の **Releases → `ios-latest`** から **`BungoRag-unsigned.ipa`** をダウンロード
2. [Sideloadly](https://sideloadly.io/)（Mac/Windows）を起動し、iPhone を接続
3. IPA をドラッグ＆ドロップ → 自分の Apple ID でサインイン → **Start**
4. iPhone 側で開発者を信頼（方法Aの3-最終段と同じ）

> 注: 未署名 IPA はそのままではインストールできない。署名は必ず自分の Apple ID で行うこと。
> 7日で期限が切れるのは方法Aと同じ（再署名すればよい）。

---

## 3. 動作確認シナリオ（両OS共通）

| 確認項目 | 操作 | 期待結果 |
|---|---|---|
| 起動 | アプリを開く | 「📖 文語作文支援」ウェルカム画面、例文が表示 |
| 例文送信 | 例文をタップ | 応答が**逐次ストリーミング表示**される |
| コールドスタート | 初回送信 | 応答開始まで最大1〜2分かかることがある（scale-to-zero、異常ではない） |
| 手入力 | 入力→送信 | 現代語が旧字旧仮名・文語体に変換される |
| 参照元表示 | 応答完了後 | 「📚 参照した青空文庫テキスト」の折りたたみが開ける |
| 複数ターン | 続けて送信 | 会話履歴を踏まえた応答になる |
| エラー系 | 機内モードで送信 | 「⚠️ 通信エラー」が表示される（クラッシュしない） |

## 4. トラブルシューティング

| 症状 | 原因・対処 |
|---|---|
| 応答が永遠に返らない | backend 未起動/未デプロイ → §0 の `/health` を確認 |
| Android「アプリをインストールできません」 | 提供元不明アプリの許可が未設定。ダウンロードに使ったアプリへ許可を与える |
| iOS ビルドエラー "No Team" | 署名設定（方法A-2）が未完了 |
| iOS "Failed to register bundle identifier" | Bundle ID が他人と重複。`bundleIdPrefix` を変更して再生成 |
| iOS 7日後に起動不可 | 無料 Apple ID の証明書期限。再ビルド（⌘R）または Sideloadly で再署名 |
| 応答の version が古い | `/health` の `version` と main の HEAD を比較。CD の実行結果を確認 |

## 5. 配布の次の一歩（スコープ外）

- **App Store / Google Play 配布**: 開発者登録（Apple $99/年、Google $25 買い切り）と審査が必要
- **TestFlight / Internal testing**: 同上。家族・友人に配る場合の選択肢
