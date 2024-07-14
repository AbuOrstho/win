import logging
import sqlite3
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters
from telegram.constants import ParseMode
import config

import sqlite3


logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = config.TOKEN
ADMIN_USER_ID = 123456789
MONITOR_CHANNEL_1 = -1001234567890
MONITOR_CHANNEL_2 = -1001234567891
TARGET_CHANNEL = -1001234567892


def init_db():
    conn = sqlite3.connect('bot_settings.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS keywords
                 (channel1 TEXT, channel2 TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS settings
                 (time_window INTEGER)''')
    conn.commit()
    conn.close()


def add_keyword(channel1, channel2):
    conn = sqlite3.connect('bot_settings.db')
    c = conn.cursor()
    c.execute("INSERT INTO keywords VALUES (?, ?)", (channel1, channel2))
    conn.commit()
    conn.close()


def get_keywords():
    conn = sqlite3.connect('bot_settings.db')
    c = conn.cursor()
    c.execute("SELECT * FROM keywords")
    keywords = c.fetchall()
    conn.close()
    return keywords


def delete_keyword(index):
    conn = sqlite3.connect('bot_settings.db')
    c = conn.cursor()
    c.execute("SELECT * FROM keywords")
    keywords = c.fetchall()
    if 0 <= index < len(keywords):
        keyword_to_delete = keywords[index]
        c.execute("DELETE FROM keywords WHERE channel1 = ? AND channel2 = ?", keyword_to_delete)
        conn.commit()
        conn.close()
        return True
    conn.close()
    return False


def set_time_window(seconds):
    conn = sqlite3.connect('bot_settings.db')
    c = conn.cursor()
    c.execute("DELETE FROM settings")
    c.execute("INSERT INTO settings VALUES (?)", (seconds,))
    conn.commit()
    conn.close()


def get_time_window():
    conn = sqlite3.connect('bot_settings.db')
    c = conn.cursor()
    c.execute("SELECT * FROM settings")
    time_window = c.fetchone()
    conn.close()
    return time_window[0] if time_window else 30  # Default to 30 seconds if not set


def is_admin(user_id):
    return user_id == ADMIN_USER_ID


async def add_keywords(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("У вас нет прав для выполнения этой команды.")
        return

    try:
        channel1, channel2 = " ".join(context.args).split("|")
        channel1 = channel1.strip()
        channel2 = channel2.strip()
        add_keyword(channel1, channel2)
        await update.message.reply_text(f"Ключевые слова добавлены: {channel1} | {channel2}")
    except ValueError:
        await update.message.reply_text("Использование: /add_keywords <слово_канал1> | <слова_канал2>")


async def list_keywords(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("У вас нет прав для выполнения этой команды.")
        return

    keywords = get_keywords()
    if keywords:
        message = "Список ключевых слов:\n" + "\n".join([f"{i + 1}. {k[0]} | {k[1]}" for i, k in enumerate(keywords)])
    else:
        message = "Список ключевых слов пуст."
    await update.message.reply_text(message)


async def del_keywords(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("У вас нет прав для выполнения этой команды.")
        return

    try:
        index = int(context.args[0]) - 1
        if delete_keyword(index):
            await update.message.reply_text(f"Ключевое слово под номером {index + 1} удалено.")
        else:
            await update.message.reply_text("Неверный номер ключевого слова.")
    except (ValueError, IndexError):
        await update.message.reply_text("Использование: /del_keywords <номер>")


async def set_time_window_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("У вас нет прав для выполнения этой команды.")
        return

    try:
        seconds = int(context.args[0])
        set_time_window(seconds)
        await update.message.reply_text(f"Временное окно установлено: {seconds} секунд")
    except (ValueError, IndexError):
        await update.message.reply_text("Использование: /set_time_window <секунды>")


def check_conditions(text1: str, text2: str) -> bool:
    keywords = get_keywords()
    for kw1, kw2 in keywords:
        if kw1 in text1:
            channel2_keywords = kw2.split(',')
            for ch2_kw in channel2_keywords:
                ch2_kw = ch2_kw.strip()
                if '+' in ch2_kw:
                    sub_keywords = ch2_kw.split('+')
                    if all(sub_kw.strip() in text2 for sub_kw in sub_keywords):
                        return True
                elif ch2_kw in text2:
                    return True
    return False


async def handle_channel_post(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.channel_post
    current_time = datetime.now()
    time_window = get_time_window()

    if message.chat_id == MONITOR_CHANNEL_1:
        context.bot_data.setdefault('channel1_messages', []).append((message, current_time))
    elif message.chat_id == MONITOR_CHANNEL_2:
        context.bot_data.setdefault('channel2_messages', []).append((message, current_time))

    # Очистка старых сообщений
    context.bot_data['channel1_messages'] = [(m, t) for m, t in context.bot_data.get('channel1_messages', []) if
                                             current_time - t < timedelta(seconds=time_window)]
    context.bot_data['channel2_messages'] = [(m, t) for m, t in context.bot_data.get('channel2_messages', []) if
                                             current_time - t < timedelta(seconds=time_window)]

    for msg1, time1 in context.bot_data.get('channel1_messages', []):
        for msg2, time2 in context.bot_data.get('channel2_messages', []):
            if abs((time1 - time2).total_seconds()) <= time_window and check_conditions(msg1.text, msg2.text):
                link1 = f"https://t.me/c/{str(MONITOR_CHANNEL_1)[4:]}/{msg1.message_id}"
                link2 = f"https://t.me/c/{str(MONITOR_CHANNEL_2)[4:]}/{msg2.message_id}"

                await context.bot.send_message(
                    chat_id=TARGET_CHANNEL,
                    text=f"{msg1.text}\n\n[Ссылка на оригинал]({link1})",
                    parse_mode=ParseMode.MARKDOWN
                )
                await context.bot.send_message(
                    chat_id=TARGET_CHANNEL,
                    text=f"{msg2.text}\n\n[Ссылка на оригинал]({link2})",
                    parse_mode=ParseMode.MARKDOWN
                )
                logger.info("Сообщения переслано в целевой канал")
                return  # Прекращаем поиск после первого совпадения


def main() -> None:
    init_db()
    application = Application.builder().token(TOKEN).build()

    application.add_handler(CommandHandler("add_keywords", add_keywords))
    application.add_handler(CommandHandler("list_keywords", list_keywords))
    application.add_handler(CommandHandler("del_keywords", del_keywords))
    application.add_handler(CommandHandler("set_time_window", set_time_window_command))

    application.add_handler(MessageHandler(filters.ChatType.CHANNEL & filters.TEXT, handle_channel_post))

    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()


def create_db():
    conn = sqlite3.connect('bot_settings.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS keywords
                 (channel1 TEXT, channel2 TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS settings
                 (time_window INTEGER)''')
    conn.commit()
    conn.close()
    print("База данных создана успешно.")


if __name__ == '__main__':
    create_db()