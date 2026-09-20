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
from telegram.constants import ParseMode
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
REQUEST_DELAY = 0.35

# Лимит длины одного телеграм-сообщения — оставляем запас от 4096.
TELEGRAM_MESSAGE_LIMIT = 3800

# Базовое имя: латиница/цифры/подчёркивание, начинается с буквы,
# запас длины, чтобы после суффикса "_bot" уложиться в лимит юзернейма (32).
BASENAME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]{0,27}$")

MD_ESCAPE_RE = re.compile(r"([_*\[\]()~`>#+\-=|{}.!\\])")


def escape_md(text: str) -> str:
    """Экранирование для обычного (не-код) текста в MarkdownV2."""
    return MD_ESCAPE_RE.sub(r"\\\1", text)


def escape_code(text: str) -> str:
    """Экранирование для содержимого внутри `код`-спанов в MarkdownV2."""
    return text.replace("\\", "\\\\").replace("`", "\\`")


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
    
    Логика проверки в порядке приоритета:
    1. Удаленные боты с таким юзернеймом
    2. Каналы с таким юзернеймом  
    3. Активные боты с таким юзернеймом
    4. Пользователи с таким юзернеймом
    5. Если ничего из этого - свободен
    """
    try:
        # Сначала проверяем через Bot API для активных ботов
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/getChat"
        params = {"chat_id": f"@{username}"}
        
        response = requests.get(url, params=params, timeout=10)
        data = response.json()
        
        if data.get("ok"):
            # Chat существует через API - проверяем тип
            chat_info = data.get("result", {})
            chat_type = chat_info.get("type", "")
            
            # Определяем тип занятости
            if chat_type == "bot":
                log.info(f"@{username}: занят активным ботом")
                return "taken"
            elif chat_type == "channel":
                log.info(f"@{username}: занят каналом")
                return "taken"
            elif chat_type == "supergroup" or chat_type == "group":
                log.info(f"@{username}: занят группой")
                return "taken"
            elif chat_type == "private":
                log.info(f"@{username}: занят пользователем")
                return "taken"
            else:
                log.info(f"@{username}: занят (тип: {chat_type})")
                return "taken"
        else:
            error_desc = data.get("description", "").lower()
            
            # Если через API не найден, проверяем через веб-страницу
            # (для обнаружения удаленных ботов и каналов)
            if "chat not found" in error_desc:
                return check_via_webpage(username)
            else:
                log.warning(f"@{username}: ошибка API: {error_desc}")
                return "other"
                
    except Exception as e:
        log.warning("Ошибка при проверке %s через API: %s", username, e)
        # При ошибке API пробуем через веб-страницу
        return check_via_webpage(username)


def check_via_webpage(username: str) -> str:
    """Проверка через веб-страницу для обнаружения удаленных ботов и каналов."""
    try:
        url = f"https://t.me/{username}"
        
        response = requests.get(url, timeout=10, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })
        
        if response.status_code == 404:
            # Страница не существует - юзернейм точно свободен
            log.info(f"@{username}: свободен (404)")
            return "free"
        
        if response.status_code == 200:
            html = response.text.lower()
            
            # Проверяем в порядке приоритета как просили:
            
            # 1. Удаленные боты (страница существует но без кнопки start)
            if "bot" in html and "if you have telegram" in html:
                if "start" not in html and "send message" not in html:
                    log.info(f"@{username}: занят удаленным ботом")
                    return "taken"
            
            # 2. Каналы (признаки канала)
            if "channel" in html or "subscriber" in html:
                log.info(f"@{username}: занят каналом")
                return "taken"
            
            # 3. Активные боты (есть кнопка start)
            if "bot" in html and ("start" in html or "send message" in html):
                log.info(f"@{username}: занят активным ботом")
                return "taken"
            
            # 4. Пользователи (стандартная страница пользователя)
            if "if you have telegram" in html or "has telegram" in html:
                log.info(f"@{username}: занят пользователем")
                return "taken"
            
            # 5. Если есть группа
            if "group" in html or "member" in html or "join" in html:
                log.info(f"@{username}: занят группой")
                return "taken"
            
            # Если страница существует но без ясных признаков - считаем занятым
            log.info(f"@{username}: занят (неопределенный тип)")
            return "taken"
        
        return "other"
                
    except Exception as e:
        log.warning("Ошибка при проверке %s через веб-страницу: %s", username, e)
        return "other"


def check_all(basenames: list[str]) -> dict[str, dict[str, str]]:
    """
    Возвращает {basename: {"base": статус, "bot": статус, "_bot": статус}}.
    
    Логика:
    1. Сначала проверяем базовое имя (без суффиксов)
    2. Если базовое имя свободно - проверяем варианты с суффиксами
    3. Если базовое имя занято - варианты не проверяем (сразу заняты)
    """
    results: dict[str, dict[str, str]] = {b: {} for b in basenames}
    import time

    for basename in basenames:
        # Сначала проверяем базовое имя
        base_status = check_exists(basename)
        results[basename]["base"] = base_status
        time.sleep(REQUEST_DELAY)
        
        # Если базовое имя свободно, проверяем варианты с суффиксами
        if base_status == "free":
            for suffix in ("bot", "_bot"):
                username = f"{basename}{suffix}"
                status = check_exists(username)
                results[basename][suffix] = status
                time.sleep(REQUEST_DELAY)
        else:
            # Если базовое имя занято, варианты тоже считаем занятыми
            results[basename]["bot"] = "taken"
            results[basename]["_bot"] = "taken"

    return results


STATUS_BULLET = {"free": "○", "taken": "●", "other": "⚠"}
STATUS_LABEL = {"free": "free", "taken": "taken", "other": "error"}


def build_report(basenames: list[str], results: dict[str, dict[str, str]]) -> list[str]:
    """
    Строит отчёт и режет его на список сообщений (с учётом лимита длины).
    """
    free_count = taken_count = other_count = 0
    free_usernames: list[str] = []
    free_basenames: list[str] = []

    group_blocks: list[str] = []
    for basename in basenames:
        base_status = results[basename].get("base", "other")
        lines = [escape_md(f"@{basename}")]
        
        # Показываем статус базового имени
        base_bullet = STATUS_BULLET[base_status]
        base_label = STATUS_LABEL[base_status]
        lines.append(f"{base_bullet} `{escape_code('@' + basename)}` {base_label} (базовое)")
        
        if base_status == "free":
            free_basenames.append(basename)
            # Если базовое свободно, проверяем варианты
            for suffix in ("bot", "_bot"):
                status = results[basename].get(suffix, "other")
                username = f"{basename}{suffix}"
                bullet = STATUS_BULLET[status]
                label = STATUS_LABEL[status]
                lines.append(f"{bullet} `{escape_code('@' + username)}` {label}")

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
            lines.append(f"● `{escape_code('@' + basename + 'bot')}` taken (базовое занято)")
            lines.append(f"● `{escape_code('@' + basename + '_bot')}` taken (базовое занято)")
            
        group_blocks.append("\n".join(lines))

    summary = (
        f"○ free {free_count}  ● taken {taken_count} · other {other_count}"
    )
    separator = "──────────────"

    header = f"*valid отчёт*\n\n{escape_md(summary)}\n\n{separator}"

    footer_lines = [separator, "", "*свободные базовые имена*"]
    if free_basenames:
        for u in free_basenames:
            footer_lines.append(f"`{escape_code('@' + u)}`")
    else:
        footer_lines.append(escape_md("свободных базовых имён нет"))
    
    footer_lines.extend(["", "*свободные варианты с bot*"])
    if free_usernames:
        for u in free_usernames:
            footer_lines.append(f"`{escape_code('@' + u)}`")
    else:
        footer_lines.append(escape_md("свободных вариантов нет"))
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

    status_msg = await update.message.reply_text(
        f"Проверяю {len(basenames)} базовых имён, подожди немного…"
    )

    # Запускаем синхронную проверку в отдельном потоке
    loop = asyncio.get_event_loop()
    results = await loop.run_in_executor(None, check_all, basenames)
    messages = build_report(basenames, results)

    await status_msg.edit_text(messages[0], parse_mode=ParseMode.MARKDOWN_V2)
    for msg in messages[1:]:
        await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN_V2)


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
