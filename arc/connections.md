# NOCKO MDM — Подключения и Credentials

> ⚠️ **ВАЖНО:** Этот файл содержит конфиденциальные данные. Добавь `arc/` в `.gitignore`, если ещё не добавил!

---

## 🖥️ Боевой сервер (Production)

### Детали подключения

| Параметр    | Значение                   |
|-------------|----------------------------|
| **Домен**   | `mdm.it-uae.com`           |
| **IP**      | `204.168.135.131`          |
| **Пользователь** | `root`               |
| **Порт SSH** | `22`                      |
| **Путь приложения** | `/opt/nocko-mdm`  |
| **SSH-ключ (приватный)** | `arc/nocko_server_key_new` (ed25519) |
| **SSH-ключ (публичный)** | `arc/nocko_server_key_new.pub` |
| **Пароль root** | `siH9HjekNTiR` |

### SSH-подключение

Короткая команда (через alias в `~/.ssh/config`):
```bash
ssh nocko-server
```

Или напрямую с ключом из этой папки:
```bash
ssh -i arc/nocko_server_key_new root@204.168.135.131
```

> 🔑 **Приватный ключ** хранится здесь: `arc/nocko_server_key` (файл НЕ попадает в git).

`~/.ssh/config` на MacBook уже настроен:
```
Host nocko-server
    HostName 204.168.135.131
    User root
    IdentityFile /Users/rakhat/Documents/webhosting/NOCKO MDM/arc/nocko_server_key_new
    StrictHostKeyChecking no
```

### SSH-ключи для деплоя

Ключи хранятся в GitHub Secrets и используются в CI/CD пайплайне (`/.github/workflows/deploy.yml`).

**Для подключения с нового компа:**
1. Скопировать файл `arc/nocko_server_key_new` на новый комп в `~/.ssh/`
2. Задать правильные права: `chmod 600 ~/.ssh/nocko_server_key_new`
3. Подключиться: `ssh -i ~/.ssh/nocko_server_key_new root@204.168.135.131`

Или добавить в `~/.ssh/config`:
```
Host nocko-server
    HostName 204.168.135.131
    User root
    IdentityFile ~/.ssh/nocko_server_key
    StrictHostKeyChecking no
```

---

## 🔐 GitHub — Secrets для CI/CD

В GitHub репозитории должны быть прописаны следующие Secrets:
**Настройки → Secrets and variables → Actions → New repository secret**

| Secret Name    | Описание                                | Где взять / значение |
|----------------|-----------------------------------------|----------------------|
| `SERVER_HOST`  | IP или домен сервера                    | `mdm.it-uae.com`     |
| `SERVER_USER`  | Пользователь SSH на сервере             | `root`               |
| `DEPLOY_KEY`   | Приватный SSH-ключ для деплоя (ed25519) | Содержимое `~/.ssh/id_ed25519` |

### Как добавить GitHub Secret

```bash
# Скопировать приватный ключ в буфер обмена (macOS)
cat ~/.ssh/id_ed25519 | pbcopy
```

Затем вставить в GitHub: **Settings → Secrets → Actions → DEPLOY_KEY**

### Подключение GitHub репозитория к серверу

На сервере добавить GitHub в known_hosts:
```bash
ssh-keyscan github.com >> ~/.ssh/known_hosts
```

Склонировать репозиторий:
```bash
git clone git@github.com:ВАШ_ЮЗЕ/NOCKO-MDM.git /opt/nocko-mdm
```

---

## ⚙️ Переменные окружения (.env на сервере)

Файл находится на сервере: `/opt/nocko-mdm/.env`

```ini
# === Приложение ===
APP_NAME=NOCKO MDM
APP_VERSION=1.0.0
SECRET_KEY=<генерируется командой: openssl rand -hex 32>

# === Database (PostgreSQL) ===
POSTGRES_USER=mdm
POSTGRES_PASSWORD=<генерируется: openssl rand -hex 16>
POSTGRES_DB=nocko_mdm
DATABASE_URL=postgresql+asyncpg://mdm:${POSTGRES_PASSWORD}@postgres:5432/nocko_mdm

# === Redis ===
REDIS_URL=redis://redis:6379/0

# === Сервер / URLs ===
MDM_SERVER_URL=https://mdm.it-uae.com
ENROLLMENT_URL=https://mdm.it-uae.com/api/v1/enrollment
NEXT_PUBLIC_API_URL=https://mdm.it-uae.com
API_URL=http://backend:8000

# === Apple MDM (заполнить при настройке Apple Push) ===
# APPLE_PUSH_CERT_PATH=/app/certs/apple_push.pem
# APPLE_PUSH_KEY_PATH=/app/certs/apple_push.key
# APPLE_MDM_TOPIC=com.apple.mgmt.External.<uuid>
# APPLE_DEP_TOKEN_PATH=/app/certs/dep_token.p7m
# APPLE_DEP_SERVER_TOKEN_PATH=/app/certs/dep_server_token.json

# === Android Enterprise (заполнить при необходимости) ===
# GOOGLE_SERVICE_ACCOUNT_JSON=/app/certs/google_service_account.json
# ANDROID_ENTERPRISE_ID=<enterprise-id>

# === Entra ID / Azure AD (для Windows MDM) ===
# ENTRA_CLIENT_ID=<app-client-id>
# ENTRA_CLIENT_SECRET=<secret>
# ENTRA_TENANT_ID=<tenant-id>
```

Сгенерировать значения прямо на сервере:
```bash
openssl rand -hex 32   # для SECRET_KEY
openssl rand -hex 16   # для POSTGRES_PASSWORD
```

---

## 🚀 Деплой на новый сервер (пошагово)

### Шаг 1 — Подготовка сервера (запустить на сервере)
```bash
bash deploy.sh
```

### Шаг 2 — Загрузить код на сервер
```bash
# С локальной машины:
scp -r ./* root@mdm.it-uae.com:/opt/nocko-mdm/
```

Или клонировать напрямую с GitHub:
```bash
git clone git@github.com:ВАШ_ЮЗЕ/NOCKO-MDM.git /opt/nocko-mdm
```

### Шаг 3 — Заполнить .env
```bash
nano /opt/nocko-mdm/.env
```

### Шаг 4 — Запустить сервисы
```bash
cd /opt/nocko-mdm
docker compose up -d
```

### Шаг 5 — Включить HTTPS (Let's Encrypt)
```bash
certbot --nginx -d mdm.it-uae.com --non-interactive --agree-tos -m admin@it-uae.com
```

### Шаг 6 — Проверка
```bash
# Статус контейнеров
docker compose ps

# Логи backend
docker compose logs -f backend

# Health check
curl https://mdm.it-uae.com/health
```

---

## 🔄 Управление на работающем сервере

```bash
# Перезапустить всё
docker compose restart

# Обновить код и перезапустить (вручную)
cd /opt/nocko-mdm
git pull origin main
docker compose build backend frontend
docker compose up -d --no-deps backend frontend

# Посмотреть логи
docker compose logs -f

# Остановить всё
docker compose down

# Бэкап базы данных
docker compose exec postgres pg_dump -U mdm nocko_mdm > backup_$(date +%Y%m%d).sql
```

---

## 📁 Структура на сервере

```
/opt/nocko-mdm/          ← Полная копия репозитория
├── .env                 ← Боевые переменные (НЕ в git)
├── docker-compose.yml
├── backend/
├── frontend/
├── certs/               ← Apple MDM сертификаты (НЕ в git)
└── ...

/var/nocko/
└── agent-binaries/      ← Собранные .exe агенты для Windows
```

---

## 🌐 Nginx

Конфиг: `/etc/nginx/sites-available/nocko-mdm`

| Путь              | Проксируется на           |
|-------------------|---------------------------|
| `/`               | `http://127.0.0.1:3002` (Next.js frontend) |
| `/api/`           | `http://127.0.0.1:8000` (FastAPI backend)  |
| `/EnrollmentServer/` | `http://127.0.0.1:8000` (Windows OMA-DM) |

```bash
# Перезагрузить конфиг nginx
nginx -t && systemctl reload nginx
```

---

## 📝 Для нового проекта (checklist)

- [ ] Создать SSH-ключ и добавить на сервер
- [ ] Добавить 3 GitHub Secrets: `SERVER_HOST`, `SERVER_USER`, `DEPLOY_KEY`
- [ ] Скопировать `.github/workflows/deploy.yml` в новый репозиторий
- [ ] Скопировать `deploy.sh` и обновить `DOMAIN` в нём
- [ ] Создать `.env` на сервере по шаблону выше
- [ ] Настроить Certbot для HTTPS
