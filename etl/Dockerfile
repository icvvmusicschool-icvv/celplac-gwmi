FROM python:3.12-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends postgresql-client && rm -rf /var/lib/apt/lists/*
COPY core ./core
COPY etl ./etl
COPY db ./db
RUN pip install --no-cache-dir ./core ./etl
ENV GWMI_MIGRATIONS_DIR=/app/db/migrations
ENTRYPOINT ["gwmi-etl"]
CMD ["status"]
