import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
import os
import sqlite3
from aiogram import Bot, Dispatcher, executor, types

# ==========================================
# 1. ФЕЙК-СЕРВЕР ДЛЯ ОБХОДА ОГРАНИЧЕНИЙ RENDER
# ==========================================
class FakeServer(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()
        self.wfile.write(b"Bot is alive!")

def run_fake_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), FakeServer)
    server.serve_forever()

# Запускаем фоновый веб-сервер
threading.Thread(target=run_fake_server, daemon=True).start()


# ==========================================
# 2. НАСТРОЙКА БОТА И БАЗЫ ДАННЫХ
# ==========================================
TOKEN = "8755450072:AAGO85vA7uUq8Af_3ZzDoKpXrvajpfbPO6Q"  # Твой токен
ADMIN_IDS = [7287525738]  # Твой Telegram ID

bot = Bot(token=TOKEN)
dp = Dispatcher(bot)

def init_db():
    conn = sqlite3.connect("bot_base.db")
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            status TEXT DEFAULT 'Покупатель'
        )
    ''')
    conn.commit()
    conn.close()

init_db()


# ==========================================
# 3. ХЕНДЛЕРЫ И КОМАНДЫ БОТА (aiogram 2.x)
# ==========================================

# Команда /start
@dp.message_handler(commands=['start'])
async def send_welcome(message: types.Message):
    await message.reply(
        "Привет! Отправь мне юзернейм (например, @username или username), "
        "чтобы проверить его статус в базе."
    )

# Команда /add (Только для админа)
@dp.message_handler(commands=['add'])
async def add_scammer(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    
    args = message.get_args().split()
    if not args:
        await message.reply("Использование: /add @username")
        return
    
    username = args[0].replace("@", "").lower().strip()
    
    conn = sqlite3.connect("bot_base.db")
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO users (username, status) VALUES (?, 'Скам') "
        "ON CONFLICT(username) DO UPDATE SET status='Скам'",
        (username,)
    )
    conn.commit()
    conn.close()
    
    await message.reply(f"Пользователь @{username} успешно внесен в базу как 🛑 СКАМ!")

# Команда /addun (Только для админа)
@dp.message_handler(commands=['addun'])
async def add_unscammer(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    
    args = message.get_args().split()
    if not args:
        await message.reply("Использование: /addun @username")
        return
    
    username = args[0].replace("@", "").lower().strip()
    
    conn = sqlite3.connect("bot_base.db")
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO users (username, status) VALUES (?, 'Покупатель') "
        "ON CONFLICT(username) DO UPDATE SET status='Покупатель'",
        (username,)
    )
    conn.commit()
    conn.close()
    
    await message.reply(f"Пользователь @{username} отмечен как ✅ Чистый/Покупатель.")

# Проверка юзернеймов по обычному тексту
@dp.message_handler()
async def check_user(message: types.Message):
    text = message.text.strip()
    if text.startswith("/"):
        return

    username = text.replace("@", "").lower().strip()
    
    conn = sqlite3.connect("bot_base.db")
    cursor = conn.cursor()
    cursor.execute("SELECT status FROM users WHERE username = ?", (username,))
    result = cursor.fetchone()
    conn.close()
    
    if result:
        status = result[0]
        if status == 'Скам':
            await message.reply(f"⚠️ **ВНИМАНИЕ!** Пользователь @{username} находится в базе: **🛑 СКАМЕР**!")
        else:
            await message.reply(f"Пользователь @{username} найден в базе. Статус: **✅ {status}**")
    else:
        await message.reply(f"Пользователь @{username} не найден в базе скамеров (Статус по умолчанию: **Покупатель**).")


# ==========================================
# 4. ЗАПУСК БОТА
# ==========================================
if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)
