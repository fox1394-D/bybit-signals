import os
import requests
import pandas as pd
from datetime import datetime, timezone

# ==============================
# НАСТРОЙКИ
# ==============================

SYMBOLS = ["BTCUSDT", "ETHUSDT"]

INTERVAL = "15m"
LIMIT = 100

RSI_PERIOD = 14
EMA_PERIOD = 50

RSI_OVERSOLD = 30

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

BYBIT_URL = "https://api.bytick.com/v5/market/kline"
TELEGRAM_URL = "https://api.telegram.org/bot{}/sendMessage"


# ==============================
# ПОЛУЧЕНИЕ ДАННЫХ BYBIT
# ==============================

def get_klines(symbol):

    params = {
        "category": "linear",
        "symbol": symbol,
        "interval": INTERVAL,
        "limit": LIMIT
    }

    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json"
    }

    response = requests.get(
        BYBIT_URL,
        params=params,
        headers=headers,
        timeout=20
    )

    print(f"{symbol}: HTTP {response.status_code}")

    if response.status_code != 200:
        print("Ответ Bybit:", response.text[:2000])
        print("Заголовки:", {
            "server": response.headers.get("server"),
            "cf-ray": response.headers.get("cf-ray"),
            "x-bapi-limit-status": response.headers.get("x-bapi-limit-status")
        })
        response.raise_for_status()

    data = response.json()

    if data.get("retCode") != 0:
        raise Exception(
            f"Ошибка Bybit: {data.get('retCode')} - {data.get('retMsg')}"
        )

    candles = data.get("result", {}).get("list", [])

    if not candles:
        raise Exception(f"Bybit не вернул свечи для {symbol}")

    df = pd.DataFrame(
        candles,
        columns=[
            "timestamp",
            "open",
            "
