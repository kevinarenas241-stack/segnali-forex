"""Revisione periodica automatica (Claude via API Anthropic) dello storico
REALE di Segnali (non backtest).

QUANDO scatta la revisione (chiamata API di analisi): run_review_if_due()
viene richiamata da signal_engine.py dopo OGNI chiusura di operazione
(controllo gratuito, solo un conteggio, nessuna chiamata API) - la vera
analisi scatta appena si sono accumulate almeno REVIEW_EVERY_N_NEW
operazioni NUOVE dall'ultima revisione. Nessuna soglia minima assoluta
oltre a questa (rimossa su richiesta esplicita: prima c'era anche un
minimo di 30 operazioni totali, ora conta solo il conteggio incrementale).

COSA puo' fare l'AI dopo l'analisi: puo' APPLICARE DA SOLA, senza bisogno
di approvazione umana, UN cambiamento a UNO dei parametri in
ALLOWED_PARAM_RANGES - ma solo entro il range fisso li' definito (l'AI non
puo' proporre un valore fuori range: viene scartato anche se lo scrive), e
solo se ci sono almeno APPLY_MIN_TRADES operazioni chiuse in totale (soglia
piu' alta della soglia di revisione, apposta: rivedere spesso va bene,
agire richiede piu' fiducia). Ogni parametro non nella lista (periodo
Bollinger, sessione oraria, simboli, rischio per operazione) resta
IRRAGGIUNGIBILE per l'AI, qualunque cosa scriva - la validazione del range
e della soglia avviene PRIMA di chiamare l'endpoint, e di nuovo lato server
(api/segnali/segnali_status.php) come seconda barriera.

Ogni modifica applicata genera SEMPRE un messaggio Telegram esplicito (cosa
e' cambiato, perche', da quale valore a quale) e resta nello storico
"applied_changes" sulla dashboard - mai un cambiamento silenzioso.

COSA fa l'AI se ritiene che l'INTERA strategia (non un parametro) non
funzioni piu': puo' segnalarlo (STRATEGY_CONCERN), ma questo NON viene MAI
applicato automaticamente - genera solo un avviso ben distinto su
Telegram/dashboard che dice esplicitamente "richiede un backtest vero prima
di essere attivato". La decisione di testare e attivare una strategia
diversa resta un processo fatto insieme all'utente in conversazione, con
dati storici e verifica in-sample/out-of-sample - esattamente come ogni
altra strategia validata in questo progetto finora. Bar di evidenza molto
piu' alto del semplice cambio di parametro: non basta una coppia in
perdita, serve un problema sistemico su gran parte del campione.
"""

import os
import re
import requests

from dashboard_client import (
    get_status, set_strategy_note, mark_reviewed, apply_param_change, flag_strategy_concern,
)
from telegram_client import send_message

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
MODEL = "claude-sonnet-5"
REVIEW_EVERY_N_NEW = 10
APPLY_MIN_TRADES = 50

# DEVONO restare identici ai limiti in api/segnali/segnali_config.php
# (SEGNALI_PARAM_RANGES) - controllati qui PRIMA di chiamare l'endpoint,
# che li ricontrolla comunque lato server come seconda barriera.
ALLOWED_PARAM_RANGES = {
    "rsi_oversold": (25, 35),
    "rsi_overbought": (65, 75),
    "sl_atr_mult": (1.2, 1.8),
}

PARAM_CHANGE_RE = re.compile(r"PARAM_CHANGE:\s*(\w+)\s*=\s*([\d.]+)")
STRATEGY_CONCERN_RE = re.compile(r"STRATEGY_CONCERN:\s*(.+)")

SYSTEM_PROMPT = f"""Sei un analista quantitativo che revisiona lo storico REALE
(non backtest) di un sistema di segnali forex mean-reversion (Bollinger 20/2.0
+ RSI 14/30/70, sessione 1-20h UTC, gia' validato su backtest storici su 6
mesi/1 anno prima del lancio).

Regole non negoziabili:
- Non trarre conclusioni su un simbolo con meno di 15 operazioni chiuse:
  scrivi esplicitamente che il campione e' insufficiente per quel simbolo.
- Distingui sempre tra "sfortuna in un campione piccolo" e "un problema
  strutturale reale" - un win rate diverso dall'atteso su poche decine di
  trade e' quasi sempre rumore statistico, non un segnale affidabile.
- La variazione normale a breve termine e' attesa in un sistema
  mean-reversion (era gia' visibile nei backtest): non e' di per se' un
  motivo per cambiare nulla.

Hai a disposizione DUE meccanismi distinti, tra loro alternativi (usa al
massimo uno dei due, e solo se davvero giustificato - il caso piu' comune,
dato che la strategia e' gia' validata, e' non usarne nessuno):

1. AGGIUSTAMENTO FINE (si applica da solo): se hai prove solide che UNO dei
   tre parametri regolabili avrebbe fatto chiaramente meglio, scrivi come
   ULTIMA riga della risposta, ESATTAMENTE nel formato:
   PARAM_CHANGE: <nome>=<valore>
   dove <nome> e' uno tra: rsi_oversold (consentito 25-35), rsi_overbought
   (consentito 65-75), sl_atr_mult (consentito 1.2-1.8). Un valore fuori da
   questi range viene scartato automaticamente. Il resto del testo va
   scritto come se il cambiamento fosse gia' un fatto compiuto (verra'
   applicato in automatico).

2. SEGNALAZIONE STRUTTURALE (MAI applicata da sola, solo un avviso per
   revisione umana): usala SOLO se il problema non e' un parametro da
   limare ma sembra che l'intero approccio mean-reversion non funzioni piu'
   - serve un problema sistemico su gran parte del campione (non una sola
   coppia sfortunata), su un numero di operazioni ampio. Scrivi come ULTIMA
   riga:
   STRATEGY_CONCERN: <spiegazione breve del problema>
   Questo NON cambia mai nulla da solo: attiva solo un avviso che dice
   esplicitamente che serve un backtest vero prima di agire.

Massimo 400 caratteri di testo (esclusa l'eventuale riga finale), in
italiano, tono diretto - finisce su una dashboard pubblica e su un
messaggio Telegram, deve essere leggibile in pochi secondi."""


def build_prompt(status: dict) -> str:
    trades = status.get("closed_trades", [])
    n = len(trades)
    wins = sum(1 for t in trades if (t.get("pnl_eur") or 0) > 0)

    by_symbol = {}
    for t in trades:
        sym = t.get("symbol", "?")
        entry = by_symbol.setdefault(sym, {"n": 0, "wins": 0, "pnl": 0.0})
        entry["n"] += 1
        entry["wins"] += 1 if (t.get("pnl_eur") or 0) > 0 else 0
        entry["pnl"] += t.get("pnl_eur") or 0

    active = status.get("active_params", {})
    lines = [
        f"Capitale iniziale: {status.get('initial_capital')} EUR",
        f"Capitale attuale: {status.get('current_capital')} EUR",
        f"Operazioni totali: {n}, vincenti: {wins} ({wins / n * 100:.1f}%)" if n else "Operazioni totali: 0",
        f"Parametri attivi ora: rsi_oversold={active.get('rsi_oversold', 30)}, "
        f"rsi_overbought={active.get('rsi_overbought', 70)}, sl_atr_mult={active.get('sl_atr_mult', 1.5)}",
        f"Puoi applicare un cambiamento: {'si' if n >= APPLY_MIN_TRADES else f'no, servono almeno {APPLY_MIN_TRADES} operazioni totali (ce ne sono {n})'}",
        "Per coppia:",
    ]
    for sym, s in by_symbol.items():
        win_rate = s["wins"] / s["n"] * 100 if s["n"] else 0
        lines.append(f"  {sym}: {s['n']} operazioni, win rate {win_rate:.1f}%, pnl {s['pnl']:.2f} EUR")

    return "\n".join(lines)


def _call_anthropic(prompt: str) -> str:
    api_key = os.environ["ANTHROPIC_API_KEY"]
    resp = requests.post(
        ANTHROPIC_URL,
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": MODEL,
            "max_tokens": 300,
            "system": SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=60,
    )
    resp.raise_for_status()
    body = resp.json()
    return "".join(block.get("text", "") for block in body.get("content", [])).strip()


def _extract_param_change(text: str):
    """Ritorna (testo_senza_riga, param, valore) o (testo, None, None)."""
    match = PARAM_CHANGE_RE.search(text)
    if not match:
        return text.strip(), None, None
    param, value_str = match.group(1), match.group(2)
    clean_text = PARAM_CHANGE_RE.sub("", text).strip()
    try:
        return clean_text, param, float(value_str)
    except ValueError:
        return clean_text, None, None


def _extract_strategy_concern(text: str):
    """Ritorna (testo_senza_riga, spiegazione) o (testo, None)."""
    match = STRATEGY_CONCERN_RE.search(text)
    if not match:
        return text.strip(), None
    clean_text = STRATEGY_CONCERN_RE.sub("", text).strip()
    return clean_text, match.group(1).strip()


def run_review_if_due(status: dict = None) -> bool:
    """Controllo economico (nessuna chiamata API) da fare dopo OGNI chiusura
    di operazione: valuta se e' il momento di una revisione vera. Ritorna
    True se ha effettivamente pubblicato una revisione."""
    if status is None:
        status = get_status()

    trades = status.get("closed_trades", [])
    n_total = len(trades)
    n_reviewed = status.get("trades_reviewed_count", 0)
    n_new = n_total - n_reviewed

    if n_new < REVIEW_EVERY_N_NEW:
        print(f"[ai_review] solo {n_new} operazioni nuove dall'ultima revisione (soglia {REVIEW_EVERY_N_NEW}): salto.")
        return False

    raw_text = _call_anthropic(build_prompt(status))
    if not raw_text:
        print("[ai_review] risposta vuota dall'API, non pubblico nulla.")
        return False

    text, param, value = _extract_param_change(raw_text)
    text, concern = _extract_strategy_concern(text)
    applied = False

    if param is not None:
        low, high = ALLOWED_PARAM_RANGES.get(param, (None, None))
        eligible = n_total >= APPLY_MIN_TRADES
        in_range = low is not None and low <= value <= high

        if eligible and in_range:
            old_value = status.get("active_params", {}).get(param)
            apply_param_change(param, value, text)
            send_message(
                f"⚡ <b>MODIFICA APPLICATA</b>\n{param}: {old_value} → {value}\n{text}"
            )
            applied = True
            print(f"[ai_review] modifica applicata: {param} {old_value} -> {value}")
        else:
            reason = "campione insufficiente" if not eligible else "valore proposto fuori dai limiti consentiti"
            text = f"{text}\n(Proposta {param}={value} scartata: {reason}.)"
            print(f"[ai_review] proposta di modifica scartata ({reason}): {param}={value}")

    if concern:
        flag_strategy_concern(concern)
        send_message(
            f"⚠️ <b>PROPOSTA STRUTTURALE - richiede backtest prima di essere attivata</b>\n{concern}\n\n"
            f"Nessun cambiamento applicato: portala in conversazione per un test vero prima di agire."
        )
        print(f"[ai_review] segnalazione strutturale (mai applicata da sola): {concern}")

    set_strategy_note(text)
    if not applied:
        send_message(f"\U0001F4CA <b>Revisione periodica</b>\n{text}")
    mark_reviewed(n_total)
    print(f"[ai_review] revisione pubblicata ({n_total} operazioni totali, {n_new} nuove dall'ultima volta).")
    return True


def main():
    run_review_if_due()


if __name__ == "__main__":
    main()
