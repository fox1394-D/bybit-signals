import requests
import pandas as pd
import numpy as np
import os
from datetime import datetime

# ================== НАСТРОЙКИ ==================
SYMBOLS = ["BTCUSDT", "ETHUSDT"]
INTERVAL = "15"
LIMIT = 100

RSI_PERIOD = 14
EMA_PERIOD = 50
RSI_OVERSOLD = 30
# ===============================================

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

def get_klines(symbol, interval, limit):
    url = "https://api.bybit.com/v5/market/kline"
    params = {
        "category": "linear",
        "symbol": symbol,
        "interval": interval,
        "limit": limit
    }
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    
    response = requests.get(url, params=params, headers=headers, timeout=15)
    
    # Показываем, что реально вернул сервер
    print(f"=== {symbol} ===")
    print(f"Status code: {response.status_code}")
    print(f"Response text (first 300 chars): {response.text[:300]}")
    
    try:
        data = response.json()
    except Exception as e:
        raise Exception(f"Не JSON ответ. Ошибка: {e}")
    
    if data.get("retCode") != 0:
        raise Exception(f"Bybit error: {data.get('retMsg')}")
    
    klines = data["result"]["list"]
    klines = list(reversed(klines))
    
    df = pd.DataFrame(klines, columns=[
        "timestamp", "open", "high", "low", "close", "volume", "turnover"
    ])
    
    df["close"] = df["close"].astype(float)
    df["high"] = df["high"].astype(float)
    df["low"] = df["low"].astype(float)
    df["volume"] = df["volume"].astype(float)
    
    return df

def calculate_rsi(series, period=14):
    delta = series.diff()
    gain = delta.where(delta > 0, 0)
    loss = -delta.where(delta < 0, 0)
    
    avg_gain = gain.ewm(alpha=1/period, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1/period, min_periods=period).mean()
    
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

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
            
            signal = False
            signal_type = ""
            
            if prev["rsi"] >= RSI_OVERSOLD and rsi < RSI_OVERSOLD and price > ema:
                signal = True
                signal_type = "🟢 LONG (RSI oversold + выше EMA)"
            
            if signal:
                msg = (
                    f"<b>{symbol}</b> | {INTERVAL}m\n"
                    f"{signal_type}\n"
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
        print("Сигнал отправлен:", msg)
    
    if not messages:
        print("Сигналов нет")

if __name__ == "__main__":
    check_signals()
