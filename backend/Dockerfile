FROM python:3.12-slim
WORKDIR /app
COPY core ./core
COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir ./core -r backend/requirements.txt
COPY backend ./backend
WORKDIR /app/backend
EXPOSE 8000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips=*"]
