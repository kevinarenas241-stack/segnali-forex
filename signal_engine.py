"""Motore principale di "Segnali": per ciascuna coppia, gestisce un segnale
gia' aperto (controlla se ha toccato stop/target sui prezzi reali) oppure
cerca un nuovo segnale (mean_reversion.py) e lo manda via Telegram.

Nessun ordine reale: l'utente esegue a mano su MT4 seguendo il messaggio
Telegram; questo script traccia da solo l'esito seguendo i prezzi di Twelve
Data, usando una size "virtuale" (0.3% di rischio per operazione, la stessa
configurazione validata su Stardust Dragon) solo per calcolare un P&L in EUR
comparabile, non per determinare lotti reali.

Pensato per girare su un programma esterno (GitHub Actions), non sul PC
dell'utente: ad ogni esecuzione rilegge lo stato da segnali_status.php (che
e' la memoria persistente tra un'esecuzione e l'altra) invece di tenerlo in
locale.

Uso:
    python signal_engine.py
Variabili d'ambiente richieste:
    TWELVEDATA_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, SEGNALI_API_KEY
"""

from twelvedata_client import fetch_ohlc
from telegram_client import send_message
from dashboard_client import get_status, open_signal, close_signal, heartbeat
from mean_reversion import add_indicators, check_entry_signal, check_exit

SYMBOLS = ["EURUSD", "GBPUSD", "USDJPY", "EURGBP", "USDCHF", "AUDUSD"]
RISK_PCT = 0.003


def _decimals(symbol):
    return 3 if symbol.endswith("JPY") else 5


def _process_open_signal(symbol, open_pos, last, current_capital):
    direction = open_pos["direction"]
    stop_loss = float(open_pos["stop_loss"])
    entry_price = float(open_pos["entry_price"])
    capital_at_open = float(open_pos.get("capital_at_open", current_capital))

    exit_price, reason = check_exit(direction, stop_loss, last)
    if exit_price is None:
        print(f"[{symbol}] segnale aperto ({direction} da {entry_price}), nessun tocco di stop/target")
        return

    risk_distance = abs(entry_price - stop_loss)
    direction_mult = 1 if direction == "LONG" else -1
    reward_distance = (exit_price - entry_price) * direction_mult
    r_multiple = reward_distance / risk_distance if risk_distance > 0 else 0.0
    risk_amount = capital_at_open * RISK_PCT
    pnl_eur = r_multiple * risk_amount
    pnl_pct = (pnl_eur / capital_at_open * 100) if capital_at_open else 0.0

    decimals = _decimals(symbol)
    close_signal(symbol, round(exit_price, decimals), round(pnl_eur, 2), round(pnl_pct, 3), reason)

    esito = "TARGET raggiunto" if reason == "MEAN_REVERSION_TARGET" else "STOP LOSS"
    emoji = "✅" if pnl_eur >= 0 else "\U0001F534"
    segno = "+" if pnl_eur >= 0 else ""
    send_message(
        f"{emoji} <b>{symbol} CHIUSA</b> ({esito})\n"
        f"Se avevi eseguito il segnale: {segno}{pnl_eur:.2f} EUR ({segno}{pnl_pct:.2f}%)\n"
        f"Uscita a {exit_price:.{decimals}f}"
    )
    print(f"[{symbol}] chiuso: {reason}, pnl={pnl_eur:.2f}EUR ({pnl_pct:.2f}%)")


def _process_new_signal(symbol, last, hour_utc, current_capital):
    direction, stop_loss = check_entry_signal(last, hour_utc)
    if direction is None:
        rsi = last["rsi"]
        rsi_str = f"{rsi:.1f}" if rsi == rsi else "n/d"  # rsi != rsi se e' NaN
        print(f"[{symbol}] nessun segnale (rsi={rsi_str})")
        return

    entry_price = float(last["close"])
    decimals = _decimals(symbol)
    open_signal(symbol, direction, round(entry_price, decimals), round(stop_loss, decimals), current_capital)

    emoji = "\U0001F7E2" if direction == "LONG" else "\U0001F534"
    verbo = "COMPRA" if direction == "LONG" else "VENDI"
    send_message(
        f"{emoji} <b>SEGNALE {symbol}</b>\n"
        f"{verbo} a mercato (~{entry_price:.{decimals}f})\n"
        f"Stop loss: {stop_loss:.{decimals}f}\n"
        f"Target: ritorno alla media mobile (dinamico, ti avviso io quando chiudere)"
    )
    print(f"[{symbol}] SEGNALE {direction} a {entry_price}, stop={stop_loss}")


def main():
    status = get_status()
    current_capital = status.get("current_capital", 10000.0)
    open_signals = status.get("open_signals", {})

    for symbol in SYMBOLS:
        try:
            df = add_indicators(fetch_ohlc(symbol, interval="15min", outputsize=60))
            last = df.iloc[-1]
            hour_utc = last.name.hour

            if symbol in open_signals:
                _process_open_signal(symbol, open_signals[symbol], last, current_capital)
            else:
                _process_new_signal(symbol, last, hour_utc, current_capital)
        except Exception as e:
            print(f"[{symbol}] ERRORE: {e}")

    heartbeat()


if __name__ == "__main__":
    main()
