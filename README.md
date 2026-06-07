# Random Coffee Bot для Mattermost

Бот еженедельных random coffee: собирает случайные пары участников по понедельникам,
напоминает о встрече, собирает оценки и ведёт рейтинг.

Документация: [спецификация](spec/random-coffee-bot.md) · [архитектура](spec/architecture.md) ·
[план](spec/plan.md) · [бэклог](spec/backlog.md)

**Статус: этап 1 (MVP)** — регистрация/пауза/профиль (кнопки + команды в личке),
еженедельный матчинг пар с годовым кулдауном, знакомство пары в групповом чате,
анонсы в канал, справка.

## Как пользоваться (участнику)

Напишите боту в личку `помощь` — он покажет справку и кнопки. Команды:
`регистрация` · `пауза` · `возобновить` · `профиль` · `помощь`.

## Создание bot-аккаунта в Mattermost

1. **System Console → Integrations → Bot Accounts** → включить `Enable Bot Account Creation`.
2. В любой команде: **Integrations → Bot Accounts → Add Bot Account**:
   - Username: `random-coffee`, Display Name: `Random Coffee`
   - Role: `Member` (права админа не нужны)
3. Скопировать сгенерированный **Token** → переменная `MM_BOT_TOKEN`.
4. Добавить бота в команду (team), где будут участники.

## Настройка интерактивных кнопок

Кнопки в сообщениях бота работают через HTTP-callback: сервер Mattermost шлёт POST
на `ACTIONS_BASE_URL/actions/<ACTIONS_SECRET>`.

1. Сгенерируйте секрет: `python -c "import secrets; print(secrets.token_urlsafe(32))"`
   → `ACTIONS_SECRET` (обязателен: Mattermost Free не подписывает callback-запросы,
   секрет в URL + внутренняя сеть — единственная аутентификация).
2. `ACTIONS_BASE_URL` — URL, по которому **сервер Mattermost** достучится до бота:
   - оба на одном хосте без Docker: `http://127.0.0.1:9000`
   - Mattermost в Docker, бот в Docker (как в compose): адрес хоста из docker-сети MM,
     обычно `http://172.17.0.1:9000`, либо общая docker-сеть и `http://coffeebot:9000`
3. В **System Console → Environment → Developer** добавьте адрес бота в
   `Allow untrusted internal connections to` (например `127.0.0.1 172.17.0.1`),
   иначе Mattermost откажется слать POST на внутренний адрес.
4. Эндпоинт не должен быть доступен извне: в compose порт открыт только на
   `127.0.0.1` хоста.

## Запуск в Docker (рекомендуется)

Образ собирается автоматически (GitHub Actions → Docker Hub:
[`promsoft/mattermost-random-coffee`](https://hub.docker.com/r/promsoft/mattermost-random-coffee),
теги: `latest` из main, `X.Y.Z` из git-тегов `v*`).

```bash
cp .env.example .env   # заполнить MM_URL, MM_BOT_TOKEN, ACTIONS_SECRET, ACTIONS_BASE_URL
docker compose pull && docker compose up -d     # деплой готового образа
docker compose logs -f coffeebot
```

Локальная сборка вместо Docker Hub: `docker compose up -d --build`.

Обновление на сервере: `docker compose pull && docker compose up -d` (миграции
применяются при старте контейнера автоматически).

База SQLite живёт в named volume `coffee-data` (`/data/coffee.db`).
Если Mattermost слушает только localhost — см. `network_mode: host` в compose.

## Локальная разработка

Окружение: pyenv virtualenv `projects_mattermost_random_coffee` (активируется
автоматически через `.python-version`).

```bash
uv pip install -r requirements.txt -e .   # зависимости + пакет (editable)
cp .env.example .env                      # заполнить MM_URL, MM_BOT_TOKEN
alembic upgrade head                      # миграции (файл coffee.db рядом)
python -m coffeebot.main                  # запуск бота
```

Проверка: написать боту в личку — на этапе 0 он отвечает эхом.

### Тесты и линт

```bash
python -m pytest -q
ruff check .
```

### Зависимости

Прямые зависимости объявляются в `requirements.in`, лочатся в `requirements.txt`:

```bash
uv pip compile requirements.in -o requirements.txt
uv pip install -r requirements.txt
```

### Миграции БД

```bash
alembic revision --autogenerate -m "описание"   # после изменения моделей
alembic upgrade head
```

## Переменные окружения

| Переменная | По умолчанию | Описание |
|---|---|---|
| `MM_URL` | `http://localhost:8065` | URL сервера Mattermost |
| `MM_BOT_TOKEN` | — | токен bot-аккаунта |
| `ANNOUNCE_CHANNEL_ID` | пусто | ID канала анонсов (пусто — выключено) |
| `ADMIN_USERNAMES` | пусто | админы бота, имена через запятую |
| `ACTIONS_BASE_URL` | `http://127.0.0.1:9000` | URL бота для callback'ов кнопок |
| `ACTIONS_SECRET` | — | **обязательный** секрет в URL кнопок |
| `HTTP_HOST` / `HTTP_PORT` | `127.0.0.1` / `9000` | где слушает эндпоинт кнопок |
| `MATCH_WEEKDAY` / `MATCH_HOUR` / `MATCH_MINUTE` | `0` / `7` / `0` | расписание матчинга (0 = пн) |
| `DB_PATH` | `coffee.db` | путь к файлу SQLite |
| `LOG_LEVEL` | `INFO` | уровень логирования |
| `TZ` | `Europe/Moscow` | часовой пояс расписаний |

При старте бот «догоняет» пропущенный матчинг недели (если время прошло, а пар нет)
и досылает неотправленные уведомления — рестарт ничего не дублирует.
