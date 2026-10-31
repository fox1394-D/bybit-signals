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

# При ручном запуске GitHub Actions выполняется тест Telegram.
MANUAL_RUN = os.getenv("MANUAL_RUN", "false").lower() == "true"

BINANCE_URL = "https://data-api.binance.vision/api/v3/klines"
TELEGRAM_URL = "https://api.telegram.org/bot{}/sendMessage"


# ==============================
# ПОЛУЧЕНИЕ ДАННЫХ BINANCE
# ==============================

def get_klines(symbol):

    params = {
        "symbol": symbol,
        "interval": INTERVAL,
        "limit": LIMIT
    }

    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json"
    }

    response = requests.get(
        BINANCE_URL,
        params=params,
        headers=headers,
        timeout=20
    )

    print(
        f"{symbol}: HTTP {response.status_code}",
        flush=True
    )

    if response.status_code != 200:
        print(
            "Ответ Binance:",
            response.text[:2000],
            flush=True
        )
        response.raise_for_status()

    candles = response.json()

    if not isinstance(candles, list) or not candles:
        raise Exception(
            f"Binance не вернул свечи для {symbol}: {candles}"
        )

    df = pd.DataFrame(
        candles,
        columns=[
            "timestamp",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "close_time",
            "quote_volume",
            "trades",
            "taker_buy_volume",
            "taker_buy_quote_volume",
            "ignore"
        ]
    )

    df["timestamp"] = pd.to_numeric(df["timestamp"])

    df["timestamp"] = pd.to_datetime(
        df["timestamp"],
        unit="ms",
        utc=True
    )

    for column in ["open", "high", "low", "close", "volume"]:
        df[column] = pd.to_numeric(df[column])

    df = df.sort_values("timestamp").reset_index(drop=True)

    # Исключаем последнюю незакрытую свечу.
    df = df.iloc[:-1].copy()

    if len(df) < max(RSI_PERIOD, EMA_PERIOD) + 2:
        raise Exception(
            f"Недостаточно свечей для {symbol}"
        )

    return df


# =============================
