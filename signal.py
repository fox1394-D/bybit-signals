import os
import time
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

BYBIT_URL = "https://api.bybit.com/v5/market/kline"
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
            "high",
            "low",
            "close",
            "volume",
            "turnover"
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

    # Bybit возвращает свечи от новых к старым.
    df = df.sort_values("timestamp").reset_index(drop=True)

    # Исключаем последнюю незакрытую свечу.
    df = df.iloc[:-1].copy()

    if len(df) < max(RSI_PERIOD, EMA_PERIOD) + 2:
        raise Exception(f"Недостаточно свечей для {symbol}")

    return df


# ==============================
# РАСЧЁТ RSI
# ==============================

def calculate_rsi(series, period=14):

    delta = series.diff()

    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(
        alpha=1 / period,
        min_periods=period,
        adjust=False
    ).mean()

    avg_loss = loss.ewm(
        alpha=1 / period,
        min_periods=period,
        adjust=False
    ).mean()

    rs = avg_gain / avg_loss

    rsi = 100 - (100 / (1 + rs))

    return rsi


# ==============================
# РАСЧЁТ EMA
# ==============================

def calculate_ema(series, period=50):

    return series.ewm(
        span=period,
        adjust=False
    ).mean()


# ==============================
# ОТПРАВКА В TELEGRAM
# ==============================

def send_telegram(message):

    if not TELEGRAM_TOKEN:
        raise Exception("Не задан TELEGRAM_TOKEN в GitHub Secrets")

    if not TELEGRAM_CHAT_ID:
        raise Exception("Не задан TELEGRAM_CHAT_ID в GitHub Secrets")

    url = TELEGRAM_URL.format(TELEGRAM_TOKEN)

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML"
    }

    response = requests.post(
        url,
        json=payload,
        timeout=20
    )

    response.raise_for_status()

    result = response.json()

    if not result.get("ok"):
        raise Exception(f"Ошибка Telegram: {result}")

    print("Сообщение успешно отправлено в Telegram")


# ==============================
# ПРОВЕРКА СИГНАЛОВ
# ==============================

def check_signals():

    signals = []
    errors = []

    for symbol in SYMBOLS:

        try:
            print(f"\nПроверяем {symbol}...")

            df = get_klines(symbol)

            df["RSI"] = calculate_rsi(
                df["close"],
                RSI_PERIOD
            )

            df["EMA"] = calculate_ema(
                df["close"],
                EMA_PERIOD
            )

            previous = df.iloc[-2]
            current = df.iloc[-1]

            print(
                f"{symbol}: "
                f"Цена={current['close']:.4f}, "
                f"RSI={current['RSI']:.2f}, "
                f"EMA={current['EMA']:.4f}"
            )

            # Условие LONG:
            # Предыдущий RSI был не ниже 30,
            # текущий RSI опустился ниже 30,
            # цена находится выше EMA 50.

            long_signal = (
                previous["RSI"] >= RSI_OVERSOLD
                and current["RSI"] < RSI_OVERSOLD
                and current["close"] > current["EMA"]
            )

            if long_signal:

                message = (
                    "🟢 <b>СИГНАЛ LONG</b>\n\n"
                    f"Монета: <b>{symbol}</b>\n"
                    f"Таймфрейм: {INTERVAL}\n"
                    f"Цена: <b>{current['close']}</b>\n"
                    f"RSI: <b>{current['RSI']:.2f}</b>\n"
                    f"EMA {EMA_PERIOD}: <b>{current['EMA']:.4f}</b>\n"
                    f"Время свечи: {current['timestamp'].strftime('%d.%m.%Y %H:%M UTC')}"
                )

                signals.append(message)

        except Exception as error:

            error_message = f"{symbol}: {str(error)}"

            errors.append(error_message)

            print("ОШИБКА:", error_message)

    # Отправляем найденные сигналы.

    for signal in signals:

        send_telegram(signal)

    if signals:
        print(f"\nНайдено сигналов: {len(signals)}")

    elif errors:
        print("\nСигналы не проверены из-за ошибок:")
        for error in errors:
            print(error)

    else:
        print("\nСигналов нет.")


# ==============================
# ЗАПУСК
# ==============================

if __name__ == "__main__":

    print("=" * 50)
    print("ЗАПУСК КРИПТОСИГНАЛОВ BYBIT")
    print(
        "Время запуска:",
        datetime.now(timezone.utc).strftime("%d.%m.%Y %H:%M:%S UTC")
    )
    print("=" * 50)

    try:
        check_signals()

    except Exception as error:
        print("КРИТИЧЕСКАЯ ОШИБКА:", error)
        raise
