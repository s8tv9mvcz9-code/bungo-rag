"""
app.py — 戦前文体 作文支援チャットボット（Streamlit）
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

import streamlit as st
from dotenv import load_dotenv
from rag import search_chunks, stream_answer, format_context

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

# ── ページ設定 ───────────────────────────────────────────
st.set_page_config(
    page_title="文語作文支援 — 青空文庫RAG",
    page_icon="📖",
    layout="wide",
)

st.title("📖 文語作文支援")
st.caption("青空文庫（旧字旧仮名・旧字新仮名）をコーパスとした戦前日本語スタイル支援")

# ── サイドバー ───────────────────────────────────────────
with st.sidebar:
    st.header("使い方")
    st.markdown("""
**できること**
- 現代語 → 戦前文体に変換
- テーマを指定して文語文を生成
- 文章の添削・格調アップ
- 文体の特徴を解説

**入力例**
```
この文章を旧字旧仮名で書き直して
「春の朝」というテーマで書いて
もっと夏目漱石らしい文体に
「です・ます」を文語体に変えて
```
""")
    st.divider()

    top_k = st.slider("参照チャンク数", 3, 10, 5)

    if st.button("🗑️ 会話をリセット"):
        st.session_state.messages = []
        st.session_state.sources = []
        st.rerun()

    st.divider()
    st.caption("Embedding: Azure OpenAI  \nChat: Azure AI Foundry — Claude Opus 4.8")
    st.divider()
    st.info("💤 一定時間アクセスがない場合、次回初回アクセス時に起動まで1〜2分かかることがあります。")

# ── セッション初期化 ─────────────────────────────────────
if "messages" not in st.session_state:
    st.session_state.messages = []
if "sources" not in st.session_state:
    st.session_state.sources = []

# ── ウェルカム画面（会話が空のとき）────────────────────
if not st.session_state.messages:
    st.markdown("### はじめる")
    cols = st.columns(2)
    examples = [
        "「今日はいい天気ですね」を旧字旧仮名に変換して",
        "「秋の夕暮れ」というテーマで文語体の文章を書いて",
        "「桜が散った。風が吹いた。」を格調高い文体に",
        "旧字旧仮名とはどういうものか教えて",
    ]
    for i, ex in enumerate(examples):
        if cols[i % 2].button(ex, use_container_width=True):
            st.session_state.messages.append({"role": "user", "content": ex})
            st.rerun()

# ── チャット履歴表示 ─────────────────────────────────────
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# ── 入力欄 ───────────────────────────────────────────────
if prompt := st.chat_input("依頼を入力してください（例：「月夜の情景を文語体で」）"):

    # ユーザーメッセージ表示
    with st.chat_message("user"):
        st.markdown(prompt)
    st.session_state.messages.append({"role": "user", "content": prompt})

    # 生成
    with st.chat_message("assistant"):
        placeholder = st.empty()
        full_response = ""

        try:
            token_stream, source_chunks = stream_answer(
                user_message=prompt,
                history=st.session_state.messages[:-1],
                top=top_k,
            )
            for token in token_stream:
                full_response += token
                placeholder.markdown(full_response + "▌")
            placeholder.markdown(full_response)
            st.session_state.sources = source_chunks

        except Exception as e:
            full_response = f"⚠️ エラーが発生しました: {e}"
            placeholder.markdown(full_response)

    st.session_state.messages.append({"role": "assistant", "content": full_response})

    # 参照元表示
    if st.session_state.sources:
        with st.expander(f"📚 参照した青空文庫テキスト（{len(st.session_state.sources)} 件）"):
            for i, c in enumerate(st.session_state.sources, 1):
                st.markdown(f"**[{i}] {c['title']} / {c['author']}** （{c.get('style','')}）")
                st.text(c["text"][:300] + ("…" if len(c["text"]) > 300 else ""))
                st.divider()
