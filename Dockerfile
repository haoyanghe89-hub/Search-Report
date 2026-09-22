FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml README.md alembic.ini ./
COPY src ./src
COPY migrations ./migrations
COPY case_data ./case_data

RUN python -m pip install --no-cache-dir ".[web,server]"

EXPOSE 8000

CMD ["search-report-api"]
