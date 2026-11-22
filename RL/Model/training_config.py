"""The capital and the Zerodha delivery charge, locked before the baseline report.

Starting capital is ₹1,00,000. Brokerage on delivery equity is zero.
The statutory rates are the ones on the user's Zerodha calculator:
buy ₹1,000, sell ₹1,100, quantity 1,000, total charges ₹2,328.55.
They are not moved to improve the report.
"""

from __future__ import annotations


STARTING_CAPITAL = 100_000.0

# 0.1% of the buy value and 0.1% of the sell value.
STT_RATE = 0.001
# NSE exchange transaction charge, from 64.47 / 21,00,000.
EXCHANGE_RATE = 0.0000307
# ₹10 per crore.
SEBI_RATE = 0.000001
# 0.015% of the buy value. 150 / 10,00,000.
STAMP_RATE = 0.00015
# 18% of the exchange charge and the SEBI charge. Brokerage is zero.
GST_RATE = 0.18


def _paisa(value: float) -> float:
    return round(value + 0.0, 2)


def delivery_rupees(entry_fill: float, exit_fill: float, shares: int) -> float:
    """Zerodha delivery equity, NSE, on one filled round trip."""
    buy = entry_fill * shares
    sell = exit_fill * shares
    turnover = buy + sell
    stt = _paisa(STT_RATE * turnover)
    exchange = _paisa(EXCHANGE_RATE * turnover)
    sebi = _paisa(SEBI_RATE * turnover)
    stamp = _paisa(STAMP_RATE * buy)
    gst = _paisa(GST_RATE * (exchange + sebi))
    return _paisa(stt + exchange + sebi + stamp + gst)


def require_training_config():
    """The locked book. Capital is ₹1,00,000 and the charge is delivery equity."""
    from Model.baseline import BookConfig, ChargeSchedule

    return BookConfig(STARTING_CAPITAL, ChargeSchedule(0.0, 0.0, delivery=True))
