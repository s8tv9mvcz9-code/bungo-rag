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

> `gradle-wrapper.jar` はコミット済みなので、`./gradlew` がそのまま動く
> （CI もこれを使う）。Android Studio で `android/` を開けば SDK/依存も自動解決される。

## API のベースURL設定

既定の接続先は **本番 bungo-api**（iOS と同一URL）。ローカルバックエンドに
向けたいときだけ `android/gradle.properties` の `BUNGO_BASE_URL` を変更するか、
ビルド時に `-PBUNGO_BASE_URL=...` で一時上書きする：

| 実行環境 | 値 |
|---|---|
| 本番（Container Apps） | `https://bungo-api.gentleground-ba3d7ba2.japaneast.azurecontainerapps.io`（既定） |
| エミュレータ → ホストPCのバックエンド | `http://10.0.2.2:8000` |
| 同一LANの実機 → PC | `http://<PCのLAN IP>:8000` |

コマンドラインで一時上書きする例（ローカルのバックエンドに向ける）：

```bash
cd android
./gradlew installDebug -PBUNGO_BASE_URL=http://10.0.2.2:8000
```

## ローカルでの動作確認手順

既定では本番 bungo-api に繋がるので、`./gradlew installDebug` だけで動作確認できる。
ローカルのバックエンドで試す場合は次の手順：

1. バックエンドを起動（`../backend/README.md` 参照、`.env` 必須）
2. エミュレータを起動（ホストの 8000 番は `10.0.2.2:8000` で見える）
3. `./gradlew installDebug -PBUNGO_BASE_URL=http://10.0.2.2:8000` でインストール → アプリ起動
4. 例文タップ or 入力欄から送信 → 文語体がストリーミング表示される

## 通信プロトコル

`POST /chat` の NDJSON を 1 行ずつ `StreamEvent` にデコード：

- `token` … 生成トークン（逐次追記して表示）
- `sources` … 参照した青空文庫チャンク（折りたたみカードで表示）
- `done` … 完了
- `error` … エラー（メッセージ表示）

## CI 配布と署名

- main への push で CI が debug APK をビルドし、GitHub Releases **`android-latest`** に添付する
  （実機へのインストール手順は [`../docs/device-testing.md`](../docs/device-testing.md)）。
- debug ビルドはコミット済みの **`ci-debug.keystore`** で署名される（CI・ローカル共通）。
  ランナー毎に生成される鍵だと APK 更新のたびに署名不一致で再インストールが必要になるため固定している。
  debug 証明書はストア公開に使えないため秘匿する価値は無い（release 署名鍵とは別物）。

## セキュリティ注意

- API キー（Azure / GitHub Models）は **アプリに含めない**。すべてバックエンドが保持する。
- 既定の本番接続は HTTPS（TLS 必須）。平文 HTTP を許可しているのは開発用の
  `10.0.2.2 / localhost / 127.0.0.1` のみ（`res/xml/network_security_config.xml`）で、
  本番ドメインはこの例外に含めていない。
