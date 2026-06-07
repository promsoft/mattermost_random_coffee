# alpine вместо slim: в базовом slim (Debian) висят CRITICAL/HIGH CVE в perl и
# ncurses без доступных фиксов; alpine их просто не содержит. См. spec/security.md
FROM python:3.12-alpine

# apk upgrade подтягивает патчи базовых пакетов; tzdata — для zoneinfo (Europe/Moscow)
RUN apk upgrade --no-cache && apk add --no-cache tzdata

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY pyproject.toml alembic.ini ./
COPY alembic ./alembic
COPY src ./src
RUN pip install --no-cache-dir --no-deps -e .

ENV DB_PATH=/data/coffee.db
VOLUME /data

# Применяем миграции и запускаем бота
CMD ["sh", "-c", "alembic upgrade head && python -m coffeebot.main"]
