FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY notifier/ notifier/
COPY config.yaml .

EXPOSE 8550

CMD ["python", "-m", "notifier.main"]
