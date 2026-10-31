import os
from datetime import datetime, timezone

import pandas as pd
import requests


# Настройки стратегии
SYMBOLS = ["BTCUSDT", "ETHUSDT"]
INTERVAL = "15m"  # Для Bybit будет преобразован в "15"
LIMIT = 100

RSI_PERIOD = 14
EMA_PERIOD = 50
RSI_OVERSOLD = 30

BYBIT_URL = "https://api.bybit.com/v5/market/kline"

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


def bybit_interval(interval):
    """Преобразует обозначение таймфрейма в формат Bybit API."""
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
        "1M": "M",
    }
    if interval not in mapping:
        raise ValueError(f"Неподдерживаемый таймфрейм: {interval}")
    return mapping[interval]


def get_klines(symbol, interval, limit):
    """Получает свечи линейных USDT-фьючерсов с Bybit."""
    params = {
        "category": "linear",
        "symbol": symbol,
        "interval": bybit_interval(interval),
        "limit": limit,
    }

    response = requests.get(BYBIT_URL, params=params, timeout=20)

print(f"=== {symbol} ===")
print("Источник: Bybit")
print(f"HTTP status: {response.status_code}")

if response.status_code != 200:
    print("Текст ошибки Bybit:")
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
            f"Bybit API error {data.get('retCode')}: {data.get('retMsg')}"
        )

    candles = data.get("result", {}).get("list", [])
    if len(candles) < max(RSI_PERIOD, EMA_PERIOD) + 2:
        raise RuntimeError(
            f"Bybit вернул недостаточно свечей: {len(candles)}"
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
            "turnover",
        ],
    )

    # Bybit возвращает свечи от новых к старым — разворачиваем хронологически.
    df = df.iloc[::-1].reset_index(drop=True)

    for column in ["open", "high", "low", "close", "volume", "turnover"]:
        df[column] = pd.to_numeric(df[column], errors="coerce")

    df["timestamp"] = pd.to_datetime(
        pd.to_numeric(df["timestamp"]), unit="ms", utc=True
    )

    df = df.dropna(subset=["close"]).reset_index(drop=True)

    # Последняя свеча может быть ещё не закрыта. Не используем её в сигнале.
    if len(df) > 1:
        df = df.iloc[:-1].reset_index(drop=True)

    if len(df) < max(RSI_PERIOD, EMA_PERIOD) + 2:
        raise RuntimeError("Недостаточно закрытых свечей для расчёта индикаторов")

    return df


def calculate_rsi(series, period=14):
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)

    avg_gain = gain.ewm(
        alpha=1 / period, min_periods=period, adjust=False
    ).mean()
    avg_loss = loss.ewm(
        alpha=1 / period, min_periods=period, adjust=False
    ).mean()

    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))

    # Обработка крайних случаев, когда цена только росла или только падала.
    rsi = rsi.mask((avg_loss == 0) & (avg_gain > 0), 100)
    rsi = rsi.mask((avg_gain == 0) & (avg_loss > 0), 0)
    return rsi


def calculate_ema(series, period):
    return series.ewm(span=period, adjust=False).mean()


def send_telegram(message):
    """Отправляет сообщение и проверяет ответ Telegram."""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        raise RuntimeError(
            "Не заданы TELEGRAM_TOKEN или TELEGRAM_CHAT_ID в GitHub Secrets"
        )

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
    }

    response = requests.post(url, json=payload, timeout=20)
    response.raise_for_status()

    result = response.json()
    if not result.get("ok"):
        raise RuntimeError(f"Telegram API error: {result}")

    print("Telegram: сообщение успешно доставлено")


def check_signals():
    messages = []

    for symbol in SYMBOLS:
        try:
            df = get_klines(symbol, INTERVAL, LIMIT)

            df["rsi"] = calculate_rsi(df["close"], RSI_PERIOD)
            df["ema"] = calculate_ema(df["close"], EMA_PERIOD)

            last = df.iloc[-1]
            prev = df.iloc[-2]

            price = float(last["close"])
            rsi = float(last["rsi"])
            ema = float(last["ema"])

            print(
                f"Последняя закрытая свеча: {last['timestamp']}; "
                f"Цена: {price}; RSI: {rsi:.2f}; EMA{EMA_PERIOD}: {ema:.2f}"
            )

            # Сохраняем исходное условие LONG без изменения торговой логики.
            if (
                prev["rsi"] >= RSI_OVERSOLD
                and rsi < RSI_OVERSOLD
                and price > ema
            ):
                msg = (
                    f"<b>{symbol}</b> | {INTERVAL}\n"
                    f"🟢 LONG (RSI пересёк уровень 30 вниз + цена выше EMA)\n"
                    f"Цена: <b>{price}</b>\n"
                    f"RSI: {rsi:.1f}\n"
                    f"EMA{EMA_PERIOD}: {ema:.1f}\n"
                    f"Время: {last['timestamp'].strftime('%Y-%m-%d %H:%M')} UTC"
                )
                messages.append(msg)

        except Exception as error:
            print(f"Ошибка по {symbol}: {error}")

    for message in messages:
        try:
            send_telegram(message)
        except Exception as error:
            print(f"Не удалось отправить сообщение в Telegram: {error}")
            raise

    if not messages:
        print("Сигналов нет")


if __name__ == "__main__":
    check_signals()
