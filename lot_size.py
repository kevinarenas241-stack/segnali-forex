"""Calcolo dei lotti da suggerire nel messaggio Telegram, cosi' l'utente sa
quanto aprire su MT4 invece di usare sempre 1 lotto fisso. Nessuna
connessione MT4 (Segnali non ne ha una): il valore del punto per lotto e'
calcolato dai prezzi correnti (gia' scaricati da Twelve Data per generare il
segnale), con le convenzioni standard di mercato (lotto = 100.000 unita'),
convertito in EUR (valuta del capitale virtuale) tramite EURUSD.

E' una STIMA, non il valore esatto del tuo broker (spread/commissioni non
inclusi) - abbastanza precisa per dimensionare il rischio, ma controlla
sempre il margine libero reale su MT4 prima di confermare l'ordine.
"""

LOT_UNITS = 100_000
RISK_PCT = 0.003  # stesso rischio gia' usato per il P&L virtuale in signal_engine.py

MIN_LOT = 0.01
MAX_LOT = 20.0
LOT_STEP = 0.01


def point_size(symbol: str) -> float:
    return 0.001 if symbol.endswith("JPY") else 0.00001


def point_value_eur(symbol: str, prices: dict) -> float:
    """Valore in EUR di 1 point (point_size) per 1 lotto standard, dati i
    prezzi correnti (prices: {"EURUSD": ..., "GBPUSD": ..., ...})."""
    eurusd = prices["EURUSD"]
    pt = point_size(symbol)

    if symbol in ("EURUSD", "GBPUSD", "AUDUSD"):
        value_usd = LOT_UNITS * pt
        return value_usd / eurusd

    if symbol == "USDJPY":
        value_jpy = LOT_UNITS * pt
        value_usd = value_jpy / prices["USDJPY"]
        return value_usd / eurusd

    if symbol == "USDCHF":
        value_chf = LOT_UNITS * pt
        value_usd = value_chf / prices["USDCHF"]
        return value_usd / eurusd

    if symbol == "EURGBP":
        value_gbp = LOT_UNITS * pt
        return value_gbp / prices["EURGBP"]

    raise ValueError(f"Simbolo non gestito per il calcolo lotti: {symbol}")


def suggested_lots(symbol: str, entry_price: float, stop_loss: float, capital_at_open: float, prices: dict) -> float:
    stop_distance = abs(entry_price - stop_loss)
    if stop_distance <= 0:
        return MIN_LOT

    risk_amount = capital_at_open * RISK_PCT
    n_points = stop_distance / point_size(symbol)
    pt_value = point_value_eur(symbol, prices)
    loss_per_lot = n_points * pt_value
    if loss_per_lot <= 0:
        return MIN_LOT

    lots = risk_amount / loss_per_lot
    lots = max(MIN_LOT, min(MAX_LOT, round(lots / LOT_STEP) * LOT_STEP))
    return round(lots, 2)
