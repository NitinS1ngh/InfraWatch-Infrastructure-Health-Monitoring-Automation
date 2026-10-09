FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
	PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN python -m pip install --no-cache-dir -r requirements.txt \
	&& groupadd --system infrawatch \
	&& useradd --system --gid infrawatch --home-dir /nonexistent \
		--shell /usr/sbin/nologin infrawatch

COPY --chown=infrawatch:infrawatch app ./app
COPY --chown=infrawatch:infrawatch config/services.yaml ./config/services.yaml
RUN mkdir -p /app/logs && chown infrawatch:infrawatch /app/logs

USER infrawatch

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
