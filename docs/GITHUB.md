# 📦 Публикация на GitHub

Пошаговая инструкция для выгрузки проекта в публичный репозиторий.

## ⚠️ Что НЕ должно попасть в публичный репо

Эти файлы исключены через `.gitignore` — убедитесь что они действительно отсутствуют:

- `.env` — содержит ваш ключ DeepSeek API и логин/пароль веб-интерфейса (`WEB_LOGIN`/`WEB_PASSWORD`)
- `nginx/.htpasswd` — генерируется внутри контейнера nginx, на хосте его быть не должно
- `data/` — данные приложения, БД, история обработок

Перед первым коммитом проверьте:

```bash
cd ~/whisper-app
git status  # эти файлы НЕ должны появиться в списке
```

Если случайно увидите их — НЕ КОММИТЬТЕ. Проверьте `.gitignore`.

---

## Шаг 1 — Создание репозитория на GitHub

1. Откройте https://github.com/new (нужен аккаунт)
2. Имя репозитория: `tldw` (или любое другое)
3. Описание: «Self-hosted video & audio summarization with Whisper + DeepSeek»
4. Выберите **Public**
5. **НЕ** ставьте галочки «Add a README», «.gitignore», «license» (они уже есть в проекте)
6. Нажмите **Create repository**

GitHub покажет страницу с командами. Используйте раздел **«…or push an existing repository from the command line»** — ниже мы это сделаем.

## Шаг 2 — Настройка Git на VPS

Если ещё не настраивали:

```bash
git config --global user.name "Ваше Имя"
git config --global user.email "your@email.com"
```

## Шаг 3 — Аутентификация через Personal Access Token

GitHub больше не принимает пароли для git push. Нужен токен:

1. https://github.com/settings/tokens → **Generate new token (classic)**
2. Note: `tldw-vps-push`
3. Expiration: 90 дней (или больше)
4. Scopes: ✅ только **`repo`**
5. Скопируйте токен `ghp_XXXX...` — он покажется один раз!

## Шаг 4 — Инициализация и коммит

```bash
cd ~/whisper-app

# Если репозитория ещё нет
git init -b main

# Проверка что секреты НЕ попадают в коммит
git status

# Добавить все файлы (кроме игнорируемых)
git add .

# Финальная проверка перед коммитом
git status

# Если в списке нет .env, .htpasswd, data/ — делаем коммит
git commit -m "Initial commit: TLDW self-hosted video summarization"
```

## Шаг 5 — Связать с GitHub и запушить

```bash
git remote add origin https://github.com/losoph/tldw.git

git push -u origin main
```

При запросе:
- **Username:** ваш GitHub username
- **Password:** вставьте токен `ghp_XXX...` (не пароль от GitHub!)

## Шаг 6 — Проверка

Откройте `https://github.com/losoph/tldw` — все файлы должны быть на месте, кроме исключённых.

Проверьте что в репозитории НЕТ:
- `.env` (только `.env.example`)
- `nginx/.htpasswd`
- `data/jobs.db` и других данных

---

## Если что-то секретное случайно попало в репо

⚠️ **Удалить файл из истории — недостаточно если репо публичный.** Содержимое уже могли увидеть/скопировать.

Действия:
1. **Сразу отзовите ключ DeepSeek** в [platform.deepseek.com](https://platform.deepseek.com) и создайте новый
2. **Смените `WEB_PASSWORD`** в `.env` и перезапустите nginx (`docker compose up -d --build nginx`)
3. Удалите файл из истории:
   ```bash
   git rm --cached .env
   git commit -m "Remove leaked .env"
   git push
   ```
4. Для полного удаления из истории (опционально, сложнее):
   ```bash
   git filter-repo --path .env --invert-paths
   git push --force
   ```

---

## Дальнейшие обновления

```bash
cd ~/whisper-app
git add .
git commit -m "Add feature X"
git push
```

При запросе токена можно сохранить его на сервере:

```bash
git config --global credential.helper store
```

(токен сохранится в `~/.git-credentials` в открытом виде — используйте только на доверенном VPS)

## Деплой на новый VPS из репозитория

```bash
git clone https://github.com/losoph/tldw.git ~/whisper-app
cd ~/whisper-app
cp .env.example .env
nano .env  # вставить ключ DeepSeek; логин/пароль (WEB_LOGIN/WEB_PASSWORD) — прежние
docker compose up -d --build
```

Шаг с `htpasswd` больше не нужен — nginx сгенерирует `.htpasswd` из `.env` сам.
Полная инструкция: [DEPLOY.md](DEPLOY.md).
