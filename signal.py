import os
import requests
import pandas as pd
from datetime import datetime, timezone


# ==========================================
# НАСТРОЙКИ
# ==========================================

SYMBOLS = ["BTCUSDT", "ETHUSDT"]

INTERVAL = "15m"
LIMIT = 100

RSI_PERIOD = 14
EMA_PERIOD = 50
RSI_OVERSOLD = 30

BYBIT_URL = "https://api.bybit.com/v5/market/kline"

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


# ==========================================
# ТАЙМФРЕЙМ
# ==========================================

def bybit_interval(interval):

    mapping = {
        "1m": "1",
        "3m": "3",
        "5m": "5",
        "15m": "15",
        "30m": "30",
        "1h": "60",
        "2h": "120",
        "4h": "240",
        "6h": "360",
        "12h": "720",
        "1d": "D",
        "1w": "W",
        "1M": "M"
    }

    if interval not in mapping:
        raise ValueError(f"Неподдерживаемый таймфрейм: {interval}")

    return mapping[interval]


# ==========================================
# ПОЛУЧЕНИЕ СВЕЧЕЙ BYBIT
# ==========================================

def get_klines(symbol, interval, limit):

    params = {
        "category": "linear",
        "symbol": symbol,
        "interval": bybit_interval(interval),
        "limit": limit
    }

    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json"
    }

    print(f"\n=== {symbol} ===")
    print("Источник: Bybit")

    response = requests.get(
        BYBIT_URL,
        params=params,
        headers=headers,
        timeout=20
    )

    print(f"HTTP status: {response.status_code}")

    # Диагностика ошибок HTTP

    if response.status_code != 200:

        print("Текст ответа сервера:")
        print(response.text[:2000])

        print("Дополнительная информация:")

        for key in ["server", "cf-ray", "x-bapi-limit-status"]:
            if key in response.headers:
                print(f"{key}: {response.headers[key]}")

        raise Exception(
            f"Bybit вернул ошибку HTTP {response.status_code}"
        )

    data = response.json()

    if data.get("retCode") != 0:

        raise RuntimeError(
            f"Bybit API error: "
            f"{data.get('retCode')} - {data.get('retMsg')}"
        )

    candles = data.get("result", {}).get("list", [])

    if len(candles) < EMA_PERIOD + 2:

        raise RuntimeError(
            f"Недостаточно свечей: {len(candles)}"
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
            "turnover"
        ]
    )

    # Сортировка свечей от старых к новым

    df = df.iloc[::-1].reset_index(drop=True)

    # Преобразование числовых данных

    for column in [
        "open",
        "high",
        "low",
        "close",
        "volume",
        "turnover"
    ]:

        df[column] = pd.to_numeric(
            df[column],
            errors="coerce"
        )

    df["timestamp"] = pd.to_datetime(
        pd.to_numeric(df["timestamp"]),
        unit="ms",
        utc=True
    )

    df = df.dropna(subset=["close"]).reset_index(drop=True)

    # Исключаем незакрытую свечу

    df = df.iloc[:-1].reset_index(drop=True)

    if len(df) < EMA_PERIOD + 2:

        raise RuntimeError(
            "Недостаточно закрытых свечей"
        )

    print(f"Получено закрытых свечей: {len(df)}")

    return df


# ==========================================
# РАСЧЁТ RSI
# ==========================================

def calculate_rsi(series, period=14):

    delta = series.diff()

    gain = delta.where(delta > 0, 0)
    loss = -delta.where(delta < 0, 0)

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

    rsi = rsi.mask(
        (avg_loss == 0) & (avg_gain > 0),
        100
    )

    rsi = rsi.mask(
        (avg_gain == 0) & (avg_loss > 0),
        0
    )

    return rsi


# ==========================================
# РАСЧЁТ EMA
# ==========================================

def calculate_ema(series, period):

    return series.ewm(
        span=period,
        adjust=False
    ).mean()


# ==========================================
# ОТПРАВКА В TELEGRAM
# ==========================================

def send_telegram(message):

    if not TELEGRAM_TOKEN:

        raise RuntimeError(
            "Не задан TELEGRAM_TOKEN в GitHub Secrets"
        )

    if not TELEGRAM_CHAT_ID:

        raise RuntimeError(
            "Не задан TELEGRAM_CHAT_ID в GitHub Secrets"
        )

    url = (
        f"https://api.telegram.org/"
        f"bot{TELEGRAM_TOKEN}/sendMessage"
    )

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

        raise RuntimeError(
            f"Ошибка Telegram: {result}"
        )

    print("Telegram: сообщение успешно отправлено")


# ==========================================
# ПРОВЕРКА ТОРГОВЫХ СИГНАЛОВ
# ==========================================

def check_signals():

    messages = []

    for symbol in SYMBOLS:

        try:

            df = get_klines(
                symbol,
                INTERVAL,
                LIMIT
            )

            df["rsi"] = calculate_rsi(
                df["close"],
                RSI_PERIOD
            )

            df["ema"] = calculate_ema(
                df["close"],
                EMA_PERIOD
            )

            last = df.iloc[-1]
            prev = df.iloc[-2]

            price = float(last["close"])
            rsi = float(last["rsi"])
            ema = float(last["ema"])

            prev_rsi = float(prev["rsi"])

            print(
                f"Цена: {price}\n"
                f"RSI: {rsi:.2f}\n"
                f"Предыдущий RSI: {prev_rsi:.2f}\n"
                f"EMA{EMA_PERIOD}: {ema:.2f}"
            )

            # УСЛОВИЕ LONG
            # RSI пересёк уровень 30 сверху вниз
            # Цена находится выше EMA50

            if (
                prev_rsi >= RSI_OVERSOLD
                and rsi < RSI_OVERSOLD
                and price > ema
            ):

                msg = (
                    f"<b>{symbol}</b> | {INTERVAL}\n"
                    f"🟢 LONG\n"
                    f"RSI пересёк уровень 30 сверху вниз\n"
                    f"Цена выше EMA{EMA_PERIOD}\n\n"
                    f"Цена: <b>{price}</b>\n"
                    f"RSI: {rsi:.2f}\n"
                    f"EMA{EMA_PERIOD}: {ema:.2f}\n"
                    f"Время: "
                    f"{last['timestamp'].strftime('%Y-%m-%d %H:%M')} UTC"
                )

                messages.append(msg)

                print("Обнаружен сигнал LONG")

            else:

                print("Условие LONG не выполнено")

        except Exception as error:

            print(
                f"Ошибка по {symbol}: {error}"
            )

    # Отправка найденных сигналов

    for message in messages:

        send_telegram(message)

    if not messages:

        print("\nСигналов нет")


# ==========================================
# ЗАПУСК
# ==========================================

if __name__ == "__main__":

    print("================================")
    print("BYBIT CRYPTO SIGNALS")
    print("================================")

    print(
        "Время запуска:",
        datetime.now(timezone.utc).strftime(
            "%Y-%m-%d %H:%M:%S UTC"
        )
    )

    check_signals()

    print("================================")
    print("Проверка завершена")
    print("================================")
```
