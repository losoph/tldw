#!/bin/bash
APP_DIR="$HOME/whisper-app"
case "$1" in
  start)   cd $APP_DIR && docker compose up -d ;;
  stop)    cd $APP_DIR && docker compose down ;;
  restart) cd $APP_DIR && docker compose restart ;;
  rebuild) cd $APP_DIR && docker compose up -d --build ;;
  logs)    cd $APP_DIR && docker compose logs -f ${2:-} ;;
  status)  cd $APP_DIR && docker compose ps ;;
  worker)  cd $APP_DIR && docker compose restart worker ;;
  web)     cd $APP_DIR && docker compose restart web ;;
  *)
    echo "Использование: tldw {start|stop|restart|rebuild|logs|status|worker|web}"
    ;;
esac
