FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY journey_book ./journey_book
COPY roadmap ./roadmap
COPY start_backend.sh ./start_backend.sh
COPY start_backend.ps1 ./start_backend.ps1

EXPOSE 8000

CMD ["gunicorn", "roadmap.wsgi:application", "--chdir", "roadmap", "--bind", "0.0.0.0:8000", "--log-file", "-"]
