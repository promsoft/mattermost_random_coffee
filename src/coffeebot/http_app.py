"""HTTP-эндпоинт для callback'ов интерактивных кнопок Mattermost.

Mattermost Free не подписывает эти запросы, поэтому аутентификация —
секрет в пути URL (известен только серверу Mattermost из props постов)
+ эндпоинт слушает только внутреннюю сеть. См. spec/architecture.md.
"""

import hmac
import logging

from fastapi import FastAPI, HTTPException, Request

from coffeebot.handlers import BotHandlers

log = logging.getLogger(__name__)


def create_app(handlers: BotHandlers, actions_secret: str) -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.post("/actions/{secret}")
    async def actions(secret: str, request: Request) -> dict:
        if not hmac.compare_digest(secret, actions_secret):
            raise HTTPException(status_code=403)
        payload = await request.json()
        user_id = payload.get("user_id")
        username = payload.get("user_name") or ""
        action = (payload.get("context") or {}).get("action")
        if not user_id or not action:
            raise HTTPException(status_code=400)
        try:
            handlers.on_action(user_id, username, action)
        except Exception:
            log.exception("Ошибка обработки действия %s от %s", action, user_id)
            return {"ephemeral_text": "Что-то пошло не так, попробуйте ещё раз."}
        # Ответы бот шлёт отдельными сообщениями; сам пост с кнопками не трогаем
        return {}

    @app.get("/healthz")
    async def healthz() -> dict:
        return {"status": "ok"}

    return app
