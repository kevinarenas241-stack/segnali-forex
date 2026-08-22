"""Motore di backtest per Segnali, coerente con la logica REALMENTE in
produzione (signal_engine.py): nessun lotto/margine reale da calcolare (il
sistema non apre mai ordini), il P&L e' basato sui multipli di R esattamente
come dal vivo - rischio fisso (RISK_PCT del capitale) per operazione,
capital_at_open congelato all'apertura."""

from dataclasses import dataclass

import pandas as pd

from mean_reversion import check_entry_signal, check_exit

RISK_PCT = 0.003


@dataclass
class Position:
    symbol: str
    direction: str
    entry_time: object
    entry_price: float
    stop_loss: float
    capital_at_open: float


@dataclass
class Trade:
    symbol: str
    direction: str
    entry_time: object
    entry_price: float
    exit_time: object
    exit_price: float
    pnl_eur: float
    pnl_pct: float
    reason: str


def _pnl(direction, entry_price, exit_price, stop_loss, capital_at_open):
    risk_distance = abs(entry_price - stop_loss)
    direction_mult = 1 if direction == "LONG" else -1
    reward_distance = (exit_price - entry_price) * direction_mult
    r_multiple = reward_distance / risk_distance if risk_distance > 0 else 0.0
    pnl_eur = r_multiple * (capital_at_open * RISK_PCT)
    pnl_pct = (pnl_eur / capital_at_open * 100) if capital_at_open else 0.0
    return pnl_eur, pnl_pct


class SegnaliBacktestEngine:
    def __init__(self, dfs: dict, initial_capital: float,
                 rsi_oversold: float = 30, rsi_overbought: float = 70, sl_atr_mult: float = 1.5):
        self.dfs = dfs
        self.initial_capital = initial_capital
        self.capital = initial_capital
        self.rsi_oversold = rsi_oversold
        self.rsi_overbought = rsi_overbought
        self.sl_atr_mult = sl_atr_mult
        self.open_positions: dict[str, Position] = {}
        self.trades: list[Trade] = []
        self.equity_curve: list[tuple] = []

    def run(self):
        all_timestamps = sorted(set().union(*[set(df.index) for df in self.dfs.values()]))

        for t in all_timestamps:
            for symbol in list(self.open_positions.keys()):
                df = self.dfs[symbol]
                if t not in df.index:
                    continue
                bar = df.loc[t]
                pos = self.open_positions[symbol]
                exit_price, reason = check_exit(pos.direction, pos.stop_loss, bar)
                if exit_price is not None:
                    pnl_eur, pnl_pct = _pnl(pos.direction, pos.entry_price, exit_price, pos.stop_loss, pos.capital_at_open)
                    self.capital += pnl_eur
                    self.trades.append(Trade(
                        symbol=symbol, direction=pos.direction, entry_time=pos.entry_time,
                        entry_price=pos.entry_price, exit_time=t, exit_price=exit_price,
                        pnl_eur=pnl_eur, pnl_pct=pnl_pct, reason=reason,
                    ))
                    del self.open_positions[symbol]

            for symbol, df in self.dfs.items():
                if symbol in self.open_positions or t not in df.index:
                    continue
                bar = df.loc[t]
                direction, stop_loss = check_entry_signal(
                    bar, t.hour, t.weekday(), rsi_oversold=self.rsi_oversold,
                    rsi_overbought=self.rsi_overbought, sl_atr_mult=self.sl_atr_mult,
                )
                if direction is None:
                    continue
                self.open_positions[symbol] = Position(
                    symbol=symbol, direction=direction, entry_time=t,
                    entry_price=float(bar["close"]), stop_loss=float(stop_loss),
                    capital_at_open=self.capital,
                )

            self.equity_curve.append((t, self.capital))

        return self.report()

    def report(self):
        trades_df = pd.DataFrame([t.__dict__ for t in self.trades])
        equity_df = pd.DataFrame(self.equity_curve, columns=["time", "capital"]).set_index("time")

        if trades_df.empty:
            return {"trades": trades_df, "equity_curve": equity_df, "summary": "Nessuna operazione."}

        wins = trades_df[trades_df["pnl_eur"] > 0]
        losses = trades_df[trades_df["pnl_eur"] <= 0]
        total_return_pct = (self.capital - self.initial_capital) / self.initial_capital * 100

        running_max = equity_df["capital"].cummax()
        drawdown = (equity_df["capital"] - running_max) / running_max * 100
        max_drawdown_pct = drawdown.min()

        summary = {
            "n_trades": len(trades_df),
            "win_rate_pct": round(len(wins) / len(trades_df) * 100, 1),
            "total_return_pct": round(total_return_pct, 2),
            "final_capital": round(self.capital, 2),
            "max_drawdown_pct": round(max_drawdown_pct, 2),
            "best_trade_pct": round(trades_df["pnl_pct"].max(), 2),
            "worst_trade_pct": round(trades_df["pnl_pct"].min(), 2),
        }
        return {"trades": trades_df, "equity_curve": equity_df, "summary": summary}
