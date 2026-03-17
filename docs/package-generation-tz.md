# ТЗ: генерация Windows-пакета для NOCKO MDM

## 1. Назначение

Настоящее ТЗ описывает реализованную логику генерации и выдачи Windows-пакета
агента `NOCKO MDM` для конечного заказчика через портал.

Цель решения:

- отказаться от сборки Windows-инсталляторов на production-сервере;
- выдавать пользователю один понятный файл для установки;
- использовать предсобранный Windows-артефакт и персонализировать его под
  конкретного клиента;
- передавать параметры подключения и установки без пересборки агента под
  каждого клиента.

## 2. Основание для реализации

До изменения логики генерация Windows-пакетов на production была нестабильной,
так как Linux-сервер не должен выступать средой сборки Windows-инсталляторов.

Принятое решение:

- сборка базовых Windows-артефактов выполняется в GitHub Actions на Windows runner;
- production хранит только код backend/frontend и manifest доступных релизов;
- портал получает список доступных артефактов, берет базовый `EXE`,
  встраивает tenant bootstrap config и отдает клиенту готовый единый файл.

## 3. Объект автоматизации

Подсистема генерации пакета включает:

- backend API генерации и каталога пакетов;
- frontend-страницу `Enrollment -> Windows -> Deployment Package`;
- manifest релизов Windows-агента;
- GitHub Actions workflow сборки agent release;
- bootstrap-механику встраивания конфигурации в базовый `EXE`;
- self-install поведение Windows-агента.

## 4. Бизнес-требование

Пользователь портала должен иметь возможность скачать один персонализированный
Windows `EXE`, который:

- уже содержит адрес сервера MDM;
- уже содержит enrollment token;
- уже содержит customer identifier;
- содержит настройки установки и запуска агента;
- при запуске от имени администратора устанавливает Windows service;
- отображается в списке установленных программ и может быть удален стандартным
  способом Windows.

## 5. Источник входных данных

Для генерации пакета должны использоваться следующие данные:

### 5.1. Данные клиента

Из backend БД:

- `customer_id`;
- `customer_name`;
- `customer_slug`;
- активный `enrollment_token` клиента.

### 5.2. Системные настройки портала

Из `System Settings`:

- `mdm_server_url`;
- `agent_log_level`;
- `agent_heartbeat_interval`;
- `agent_metrics_interval`;
- `agent_inventory_interval`;
- `agent_commands_interval`;
- `siem_enabled`.

### 5.3. Пользовательские параметры формы

С frontend-страницы генерации:

- формат пакета;
- архитектура;
- install mode;
- agent display name;
- install directory;
- log directory;
- auto-start service.

## 6. Выходной результат

Основной результат генерации:

- один файл `EXE` формата `application/octet-stream`, подготовленный для
  конкретного клиента.

Имя файла формируется по шаблону:

- `nocko-mdm-agent-<customer-slug>-<timestamp>.exe`

Дополнительный fallback-результат:

- `ZIP` bootstrap package для внутреннего или резервного сценария.

## 7. Функциональные требования

### 7.1. Каталог релизов

Backend должен предоставлять endpoint каталога:

- `GET /api/v1/packages/catalog`

Каталог должен возвращать:

- идентификатор клиента;
- имя клиента;
- server URL;
- enrollment token;
- release channel;
- release version;
- generated_at;
- список доступных артефактов;
- список допустимых bootstrap formats.

Источник данных каталога:

- `backend/package_builder/agent_releases.json`

Допускается override через environment variable:

- `AGENT_RELEASES_MANIFEST`

### 7.2. Генерация customer-specific EXE

Backend должен предоставлять endpoint:

- `POST /api/v1/packages/generate`

Для формата `exe` логика должна быть следующей:

1. Проверить существование клиента.
2. Проверить наличие активного enrollment token.
3. Прочитать package settings из системных настроек.
4. Найти в manifest подходящий базовый Windows `EXE` по формату и архитектуре.
5. Скачать базовый артефакт по `download_url`.
6. Сформировать bootstrap config.
7. Встроить bootstrap config в конец `EXE`.
8. Вернуть готовый бинарный файл пользователю.

### 7.3. Генерация fallback ZIP

Для формата `zip` backend должен:

1. Собрать bootstrap archive с `config.json`.
2. Включить в него те же tenant-specific параметры, что и для `EXE`.
3. Отдать архив пользователю как резервный сценарий.

### 7.4. Ошибки генерации

При отсутствии артефакта backend должен вернуть понятную ошибку:

- для неподходящей архитектуры;
- для отсутствующего `EXE`;
- для невозможности скачать релизный файл;
- для отсутствующего enrollment token;
- для отсутствующего клиента.

## 8. Состав bootstrap config

В персонализированный `EXE` должна встраиваться JSON-конфигурация со следующими
полями:

- `server_url`
- `enrollment_token`
- `customer_id`
- `heartbeat_interval`
- `metrics_interval`
- `inventory_interval`
- `commands_interval`
- `mdm_enabled`
- `siem_enabled`
- `backup_enabled`
- `remote_enabled`
- `log_level`
- `agent_version`
- `device_id`
- `install_dir`
- `log_dir`
- `start_immediately`
- `agent_display_name`

## 9. Требования к frontend

Страница генерации пакета должна:

- показывать текущий `server_url`;
- показывать текущий `enrollment_token`;
- показывать доступный release version;
- показывать поддерживаемую архитектуру публикации;
- позволять задать install path и log path;
- позволять задать agent display name;
- генерировать и скачивать один `EXE`;
- блокировать генерацию, если подходящий базовый артефакт отсутствует;
- отображать пользователю понятное описание, что это single EXE installer с
  embedded config.

На текущем этапе основной видимый пользователю формат:

- `Single EXE Installer`

На текущем этапе основная поддерживаемая архитектура публикации:

- `x64`

## 10. Требования к GitHub Actions

Сборка Windows-артефактов должна выполняться отдельно от production deployment.

Workflow должен:

1. Запускаться на Windows runner.
2. Собирать portable `EXE` через PyInstaller.
3. Публиковать portable `EXE` в GitHub Releases.
4. Обновлять `backend/package_builder/agent_releases.json`.

К production deployment workflow это относится только как источник готовых
артефактов. Production не должен выполнять Windows build.

## 11. Требования к production

Production-сервер должен:

- принимать обновления кода через GitHub deployment flow;
- разворачивать backend/frontend;
- отдавать catalog endpoint;
- отдавать generate endpoint;
- скачивать уже готовые Windows-артефакты;
- встраивать конфигурацию только на этапе выдачи клиенту;
- не устанавливать Windows build tools для runtime генерации пакета.

## 12. Требования к установке агента

Сгенерированный `EXE` должен:

1. При запуске прочитать embedded bootstrap config.
2. При необходимости запросить elevation.
3. Скопировать рабочий бинарник в install directory.
4. Сохранить config на машине.
5. Установить Windows service с автозапуском.
6. При включенной опции `start_immediately` сразу запустить service.
7. Зарегистрировать uninstall entry в Windows Installed Apps.
8. Поддерживать штатное удаление агента.

## 13. Нефункциональные требования

- Production не должен зависеть от Windows toolchain.
- Генерация пакета должна занимать минимальное время и не включать этап сборки.
- Логика должна быть воспроизводимой и одинаковой для всех клиентов.
- Решение должно поддерживать масштабирование по числу клиентов без отдельной
  пересборки агента на каждого клиента.
- Конечный пользователь должен получать один понятный файл, без набора
  дополнительных конфигурационных файлов.

## 14. Ограничения

- Персонализация выполняется только для `EXE`, который поддерживает embedded
  bootstrap config.
- Если release manifest не содержит нужный артефакт, портал не должен
  генерировать пакет "из воздуха".
- Полноценная сборка Windows-агента допустима только в GitHub Actions на Windows.

## 15. Критерии приемки

Решение считается реализованным, если одновременно выполняются следующие условия:

1. В портале доступна генерация одного customer-specific `EXE`.
2. Backend берет базовый `EXE` из release manifest, а не собирает его на сервере.
3. В итоговый `EXE` встраиваются tenant-specific настройки.
4. Пользователь скачивает один файл и может установить агент без дополнительных
   файлов конфигурации.
5. После запуска `EXE` агент устанавливается как Windows service.
6. Агент появляется в списке установленных программ Windows.
7. Агент можно удалить штатным uninstall-сценарием.
8. При отсутствии релизного артефакта пользователь получает корректную ошибку.
9. Production deploy не содержит этапа сборки Windows installer.

## 16. Текущее соответствие реализации

По состоянию на текущую реализацию:

- основная схема `single EXE with embedded config` внедрена;
- backend catalog и generate endpoints реализованы;
- settings для package generation берутся из портала;
- GitHub Actions release flow реализован;
- production deploy отделен от Windows build;
- self-install, Windows service и uninstall entry реализованы;
- fallback ZIP сохранен как резервный сценарий.
