FROM python:3.11-slim

# nodejs — JS-рантайм для yt-dlp (extraction YouTube требует исполнения JS;
# deno с GitHub CDN недоступен с российского IP, ставим node из Debian-репы)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg nodejs \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000
