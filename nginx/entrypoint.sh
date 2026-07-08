#!/bin/sh
set -e

# Генерируем .htpasswd из логина/пароля, заданных в .env.
# Так при деплое на новый сервер не нужен ни apache2-utils на хосте,
# ни отдельная команда htpasswd — достаточно отредактировать .env.
: "${WEB_LOGIN:?WEB_LOGIN не задан в .env}"
: "${WEB_PASSWORD:?WEB_PASSWORD не задан в .env}"

# Основной админский пользователь (-c создаёт файл заново)
htpasswd -bc /etc/nginx/.htpasswd "$WEB_LOGIN" "$WEB_PASSWORD" >/dev/null 2>&1
echo "[entrypoint] .htpasswd: пользователь '$WEB_LOGIN'"

# Дополнительные пользователи команды tldw1..tldw4 — у каждого своя история
# обработок (изоляция по логину через заголовок X-Auth-User). Пароли задаются
# в .env переменными TLDW1_PASSWORD..TLDW4_PASSWORD; пустые — пропускаются.
for n in 1 2 3 4; do
    eval "pw=\${TLDW${n}_PASSWORD:-}"
    if [ -n "$pw" ]; then
        htpasswd -b /etc/nginx/.htpasswd "tldw${n}" "$pw" >/dev/null 2>&1
        echo "[entrypoint] .htpasswd: пользователь 'tldw${n}'"
    fi
done

exec nginx -g 'daemon off;'
