# Random Coffee Bot для Mattermost

Бот еженедельных random coffee: собирает случайные пары участников по понедельникам,
напоминает о встрече, собирает оценки и ведёт рейтинг.

Документация: [спецификация](spec/random-coffee-bot.md) · [архитектура](spec/architecture.md) ·
[план](spec/plan.md) · [бэклог](spec/backlog.md)

**Статус: этап 0** — каркас, подключение к Mattermost, эхо-бот в личных сообщениях.

## Создание bot-аккаунта в Mattermost

1. **System Console → Integrations → Bot Accounts** → включить `Enable Bot Account Creation`.
2. В любой команде: **Integrations → Bot Accounts → Add Bot Account**:
   - Username: `random-coffee`, Display Name: `Random Coffee`
   - Role: `Member` (права админа не нужны)
3. Скопировать сгенерированный **Token** → переменная `MM_BOT_TOKEN`.
4. Добавить бота в команду (team), где будут участники.

## Запуск в Docker (рекомендуется)

```bash
cp .env.example .env   # заполнить MM_URL и MM_BOT_TOKEN
docker compose up -d --build
docker compose logs -f coffeebot
```

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
| `DB_PATH` | `coffee.db` | путь к файлу SQLite |
| `LOG_LEVEL` | `INFO` | уровень логирования |
| `TZ` | `Europe/Moscow` | часовой пояс расписаний |
