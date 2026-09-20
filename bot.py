"""
Телеграм-бот для проверки занятости юзернеймов БОТОВ.

Как это работает:
    Ты присылаешь боту "базовые" имена, например:

        kow553
        puy727
        pkla3

    Для каждого базового имени бот сам строит ДВА варианта юзернейма бота:
        {имя}bot     -> kow553bot
        {имя}_bot    -> kow553_bot

    и проверяет занят ли КАЖДЫЙ из них. Так как проверяются только
    варианты с суффиксом bot/_bot — это всегда именно юзернеймы ботов,
    а не обычных аккаунтов или каналов.

    Проверка занятости идёт через Telegram Bot API (надежный метод).

Установка:
    pip install python-telegram-bot==21.* aiohttp requests

Запуск:
    export BOT_TOKEN="токен_от_BotFather"
    python bot.py

Использование:
    Присылаешь одно или несколько базовых имён (каждое с новой строки
    или через пробел/запятую), например:

        kow553
        puy727
        pkla3

    Бот пришлёт отчёт со статусами @kow553bot / @kow553_bot и т.д.,
    результат в моноширинном формате — можно тапнуть и скопировать.
"""

import asyncio
import logging
import os
import re

import aiohttp
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
import requests

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
log = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN", "8770957416:AAHSjDJ42QfsA5ofKR1T6gzj-Q3ARGK940o")

# Не более N одновременных запросов к API, чтобы не словить бан.
MAX_CONCURRENT_REQUESTS = 5
# Небольшая пауза между запросами (в секундах).
REQUEST_DELAY = 0.1  # Уменьшил до 0.1 для максимальной скорости
# Таймаут для всей проверки (в секундах)
CHECK_TIMEOUT = 60

# Лимит длины одного телеграм-сообщения — оставляем запас от 4096.
TELEGRAM_MESSAGE_LIMIT = 3800

# Базовое имя: латиница/цифры/подчёркивание, начинается с буквы,
# запас длины, чтобы после суффикса "_bot" уложиться в лимит юзернейма (32).
BASENAME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]{0,27}$")




def extract_basenames(text: str) -> list[str]:
    """Достаём из сообщения все базовые имена (без суффикса bot/_bot)."""
    raw_tokens = re.split(r"[\s,;]+", text.strip())
    names = []
    for token in raw_tokens:
        token = token.strip()
        if not token:
            continue
        token = token.replace("https://t.me/", "").replace("http://t.me/", "")
        token = token.lstrip("@")
        # если по ошибке уже прислали с суффиксом — срежем его,
        # чтобы не получилось "namebotbot"
        if token.lower().endswith("_bot"):
            token = token[:-4]
        elif token.lower().endswith("bot"):
            token = token[:-3]
        if token and BASENAME_RE.match(token):
            names.append(token)
    # убираем дубликаты, сохраняя порядок
    seen = set()
    unique = []
    for n in names:
        if n.lower() not in seen:
            seen.add(n.lower())
            unique.append(n)
    return unique


def check_exists(username: str) -> str:
    """Возвращает 'taken', 'free' или 'other' (ошибка проверки).
    
    Упрощенная проверка только через API для скорости и надежности.
    """
    try:
        # Проверяем только через Bot API
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/getChat"
        params = {"chat_id": f"@{username}"}
        
        response = requests.get(url, params=params, timeout=2)  # Агрессивный timeout
        data = response.json()
        
        if data.get("ok"):
            # Chat существует - занято (любой тип)
            return "taken"
        else:
            error_desc = data.get("description", "").lower()
            if "chat not found" in error_desc:
                return "free"
            else:
                log.warning(f"@{username}: ошибка API: {error_desc}")
                return "other"
                
    except requests.exceptions.Timeout:
        log.warning(f"@{username}: timeout")
        return "other"
    except requests.exceptions.RequestException as e:
        log.warning(f"@{username}: ошибка сети: {e}")
        return "other"
    except Exception as e:
        log.warning("Ошибка при проверке %s: %s", username, e)
        return "other"





STATUS_BULLET = {"free": "○", "taken": "●", "other": "⚠"}
STATUS_LABEL = {"free": "free", "taken": "taken", "other": "error"}


def build_report(basenames: list[str], results: dict[str, dict[str, str]]) -> list[str]:
    """
    Строит отчёт без Markdown для избежания ошибок форматирования.
    """
    free_count = taken_count = other_count = 0
    free_usernames: list[str] = []
    free_basenames: list[str] = []

    group_blocks: list[str] = []
    for basename in basenames:
        base_status = results[basename].get("base", "other")
        lines = [f"@{basename}"]
        
        # Показываем статус базового имени
        base_bullet = STATUS_BULLET[base_status]
        base_label = STATUS_LABEL[base_status]
        lines.append(f"{base_bullet} @{basename} {base_label} (базовое)")
        
        if base_status == "free":
            free_basenames.append(basename)
            # Если базовое свободно, проверяем варианты
            for suffix in ("bot", "_bot"):
                status = results[basename].get(suffix, "other")
                username = f"{basename}{suffix}"
                bullet = STATUS_BULLET[status]
                label = STATUS_LABEL[status]
                lines.append(f"{bullet} @{username} {label}")

                if status == "free":
                    free_count += 1
                    free_usernames.append(username)
                elif status == "taken":
                    taken_count += 1
                else:
                    other_count += 1
        else:
            # Если базовое занято, варианты тоже заняты
            taken_count += 2  # bot и _bot
            lines.append(f"● @{basename}bot taken (базовое занято)")
            lines.append(f"● @{basename}_bot taken (базовое занято)")
            
        group_blocks.append("\n".join(lines))

    summary = (
        f"○ free {free_count}  ● taken {taken_count} · other {other_count}"
    )
    separator = "──────────────"

    header = f"VALID REPORT\n\n{summary}\n\n{separator}"

    footer_lines = [separator, "", "Свободные базовые имена:"]
    if free_basenames:
        for u in free_basenames:
            footer_lines.append(f"@{u}")
    else:
        footer_lines.append("Свободных базовых имён нет")
    
    footer_lines.extend(["", "Свободные варианты с bot:"])
    if free_usernames:
        for u in free_usernames:
            footer_lines.append(f"@{u}")
    else:
        footer_lines.append("Свободных вариантов нет")
    footer = "\n".join(footer_lines)

    # Режем группы на чанки, чтобы уложиться в лимит длины сообщения
    messages = []
    current = header
    for block in group_blocks:
        candidate = current + "\n\n" + block
        if len(candidate) > TELEGRAM_MESSAGE_LIMIT:
            messages.append(current)
            current = block
        else:
            current = candidate

    # последний чанк групп + подвал
    if len(current) + len(footer) + 2 > TELEGRAM_MESSAGE_LIMIT:
        messages.append(current)
        messages.append(footer)
    else:
        messages.append(current + "\n\n" + footer)

    return messages


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привет! Пришли базовые имена для проверки (каждое с новой "
        "строки или через пробел/запятую), например:\n\n"
        "zalupa122\nkoch121\nfog229\n\n"
        "Я проверю:\n"
        "1. Удаленные боты с таким юзернеймом\n"
        "2. Каналы с таким юзернеймом\n"
        "3. Активные боты с таким юзернеймом\n"
        "4. Пользователи с таким юзернеймом\n\n"
        "Если базовое имя свободно - проверю варианты с суффиксами bot/_bot"
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text or ""
    basenames = extract_basenames(text)

    if not basenames:
        await update.message.reply_text(
            "Не нашёл ни одного подходящего базового имени. Имя должно "
            "начинаться с буквы и состоять из латинских букв, цифр и "
            "подчёркивания."
        )
        return

    # Ограничиваем количество проверяемых юзернеймов
    MAX_USERNAMES = 10  # Уменьшил с 20 до 10 для надежности
    if len(basenames) > MAX_USERNAMES:
        await update.message.reply_text(
            f"Слишком много юзернеймов! Максимум {MAX_USERNAMES} за раз. "
            f"Вы отправили {len(basenames)}. Разделите на несколько сообщений."
        )
        return

    status_msg = await update.message.reply_text(
        f"Проверяю {len(basenames)} базовых имён, подожди немного…"
    )

    try:
        # Запускаем проверку с прогресс-индикатором
        results = {}
        total = len(basenames)
        
        for i, basename in enumerate(basenames):
            try:
                # Обновляем прогресс
                progress = f"Проверяю {i+1}/{total}: @{basename}…"
                await status_msg.edit_text(progress)
                
                # Проверяем базовое имя
                base_status = check_exists(basename)
                results[basename] = {"base": base_status}
                
                # Если базовое свободно, проверяем варианты
                if base_status == "free":
                    for suffix in ("bot", "_bot"):
                        username = f"{basename}{suffix}"
                        status = check_exists(username)
                        results[basename][suffix] = status
                else:
                    results[basename]["bot"] = "taken"
                    results[basename]["_bot"] = "taken"
                    
            except Exception as e:
                log.warning(f"Ошибка при проверке {basename}: {e}")
                results[basename] = {"base": "other", "bot": "other", "_bot": "other"}
        
        # Формируем и отправляем отчет
        messages = build_report(basenames, results)
        await status_msg.edit_text(messages[0])
        for msg in messages[1:]:
            await update.message.reply_text(msg)
            
    except Exception as e:
        log.error(f"Ошибка при обработке сообщения: {e}")
        await status_msg.edit_text(
            f"Произошла ошибка при проверке. Попробуйте снова с меньшим количеством юзернеймов."
        )


def main():
    if not BOT_TOKEN or BOT_TOKEN == "your_bot_token_here":
        raise SystemExit(
            "BOT_TOKEN не найден. Установите переменную окружения BOT_TOKEN "
            "или добавьте токен в код."
        )

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", start_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    log.info("Бот запущен, жду сообщений…")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
