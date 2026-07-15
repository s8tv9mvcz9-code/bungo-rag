# 📌 プロジェクト現況・引き継ぎメモ（bungo-rag）

> **これは人間＋次のClaudeセッション向けの全体像です。まずここを読めば迷いません。**
> 技術的な設計詳細は [`CLAUDE.md`](./CLAUDE.md)、全体の入口は [`README.md`](./README.md)。最終更新: 2026-07-15

---

## 🎯 このアプリは何か

青空文庫をコーパスにした **現代語→戦前文体（旧字旧仮名・文語体）変換 RAG チャットボット**。
LLM が生成の主体、RAG は「文体参照」用（内容の転用は禁止）。
**Web(Streamlit) / iOS / Android の3プラットフォーム**が単一の RAG ロジック（SSOT: `app/rag.py`）を共有する。

## 🌐 ライブ環境

- **Web**: https://bungo-app.gentleground-ba3d7ba2.japaneast.azurecontainerapps.io
- **API（モバイル用）**: https://bungo-api.gentleground-ba3d7ba2.japaneast.azurecontainerapps.io （`/health` が version=git SHA を返す）
- **チャット**: Azure AI Foundry の **Claude Opus 4.8**（Anthropic Messages API 経由、Prompt Caching 有効）
- **Embedding**: Azure OpenAI `text-embedding-3-small`
- **検索**: Azure AI Search `bungo-chunks`（**free tier = $0**、300作品 / 約7千チャンク）

## 💰 コスト

- **固定費: $0**（Search=free、Container Apps=scale-to-zero、レジストリ=ghcr.io public）
- **変動費**: Opus トークンのみ（〜$0.02〜0.04/メッセージ）＋Embedding は無視できる額

## 🚀 CI/CD（すべて main push で自動、人間介入なし）

| Workflow | 対象 | 成果物 |
|---|---|---|
| `deploy.yml` | Web | `bungo-app` 更新 |
| `deploy-backend.yml` | API | `bungo-api` 更新（未作成なら bungo-app から env 複製して**自動作成**）＋ `/health` 疎通ゲート |
| `android-ci.yml` | Android | APK 検証 ＋ Releases **`android-latest`** に debug APK 添付（固定署名鍵 `android/ci-debug.keystore` で更新インストール可） |
| `ios-ci.yml` | iOS | シミュレータ検証 ＋ Releases **`ios-latest`** に未署名 IPA 添付 |

- 実機テスト手順: [`docs/device-testing.md`](./docs/device-testing.md)（Android=APK直インストール / iOS=自分のApple IDで署名）
- ローカルからの手動デプロイ: `./deploy.sh`（Web）/ `bash backend/deploy-api.sh`（API、.env のシークレット注入つき初回作成に使う）

## ✅ 直近セッションで完了したこと（2026-07-15）

1. **モバイル対応を main に統合** — backend(FastAPI/NDJSON) + iOS(SwiftUI) + Android(Compose)。API契約（token/sources/done/error）は3クライアントで整合確認済み。
2. **`deploy-backend.yml` の致命バグ修正** — 旧版はフロースタイルYAML内の `${{ }}` でパース不能となり**全10回 startup failure**（bungo-api が一度もCDデプロイされていなかった）。ブロックスタイルで書き直し、bungo-app からの env 複製による自動初回作成と `/health` ゲートを追加。
3. **実機配布 CI/CD** — Android: APK を `android-latest` にローリング添付（固定 debug keystore で署名安定化）。iOS: 未署名 IPA を `ios-latest` に添付。
4. **リポジトリ整理** — root README 新設、実機テストdocsを `docs/device-testing.md` に統合、`startup.sh`（未参照の遺物）削除、Dockerfile HEALTHCHECK 修正（curl→python）、deploy-api.sh のログイン欠落修正、古いPR #4/#5 クローズ。
5. **生成品質ロードマップ策定** — [`docs/quality-roadmap.md`](./docs/quality-roadmap.md)（3視点独立立案→統合。リンタが要石）。

## ⚠️ ハマりどころ・次セッションへの注意

- **⚠️ workflow YAML はブロックスタイルで書く** — `with: { creds: ${{ secrets.X }} }` のようなフロースタイルは `}}` がマッピングを閉じて**パース不能**になり、全 push が startup failure になる（実際に起きた）。
- **⚠️ 新規 ghcr パッケージは既定 private** — Azure Container Apps は匿名 pull（public 前提）でイメージを引くため、新パッケージを作ったら **Profile → Packages → 該当 → Change visibility → Public** が必須（忘れると `UNAUTHORIZED: authentication required` でデプロイ失敗。`bungo-rag-api` で実際に発生し public 化で解決）。deploy-backend.yml に public 事前確認ステップあり。
- **⚠️ 並行セッションで `main` が分岐しやすい** — push 前に必ず `git fetch origin` して origin/main との差分を確認。
- **`.env` は本番シークレット** — gitignore 維持・絶対にコミットしない。bungo-api の env は bungo-app から複製済み（キー更新時は両方に反映）。
- **Foundry の Claude 制約**: `temperature` は 400 で拒否（送らない）／ `system` はトップレベル引数／ Prompt Caching は β（`anthropic-beta` ヘッダ必須）。
- **再インデックス**（`python3 scripts/build_index.py`）は**ライブの検索インデックスを上書き**する。
- **provider 判定は2ファイル**（`app/rag.py` と `scripts/query.py`）に重複。両方同時に変更（一本化は quality-roadmap 3-1）。
- **bungo-api の FQDN 変更時**は4箇所＋docsを同時更新: `android/gradle.properties` / `android/app/build.gradle.kts` / `ios/project.yml` / `ios/Sources/Config.swift`。
- **AZURE_CREDENTIALS**（Service Principal の client secret）には**有効期限**がある。失効すると deploy 系2本が同時に壊れる。恒久対策は OIDC 移行（未着手）。
- **Android の未知イベント type** は例外を投げる（sealed 契約）。NDJSON に新イベントを足す前に前方互換化が必要（quality-roadmap 3-2）。

## 🗂 ブランチの状態（2026-07-15 棚卸し）

- **`main`** — 唯一の開発基点。全成果はここにある。
- **削除候補（main に完全包含、独自コミット0 — 消しても何も失われない）**: `claude/ios-app`, `claude/iphone-claude-code-setup-d2w3m`, `develop`
  削除する場合: `git push origin --delete claude/ios-app claude/iphone-claude-code-setup-d2w3m develop`
- **アーカイブ（未マージの独自コミットあり・PRはクローズ済み）**:
  - `claude/foundry-claude` — ゼロコスト・ローカル検索＆マルチプロバイダ対応（PR #5）
  - `claude/android-native` — 旧Android試作（PR #4、現行版に置換済み）
  - `claude/zero-cost-stack` — 無料ホスティング調査
  - `claude/azure-bicep-iac` — Azure構成のBicep化
  - 必要になったら main を基点に作り直すか、該当ブランチから cherry-pick する。

## 🔜 次にやること（推奨順）

1. **品質ロードマップ Phase 0**（styleフィルタ1行・few-shot差し替え・max_tokens）— [`docs/quality-roadmap.md`](./docs/quality-roadmap.md) 参照。即効・低リスク。
2. **Phase 1 リンタ**（要石。評価/監査/リランキング/自己検証の4用途）。
3. AZURE_CREDENTIALS の OIDC 移行（期限切れ事故の予防）。
4. `.env` の GitHub PAT ローテーション（推奨）。

## 🗂 主要リソース名

| 種別 | 名前 |
|---|---|
| Resource Group | `bungo-rag-rg` |
| Container Apps | `bungo-app`（Web）/ `bungo-api`（API）/ env `bungo-env`（japaneast） |
| Search サービス | `bungo-search`（free）/ index `bungo-chunks` |
| コンテナレジストリ | `ghcr.io/s8tv9mvcz9-code/bungo-rag`（Web）/ `bungo-rag-api`（API）— 共に public |
| モバイル配布 | GitHub Releases `android-latest` / `ios-latest`（ローリング更新） |
| GitHub リポジトリ | `s8tv9mvcz9-code/bungo-rag` |
