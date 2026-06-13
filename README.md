# 🎙️ TLDW — Self-hosted Video & Audio Summarization

Сервис для автоматической транскрибации и структурированного саммари аудио/видео файлов. Полностью self-hosted, работает на собственном VPS, не передаёт данные третьим лицам кроме DeepSeek API для финальной саммаризации.

> **TLDW** = Too Long; Didn't Watch

## ✨ Возможности

- 🎬 **Видео:** mp4, mkv, avi, mov, webm
- 🎵 **Аудио:** mp3, m4a, wav, ogg, flac, aac, opus
- 📦 Файлы **до 2 ГБ** через drag & drop
- 🌍 Транскрибация локально через **faster-whisper** (CPU)
- 🤖 Структурированное саммари через **DeepSeek API**
- ⏱ Оценка времени обработки в реальном времени
- 🔐 Базовая HTTP-авторизация через nginx
- 📊 История задач, удаление, статусы
- 🐳 Полностью контейнеризован (Docker Compose)
- ♻️ Автозапуск через systemd, сброс зависших задач

## 🏗 Архитектура

```
   Пользователь
        ↓
  ┌──────────┐       ┌────────────────────────┐
  │  Nginx   │ ───→  │  FastAPI (web)         │
  │ +auth    │       │  загрузка, статусы, UI │
  └──────────┘       └─────────┬──────────────┘
                               │ SQLite (очередь)
                               ↓
                     ┌─────────────────────────┐
                     │  Worker                 │
                     │  FFmpeg → Whisper →     │
                     │  DeepSeek               │
                     └─────────────────────────┘
```

## 🚀 Быстрый старт

```bash
git clone https://github.com/losoph/tldw.git ~/whisper-app
cd ~/whisper-app

# 1. Настроить окружение — единственный шаг с ручным вводом
cp .env.example .env
nano .env   # вставить DEEPSEEK_API_KEY, при желании сменить WEB_LOGIN/WEB_PASSWORD

# 2. Запустить
docker compose up -d --build
```

Логин и пароль для веб-интерфейса берутся прямо из `.env` (`WEB_LOGIN` / `WEB_PASSWORD`) —
nginx сам генерирует `.htpasswd` при старте. Отдельная команда `htpasswd` и пакет
`apache2-utils` больше не нужны: чтобы развернуть проект заново, достаточно вписать ключ
DeepSeek в `.env`.

Подробнее — см. [`docs/DEPLOY.md`](docs/DEPLOY.md) для пошаговой установки на чистый VPS.

## 💰 Экономика

При обработке ~50 видео/месяц на VPS 2 CPU / 4 ГБ:

| Статья | Стоимость |
|---|---|
| Транскрибация (Whisper, локально) | $0 |
| Саммаризация (DeepSeek API) | ~$0.30/мес |
| VPS (Hetzner/VDSina/etc) | $10–20/мес |
| **Итого** | **~$10–20/мес** |

## 📚 Документация

- [`DEPLOY.md`](docs/DEPLOY.md) — пошаговая установка на чистый VPS
- [`ARCHITECTURE.md`](docs/ARCHITECTURE.md) — компоненты системы и потоки данных
- [`OPERATIONS.md`](docs/OPERATIONS.md) — управление, мониторинг, бэкапы
- [`TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md) — частые ошибки и фиксы
- [`ROADMAP.md`](docs/ROADMAP.md) — план развития проекта

## 🛠 Стек

- **Backend:** Python 3.11, FastAPI, Uvicorn
- **Queue:** SQLite + поллинг (single worker)
- **STT:** faster-whisper (small, int8, CPU)
- **LLM:** DeepSeek API (deepseek-chat)
- **Media:** FFmpeg + ffprobe
- **Proxy:** Nginx (auth_basic, 2 ГБ upload)
- **Deploy:** Docker Compose + systemd

## 🤝 License

MIT — см. [LICENSE](LICENSE)
