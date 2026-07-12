"""
explore_zorapi.py
ZORAPI のレスポンス形式を確認するための診断スクリプト

build_index.py を実行する前に、このスクリプトでAPIの動作を確認してください。
"""

import os
import json
import requests
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

ZORAPI_BASE = os.environ.get("ZORAPI_BASE_URL", "https://api.bungomail.com/v0")


def check_endpoint(path: str, params: Optional[dict] = None):
    url = f"{ZORAPI_BASE}{path}"
    print(f"\n{'='*60}")
    print(f"GET {url}")
    if params:
        print(f"params: {params}")
    try:
        resp = requests.get(url, params=params, timeout=15)
        print(f"Status: {resp.status_code}")
        data = resp.json()
        print(f"Response (先頭 500 文字):")
        print(json.dumps(data, ensure_ascii=False, indent=2)[:500])
        return data
    except Exception as e:
        print(f"Error: {e}")
        return None


if __name__ == "__main__":
    # 1. 作品リスト確認
    books_data = check_endpoint("/books", {"limit": 3})

    # 2. 作品リストから1件取り出して詳細取得を試みる
    books = []
    if isinstance(books_data, list):
        books = books_data
    elif isinstance(books_data, dict):
        for key in ("books", "works", "data", "items", "results"):
            if key in books_data:
                books = books_data[key]
                break

    if books:
        first = books[0]
        print(f"\n最初の作品のキー: {list(first.keys())}")
        print(f"最初の作品のデータ: {first}")

        # book_id / work_id の候補キーを探す
        book_id = (
            first.get("book_id") or
            first.get("work_id") or
            first.get("id")
        )
        print(f"book_id 候補: {book_id}")

        if book_id:
            check_endpoint(f"/books/{book_id}")
    else:
        print("\n⚠ 作品リストを取り出せませんでした。ZORAPI のレスポンス形式を確認してください。")

    # 3. 人物リストも確認
    check_endpoint("/persons", {"limit": 2})
