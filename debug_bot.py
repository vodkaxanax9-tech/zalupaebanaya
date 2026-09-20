"""
Тестовый скрипт для диагностики проблем с ботом
"""
import os
import requests
import sys

# Fix encoding for Windows
if sys.platform == "win32":
    import codecs
    sys.stdout = codecs.getwriter("utf-8")(sys.stdout.buffer, "strict")

BOT_TOKEN = os.environ.get("BOT_TOKEN", "8770957416:AAHSjDJ42QfsA5ofKR1T6gzj-Q3ARGK940o")

print("=== Диагностика бота ===")
print(f"BOT_TOKEN: {BOT_TOKEN[:20]}..." if BOT_TOKEN else "BOT_TOKEN: None")

# 1. Проверка токена
print("\n1. Проверка токена...")
try:
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getMe"
    response = requests.get(url, timeout=10)
    data = response.json()
    
    if data.get("ok"):
        bot_info = data.get("result", {})
        print(f"[OK] Токен валиден")
        print(f"   Бот: @{bot_info.get('username', 'unknown')}")
        print(f"   ID: {bot_info.get('id', 'unknown')}")
    else:
        print(f"[ERROR] Токен невалиден: {data.get('description', 'Unknown error')}")
except Exception as e:
    print(f"[ERROR] Ошибка проверки токена: {e}")

# 2. Проверка webhook
print("\n2. Проверка webhook...")
try:
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getWebhookInfo"
    response = requests.get(url, timeout=10)
    data = response.json()
    
    if data.get("ok"):
        webhook_info = data.get("result", {})
        webhook_url = webhook_info.get("url", "")
        if webhook_url:
            print(f"[WARNING] Webhook установлен: {webhook_url}")
            print("   Это может мешать polling режиму")
        else:
            print(f"[OK] Webhook не установлен (хорошо для polling)")
    else:
        print(f"[ERROR] Ошибка проверки webhook: {data.get('description', 'Unknown error')}")
except Exception as e:
    print(f"[ERROR] Ошибка проверки webhook: {e}")

# 3. Удаление webhook (если есть)
print("\n3. Удаление webhook...")
try:
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/deleteWebhook"
    response = requests.get(url, timeout=10)
    data = response.json()
    
    if data.get("ok"):
        print("[OK] Webhook удален")
    else:
        print(f"[WARNING] Ошибка удаления webhook: {data.get('description', 'Unknown error')}")
except Exception as e:
    print(f"[ERROR] Ошибка удаления webhook: {e}")

# 4. Проверка получения обновлений
print("\n4. Проверка получения обновлений...")
try:
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
    response = requests.get(url, timeout=10)
    data = response.json()
    
    if data.get("ok"):
        updates = data.get("result", [])
        print(f"[OK] Получено {len(updates)} обновлений")
        if updates:
            print("   Последние обновления:")
            for update in updates[-3:]:  # Последние 3
                print(f"   - Update ID: {update.get('update_id')}")
    else:
        print(f"[ERROR] Ошибка получения обновлений: {data.get('description', 'Unknown error')}")
except Exception as e:
    print(f"[ERROR] Ошибка получения обновлений: {e}")

print("\n=== Рекомендации ===")
print("1. Если webhook был установлен - бот должен работать в webhook режиме")
print("2. Если webhook не установлен - бот должен работать в polling режиме")
print("3. Убедитесь что Railway переменная BOT_TOKEN установлена правильно")
print("4. Проверьте логи Railway на наличие ошибок")
