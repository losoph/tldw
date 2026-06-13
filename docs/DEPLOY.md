# 🚀 Развёртывание TLDW на новом VPS

Пошаговая инструкция для чистого Ubuntu 22.04/24.04. Время на полное развёртывание — **30–45 минут** (большая часть — скачивание модели Whisper).

## Требования к VPS

| Компонент | Минимум | Рекомендуется |
|---|---|---|
| CPU | 2 ядра | 2-4 ядра, 2.8+ GHz |
| RAM | 4 ГБ (для модели `small`) | 8 ГБ (для `medium`/`large`) |
| Диск | 30 ГБ | 50+ ГБ |
| OS | Ubuntu 22.04 LTS | Ubuntu 24.04 LTS |

## Шаг 1 — Базовая настройка сервера

```bash
# Войти под root, обновить систему
apt update && apt upgrade -y
apt install -y curl git ufw nano htop

# Создать рабочего пользователя
adduser deploy
usermod -aG sudo deploy
rsync --archive --chown=deploy:deploy ~/.ssh /home/deploy

# Фаервол
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw enable
```

Перелогиниться под `deploy`:

```bash
exit
ssh deploy@SERVER_IP
```

## Шаг 2 — Установка Docker

```bash
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
sudo usermod -aG docker $USER
sudo systemctl enable docker
sudo systemctl start docker
```

Выйти и зайти заново чтобы группа `docker` применилась:

```bash
exit
ssh deploy@SERVER_IP
docker run hello-world  # проверка
```

## Шаг 3 — Клонирование проекта

```bash
git clone https://github.com/losoph/tldw.git ~/whisper-app
cd ~/whisper-app
```

## Шаг 4 — Конфигурация (единственный файл — `.env`)

```bash
cp .env.example .env
nano .env
```

Заполнить значения:

```
DEEPSEEK_API_KEY=sk-XXXXXXXXXXXXXXXXXXXX   # ключ от platform.deepseek.com
WEB_LOGIN=admin                           # логин для входа в веб-интерфейс
WEB_PASSWORD=ваш_надёжный_пароль          # пароль для входа в веб-интерфейс
WHISPER_MODEL=small
LANGUAGE=ru
RTF=2.0
```

Логин и пароль на веб-интерфейс задаются здесь же. При старте контейнер nginx сам
сгенерирует `.htpasswd` из `WEB_LOGIN`/`WEB_PASSWORD` — устанавливать `apache2-utils`
и запускать `htpasswd` вручную не нужно.

> При повторном развёртывании на новом сервере достаточно вписать новый ключ DeepSeek,
> а логин/пароль оставить прежними — больше ничего настраивать не требуется.

## Шаг 5 — Запуск

```bash
docker compose up -d --build
```

Первая сборка займёт 5–10 минут. Затем воркер начнёт скачивать модель Whisper (~500 МБ для `small`, ~1.5 ГБ для `medium`).

Следить за процессом:

```bash
docker compose logs -f worker
```

Готово к работе когда увидите: `Воркер запущен (RTF=2.0). Ожидание задач...`

Открыть в браузере: `http://SERVER_IP` → ввести логин/пароль.

## Шаг 6 — Защита (рекомендуется)

### Базовая защита SSH

```bash
sudo nano /etc/ssh/sshd_config
```

Изменить:
```
PermitRootLogin no
PasswordAuthentication no   # если работают SSH-ключи
MaxAuthTries 3
```

Перезапустить:

```bash
sudo systemctl restart ssh
```

### Fail2ban против brute-force

```bash
sudo apt install -y fail2ban

sudo tee /etc/fail2ban/jail.d/ssh.conf > /dev/null << 'EOF'
[sshd]
enabled  = true
port     = ssh
maxretry = 4
findtime = 1h
bantime  = 24h
EOF

sudo systemctl enable --now fail2ban
```

### Автоматические обновления безопасности

```bash
sudo apt install -y unattended-upgrades
sudo dpkg-reconfigure -plow unattended-upgrades  # ответить Yes
```

## Шаг 7 — Автозапуск через systemd

```bash
sudo cp tldw.service /etc/systemd/system/tldw.service

# Замените CHANGEME на реальное имя пользователя
sudo sed -i "s|CHANGEME|$USER|" /etc/systemd/system/tldw.service

sudo systemctl daemon-reload
sudo systemctl enable tldw.service
sudo systemctl start tldw.service
```

Проверка: `sudo systemctl status tldw.service` → должно быть `active (exited)`.

## Шаг 8 — CLI-утилита `tldw`

```bash
chmod +x tldw.sh
sudo ln -sf ~/whisper-app/tldw.sh /usr/local/bin/tldw

tldw status   # проверка работы
```

## Проверка

```bash
# Все контейнеры запущены?
docker compose ps

# Воркер готов?
docker compose logs worker | tail -3

# Открытые порты (должны быть 22 и 80, НЕ 8000)
sudo ss -tlnp
```

Загрузите тестовое короткое видео через веб-интерфейс. Если за 5–10 минут появилось саммари — деплой успешен ✅

## Повторный деплой без бэкапа

Проект спроектирован так, чтобы разворачиваться «с нуля» без переноса данных со старого
сервера. Полный цикл переезда:

```bash
git clone https://github.com/losoph/tldw.git ~/whisper-app
cd ~/whisper-app
cp .env.example .env
nano .env            # вписать ключ DeepSeek, логин/пароль оставить прежними
docker compose up -d --build
```

- **База данных** (`data/jobs.db`) создаётся пустой автоматически — история обработок
  начинается заново, никаких миграций не требуется.
- **`.htpasswd`** генерируется nginx из `.env` при старте — копировать его не нужно.
- **Модель Whisper** скачается заново при первом запуске воркера (несколько минут).

Бэкап старого сервера не требуется. Единственное новое значение, которое нужно ввести, —
ключ DeepSeek.
