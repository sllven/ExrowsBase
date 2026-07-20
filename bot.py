import asyncio
import logging
import re
import aiohttp
import aiosqlite
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = '8755450072:AAGO85vA7uUq8Af_3ZzDoKpXrvajpfbPO6Q'
ADMIN_IDS = [7287525738]

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

TEXT_GARANT = (
    "Действующие гаранты:\n"
    "@Kristxyz | 7667435125 [до 6000₽]\n\n"
    "Владелец проекта: @sllven\n"
    "Канал @ExrowsBaseInfo"
)

LINK_SCAM_BASE = "https://t.me/ExrowsBase"
TEXT_CLAIM = (
    "Для подачи жалобы перейдите сюда https://t.me/ExrowsBase/231 и отправьте все как в шаблоне закрепе. "
    "Либо можете подать жалобу на прямую @sllven | @sllvenBot"
)

DB_PATH = "scammers.db"

async def init_db():
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS scammers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username1 TEXT,
                username2 TEXT,
                username3 TEXT,
                user_id TEXT UNIQUE
            )
        """)
        await conn.commit()

async def find_scammer(query: str):
    query = query.replace("@", "").lower().strip()
    async with aiosqlite.connect(DB_PATH) as conn:
        async with conn.execute("""
            SELECT username1, username2, username3, user_id FROM scammers 
            WHERE LOWER(user_id) = ? OR LOWER(username1) = ? OR LOWER(username2) = ? OR LOWER(username3) = ?
        """, (query, query, query, query)) as cursor:
            return await cursor.fetchone()

def get_inline_main_menu():
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="Staff | Гаранты", callback_data="menu_staff"))
    builder.row(types.InlineKeyboardButton(text="Подать Жалобу", callback_data="menu_claim"))
    return builder.as_markup()

def get_dynamic_links_keyboard(target_id: str):
    builder = InlineKeyboardBuilder()
    link_android = f"tg://openmessage?user_id={target_id}"
    link_apple = f"https://t.me/@{target_id}"
    builder.row(
        types.InlineKeyboardButton(text="android", url=link_android),
        types.InlineKeyboardButton(text="apple", url=link_apple)
    )
    return builder.as_markup()

async def fetch_tg_id(username: str):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"https://t.me/{username}") as response:
                html = await response.text()
                match = re.search(r'tg://resolve\?domain=.*?&amp;id=(\d+)', html)
                if match:
                    return match.group(1)
    except Exception:
        pass
    return None

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    if message.chat.type == "private":
        start_text = (
            "ExrowsBase — проверка статуса в базе Telegram-аккаунтов. Добро пожаловать.\n\n"
            "Пришлите @username или числовой id — я покажу статус в базе.\n\n"
            "Команды:\n"
            "• /check @username — проверить пользователя"
        )
        await message.answer(start_text, reply_markup=get_inline_main_menu())

@dp.callback_query(F.data.in_(["menu_staff", "menu_claim"]))
async def process_menu_callbacks(call: types.CallbackQuery):
    if call.data == "menu_staff":
        await call.message.answer(TEXT_GARANT)
    elif call.data == "menu_claim":
        await call.message.answer(TEXT_CLAIM, disable_web_page_preview=True)
    await call.answer()

@dp.message(Command("add"))
async def cmd_add_scammer(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return

    if not message.text or len(message.text.split()) < 5:
        await message.answer("❌ Неверный формат! Используй:\n`/add Юз1 Юз2 Юз3 Айди`")
        return

    args = message.text.split()[1:]
    u1, u2, u3, uid = args[0], args[1], args[2], args[3]
    u1 = u1.replace("@", "") if u1 != "-" else ""
    u2 = u2.replace("@", "") if u2 != "-" else ""
    u3 = u3.replace("@", "") if u3 != "-" else ""
    
    try:
        async with aiosqlite.connect(DB_PATH) as conn:
            await conn.execute(
                "INSERT OR REPLACE INTO scammers (username1, username2, username3, user_id) VALUES (?, ?, ?, ?)",
                (u1, u2, u3, uid)
            )
            await conn.commit()
        await message.answer(f"✅ Скамер успешно добавлен!\nID: `{uid}`")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")

# Новая команда удаления скамера из базы
@dp.message(Command("addun"))
async def cmd_remove_scammer(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return

    args = message.text.split()[1:] if message.text else []
    if not args:
        await message.answer("❌ Неверный формат! Используй:\n`/addun @username` или `/addun ID`")
        return

    target = args[0].replace("@", "").lower().strip()

    try:
        async with aiosqlite.connect(DB_PATH) as conn:
            # Удаляем запись, если таргет совпал с любой из колонок
            async with conn.execute(
                """
                DELETE FROM scammers 
                WHERE LOWER(user_id) = ? OR LOWER(username1) = ? OR LOWER(username2) = ? OR LOWER(username3) = ?
                """, 
                (target, target, target, target)
            ) as cursor:
                changes = cursor.rowcount
            await conn.commit()
            
        if changes > 0:
            await message.answer(f"✅ Пользователь успешно удален из базы скамеров.")
        else:
            await message.answer(f"❌ Пользователь не найден в базе.")
            
    except Exception as e:
        await message.answer(f"❌ Ошибка при удалении: {e}")

async def process_check(message: types.Message, target: str):
    clean_target = target.replace("@", "").strip()
    if not clean_target:
        return
        
    resolved_id = None
    if clean_target.isdigit():
        resolved_id = clean_target
    else:
        try:
            chat_info = await bot.get_chat(f"@{clean_target}")
            resolved_id = str(chat_info.id)
        except Exception:
            resolved_id = await fetch_tg_id(clean_target)

    scammer_data = await find_scammer(clean_target)
    
    if scammer_data:
        u1, u2, u3, uid = scammer_data
        main_username = f"@{u1}" if u1 else f"@{clean_target}"
        user_id = uid if uid and uid != "-" else (resolved_id if resolved_id else "Неизвестен")
        
        response_text = (
            f"{main_username} ({user_id})\n\n"
            f"Скамер/Мошенник\n"
            f"Найден в базе скамеров {LINK_SCAM_BASE}. Будьте осторожны и не имейте с ним делов."
        )
    else:
        main_username = f"@{clean_target}" if not clean_target.isdigit() else "Пользователь"
        user_id = resolved_id if resolved_id else "Неизвестен"
            
        response_text = (
            f"{main_username} ({user_id})\n\n"
            f"Нет в базе скамеров. Будьте осторожны, используйте гарантов"
        )

    reply_markup = get_dynamic_links_keyboard(user_id) if user_id != "Неизвестен" else None
    await message.answer(response_text, reply_markup=reply_markup, disable_web_page_preview=True)

@dp.message(F.text)
async def handle_all_messages(message: types.Message):
    if not message.text:
        return

    text_lower = message.text.lower().strip()
    match = re.match(r'^(взять|чек|проверить|/check)\s*(.*)', text_lower)
    
    if match:
        raw_args = message.text.split(maxsplit=1)
        if len(raw_args) > 1:
            await process_check(message, raw_args[1].strip())
            return
            
    if message.chat.type == "private":
        await process_check(message, message.text.strip())

async def main():
    await init_db()
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
