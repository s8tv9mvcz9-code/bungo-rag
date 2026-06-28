# bungo-rag Android (Kotlin + Jetpack Compose)

戦前文体 RAG チャットボットの Android ネイティブクライアント。
RAG 処理は `../backend`（FastAPI）が担い、本アプリはその NDJSON ストリームを
Ktor で逐次受信して表示する。

## 構成

```
android/
  settings.gradle.kts / build.gradle.kts / gradle.properties
  gradle/libs.versions.toml         — バージョンカタログ
  app/
    build.gradle.kts                — BASE_URL を BuildConfig に埋め込み
    src/main/
      AndroidManifest.xml
      res/                          — テーマ・文字列・アダプティブアイコン・network_security_config
      java/com/bungo/rag/
        MainActivity.kt
        ChatViewModel.kt            — StateFlow で UI 状態管理、ストリーミング集約
        data/
          Models.kt                 — ChatRequest / Source / StreamEvent（sealed）
          BungoApi.kt               — Ktor で /chat を NDJSON ストリーム受信
        ui/
          ChatScreen.kt             — Compose チャット UI（履歴・例・参照元）
          theme/                    — 墨×生成りの古典配色 + 明朝
```

## ビルド前提

- Android Studio（Koala 以降）または Android SDK + JDK 17
- `compileSdk = 34` / `minSdk = 26`

> **gradle-wrapper.jar は未コミット**（バイナリのため）。初回のみ次のどちらかで生成する：
> - Android Studio で `android/` を開く（自動生成）
> - `cd android && gradle wrapper`（ローカルに Gradle がある場合）

## API のベースURL設定

`android/gradle.properties` の `BUNGO_BASE_URL` を環境に合わせて変更する：

| 実行環境 | 値 |
|---|---|
| エミュレータ → ホストPCのバックエンド | `http://10.0.2.2:8000`（既定） |
| 同一LANの実機 → PC | `http://<PCのLAN IP>:8000` |
| 本番（Container Apps） | `https://bungo-api.<region>.azurecontainerapps.io` |

コマンドラインで一時上書きも可能：

```bash
cd android
./gradlew installDebug -PBUNGO_BASE_URL=https://bungo-api.example.azurecontainerapps.io
```

## ローカルでの動作確認手順

1. バックエンドを起動（`../backend/README.md` 参照、`.env` 必須）
2. エミュレータを起動（ホストの 8000 番は `10.0.2.2:8000` で見える）
3. `./gradlew installDebug` でインストール → アプリ起動
4. 例文タップ or 入力欄から送信 → 文語体がストリーミング表示される

## 通信プロトコル

`POST /chat` の NDJSON を 1 行ずつ `StreamEvent` にデコード：

- `token` … 生成トークン（逐次追記して表示）
- `sources` … 参照した青空文庫チャンク（折りたたみカードで表示）
- `done` … 完了
- `error` … エラー（メッセージ表示）

## セキュリティ注意

- API キー（Azure / GitHub Models）は **アプリに含めない**。すべてバックエンドが保持する。
- 開発用に平文 HTTP を許可しているのは `10.0.2.2 / localhost / 127.0.0.1` のみ
  （`res/xml/network_security_config.xml`）。本番は HTTPS のみで、この許可は不要。
