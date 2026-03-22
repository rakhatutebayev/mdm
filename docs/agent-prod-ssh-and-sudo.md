# Боевой proxy-agent: SSH-ключ и деплой без пароля sudo

Хост по умолчанию: **`192.168.11.153`**, пользователь **`stsadmin`**.

## 1. SSH-ключ (один раз с вашей машины)

Из корня репозитория:

```bash
chmod +x scripts/setup-agent-prod-ssh.sh
./scripts/setup-agent-prod-ssh.sh
# если спросит пароль stsadmin последний раз:
SSHPASS='ваш_пароль' ./scripts/setup-agent-prod-ssh.sh
```

Дальше **`./scripts/deploy-proxy-agent-prod.sh`** может работать **без `SSHPASS`**.

## 2. Скрипт на сервере + sudoers (без `PROD_AGENT_SUDO_PASS`)

Скопируйте helper на агент и выставьте права **от root**:

```bash
scp scripts/remote/nocko-agent-deploy-sync.sh root@192.168.11.153:/tmp/
ssh root@192.168.11.153 'install -m 700 /tmp/nocko-agent-deploy-sync.sh /usr/local/sbin/nocko-agent-deploy-sync.sh'
```

Добавьте правило **только через `visudo`** (файл `/etc/sudoers.d/nocko-agent-deploy`):

```sudoers
stsadmin ALL=(root) NOPASSWD: /usr/local/sbin/nocko-agent-deploy-sync.sh
```

Проверка (после того как деплой один раз положил стейджинг, или вручную `mkdir -p ~/tmp-nocko-agent-rsync-deploy`):

```bash
ssh stsadmin@192.168.11.153 'sudo env NOCKO_STAGING_USER=stsadmin /usr/local/sbin/nocko-agent-deploy-sync.sh'
```

Скрипт деплоя ищет helper через **`test -f`** (не `-x`): при правах `0700` у root обычный пользователь не видит «исполняемость», но `sudo` по NOPASSWD всё равно запускает полный путь.

После этого **`deploy-proxy-agent-prod.sh`** сам обнаружит helper и вызовет **`sudo /usr/local/sbin/nocko-agent-deploy-sync.sh`** — пароль sudo не нужен.

Если пользователь стейджинга не `stsadmin`, на сервере в начале скрипта задайте `NOCKO_STAGING_USER` (или правьте скрипт): деплой передаёт `sudo env NOCKO_STAGING_USER=…`.

## 3. Что делает helper

См. [`scripts/remote/nocko-agent-deploy-sync.sh`](../scripts/remote/nocko-agent-deploy-sync.sh): копирует `~/tmp-nocko-agent-rsync-deploy/` → `/opt/nocko-agent/`, `chown`, `pip install -r requirements.txt`, `systemctl restart nocko-agent`, удаляет стейджинг.
