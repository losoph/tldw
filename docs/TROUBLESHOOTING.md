# 🩺 Решение проблем

## Веб-интерфейс возвращает 403 Forbidden / не пускает по паролю

**Причина:** `.htpasswd` внутри контейнера не сгенерировался. Он создаётся из
`WEB_LOGIN`/`WEB_PASSWORD` при старте nginx.

```bash
# 1. Проверить, что переменные заданы в .env
grep -E 'WEB_LOGIN|WEB_PASSWORD' ~/whisper-app/.env

# 2. Проверить, что файл сгенерировался внутри контейнера
docker compose exec nginx cat /etc/nginx/.htpasswd
# должно быть: <логин>:$apr1$.....

# 3. В логах nginx должна быть строка про генерацию
docker compose logs nginx | grep entrypoint
```

Если значения в `.env` меняли — пересоберите/перезапустите nginx, чтобы `.htpasswd`
сгенерировался заново:

```bash
docker compose up -d --build nginx
```

## Воркер падает с `ModuleNotFoundError: No module named 'requests'`

Проверьте `requirements.txt` — должны быть указаны `requests==2.32.3` и `httpx==0.27.2`. Это известные конфликты зависимостей `openai==1.35.0` + `faster-whisper`.

```bash
tldw rebuild
```

## `Client.__init__() got an unexpected keyword argument 'proxies'`

Конфликт версий `openai` и `httpx`. В `requirements.txt` должен быть жёсткий пин:
```
openai==1.35.0
httpx==0.27.2
```

## Транскрибация идёт 6+ часов на час видео

Проверьте параметры в `worker.py`:
- `WHISPER_MODEL=small` (а не medium/large)
- `beam_size=2`
- `vad_filter=True`
- `cpu_threads=4`
- `condition_on_previous_text=False`

Все они должны быть установлены — иначе любой один может убить производительность.

Проверьте загрузку CPU при работе:
```bash
docker stats
```

Worker должен использовать ~100% × количество ядер.

## Задача застряла в статусе `pending`

```bash
tldw logs worker | tail -30
```

Скорее всего воркер упал и перезапускается. Смотрите ошибки. После исправления:

```bash
tldw worker  # воркер сам сбросит зависшие задачи при старте
```

## Браузер показывает кэшированный старый фронт

```bash
# 1. Hard refresh в браузере: Ctrl+Shift+R (Cmd+Shift+R на Mac)

# 2. Если не помогает — проверьте что docker подхватил новый файл:
tldw rebuild  # пересобрать с нуля
```

В `docker-compose.yml` уже есть volume `./app/templates:/app/templates`, так что любые изменения `index.html` подхватываются без пересборки. Но если меняли что-то в `main.py` — нужен `rebuild`.

## Whisper качает модель каждый раз при перезапуске

Не должен — есть volume `whisper_cache`. Проверьте:

```bash
docker volume inspect whisper-app_whisper_cache
docker volume ls | grep whisper
```

Если volume отсутствует:

```bash
docker compose down
docker compose up -d
```

## Контейнеры не стартуют после перезагрузки VPS

```bash
# Проверка systemd
sudo systemctl status tldw.service

# Если ошибка — посмотрите подробности
sudo journalctl -u tldw.service -n 50
```

Частая причина — в `/etc/systemd/system/tldw.service` неправильный `WorkingDirectory`. Должен быть актуальный путь типа `/home/deploy/whisper-app`.

## DeepSeek возвращает ошибки

### `Insufficient Balance`

Пополните баланс на [platform.deepseek.com](https://platform.deepseek.com).

### `Invalid API Key`

Проверьте `.env`:
```bash
grep DEEPSEEK_API_KEY ~/whisper-app/.env
```

Ключ должен начинаться с `sk-` и не содержать пробелов/кавычек. После исправления:

```bash
tldw worker
```

### `Rate limit exceeded`

DeepSeek имеет лимиты на запросы. Подождите минуту и попробуйте снова.

## Загрузка файла обрывается на 50–80%

Проверьте `client_max_body_size` в `nginx/nginx.conf` — должно быть `2048m` или больше. Также проверьте свободное место:

```bash
df -h
```

## ffmpeg: `Permission denied` или `No such file`

Файл загрузки повреждён или удалён. Проверьте:

```bash
ls -la ~/whisper-app/data/uploads/
```

Если задача застряла — удалите её через UI и загрузите файл заново.

## Полная переустановка

Если что-то сломалось до неузнаваемости:

```bash
cd ~/whisper-app

# .env уже содержит всю конфигурацию (ключ + логин/пароль) — трогать его не нужно.
# Снести контейнеры, volume и образы:
docker compose down -v
docker system prune -a

# Поднять заново:
docker compose up -d --build
```

`.htpasswd` сгенерируется заново из `.env`, Whisper-модели скачаются заново (несколько минут).
