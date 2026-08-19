"""Client per api/segnali/segnali_status.php (operatorchat.info): questo
endpoint E' la memoria persistente dello script tra un'esecuzione schedulata
e l'altra (GitHub Actions non mantiene stato locale tra un run e il
successivo)."""

import os
import requests

STATUS_URL = "https://operatorchat.info/api/segnali/segnali_status.php"


def _headers():
    return {"X-Api-Key": os.environ["SEGNALI_API_KEY"]}


def get_status() -> dict:
    resp = requests.get(STATUS_URL, headers=_headers(), timeout=15)
    resp.raise_for_status()
    return resp.json()


def _post(action: str, symbol: str = None, data: dict = None) -> None:
    payload = {"action": action}
    if symbol is not None:
        payload["symbol"] = symbol
    if data is not None:
        payload["data"] = data
    resp = requests.post(STATUS_URL, headers=_headers(), json=payload, timeout=15)
    resp.raise_for_status()
    body = resp.json()
    if not body.get("success"):
        raise RuntimeError(f"segnali_status.php ha rifiutato l'azione '{action}': {body}")


def open_signal(symbol: str, direction: str, entry_price: float, stop_loss: float, capital_at_open: float) -> None:
    _post("open", symbol, {
        "direction": direction, "entry_price": entry_price, "stop_loss": stop_loss,
        "capital_at_open": capital_at_open,
    })


def close_signal(symbol: str, exit_price: float, pnl_eur: float, pnl_pct: float, reason: str) -> None:
    _post("close", symbol, {
        "exit_price": exit_price, "pnl_eur": pnl_eur, "pnl_pct": pnl_pct, "reason": reason,
    })


def heartbeat() -> None:
    _post("heartbeat")


def set_strategy_note(text: str) -> None:
    _post("note", data={"text": text})


def mark_reviewed(count: int) -> None:
    _post("mark_reviewed", data={"count": count})


def apply_param_change(param: str, new_value: float, reasoning: str) -> None:
    _post("apply_param_change", data={"param": param, "new_value": new_value, "reasoning": reasoning})


def flag_strategy_concern(text: str) -> None:
    _post("flag_strategy_concern", data={"text": text})
