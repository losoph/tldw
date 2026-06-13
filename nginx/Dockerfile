FROM nginx:alpine

# htpasswd (из apache2-utils) нужен, чтобы сгенерировать .htpasswd
# из WEB_LOGIN/WEB_PASSWORD при старте контейнера.
RUN apk add --no-cache apache2-utils

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
