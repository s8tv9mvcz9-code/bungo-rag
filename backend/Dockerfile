FROM python:3.11-slim

WORKDIR /srv

# RAG コア依存 + API 依存
COPY requirements.txt ./requirements.txt
COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt \
 && pip install --no-cache-dir -r backend/requirements.txt

# 共有 RAG ロジックと API
COPY app/ ./app/
COPY backend/ ./backend/

EXPOSE 8000

# Container Apps / App Service の PORT に追従（無ければ 8000）
CMD ["sh", "-c", "uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
