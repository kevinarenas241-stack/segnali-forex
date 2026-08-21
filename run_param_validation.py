"""
Ri-validazione dei parametri di Segnali (RSI ipervenduto/ipercomprato,
moltiplicatore ATR) sui dati REALI usati in produzione (Twelve Data),
non su quelli di histdata.com/MT4 usati per tarare Stardust Dragon - le due
fonti divergono abbastanza (vedi la discrepanza RSI osservata il 2026-08-20)
da rendere onesto rifare la verifica sulla fonte dati vera.

Ricerca SOLO sui primi 5 mesi (in-sample), poi verifica UNA SOLA VOLTA
sull'ultimo mese (mai visto) - stessa disciplina di tutta la sessione.
Il grid di ricerca coincide con i limiti gia' fissati per l'auto-modifica
dell'AI (ai_review.ALLOWED_PARAM_RANGES), cosi' il risultato e' direttamente
utilizzabile come nuovo punto di partenza "active_params" se onestamente
migliore del default attuale (30/70/1.5).

Uso:
    python run_param_validation.py
"""

import os
from pathlib import Path

import pandas as pd

from mean_reversion import add_indicators
from backtest_engine import SegnaliBacktestEngine

DATA_DIR = Path(__file__).resolve().parent / "historical_data_twelvedata"
SYMBOLS = ["EURUSD", "GBPUSD", "USDJPY", "EURGBP", "USDCHF", "AUDUSD"]
INITIAL_CAPITAL = 20000.0
OUT_OF_SAMPLE_DAYS = 30
MIN_TRADES = 15

RSI_OVERSOLD_GRID = [30, 35, 40, 45]
RSI_OVERBOUGHT_GRID = [55, 60, 65, 70]
SL_ATR_MULT_GRID = [1.2, 1.5]
DEFAULT_COMBO = (30, 70, 1.5)


def load_data():
    dfs = {}
    for symbol in SYMBOLS:
        path = DATA_DIR / f"{symbol}_M15.csv"
        raw = pd.read_csv(path, index_col=0, parse_dates=True)
        print(f"Carico {symbol}: {len(raw)} barre ({raw.index.min()} -> {raw.index.max()})")
        dfs[symbol] = add_indicators(raw)
    return dfs


def run_window(dfs, rsi_oversold, rsi_overbought, sl_atr_mult, start=None, end=None):
    sliced = {}
    for symbol, df in dfs.items():
        s = df
        if start is not None:
            s = s[s.index >= start]
        if end is not None:
            s = s[s.index < end]
        sliced[symbol] = s
    engine = SegnaliBacktestEngine(sliced, INITIAL_CAPITAL, rsi_oversold, rsi_overbought, sl_atr_mult)
    return engine.run()


def score(summary):
    if isinstance(summary, str) or summary["n_trades"] < MIN_TRADES:
        return None
    return summary["total_return_pct"] - 0.5 * abs(summary["max_drawdown_pct"])


def show(label, result):
    summary = result["summary"]
    print(f"\n{'=' * 60}\n{label}\n{'=' * 60}")
    if isinstance(summary, str):
        print(summary)
        return
    for k, v in summary.items():
        print(f"{k:<20} {v}")
    trades = result["trades"]
    print("\nPer coppia:")
    per_symbol = trades.groupby("symbol")["pnl_eur"].agg(operazioni="count", pnl_totale="sum")
    per_symbol["win_rate"] = trades.groupby("symbol")["pnl_eur"].apply(lambda s: (s > 0).mean() * 100)
    print(per_symbol.round(2))


def main():
    dfs = load_data()
    data_start = min(df.index.min() for df in dfs.values())
    data_end = max(df.index.max() for df in dfs.values())
    cutoff = data_end - pd.Timedelta(days=OUT_OF_SAMPLE_DAYS)
    print(f"\nCutoff in-sample/out-of-sample: {cutoff}\n")

    print("--- Verifica il DEFAULT attuale (30/70/1.5) in-sample, come riferimento ---")
    default_in = run_window(dfs, *DEFAULT_COMBO, end=cutoff)
    default_score = score(default_in["summary"])
    print(f"Default in-sample: score={default_score}")

    print(f"\n--- Ricerca su {len(RSI_OVERSOLD_GRID) * len(RSI_OVERBOUGHT_GRID) * len(SL_ATR_MULT_GRID)} combinazioni, SOLO in-sample ---\n")
    results = []
    for rsi_os in RSI_OVERSOLD_GRID:
        for rsi_ob in RSI_OVERBOUGHT_GRID:
            for sl_mult in SL_ATR_MULT_GRID:
                r = run_window(dfs, rsi_os, rsi_ob, sl_mult, end=cutoff)
                s = score(r["summary"])
                if isinstance(r["summary"], dict):
                    print(f"rsi_os={rsi_os} rsi_ob={rsi_ob} sl_mult={sl_mult}  "
                          f"rendimento={r['summary']['total_return_pct']:>7.2f}%  "
                          f"dd={r['summary']['max_drawdown_pct']:>7.2f}%  "
                          f"trade={r['summary']['n_trades']:>4}  "
                          f"win={r['summary']['win_rate_pct']:>5.1f}%"
                          + ("" if s is not None else "  (scartata)"))
                if s is not None:
                    results.append((s, rsi_os, rsi_ob, sl_mult))

    results.sort(key=lambda r: r[0], reverse=True)
    if not results:
        print("\nNessuna combinazione valida in-sample.")
        return

    best_score, best_os, best_ob, best_mult = results[0]
    print(f"\nMigliore candidato IN-SAMPLE: rsi_os={best_os} rsi_ob={best_ob} sl_mult={best_mult}  score={best_score:.2f}")
    print(f"(per confronto, il default 30/70/1.5 aveva score={default_score})")

    print("\n--- Verifica FINALE, una sola volta, sull'ultimo mese mai visto ---")
    default_out = run_window(dfs, *DEFAULT_COMBO, start=cutoff)
    best_in = run_window(dfs, best_os, best_ob, best_mult, end=cutoff)
    best_out = run_window(dfs, best_os, best_ob, best_mult, start=cutoff)

    show("DEFAULT (30/70/1.5) - OUT-OF-SAMPLE", default_out)
    show(f"MIGLIOR CANDIDATO ({best_os}/{best_ob}/{best_mult}) - IN-SAMPLE", best_in)
    show(f"MIGLIOR CANDIDATO ({best_os}/{best_ob}/{best_mult}) - OUT-OF-SAMPLE (mai visto)", best_out)


if __name__ == "__main__":
    main()
