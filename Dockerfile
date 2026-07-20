FROM python:3.10-slim
WORKDIR /app
COPY . .
# Эта команда выведет список всех файлов, которые Docker реально видит
RUN ls -la
RUN pip install --no-cache-dir -r requirements.txt
CMD ["python", "bot.py"]
