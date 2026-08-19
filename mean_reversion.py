"""Strategia MEAN-REVERSION di Stardust Dragon (Bollinger Bands + RSI),
copiata INVARIATA - stessa configurazione validata su 6 mesi di storico
reale (+7.81% out-of-sample, mai bloccata, la migliore trovata contro dieci
alternative diverse testate). Nessuna dipendenza da config.settings: questo
progetto (Segnali) e' completamente separato da YUSEI e Stardust Dragon, i
parametri sono costanti locali.

Entrata:
  LONG  quando close < banda inferiore  E  RSI < RSI_OVERSOLD
  SHORT quando close > banda superiore  E  RSI > RSI_OVERBOUGHT
  (solo dentro la finestra di sessione 1h-20h UTC, gia' validata)

Uscita:
  Target: ritorno alla banda centrale (dinamico, letto ogni barra).
  Stop loss: ATR-based, rete di sicurezza.
"""

import pandas as pd
import pandas_ta as ta  # noqa: F401  (registra l'accessor .ta su DataFrame)

BB_PERIOD = 20
BB_STD = 2.0
RSI_PERIOD = 14
RSI_OVERSOLD = 30
RSI_OVERBOUGHT = 70
SL_ATR_MULT = 1.5
ATR_PERIOD = 14
SESSION_START, SESSION_END = 1, 20  # ore UTC, gia' validate su Stardust Dragon


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    sma = out["close"].rolling(BB_PERIOD).mean()
    std = out["close"].rolling(BB_PERIOD).std()
    out["bb_mid"] = sma
    out["bb_upper"] = sma + BB_STD * std
    out["bb_lower"] = sma - BB_STD * std
    out["rsi"] = out.ta.rsi(length=RSI_PERIOD)
    out["atr"] = out.ta.atr(length=ATR_PERIOD)
    return out


def check_entry_signal(last_row, hour_utc: int, rsi_oversold: float = RSI_OVERSOLD,
                        rsi_overbought: float = RSI_OVERBOUGHT, sl_atr_mult: float = SL_ATR_MULT):
    """Ritorna (direction, stop_loss) o (None, None). last_row: ultima riga
    del DataFrame arricchito da add_indicators (Serie pandas).

    rsi_oversold/rsi_overbought/sl_atr_mult: valori di default gia' validati
    (le costanti di modulo), ma sovrascrivibili - li passa signal_engine.py
    leggendoli da segnali_status.json ("active_params"), l'UNICO modo in cui
    la revisione AI puo' effettivamente cambiare il comportamento della
    strategia (mai modificando questo file), e solo entro i limiti fissi
    imposti da ai_review.py (questo modulo non li conosce e non li applica)."""
    if pd.isna(last_row["bb_lower"]) or pd.isna(last_row["bb_upper"]) or pd.isna(last_row["rsi"]) or pd.isna(last_row["atr"]):
        return None, None
    if not (SESSION_START <= hour_utc < SESSION_END):
        return None, None

    close = last_row["close"]
    if close < last_row["bb_lower"] and last_row["rsi"] < rsi_oversold:
        return "LONG", close - sl_atr_mult * last_row["atr"]
    if close > last_row["bb_upper"] and last_row["rsi"] > rsi_overbought:
        return "SHORT", close + sl_atr_mult * last_row["atr"]
    return None, None


def check_exit(direction, stop_loss, last_row):
    """Controlla se l'ultima barra ha toccato stop o target (bb_mid
    dinamico). Ritorna (exit_price, reason) o (None, None)."""
    high, low, bb_mid = last_row["high"], last_row["low"], last_row["bb_mid"]
    if direction == "LONG":
        if low <= stop_loss:
            return stop_loss, "STOP_LOSS"
        if high >= bb_mid:
            return bb_mid, "MEAN_REVERSION_TARGET"
    else:
        if high >= stop_loss:
            return stop_loss, "STOP_LOSS"
        if low <= bb_mid:
            return bb_mid, "MEAN_REVERSION_TARGET"
    return None, None
