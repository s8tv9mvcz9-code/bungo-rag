FROM python:3.11-slim

WORKDIR /app

# 依存パッケージ
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# アプリコード
COPY app/ ./app/

# ポート公開
EXPOSE 8501

# ヘルスチェック
HEALTHCHECK CMD curl -f http://localhost:8501/_stcore/health || exit 1

# 起動
CMD ["streamlit", "run", "app/app.py", \
     "--server.port=8501", \
     "--server.address=0.0.0.0", \
     "--server.headless=true"]
