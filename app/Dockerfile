FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# deno — JS-рантайм для yt-dlp (extraction YouTube требует исполнения JS)
ADD https://github.com/denoland/deno/releases/latest/download/deno-x86_64-unknown-linux-gnu.zip /tmp/deno.zip
RUN python -m zipfile -e /tmp/deno.zip /usr/local/bin/ && chmod +x /usr/local/bin/deno && rm /tmp/deno.zip

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000
