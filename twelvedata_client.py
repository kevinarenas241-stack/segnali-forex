"""Client minimale per l'API REST di Twelve Data (dati forex M15), usato al
posto del bridge MT4: questo progetto non apre mai ordini reali, quindi non
serve una connessione al broker - solo prezzi affidabili per calcolare gli
indicatori. Piano gratuito: 800 richieste/giorno, 8/minuto (6 coppie ogni 15
minuti = ~576/giorno, ampiamente sotto soglia)."""

import os
import requests
import pandas as pd

BASE_URL = "https://api.twelvedata.com/time_series"

# Formato Twelve Data per il forex: "EUR/USD" (con slash), non "EURUSD".
_SYMBOL_MAP = {
    "EURUSD": "EUR/USD", "GBPUSD": "GBP/USD", "USDJPY": "USD/JPY",
    "EURGBP": "EUR/GBP", "USDCHF": "USD/CHF", "AUDUSD": "AUD/USD",
}


def fetch_ohlc(symbol: str, interval: str = "15min", outputsize: int = 60) -> pd.DataFrame:
    """Ritorna un DataFrame ordinato cronologicamente (piu' vecchia prima),
    colonne open/high/low/close, indice UTC. Solleva ValueError se l'API
    risponde con un errore (chiave non valida, simbolo sconosciuto, limite
    di richieste superato, ecc.)."""
    api_key = os.environ["TWELVEDATA_API_KEY"]
    td_symbol = _SYMBOL_MAP.get(symbol, symbol)

    resp = requests.get(BASE_URL, params={
        "symbol": td_symbol, "interval": interval, "outputsize": outputsize,
        "timezone": "UTC", "apikey": api_key,
    }, timeout=15)
    resp.raise_for_status()
    payload = resp.json()

    if payload.get("status") == "error":
        raise ValueError(f"Twelve Data ha risposto con errore per {symbol}: {payload.get('message')}")
    values = payload.get("values")
    if not values:
        raise ValueError(f"Nessun dato ricevuto da Twelve Data per {symbol}")

    df = pd.DataFrame(values)
    df["datetime"] = pd.to_datetime(df["datetime"], utc=True)
    df = df.set_index("datetime").sort_index()
    for col in ("open", "high", "low", "close"):
        df[col] = df[col].astype(float)
    return df[["open", "high", "low", "close"]]
