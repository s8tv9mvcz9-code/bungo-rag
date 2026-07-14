# 実機iPhoneでのテスト手順（ロードマップP5）

対象：**普通のiPhone実機**（Xcode Simulatorではなく実デバイス）でこのアプリを動かして試す。

> ⚠️ **前提：Macが必須**。iOSの実機ビルドは Xcode（macOS専用）でしか行えない。
> このリポジトリの開発はどこからでもできるが、**この最終ステップだけは Mac 上で行う**。

---

## 全体の流れ

```
① Backend（bungo-api）が動いているか確認・無ければデプロイ  ← これが無いとアプリは動かない
② Mac にコードを持ってくる
③ Xcode プロジェクトを生成
④ 無料 Apple ID で署名設定
⑤ iPhone を接続し、実機を信頼
⑥ ビルド&実行
⑦ 動作確認
```

---

## ① Backend（bungo-api）の確認・デプロイ

このアプリは `bungo-api`（Azure Container Apps上のFastAPI）と通信する。**まずこれが生きているか確認する**：

```bash
curl -s https://bungo-api.gentleground-ba3d7ba2.japaneast.azurecontainerapps.io/health
```

- `{"status":"ok"}` が返れば **① は完了、③へ進んでよい**。
- 何も返らない/エラーなら、**まだデプロイされていない**。以下を実行（Azure認証が必要、あなたの作業）：

```bash
git clone https://github.com/s8tv9mvcz9-code/bungo-rag.git
cd bungo-rag
git checkout claude/ios-app   # または main にマージ済みならそちらを checkout

az login                      # Azure認証
# .env に既存の Streamlit と同じ値を用意（AZURE_SEARCH_*, AZURE_OPENAI_*, CHAT_* など）
bash backend/deploy-api.sh
```

最後に出力される `BUNGO_BASE_URL=https://...` を確認する。
**このURLが `ios/project.yml` の `BUNGO_BASE_URL` と食い違う場合**は、`ios/project.yml` の値を実際のURLに書き換えてコミットする（次のP5作業）。

> 💤 補足：`bungo-app`（Streamlit）と同じ scale-to-zero 構成なので、初回アクセス時は起動に1〜2分かかることがある。アプリがすぐ反応しなくても異常ではない。

---

## ② Mac にコードを持ってくる

Mac のターミナルで：

```bash
git clone https://github.com/s8tv9mvcz9-code/bungo-rag.git
cd bungo-rag
git checkout claude/ios-app
```

---

## ③ Xcode プロジェクトを生成

```bash
brew install xcodegen   # 未インストールなら
cd ios
xcodegen generate
open BungoRag.xcodeproj
```

Xcode が開く。

---

## ④ 無料 Apple ID で署名設定（実機インストールに必須）

有料の Apple Developer Program（年間$99）は**不要**。無料の Apple ID で実機に直接インストールできる（Xcode 9以降の仕様）。制約：**7日ごとに再ビルド・再インストールが必要**（証明書の有効期限）。

1. Xcode → **Settings**（⌘,） → **Accounts** タブ → 左下 **+** → **Apple ID でサインイン**（持っていなければ無料で作成可）
2. プロジェクトナビゲータで **BungoRag**（青いプロジェクトアイコン）をクリック
3. **TARGETS → BungoRag → Signing & Capabilities** タブを開く
4. **Automatically manage signing** にチェック
5. **Team** のドロップダウンで、先ほどサインインした Apple ID（"あなたの名前 (Personal Team)"）を選択
6. Bundle Identifier が重複エラーになったら、末尾に適当な文字列を足す（例: `com.bungo.BungoRag` → `com.bungo.BungoRagYourName`）— **これは `ios/project.yml` の `bundleIdPrefix` に依存**、エラーが出たら project.yml の `bundleIdPrefix: com.bungo` を自分だけの値に変更して `xcodegen generate` を再実行

---

## ⑤ iPhone を接続し、実機を信頼

1. iPhone を Mac に **Lightning/USB-Cケーブルで接続**（初回はワイヤレスより確実）
2. iPhone側で「**このコンピュータを信頼しますか？**」→ **信頼**
3. Xcode 上部のデバイス選択（シミュレータ名が出ている場所）をクリックし、接続した自分のiPhoneを選択
4. 初回ビルド時、iPhone側に「開発者を信頼していません」と出た場合：
   **iPhone の 設定 → 一般 → VPNとデバイス管理 → （自分のApple IDのプロファイル） → 信頼**

---

## ⑥ ビルド＆実行

Xcode で **⌘R**（または左上の ▶️ ボタン）。

- 初回はビルドに数分かかる
- iPhone側で自動的にアプリが起動する
- ホーム画面にも「文語作文支援」アイコンが追加される（次回以降はケーブル無しでも起動可能、ただし通信は必要）

---

## ⑦ 動作確認（テストシナリオ）

| 確認項目 | 操作 | 期待結果 |
|---|---|---|
| 起動 | アプリを開く | 「📖 文語作文支援」ウェルカム画面、例文4件が表示 |
| 例文送信 | 例文をタップ | ユーザー発言が表示 → アシスタント応答が**逐次ストリーミング表示**（末尾に「▌」カーソル） |
| コールドスタート | 初回送信 | backendがscale-to-zeroの場合、応答開始まで最大1〜2分かかることがある（異常ではない） |
| 手入力 | テキスト欄に入力→送信ボタン | 同様に応答が返る |
| 参照元表示 | 応答完了後 | 「📚 参照した青空文庫テキスト」の折りたたみが表示され、タップで開く |
| 複数ターン | 続けて質問 | 会話履歴を踏まえた応答になる |
| エラー系 | 機内モードにして送信 | 赤字で「⚠️ 通信エラー: ...」が表示される（クラッシュしない） |

---

## トラブルシューティング

| 症状 | 原因・対処 |
|---|---|
| ビルドエラー "No Team" | ④の署名設定ができていない |
| "Failed to register bundle identifier" | Bundle ID が他人と重複。`bundleIdPrefix` を変更して再生成 |
| 実機で起動直後にクラッシュ | Xcode の Console ログを確認。`Config.baseURL` 関連なら Info.plist の注入を疑う |
| 応答が永遠に返らない（▌のまま） | backend未デプロイ（①を再確認）、または `ios/project.yml` の BUNGO_BASE_URL が実際のデプロイURLと不一致 |
| 7日後に開けなくなる | 無料Apple IDの証明書期限切れ。Xcodeで再ビルド（⌘R）すればよい |
| Wi-Fi経由でビルドしたい | Xcode → Window → Devices and Simulators → 実機を選択 → "Connect via network" を有効化（初回はケーブル接続が必要） |

---

## 次の一歩（このガイドの範囲外）

- **App Store配布**：有料Developer Program登録・審査が必要（本ロードマップのP5は「自分の実機で試す」までがスコープ）
- **TestFlight配布**（家族・友人に配りたい場合）：同じく有料Developer Program登録が必要
