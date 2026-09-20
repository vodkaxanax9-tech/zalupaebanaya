"""
Health check script для Railway
"""
import os
import sys

# Проверка переменных окружения
required_vars = ["BOT_TOKEN"]
missing_vars = []

for var in required_vars:
    if not os.environ.get(var):
        missing_vars.append(var)

if missing_vars:
    print(f"ERROR: Missing environment variables: {', '.join(missing_vars)}")
    sys.exit(1)

print("OK: All required environment variables are set")
sys.exit(0)
