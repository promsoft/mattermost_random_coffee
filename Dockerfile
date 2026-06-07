FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY pyproject.toml alembic.ini ./
COPY alembic ./alembic
COPY src ./src
RUN pip install --no-cache-dir --no-deps -e .

ENV DB_PATH=/data/coffee.db
VOLUME /data

# Применяем миграции и запускаем бота
CMD ["sh", "-c", "alembic upgrade head && python -m coffeebot.main"]
