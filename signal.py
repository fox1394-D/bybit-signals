import requests
import pandas as pd
import numpy as np
import os
from datetime import datetime

SYMBOLS = ["BTCUSDT", "ETHUSDT"]
INTERVAL = "15m"
LIMIT = 100

RSI_PERIOD = 14
EMA_PERIOD = 50
RSI_OVERSOLD = 30

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

def get_klines(symbol, interval, limit):
    url = "https://api.binance.com/api/v3/klines"
    params = {
        "symbol": symbol,
        "interval": interval,
        "limit": limit
    }
    headers = {"User-Agent": "Mozilla/5.0"}
    
    response = requests.get(url, params=params, headers=headers, timeout=15)
    
    print(f"=== {symbol} ===")
    print(f"Status code: {response.status_code}")
    
    if response.status_code != 200:
        print(response.text[:400])
        raise Exception(f"Binance вернул ошибку {response.status_code}")
    
    data = response.json()
    
    df = pd.DataFrame(data, columns=[
        "timestamp", "open", "high", "low", "close", "volume",
        "close_time", "quote_volume", "trades", "taker_buy_base",
        "taker_buy_quote", "ignore"
    ])
    
    df["close"] = df["close"].astype(float)
    return df

def calculate_rsi(series, period=14):
    delta = series.diff()
    gain = delta.where(delta > 0, 0)
    loss = -delta.where(delta < 0, 0)
    avg_gain = gain.ewm(alpha=1/period, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1/period, min_periods=period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def calculate_ema(series, period):
    return series.ewm(span=period, adjust=False).mean()

def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML"
    }
    requests.post(url, json=payload, timeout=10)

def check_signals():
    messages = []
    
    for symbol in SYMBOLS:
        try:
            df = get_klines(symbol, INTERVAL, LIMIT)
            df["rsi"] = calculate_rsi(df["close"], RSI_PERIOD)
            df["ema"] = calculate_ema(df["close"], EMA_PERIOD)
            
            last = df.iloc[-1]
            prev = df.iloc[-2]
            
            price = last["close"]
            rsi = last["rsi"]
            ema = last["ema"]
            
            if prev["rsi"] >= RSI_OVERSOLD and rsi < RSI_OVERSOLD and price > ema:
                msg = (
                    f"<b>{symbol}</b> | {INTERVAL}\n"
                    f"🟢 LONG (RSI oversold + выше EMA)\n"
                    f"Цена: <b>{price}</b>\n"
                    f"RSI: {rsi:.1f}\n"
                    f"EMA{EMA_PERIOD}: {ema:.1f}\n"
                    f"Время: {datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC"
                )
                messages.append(msg)
                
        except Exception as e:
            print(f"Ошибка по {symbol}: {e}")
    
    for msg in messages:
        send_telegram(msg)
        print("Сигнал отправлен")
    
    if not messages:
        print("Сигналов нет")

if __name__ == "__main__":
    check_signals()
