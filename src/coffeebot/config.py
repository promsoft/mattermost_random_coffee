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

    @property
    def db_url(self) -> str:
        return f"sqlite:///{self.db_path}"

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
