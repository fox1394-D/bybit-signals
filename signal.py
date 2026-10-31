import os
import json
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
RSI_OVERBOUGHT = 70

STATE_FILE = "signals_state.json"

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

MANUAL_RUN = os.getenv("MANUAL_RUN", "false").lower() == "true"

BINANCE_URL = "https://data-api.binance.vision/api/v3/klines"
TELEGRAM_URL = "https://api.telegram.org/bot{}/sendMessage"


# ==========================================
# ЗАГРУЗКА И СОХРАНЕНИЕ ИСТОРИИ СИГНАЛОВ
# ==========================================

def load_signal_history():

    if not os.path.exists(STATE_FILE):
        print("Файл истории сигналов пока отсутствует. Создаём новую историю.", flush=True)
        return set()

    try:
        with open(STATE_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)

        if not isinstance(data, list):
            raise Exception("Неверный формат файла истории сигналов")

        return set(data)

    except Exception as error:
        raise Exception(f"Не удалось прочитать историю сигналов: {error}")


def save_signal_history(history):

    temporary_file = STATE_FILE + ".tmp"

    with open(temporary_file, "w", encoding="utf-8") as file:
        json.dump(sorted(history), file, ensure_ascii=False, indent=2)

    os.replace(temporary_file, STATE_FILE)

    print(
        f"История сигналов сохранена. Записей: {len(history)}",
        flush=True
    )


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

    print(f"{symbol}: HTTP {response.status_code}", flush=True)

    if response.status_code != 200:
        print("Ответ Binance:", response.text[:2000], flush=True)
        response.raise_for_status()

    candles = response.json()

    if not isinstance(candles, list) or not candles:
        raise Exception(f"Binance не вернул свечи для {symbol}: {candles}")

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
        raise Exception(f"Недостаточно свечей для {symbol}")

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

    print("HTTP статус Telegram:", response.status_code, flush=True)
    print("Ответ Telegram API:", response.text, flush=True)

    try:
        result = response.json()
    except ValueError:
        raise Exception(f"Некорректный ответ Telegram: {response.text}")

    if response.status_code != 200 or not result.get("ok"):

        error_code = result.get("error_code", "неизвестен")
        description = result.get("description", "Описание отсутствует")

        raise Exception(
            f"Ошибка Telegram API. Код: {error_code}. Причина: {description}"
        )

    print("Сообщение успешно отправлено в Telegram", flush=True)


# ==========================================
# ПРОВЕРКА ТОРГОВЫХ СИГНАЛОВ
# ==========================================

def check_signals():

    signal_history = load_signal_history()

    signals = []
    errors = []

    for symbol in SYMBOLS:

        try:

            print()
            print(f"Проверяем {symbol}...", flush=True)

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
                f"{symbol}: Цена={current['close']:.4f}, "
                f"RSI={current['RSI']:.2f}, "
                f"EMA={current['EMA']:.4f}",
                flush=True
            )

            # LONG:
            # RSI пересекает уровень 30 сверху вниз.
            # Цена находится выше EMA 50.

            long_signal = (
                previous["RSI"] >= RSI_OVERSOLD
                and current["RSI"] < RSI_OVERSOLD
                and current["close"] > current["EMA"]
            )

            # SHORT:
            # RSI пересекает уровень 70 снизу вверх.
            # Цена находится ниже EMA 50.

            short_signal = (
                previous["RSI"] <= RSI_OVERBOUGHT
                and current["RSI"] > RSI_OVERBOUGHT
                and current["close"] < current["EMA"]
            )

            candle_time = current["timestamp"].strftime("%Y-%m-%d %H:%M UTC")

            if long_signal:
                direction = "LONG"
            elif short_signal:
                direction = "SHORT"
            else:
                direction = None

            if direction is None:
                print(f"{symbol}: торгового сигнала нет.", flush=True)
                continue

            # Уникальный ключ: монета + направление + время свечи.
            # Он не позволяет повторно отправить тот же сигнал.

            signal_key = (
                f"{symbol}|{direction}|"
                f"{current['timestamp'].strftime('%Y-%m-%dT%H:%M:%S')}"
            )

            if signal_key in signal_history:

                print(
                    f"{symbol}: {direction} уже отправлялся. "
                    "Повторное сообщение пропускаем.",
                    flush=True
                )

                continue

            if direction == "LONG":

                message_lines = [
                    "🟢 <b>СИГНАЛ LONG</b>",
                    "",
                    "Источник данных: Binance Spot",
                    f"Монета: <b>{symbol}</b>",
                    f"Таймфрейм: {INTERVAL}",
                    f"Цена: <b>{current['close']}</b>",
                    f"RSI: <b>{current['RSI']:.2f}</b>",
                    f"EMA {EMA_PERIOD}: <b>{current['EMA']:.4f}</b>",
                    f"Время свечи: {candle_time}"
                ]

            else:

                message_lines = [
                    "🔴 <b>СИГНАЛ SHORT</b>",
                    "",
                    "Источник данных: Binance Spot",
                    f"Монета: <b>{symbol}</b>",
                    f"Таймфрейм: {INTERVAL}",
                    f"Цена: <b>{current['close']}</b>",
                    f"RSI: <b>{current['RSI']:.2f}</b>",
                    f"EMA {EMA_PERIOD}: <b>{current['EMA']:.4f}</b>",
                    f"Время свечи: {candle_time}"
                ]

            signals.append({
                "key": signal_key,
                "message": chr(10).join(message_lines),
                "symbol": symbol,
                "direction": direction
            })

        except Exception as error:

            error_message = f"{symbol}: {str(error)}"
            errors.append(error_message)

            print("ОШИБКА:", error_message, flush=True)

    # Отправляем только новые сигналы.
    # Записываем сигнал в историю только после успешной отправки.

    sent_count = 0

    for signal in signals:

        send_telegram(signal["message"])

        signal_history.add(signal["key"])
        save_signal_history(signal_history)

        sent_count += 1

        print(
            f"Отправлен новый сигнал: "
            f"{signal['symbol']} {signal['direction']}",
            flush=True
        )

    print()

    if errors:

        print("Проверка завершилась с ошибками:", flush=True)

        for error in errors:
            print(error, flush=True)

        raise Exception("Не удалось проверить все торговые инструменты")

    if sent_count:
        print(f"Новых сигналов отправлено: {sent_count}", flush=True)
    else:
        print("Новых сигналов нет.", flush=True)


# ==========================================
# ГЛАВНЫЙ ЗАПУСК ПРОГРАММЫ
# ==========================================

if __name__ == "__main__":

    print("=" * 50, flush=True)
    print("ЗАПУСК КРИПТОСИГНАЛОВ BINANCE", flush=True)

    current_time = datetime.now(timezone.utc)

    print(
        "Время запуска: " + current_time.strftime("%d.%m.%Y %H:%M:%S UTC"),
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

            test_message_lines = [
                "🧪 <b>ТЕСТ TELEGRAM УСПЕШЕН</b>",
                "",
                "Бот криптосигналов подключён к Telegram.",
                "Отправка сообщений работает.",
                "",
                "Источник данных: Binance Spot",
                "Проверяемые монеты: BTCUSDT, ETHUSDT",
                "Таймфрейм: 15 минут",
                "Сигналы: LONG и SHORT",
                "",
                "После теста начинается обычная проверка сигналов."
            ]

            test_message = chr(10).join(test_message_lines)

            send_telegram(test_message)

        check_signals()

        print()
        print("РАБОТА ПРОГРАММЫ ЗАВЕРШЕНА", flush=True)

    except Exception as error:

        print()
        print("КРИТИЧЕСКАЯ ОШИБКА:", str(error), flush=True)

        raise
