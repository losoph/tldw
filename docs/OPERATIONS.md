# 🔧 Эксплуатация TLDW

## Команды CLI `tldw`

```bash
tldw start      # запустить все контейнеры
tldw stop       # остановить
tldw restart    # перезапустить
tldw rebuild    # пересобрать образы и запустить (после изменений кода)
tldw logs       # все логи в реальном времени
tldw logs web   # логи только веб
tldw logs worker # логи только воркера
tldw status     # статус контейнеров
tldw web        # перезапустить только web
tldw worker     # перезапустить только worker
```

## Просмотр очереди задач

```bash
sqlite3 ~/whisper-app/data/jobs.db \
  "SELECT id, filename, status, datetime(created_at,'unixepoch') FROM jobs ORDER BY created_at DESC LIMIT 20;"
```

## Сброс зависших задач

Зависшие задачи автоматически сбрасываются при перезапуске воркера. Вручную:

```bash
sqlite3 ~/whisper-app/data/jobs.db \
  "UPDATE jobs SET status='error', error='Сброшено вручную' WHERE status NOT IN ('done','error');"
```

## Бэкапы

> Бэкап **не обязателен**: проект разворачивается с нуля, а вся конфигурация (включая
> логин/пароль) живёт в `.env`. Делайте бэкап только если хотите сохранить **историю
> обработок** (`data/jobs.db`) — она не критична и при чистом деплое создаётся пустой.

### Критические файлы

```bash
# Минимально достаточный бэкап — только конфигурация
cp ~/whisper-app/.env ~/backup-env-$(date +%Y%m%d).env

# Полный бэкап с историей обработок
tar czf ~/tldw-backup-$(date +%Y%m%d).tar.gz \
  -C ~ whisper-app/.env whisper-app/data/jobs.db
```

### Скачать на локальный компьютер

```bash
# С локальной машины
scp deploy@SERVER_IP:~/tldw-backup-*.tar.gz ~/Downloads/
```

### Автоматический ежедневный бэкап

```bash
crontab -e
```

Добавьте:
```
0 3 * * * tar czf /home/$USER/backups/tldw-$(date +\%Y\%m\%d).tar.gz -C /home/$USER whisper-app/.env whisper-app/data/jobs.db && find /home/$USER/backups -mtime +30 -delete
```

Не забудьте создать `mkdir -p ~/backups`.

## Мониторинг места на диске

```bash
# Общее использование
df -h

# Размер папки данных
du -sh ~/whisper-app/data/

# Размер Docker volumes (включая кэш Whisper)
docker system df
```

## Очистка

### Удалить старые задачи из истории (старше 30 дней)

```bash
sqlite3 ~/whisper-app/data/jobs.db \
  "DELETE FROM jobs WHERE created_at < strftime('%s', 'now', '-30 days');"

sqlite3 ~/whisper-app/data/jobs.db "VACUUM;"
```

### Зачистка Docker

```bash
# Удалить неиспользуемые образы и контейнеры
docker system prune -a

# ⚠️ Удалить volume с кэшем моделей (модели придётся скачивать заново)
docker volume rm whisper-app_whisper_cache
```

## Обновление кода из репозитория

```bash
cd ~/whisper-app
git pull
docker compose up -d --build
```

⚠️ Локальный `.env` не затронется (он в `.gitignore`), логин/пароль сохранятся.

## Загрузка по ссылке (yt-dlp)

### Обновление VK-cookies

Для скачивания видео VK, требующих авторизации, воркер использует cookies корпоративного
VK-аккаунта из `data/cookies/<домен>.txt` (netscape-формат).

⚠️ **VK привязывает сессию к IP**: cookies, экспортированные из обычного браузера,
с сервера не работают (проверено 2026-07-06 — VK отвечает «only available for registered
users» и уводит в редирект-цикл). Логиниться в VK нужно **через IP сервера** — SSH-туннелем:

1. Туннель и отдельный профиль Chrome через него:
   ```bash
   ssh -D 61080 -N aiqu-eb &
   open -na "Google Chrome" --args --user-data-dir="$HOME/.tldw/vk-chrome-profile" \
     --proxy-server="socks5://127.0.0.1:61080" --no-first-run https://vk.com
   ```
2. В открывшемся окне войдите в VK под корпоративным аккаунтом
3. Экспортируйте cookies расширением («Get cookies.txt LOCALLY», netscape-формат)
   либо `yt-dlp --cookies-from-browser "chrome:$HOME/.tldw/vk-chrome-profile" --cookies vk.txt ...`
4. Загрузите на сервер (файл покрывает и `vk.com`, и `vkvideo.ru` — просто копия):
   ```bash
   scp cookies.txt aiqu-eb:~/whisper-app/data/cookies/vk.com.txt
   ssh aiqu-eb "cp ~/whisper-app/data/cookies/vk.com.txt ~/whisper-app/data/cookies/vkvideo.ru.txt && chmod 600 ~/whisper-app/data/cookies/*"
   ```
5. Рестарт не нужен — cookies читаются на каждом скачивании

Профиль `~/.tldw/vk-chrome-profile` сохраняйте — при протухании сессии достаточно снова
открыть его через туннель и перелогиниться. Срок жизни VK-cookies неизвестен —
обновляйте по факту ошибки в UI.

Публичные VK-видео качаются **без cookies** — они нужны только для роликов с ограниченным доступом.

### Cookies для YouTube

Прокси-IP помечен у Google — YouTube отвечает «Sign in to confirm you're not a bot»
и требует cookies. Используйте **отдельный/одноразовый Google-аккаунт** (не корпоративный
и не личный — аккаунт может быть заблокирован за автоматизацию): залогиньтесь в браузере
через **тот же прокси, что качает сервер** (IP должен совпадать), экспортируйте cookies в
`data/cookies/youtube.com.txt` (продублируйте в `youtu.be.txt`).

### JS-рантайм deno для YouTube

YouTube-extraction требует исполнения JS (n-challenge). yt-dlp считает Node **unsupported**,
годятся deno/bun/quickjs. Используется **deno-бинарник в volume**: `data/bin/deno`
(linux x86_64), воркер подключает его через `--js-runtimes deno:/data/bin/deno` при наличии
файла. Бинарник лежит в volume, а не в образе, потому что с GitHub CDN он не качается с
российского IP. Переживает пересборки (`tldw rebuild`).

Обновить deno (раз в несколько месяцев): скачать свежий
`deno-x86_64-unknown-linux-gnu.zip` на машину с доступом к GitHub, распаковать, залить:
```bash
scp deno aiqu-eb:~/whisper-app/data/bin/deno
ssh aiqu-eb "chmod +x ~/whisper-app/data/bin/deno"
```
⚠️ Если после scp `deno` даёт «Text file busy» — завис `sftp-server`, держащий файл:
`ssh aiqu-eb "fuser -k ~/whisper-app/data/bin/deno"` и повторить.

VK deno не нужен — там JS-челленджа нет.

### Прокси для YouTube

YouTube с российского IP работает нестабильно. Прокси задаются per-domain в
`data/proxies.yml` (образец — `proxies.yml.example` в корне репозитория). VK качается
напрямую. Файл читается на каждом скачивании, рестарт не нужен.

### Автообновление yt-dlp

VK/YouTube регулярно ломают старые версии yt-dlp. Настройте cron (раз в 2 недели):

```bash
crontab -e
# добавить:
0 5 1,15 * * /root/whisper-app/scripts/update-ytdlp.sh >> /var/log/tldw-ytdlp.log 2>&1
```

Скрипт обновляет yt-dlp внутри контейнера воркера и перезапускает его. При `tldw rebuild`
ставится свежая версия из requirements (yt-dlp там намеренно не запинен).

## Калибровка RTF под ваш VPS

После обработки нескольких видео посмотрите фактический RTF в логах:

```bash
tldw logs worker | grep "RTF="
```

Усредните значения и обновите в `.env`:

```
RTF=1.85  # вместо 2.0 если ваш сервер быстрее
```

Перезапустите воркер: `tldw worker`. Оценка времени в UI станет точнее.

## Смена модели Whisper

```bash
nano ~/whisper-app/.env
# изменить: WHISPER_MODEL=medium

tldw worker
```

При первом запуске воркер скачает новую модель (несколько минут). Старая останется в кэше.

| Модель | RAM | Качество | RTF (2-core) |
|---|---|---|---|
| tiny    | ~0.4 ГБ | низкое        | ~0.5 |
| base    | ~0.7 ГБ | среднее       | ~0.8 |
| small   | ~1.5 ГБ | хорошее       | ~2.0 |
| medium  | ~3 ГБ   | очень хорошее | ~4.5 |
| large-v3| ~6 ГБ   | лучшее        | ~8.0 |

## Логи в Journalctl (systemd)

```bash
sudo journalctl -u tldw.service -f
sudo journalctl -u tldw.service --since "1 hour ago"
```

## Перенос на новый VPS

Переносить файлы со старого сервера не нужно — деплой выполняется с нуля:

1. Удалить старый VPS
2. Развернуть новый по [DEPLOY.md](DEPLOY.md):
   ```bash
   git clone https://github.com/losoph/tldw.git ~/whisper-app
   cd ~/whisper-app
   cp .env.example .env
   nano .env            # вписать ключ DeepSeek; логин/пароль оставить прежними
   docker compose up -d --build
   ```

История обработок начнётся заново (БД создастся пустой). Если нужно сохранить старую
историю — заранее скопируйте `data/jobs.db` со старого сервера в `data/` нового.
