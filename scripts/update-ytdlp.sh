#!/usr/bin/env bash
# Автообновление yt-dlp внутри контейнера воркера.
# VK/YouTube регулярно меняют API — старый yt-dlp перестаёт скачивать.
# Cron (раз в 2 недели): 0 5 1,15 * * /root/whisper-app/scripts/update-ytdlp.sh >> /var/log/tldw-ytdlp.log 2>&1
# Примечание: docker compose restart сохраняет файловую систему контейнера,
# поэтому обновление переживает рестарт; при rebuild ставится свежая версия из requirements.
set -euo pipefail
cd "$(dirname "$0")/.."
docker compose exec -T worker pip install -q --upgrade yt-dlp
docker compose restart worker
echo "$(date '+%F %T') yt-dlp обновлён до $(docker compose exec -T worker yt-dlp --version)"
