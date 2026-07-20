FROM python:3.10-slim

WORKDIR /app

RUN pip install --no-cache-dir aiogram==2.23.1 aiohttp==3.8.6

COPY . .

CMD ["python", "bot.py"]
