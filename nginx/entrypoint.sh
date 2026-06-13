#!/bin/sh
set -e

# Генерируем .htpasswd из логина/пароля, заданных в .env.
# Так при деплое на новый сервер не нужен ни apache2-utils на хосте,
# ни отдельная команда htpasswd — достаточно отредактировать .env.
: "${WEB_LOGIN:?WEB_LOGIN не задан в .env}"
: "${WEB_PASSWORD:?WEB_PASSWORD не задан в .env}"

htpasswd -bc /etc/nginx/.htpasswd "$WEB_LOGIN" "$WEB_PASSWORD" >/dev/null 2>&1
echo "[entrypoint] .htpasswd сгенерирован для пользователя '$WEB_LOGIN'"

exec nginx -g 'daemon off;'
