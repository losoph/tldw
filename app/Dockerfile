FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*
# JS-рантайм для YouTube (n-challenge) — deno-бинарник кладётся в volume
# data/bin/deno и подключается воркером; node yt-dlp считает unsupported.
# С GitHub CDN deno не качается с российского IP, поэтому не в образе (см. OPERATIONS.md).

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000
