# Руководство для агентов (ИИ и людей)

- **Автономность:** не задавать пользователю блокирующие вопросы «делать ли пуш / какой хост» — следовать ТЗ, коду и [`docs/deployment-runbook.md`](docs/deployment-runbook.md). Исключения — явный запрет пользователя.
- **Сразу на бой:** после правок в **`proxy-agent/`** — тут же **`./scripts/deploy-proxy-agent-prod.sh`** на **`192.168.11.153`**. После правок **backend/frontend** — пуш + на сервере портала `git pull` и пересборка Docker (или CI). Не завершать задачу только коммитом, если цель — рабочий прод.
- **Чеклист ошибок:** [`docs/operations-lessons.md`](docs/operations-lessons.md).
- **Правила Cursor:** [`.cursor/rules/nocko-autonomous-agent.mdc`](.cursor/rules/nocko-autonomous-agent.mdc).
