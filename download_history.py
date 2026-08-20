"""Scarica ~6 mesi di storico M15 da Twelve Data per le 6 coppie di Segnali,
in blocchi da 45 giorni (restano ben sotto il limite per chiamata e il tetto
giornaliero di 800 richieste/8 al minuto del piano gratuito), e li salva in
CSV locali - serve per ri-validare i parametri della strategia sui dati
REALMENTE usati da Segnali in produzione (Twelve Data), non su quelli di
histdata.com/MT4 usati per Stardust Dragon: sono due fonti diverse, un
parametro tarato sull'una non e' detto che regga sull'altra (vedi la
discrepanza RSI osservata tra le due fonti il 2026-08-20).

Uso:
    python download_history.py
"""

import os
import time
from datetime import datetime, timedelta, timezone

import pandas as pd
import requests

from twelvedata_client import BASE_URL, _SYMBOL_MAP

SYMBOLS = ["EURUSD", "GBPUSD", "USDJPY", "EURGBP", "USDCHF", "AUDUSD"]
CHUNK_DAYS = 45
MONTHS_BACK = 6
OUT_DIR = os.path.join(os.path.dirname(__file__), "historical_data_twelvedata")


def _fetch_chunk(symbol, start, end, api_key):
    resp = requests.get(BASE_URL, params={
        "symbol": _SYMBOL_MAP.get(symbol, symbol), "interval": "15min",
        "start_date": start.strftime("%Y-%m-%d %H:%M:%S"),
        "end_date": end.strftime("%Y-%m-%d %H:%M:%S"),
        "timezone": "UTC", "apikey": api_key,
    }, timeout=30)
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("status") == "error":
        raise ValueError(f"Twelve Data errore per {symbol} [{start.date()} -> {end.date()}]: {payload.get('message')}")
    return payload.get("values") or []


def download_symbol(symbol, api_key):
    end_all = datetime.now(timezone.utc)
    start_all = end_all - timedelta(days=30 * MONTHS_BACK)

    all_rows = []
    cursor = start_all
    while cursor < end_all:
        chunk_end = min(cursor + timedelta(days=CHUNK_DAYS), end_all)
        print(f"  [{symbol}] {cursor.date()} -> {chunk_end.date()}...")
        rows = _fetch_chunk(symbol, cursor, chunk_end, api_key)
        all_rows.extend(rows)
        cursor = chunk_end
        time.sleep(1.0)  # margine ampio sotto 8 richieste/minuto

    df = pd.DataFrame(all_rows)
    if df.empty:
        raise RuntimeError(f"Nessun dato ricevuto per {symbol}")
    df["datetime"] = pd.to_datetime(df["datetime"], utc=True)
    df = df.drop_duplicates(subset="datetime").set_index("datetime").sort_index()
    for col in ("open", "high", "low", "close"):
        df[col] = df[col].astype(float)

    out_path = os.path.join(OUT_DIR, f"{symbol}_M15.csv")
    df[["open", "high", "low", "close"]].to_csv(out_path)
    print(f"  [{symbol}] salvate {len(df)} barre ({df.index.min()} -> {df.index.max()}) in {out_path}")


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    api_key = os.environ["TWELVEDATA_API_KEY"]
    for symbol in SYMBOLS:
        print(f"Scarico {symbol}...")
        download_symbol(symbol, api_key)


if __name__ == "__main__":
    main()
