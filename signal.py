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

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

MANUAL_RUN = os.getenv("MANUAL_RUN", "false").lower() == "true"

BINANCE_URL = "https://data-api.binance.vision/api/v3/klines"
TELEGRAM_URL = "https://api.telegram.org/bot{}/sendMessage"


# ==========================================
# ПОЛУЧЕНИЕ ДАННЫХ BINANCE
# ==========================================

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
        print("Ответ Binance:", response.text[:2000], flush=True)
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


# ==========================================
# РАСЧЁТ RSI
# ==========================================

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

    return 100 - (100 / (1 + rs))


# ==========================================
# РАСЧЁТ EMA
# ==========================================

def calculate_ema(series, period=50):

    return series.ewm(
        span=period,
        adjust=False
    ).mean()


# ==========================================
# ОТПРАВКА СООБЩЕНИЙ В TELEGRAM
# ==========================================

def send_telegram(message):

    if not TELEGRAM_TOKEN:
        raise Exception(
            "Не задан TELEGRAM_TOKEN в GitHub Secrets"
        )

    if not TELEGRAM_CHAT_ID:
        raise Exception(
            "Не задан TELEGRAM_CHAT_ID в GitHub Secrets"
        )

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

    print(
        "HTTP статус Telegram:",
        response.status_code,
        flush=True
    )

    print(
        "Ответ Telegram API:",
        response.text,
        flush=True
    )

    try:
        result = response.json()
    except ValueError:
        raise Exception(
            f"Telegram вернул некорректный ответ: {response.text}"
        )

    if response.status_code != 200 or not result.get("ok"):

        error_code = result.get("error_code", "неизвестен")

        description = result.get(
            "description",
            "Описание ошибки отсутствует"
        )

        raise Exception(
            f"Ошибка Telegram API. Код: {error_code}. "
            f"Причина: {description}"
        )

    print(
        "Сообщение успешно отправлено в Telegram",
        flush=True
    )


# ==========================================
# ПРОВЕРКА ТОРГОВЫХ СИГНАЛОВ
# ==========================================

def check_signals():

    signals = []
    errors = []

    for symbol in SYMBOLS:

        try:

            print()
            print(
                f"Проверяем {symbol}...",
                flush=True
            )

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
                f"EMA={current['EMA']:.4f}",
                flush=True
            )

            # Условие LONG:
            # Предыдущий RSI был не ниже 30.
            # Текущий RSI опустился ниже 30.
            # Цена находится выше EMA 50.

            long_signal = (
                previous["RSI"] >= RSI_OVERSOLD
                and current["RSI"] < RSI_OVERSOLD
                and current["close"] > current["EMA"]
            )

            if long_signal:

                message_lines = [
                    "🟢 <b>СИГНАЛ LONG</b>",
                    "",
                    "Биржа данных: Binance Spot",
                    f"Монета: <b>{symbol}</b>",
                    f"Таймфрейм: {INTERVAL}",
                    f"Цена: <b>{current['close']}</b>",
                    f"RSI: <b>{current['RSI']:.2f}</b>",
                    f"EMA {EMA_PERIOD}: <b>{current['EMA']:.4f}</b>",
                    (
                        "Время свечи: "
                        + current["timestamp"].strftime(
                            "%d.%m.%Y %H:%M UTC"
                        )
                    )
                ]

                signals.append(
                    "\n".join(message_lines)
                )

        except Exception as error:

            error_message = f"{symbol}: {str(error)}"

            errors.append(error_message)

            print(
                "ОШИБКА:",
                error_message,
                flush=True
            )

    # Отправляем найденные сигналы.

    for signal in signals:
        send_telegram(signal)

    if signals:

        print()
        print(
            f"Найдено сигналов: {len(signals)}",
            flush=True
        )

    elif errors:

        print()
        print(
            "Проверка завершилась с ошибками:",
            flush=True
        )

        for error in errors:
            print(error, flush=True)

        raise Exception(
            "Не удалось проверить все торговые инструменты"
        )

    else:

        print()
        print(
            "Сигналов нет.",
            flush=True
        )


# ==========================================
# ГЛАВНЫЙ ЗАПУСК ПРОГРАММЫ
# ==========================================

if __name__ == "__main__":

    print("=" * 50, flush=True)

    print(
        "ЗАПУСК КРИПТОСИГНАЛОВ BINANCE",
        flush=True
    )

    current_time = datetime.now(timezone.utc)

    print(
        "Время запуска:",
        current_time.strftime("%d.%m.%Y %H:%M:%S UTC"),
        flush=True
    )

    print("=" * 50, flush=True)

    try:

        # Тест Telegram только при ручном запуске.

        if MANUAL_RUN:

            print(
                "Ручной запуск: проверяем отправку в Telegram...",
                flush=True
            )

            test_message = (
                "🧪 <b>ТЕСТ TELEGRAM УСПЕШЕН</b>\n\n"
                "Бот криптосигналов подключён к Telegram.\n"
                "От
