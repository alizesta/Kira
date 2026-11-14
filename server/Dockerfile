FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY requirements.txt /app/requirements.txt
COPY server/requirements.txt /app/server-requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt -r /app/server-requirements.txt

COPY . /app
ENV KIRA_ENV=production
EXPOSE 8080
CMD ["uvicorn", "server.kira_core.app:app", "--host", "0.0.0.0", "--port", "8080"]
