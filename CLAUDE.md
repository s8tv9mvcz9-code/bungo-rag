# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> **👉 まず [`STATUS.md`](./STATUS.md) を読むこと。** ライブ環境・デプロイ経路・直近の変更・ハマりどころ（特に「`main` が並行セッションで分岐しやすい → push 前に `git fetch`」）の全体像がある。

## What this is

**bungo-rag** — a RAG chatbot that converts modern Japanese into pre-war literary style (旧字旧仮名 / 文語体). It retrieves passages from Aozora Bunko (青空文庫) public-domain works as "style exemplars" and uses an LLM to rewrite/compose in that register. The corpus lives in Azure AI Search.

**This is a monorepo with three clients sharing one SSOT.** The RAG logic lives entirely in `app/rag.py`; the Streamlit web app imports it directly, `backend/main.py` (FastAPI) wraps it as an NDJSON streaming HTTP API, and the iOS (SwiftUI) / Android (Kotlin+Compose) native apps consume that API. Changing `app/rag.py` changes behavior on every platform.

Note: the codebase, comments, and prompts are written in Japanese.

## Commands

Setup:
```bash
pip install -r requirements.txt   # openai, azure-search-documents, streamlit, etc.
# Requires a .env file (gitignored) — see "Environment" below.
```

Run the apps locally:
```bash
streamlit run app/app.py                 # Web UI on :8501
uvicorn backend.main:app --reload        # Mobile API on :8000 (needs backend/requirements.txt too)
```

Build the mobile clients:
```bash
cd android && ./gradlew assembleDebug    # APK (JDK 17; wrapper jar committed)
cd ios && xcodegen generate              # then open BungoRag.xcodeproj (macOS only)
```

Build / rebuild the search index (one-time / corpus refresh — downloads ~300 works (`MAX_BOOKS`) from Aozora and embeds them):
```bash
python scripts/build_index.py
```

CLI query (bypasses Streamlit; useful for debugging retrieval):
```bash
python scripts/query.py "月の描写が美しい文章"          # search + generate
python scripts/query.py --top 5 --search-only "自然の描写"  # retrieval only, no LLM
```

Diagnose the (optional) ZORAPI metadata source before indexing:
```bash
python scripts/explore_zorapi.py
```

Deploy (Docker → ghcr.io → Azure Container Apps) — normally CI does this on push to `main`:

| Workflow | paths trigger | deploys |
|---|---|---|
| `deploy.yml` | `app/**`, `requirements.txt`, `Dockerfile`, itself | Web → `bungo-app` |
| `deploy-backend.yml` | `backend/{main.py,requirements.txt,Dockerfile}`, `app/rag.py`, `requirements.txt`, itself | API → `bungo-api` (auto-creates it by cloning env vars from `bungo-app` if missing; gates on `/health` returning the new SHA) |
| `android-ci.yml` | `android/**`, itself | builds debug APK; on `main` attaches it to rolling release **`android-latest`** |
| `ios-ci.yml` | `ios/**`, itself | simulator build check; on `main` attaches an unsigned IPA to rolling release **`ios-latest`** |

Local fallbacks: `./deploy.sh` (Web; also the only path that injects `.env` vars into the Container App) and `bash backend/deploy-api.sh` (API; used for first-time creation with secret injection). Both push to ghcr.io — the old ACR is retired and deleted.

**⚠️ Workflow YAML must be written in block style.** Flow-style mappings containing `${{ }}` (e.g. `with: { creds: ${{ secrets.X }} }`) are unparseable — the `}}` closes the flow mapping — and produce startup failures on *every* push of *every* branch. This actually happened to `deploy-backend.yml` (10 consecutive silent failures).

There is no test suite for the Python code. Mobile CI verifies that iOS/Android compile. A quality-evaluation harness is planned — see `docs/quality-roadmap.md`.

## Architecture

Two-provider RAG pipeline. **Embeddings and Chat use different backends** — this split is the central design fact:

- **Embeddings** always go through Azure OpenAI (`text-embedding-3-small`, 1536-dim).
- **Chat** goes through whatever `CHAT_ENDPOINT` points at. The provider is chosen at runtime by inspecting the endpoint string (`_chat_provider()`):
  - contains `anthropic` → **Azure AI Foundry Claude** via the `anthropic` SDK (Anthropic Messages API). This is the **current default**: `claude-opus-4-8` on `https://ty669999977444-3157-resource.services.ai.azure.com/anthropic`. The Anthropic SDK posts to `{base_url}/v1/messages`. **Caveats:** `system` is a top-level arg (not a message), and `temperature` is **not accepted** by this model — don't send it.
  - contains `openai.azure.com` → `AzureOpenAI` client.
  - otherwise → plain `OpenAI` client with `base_url` (GitHub Models / Azure MaaS, e.g. the former `Phi-4-mini-instruct`).

  This branching lives in `_chat_provider()` + `stream_answer` (`_stream_anthropic` / `_stream_openai`) in `app/rag.py`, and is mirrored in `_build_chat_client()` / `generate()` in `scripts/query.py`. The two files duplicate the logic — change both together.

Retrieval is **hybrid search**: every query is both embedded (vector search, HNSW neighbors) and passed as `search_text` (full-text, `ja.microsoft` analyzer) in a single Azure AI Search call. To avoid over-anchoring to a single work ("特定文献への引っ張られ"), retrieval over-fetches (`top*3` candidates) and then caps to `MAX_PER_BOOK` (=2) chunks per `book_id` before returning the top-K — this diversity cap lives in both `search_chunks` (`app/rag.py`) and `search` (`scripts/query.py`).

**Prompt caching (Anthropic / Foundry):** the Claude branch sends `SYSTEM_PROMPT` as a `system` block list with `cache_control: {type: "ephemeral"}` plus the `anthropic-beta: prompt-caching-2024-07-31` header (Foundry treats caching as beta). The system prompt (~1.5–2K tokens) is fixed per request, so the 2nd+ requests hit the cache (`cache_read_input_tokens`), cutting input cost/latency. Verified live on Foundry. Applied in `_stream_anthropic` (`app/rag.py`) and the anthropic branch of `generate` (`scripts/query.py`).

Request flow (`app/rag.py` → `stream_answer`):
1. Embed the user message, hybrid-search the `bungo-chunks` index for the top-K chunks.
2. Format chunks into a "文体手本" (style-exemplar) block.
3. Build messages = `SYSTEM_PROMPT` + last 8 history turns + an augmented user message that embeds the exemplars and orders the model to output converted text immediately (no preamble).
4. Stream tokens back. Returns `(token_generator, source_chunks)` so the UI can render sources separately.

`SYSTEM_PROMPT` in `app/rag.py` is where the conversion behavior lives — it encodes the 旧字旧仮名 rules (kana spellings, kanji substitutions, classical sentence endings) and few-shot examples. Retrieved passages are explicitly labeled as style references, **not** to be copied verbatim.

### Files

- `app/app.py` — Streamlit UI: chat loop, session state (`messages`, `sources`), sidebar (top-K slider, reset), streaming render with a `▌` cursor, source expander.
- `app/rag.py` — RAG core: clients, `SYSTEM_PROMPT`, `search_chunks`, `format_context`, `stream_answer`. This is the file to edit for retrieval or generation behavior.
- `backend/main.py` — FastAPI wrapper around `app/rag.py` for the native apps. `POST /chat` streams NDJSON events (`token` / `sources` / `done` / `error`); `GET /health` returns `{"status":"ok","version":"<BUILD_SHA>"}` where `BUILD_SHA` is injected by the deploy workflow (SSOT traceability). The event/field contract is mirrored in `ios/Sources/Model/Models.swift` and `android/.../data/Models.kt` — all three are verified consistent (extra keys like `book_id` are safely ignored by both clients; Android sets `ignoreUnknownKeys`, but **unknown event `type`s still throw** there — make clients forward-compatible before adding new event types).
- `ios/` — SwiftUI app. No `.xcodeproj` is committed; run `xcodegen generate` from `ios/project.yml`. Base URL comes from Info.plist injection (`project.yml`) with a hardcoded production fallback in `Config.swift`.
- `android/` — Kotlin + Jetpack Compose app (Gradle version catalog, wrapper jar committed). Base URL default is production, overridable via `-PBUNGO_BASE_URL=...`. Debug builds are signed with the committed `android/ci-debug.keystore` so CI-built APKs can update-install over each other (a per-runner keystore would cause `INSTALL_FAILED_UPDATE_INCOMPATIBLE`).
- `scripts/build_index.py` — index builder. Creates the vector index if absent, downloads the Aozora catalog ZIP, filters to `旧字旧仮名`/`旧字新仮名` + copyright-free works, cleans Aozora markup (ruby `《》`, annotations `［＃］`), chunks by paragraph (~300 chars, splitting on 。！？ when oversized), embeds in batches of 16, uploads in batches of 1000. Tunables (`MAX_BOOKS`=300, `CHUNK_SIZE`, `TARGET_STYLES`, etc.) are constants near the top. **Author metadata:** the extended catalog has no `姓名` column — author is built from the separate `姓` + `名` columns via `_author_name()` (an earlier bug wrote `author="不明"` everywhere; fixed and the index has been rebuilt — see STATUS.md).
- `scripts/query.py` — standalone CLI mirror of the RAG pipeline (non-streaming), for debugging retrieval/generation without the UI.
- `Dockerfile` — Streamlit web image on `:8501` (used by `bungo-app`). `backend/Dockerfile` — FastAPI image on `:8000` (used by `bungo-api`; copies `app/` in so `rag.py` is importable).

### Search index schema (`bungo-chunks`)

Key `id` = `{book_id}-{chunk_idx}`. Fields: `book_id`, `author`, `title`, `style`, `chunk_idx` (metadata), `text` (searchable, `ja.microsoft` analyzer), `embedding` (1536-dim, HNSW profile `bungo-profile`). Changing embedding dimensions or the model requires recreating the index — `create_index_if_not_exists()` skips creation if the index already exists, so drop it first.

## Environment

All config comes from `.env` (gitignored, loaded via `python-dotenv`; `deploy.sh` also sources it to inject vars into the Container App). Required keys:

- `AZURE_SEARCH_ENDPOINT`, `AZURE_SEARCH_ADMIN_KEY`, `SEARCH_INDEX_NAME` (default `bungo-chunks`)
- `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_API_KEY`, `EMBED_DEPLOYMENT` (default `text-embedding-3-small`) — embeddings
- `CHAT_ENDPOINT`, `CHAT_API_KEY`, `CHAT_DEPLOYMENT` — chat; the endpoint string selects the provider/SDK (see Architecture). Currently set to the Foundry Claude endpoint (`.../anthropic`, `claude-opus-4-8`); `CHAT_API_KEY` is the `key1` of the `ty669999977444-3157-resource` Foundry account. The old GitHub Models / Phi config is kept commented in `.env` as a fallback.

Azure resources: resource group `bungo-rag-rg`, apps `bungo-app` (Web) / `bungo-api` (API), Container Apps env `bungo-env`. CI publishes images to `ghcr.io/s8tv9mvcz9-code/bungo-rag` and `.../bungo-rag-api` (both public). `deploy.sh` and `backend/deploy-api.sh` are already migrated to ghcr (pushing needs `gh auth refresh -s write:packages` once). The mobile apps bake the production `bungo-api` URL at build time — if the FQDN ever changes, update `android/gradle.properties`, `android/app/build.gradle.kts`, `ios/project.yml`, `ios/Sources/Config.swift` together.
