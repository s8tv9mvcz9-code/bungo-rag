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

    # 共感覚: 入力文と手本の情調を日本の伝統色に写像して表示し、
    # 生成の語彙選びにもほのかに反映する（意味の正確な変換が常に最優先）。
    synesthesia_on = st.checkbox("🎨 共感覚（情調の色）", value=True,
                                 help="文の情調を伝統色で表示し、変換の語彙選びにほのかに反映します")

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


def _palette_band_html(p: dict) -> str:
    """共感覚パレットのグラデーション帯（入力色 → 連想色 → 手本色）"""
    stops = ", ".join(p["stops"])
    return (
        f'<div style="height:10px;border-radius:5px;'
        f'background:linear-gradient(90deg,{stops});margin:2px 0 6px"></div>'
    )


def _color_chip_html(hex_color: str) -> str:
    return (
        f'<span style="display:inline-block;width:0.75em;height:0.75em;'
        f'border-radius:50%;background:{hex_color};margin-right:0.35em;'
        f'border:1px solid rgba(0,0,0,0.15)"></span>'
    )

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
    palette = None
    with st.chat_message("assistant"):
        band = st.empty()        # 共感覚の色帯（トークンより先に出す）
        placeholder = st.empty()
        full_response = ""

        try:
            token_stream, source_chunks, palette = stream_answer(
                user_message=prompt,
                history=st.session_state.messages[:-1],
                top=top_k,
                synesthesia=synesthesia_on,
            )
            # パレットは生成前に確定するので、答えを待つ間から色を見せる
            if palette:
                band.markdown(
                    _palette_band_html(palette)
                    + f'<div style="font-size:0.8em;opacity:0.7">情調 「{palette["blend"]["name"]}」'
                    + (f'　—　{"・".join(palette["categories"])}の氣配' if palette["categories"] else "")
                    + "</div>",
                    unsafe_allow_html=True,
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

    # 参照元表示（共感覚 ON なら各手本の色を添える）
    if st.session_state.sources:
        import html as _html
        with st.expander(f"📚 参照した青空文庫テキスト（{len(st.session_state.sources)} 件）"):
            for i, c in enumerate(st.session_state.sources, 1):
                chip = _color_chip_html(c["color"]) if c.get("color") else ""
                name = f"　<span style='opacity:0.6;font-size:0.85em'>{c.get('color_name','')}</span>" \
                    if c.get("color_name") else ""
                # unsafe_allow_html に載せるため、インデックス由来の文字列はエスケープする
                title = _html.escape(f"{c['title']} / {c['author']}")
                style_l = _html.escape(c.get("style", ""))
                st.markdown(
                    f"{chip}**[{i}] {title}** （{style_l}）{name}",
                    unsafe_allow_html=True,
                )
                st.text(c["text"][:300] + ("…" if len(c["text"]) > 300 else ""))
                st.divider()
