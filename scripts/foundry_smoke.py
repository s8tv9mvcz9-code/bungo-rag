"""
foundry_smoke.py — Azure AI Foundry の Claude 接続を単独で確認する疎通テスト

Streamlit を起動せずに、Foundry デプロイへ最小リクエストを投げて
「認証・デプロイ名・ストリーミング」が通るかを診断する。

使い方（.env に Foundry 設定を入れてから）:
    pip install anthropic          # Entra 認証なら azure-identity も
    python scripts/foundry_smoke.py

.env に必要（詳細は docs/foundry-claude.md）:
    ANTHROPIC_FOUNDRY_RESOURCE=<リソース名>
    CHAT_DEPLOYMENT=claude-opus-4-8         # 省略時はこの既定
    ANTHROPIC_FOUNDRY_API_KEY=<Key>         # または FOUNDRY_AUTH=entra
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

# Foundry 経路を強制（未設定でも本テストは foundry を試す）
os.environ.setdefault("CHAT_BACKEND", "foundry")


def main() -> int:
    resource = os.environ.get("ANTHROPIC_FOUNDRY_RESOURCE") or os.environ.get("FOUNDRY_RESOURCE")
    model = os.environ.get("CHAT_DEPLOYMENT") or "claude-opus-4-8"
    auth = "Entra ID" if os.environ.get("FOUNDRY_AUTH", "").lower() == "entra" else "APIキー"

    print("=== Azure AI Foundry 疎通テスト ===")
    print(f"  リソース : {resource or '(未設定)'}")
    print(f"  デプロイ : {model}")
    print(f"  認証     : {auth}")
    if resource:
        print(f"  URL      : https://{resource}.services.ai.azure.com/anthropic/")
    print()

    if not resource:
        print("❌ ANTHROPIC_FOUNDRY_RESOURCE が未設定です。docs/foundry-claude.md を参照。")
        return 2

    try:
        import rag  # 遅延: app/rag.py の _foundry_client を再利用
        client = rag._foundry_client()
    except ModuleNotFoundError as e:
        print(f"❌ 依存不足: {e}. `pip install anthropic`（Entra なら azure-identity も）")
        return 2
    except Exception as e:  # noqa: BLE001
        print(f"❌ クライアント生成に失敗: {e}")
        return 2

    print("→ 最小リクエストを送信中（ストリーミング）...\n")
    try:
        stream = client.messages.create(
            model=model,
            max_tokens=64,
            system="あなたは簡潔に答える助手です。",
            messages=[{"role": "user", "content": "「こんにちは」と一言だけ返して。"}],
            stream=True,
        )
        got = ""
        for event in stream:
            if event.type == "content_block_delta" and getattr(event.delta, "type", None) == "text_delta":
                got += event.delta.text
                print(event.delta.text, end="", flush=True)
        print("\n")
        if got.strip():
            print("✅ 成功: 認証・デプロイ・ストリーミングすべて通りました。")
            return 0
        print("⚠️ 応答が空でした。デプロイ状態を確認してください。")
        return 1
    except Exception as e:  # noqa: BLE001
        msg = str(e)
        print(f"\n❌ リクエスト失敗: {msg}\n")
        hint = {
            "401": "APIキーが誤り。Foundryポータルの Details > Key を再確認。",
            "403": "RBAC権限不足。Foundry User / Cognitive Services User ロールを付与。",
            "404": "デプロイ名かリージョンが不一致。CHAT_DEPLOYMENT を実デプロイ名に。",
            "429": "レート制限。少し待つか Azure でクォータ引き上げ。",
        }
        for code, tip in hint.items():
            if code in msg:
                print(f"   ヒント({code}): {tip}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
