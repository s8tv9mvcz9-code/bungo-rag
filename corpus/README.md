# corpus/ — ローカル検索インデックス置き場

`index.npz`（埋め込み行列）と `meta.json`（チャンク本文・出典）をここに置くと、
アプリは Azure AI Search なしのローカル検索で動作する（`VECTOR_BACKEND=auto`）。

構築方法は `docs/zero-cost.md` を参照:
- ローカル: `python scripts/build_index.py --limit 50`
- CI: GitHub Actions の「Build Local Search Index」ワークフロー（corpus/ を自動コミット）

※ `--mock-embeddings` で作ったインデックスは検証専用。コミットしないこと。
