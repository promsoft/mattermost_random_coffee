"""Конфигурация бота: переменные окружения / .env."""

from urllib.parse import urlparse

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Полный URL сервера Mattermost, например https://mm.example.com
    # или http://localhost:8065
    mm_url: str = "http://localhost:8065"
    mm_bot_token: str = ""
    db_path: str = "coffee.db"
    log_level: str = "INFO"
    tz: str = "Europe/Moscow"

    # Канал для анонсов (ID канала; пусто — анонсы выключены)
    announce_channel_id: str = ""
    # Админы бота, имена через запятую: "ivanov,petrov" (этап 4)
    admin_usernames: str = ""

    # HTTP-эндпоинт кнопок: на нём слушает бот...
    http_host: str = "127.0.0.1"
    http_port: int = 9000
    # ...а по этому URL до него достукивается сервер Mattermost
    actions_base_url: str = "http://127.0.0.1:9000"
    # Обязательный секрет в URL кнопок: Mattermost Free не подписывает
    # callback-запросы, секрет + внутренняя сеть = аутентификация запросов
    actions_secret: str = ""

    # Расписания (день недели: 0 = понедельник; время в поясе tz)
    match_weekday: int = 0  # матчинг пар
    match_hour: int = 7
    match_minute: int = 0
    midweek_weekday: int = 2  # опрос статуса (среда)
    midweek_hour: int = 14
    midweek_minute: int = 0
    survey_weekday: int = 6  # итоги и оценка (воскресенье)
    survey_hour: int = 14
    survey_minute: int = 0

    @property
    def db_url(self) -> str:
        return f"sqlite:///{self.db_path}"

    @property
    def admin_username_set(self) -> set[str]:
        return {u.strip().lstrip("@") for u in self.admin_usernames.split(",") if u.strip()}

    @property
    def actions_url(self) -> str:
        """Полный URL эндпоинта кнопок, который зашивается в посты."""
        return f"{self.actions_base_url.rstrip('/')}/actions/{self.actions_secret}"

    @property
    def driver_options(self) -> dict:
        """Опции для mattermostdriver.Driver, разобранные из mm_url."""
        parsed = urlparse(self.mm_url)
        scheme = parsed.scheme or "http"
        port = parsed.port or (443 if scheme == "https" else 80)
        return {
            "url": parsed.hostname,
            "scheme": scheme,
            "port": port,
            "basepath": "/api/v4",
            "token": self.mm_bot_token,
            "verify": True,
        }
