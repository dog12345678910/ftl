FROM python:3.12-slim

WORKDIR /app

# Install dependencies first for better layer caching.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY footlocker_monitor/ ./footlocker_monitor/
COPY pyproject.toml README.md ./

# Config and state are mounted at runtime (see docker-compose.yml).
ENV PYTHONUNBUFFERED=1

ENTRYPOINT ["python", "-m", "footlocker_monitor"]
CMD ["-c", "/app/config.json"]
