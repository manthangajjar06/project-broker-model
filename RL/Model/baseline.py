"""Step 11. The locked 2R baseline, before any policy is trained.

Every accepted zone in 2022 and 2023 is armed with `entryPrice`, a stop at
the UOC low, and a target 2R above that entry. One bar that hits the stop
and the target stops the run and names the stock, the date, and the time.
The path behavior is the Step 10 label.

The report is written twice: every armed zone, and the zones `entry.py`
would allow. The paper book is a third pass over every armed zone. It
risks 1% of current equity, carries one balance across symbols, and takes
only the first name when several signal at the same close.

Slippage is `0.05 * atr_14` on the entry and again on a normal exit. A
09:15 open through the stop or the target sells at that open, with no
second slippage. The rupee charge is the Zerodha delivery schedule. The
starting capital is ₹1,00,000.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Sequence

from Model.behavior import (
    BASE_NEVER_TOUCHED,
    COMPLETE_STOP,
    PATH_BARS,
    SLIGHT_BREACH,
    UNRESOLVED,
    UOC_TOUCH,
    PathCandle,
    label_path,
)
from Model.clock import known_clock
from Model.fill import (
    CANCELLED,
    EXPIRY,
    NO_FILL,
    STOP,
    TARGET,
    TIME_STOP,
    ClosedCandle,
    Walk,
    begin,
    order_is_marketable,
    reveal,
)
from Model.higher import HigherBook
from Model.load import DATA_DIR, Bar, csv_path, load_bars
from Model.predict import load_frozen_model
from Model.score import accepted_zones, score_zones
from Model.zones import Zone
from entry import entry_is_due, required_plan


SLIPPAGE_ATR = 0.05
RISK_FRACTION = 0.01
VALIDATION_YEARS = (2022, 2023)
FILLED = ("win", "loss", "time_stop")
BEHAVIORS = (COMPLETE_STOP, SLIGHT_BREACH, UOC_TOUCH, BASE_NEVER_TOUCHED, UNRESOLVED)
BUCKETS = ("0.55-0.65", "0.65-0.75", "0.75+")
CUTS = ("all", "entry_py")


@dataclass(frozen=True)
class ChargeSchedule:
    """Round-trip rupees on a filled trade. A no-fill is not charged.

    `delivery` uses the Zerodha delivery schedule in the training config.
    The flat amount and the turnover rate are the fixture used by tests.
    """

    flat_rupees: float
    turnover_rate: float
    delivery: bool = False

    def rupees(self, entry_fill: float, exit_fill: float, shares: int) -> float:
        if self.delivery:
            from Model.training_config import delivery_rupees

            return delivery_rupees(entry_fill, exit_fill, shares)
        turnover = (entry_fill + exit_fill) * shares
        return self.flat_rupees + self.turnover_rate * turnover


@dataclass(frozen=True)
class BookConfig:
    starting_capital: float
    charge: ChargeSchedule


@dataclass(frozen=True)
class LockedPlan:
    entry: float
    stop: float
    target: float
    armed: bool


@dataclass(frozen=True)
class Measured:
    placed: bool
    plan: LockedPlan
    outcome: str
    behavior: str
    raw_entry: float | None
    raw_exit: float | None
    finished_index: int | None
    gap_exit: bool = False


@dataclass(frozen=True)
class ValidationTrade:
    symbol: str
    clock: datetime
    exit_clock: datetime | None
    year: int
    probability: float
    entry_py: bool
    placed: bool
    outcome: str
    behavior: str
    plan_entry: float
    plan_stop: float
    atr: float
    raw_entry: float | None
    raw_exit: float | None
    gap_exit: bool = False


@dataclass(frozen=True)
class BucketReport:
    no_fill: int
    win: int
    loss: int
    time_stop: int
    unresolved: int
    filled: int
    win_rate: float | None
    average_r: float | None
    trade_count: int
    r_count: int


@dataclass(frozen=True)
class CutReport:
    offered: int
    armed: int
    unarmed: int
    no_fill: int
    win: int
    loss: int
    time_stop: int
    unresolved: int
    filled: int
    win_rate: float | None
    average_r: float | None
    trade_count: int
    r_count: int
    behaviors: dict[str, int]
    buckets: dict[str, BucketReport]


@dataclass(frozen=True)
class BookFill:
    symbol: str
    clock: datetime
    exit_clock: datetime | None
    shares: int
    outcome: str
    pnl: float
    equity: float


@dataclass(frozen=True)
class BookResult:
    starting_capital: float
    ending_equity: float
    max_drawdown: float
    fills: tuple[BookFill, ...]
    busy_skipped: int
    masked: int
    equity_through_2022: float
    equity_through_2023: float


def locked_plan(entry: float, uoc_low: float) -> LockedPlan:
    """Stop at the UOC low. Target is 2R. A stop that is not below the entry is masked."""
    stop = uoc_low
    if not (stop < entry):
        return LockedPlan(entry, stop, entry, False)
    distance = entry - stop
    return LockedPlan(entry, stop, entry + 2 * distance, True)


def risk_budget(equity: float) -> float:
    """One percent of equity. Dividing by 100 keeps an integer equity exact."""
    return equity / 100


def share_count(equity: float, cash: float, entry: float, stop: float, atr: float) -> int:
    """Whole shares that risk 1% at the plan prices and fit in the cash.

    The cash check uses the plan entry plus the locked slippage. One share
    that risks more than 1%, or costs more than the cash, is zero shares.
    """
    if entry != entry or stop != stop or atr != atr:
        return 0
    if atr <= 0 or equity <= 0 or cash <= 0 or not (stop < entry):
        return 0
    distance = entry - stop
    budget = risk_budget(equity)
    if distance > budget:
        return 0
    planned = int(budget // distance)
    unit = entry + SLIPPAGE_ATR * atr
    if unit <= 0:
        return 0
    affordable = int(cash // unit)
    if affordable < 1 or planned < 1:
        return 0
    return min(planned, affordable)


def sized_shares(
    equity: float,
    cash: float,
    plan_entry: float,
    plan_stop: float,
    atr: float,
    raw_entry: float | None,
) -> int:
    """Plan-sized shares, reduced again when the actual fill costs more than the cash."""
    count = share_count(equity, cash, plan_entry, plan_stop, atr)
    if count < 1 or raw_entry is None:
        return count
    unit = raw_entry + SLIPPAGE_ATR * atr
    if unit <= 0:
        return 0
    affordable = int(cash // unit)
    return max(0, min(count, affordable))


def slipped_fills(
    raw_entry: float,
    raw_exit: float,
    atr: float,
    gap_exit: bool = False,
) -> tuple[float, float]:
    """A session-open gap sells at the open. That exit does not take slippage again."""
    slip = SLIPPAGE_ATR * atr
    entry_fill = raw_entry + slip
    if gap_exit:
        return entry_fill, raw_exit
    return entry_fill, raw_exit - slip


def trade_pnl(
    raw_entry: float,
    raw_exit: float,
    atr: float,
    shares: int,
    charge: ChargeSchedule,
    gap_exit: bool = False,
) -> float:
    """Rupee result after slippage and the round-trip charge, in paise."""
    entry_fill, exit_fill = slipped_fills(raw_entry, raw_exit, atr, gap_exit)
    fee = round(charge.rupees(entry_fill, exit_fill, shares), 2)
    return round((exit_fill - entry_fill) * shares - fee, 2)


def r_after_cost(
    plan_entry: float,
    plan_stop: float,
    raw_entry: float,
    raw_exit: float,
    atr: float,
    shares: int,
    charge: ChargeSchedule,
    gap_exit: bool = False,
) -> float | None:
    """Net rupees divided by the planned risk. The denominator is entry minus stop."""
    if shares < 1 or not (plan_stop < plan_entry):
        return None
    risk = (plan_entry - plan_stop) * shares
    if risk <= 0:
        return None
    return trade_pnl(raw_entry, raw_exit, atr, shares, charge, gap_exit) / risk


def measure_path(
    entry: float,
    uoc_low: float,
    uoc_high: float,
    decision_close: float,
    atr: float | None,
    candles: Sequence[ClosedCandle],
    symbol: str = "",
    ask_when_both: bool = False,
) -> Measured:
    """Drive the locked plan. Hold every bar. A later candle is not used to reprice it."""
    plan = locked_plan(entry, uoc_low)
    window = list(candles)[:PATH_BARS]
    behavior = _behavior(window, uoc_low, uoc_high, decision_close, atr)
    atr_ok = atr is not None and atr == atr and atr > 0
    if not plan.armed or not atr_ok:
        return Measured(False, plan, "unarmed", behavior, None, None, None)

    walk, finished = _drive(plan, decision_close, window, symbol, ask_when_both)
    if finished is None or walk.result is None:
        return Measured(True, plan, "unresolved", behavior, None, None, None, False)
    raw_entry, raw_exit = _raw_prices(walk)
    return Measured(
        True,
        plan,
        _outcome(walk.result),
        behavior,
        raw_entry,
        raw_exit,
        finished.index,
        walk.gap_exit,
    )


def entry_py_passes(bars: Sequence[Bar], zone: Zone, probability: float) -> bool:
    """True when entry.py has a plan and the file reaches the 6th session.

    The 2R prices are not required to equal the entry.py prices. Day 6 is
    read from session dates only. The prices after the signal are not read.
    """
    if required_plan(bars, zone, probability) is None:
        return False
    if not bars:
        return False
    return entry_is_due(bars, zone, bars[-1].date)


def list_symbols(data_dir: Path | None = None) -> list[str]:
    folder = data_dir or DATA_DIR
    prefix = "NSE_"
    suffix = "_2hour.csv"
    symbols = []
    for path in sorted(folder.glob(f"{prefix}*{suffix}")):
        symbols.append(path.name[len(prefix) : -len(suffix)])
    return symbols


def collect_validation(data_dir: Path | None = None) -> tuple[int, tuple[ValidationTrade, ...]]:
    """Accepted zones whose decision clock falls in 2022 or 2023.

    A short file is skipped until the Step 5 gate allows a decision.
    The frozen tree is loaded once.
    """
    folder = data_dir or DATA_DIR
    model = load_frozen_model()
    symbols = list_symbols(folder)
    trades: list[ValidationTrade] = []
    total = len(symbols)
    print(f"scoring {total} symbols", flush=True)
    for index, symbol in enumerate(symbols, start=1):
        print(f"{index}/{total} {symbol}", flush=True)
        bars = load_bars(csv_path(symbol, folder))
        higher = HigherBook()
        higher.run_model(symbol, bars)
        try:
            for scored in accepted_zones(score_zones(bars, model)):
                zone = scored.zone
                signal = bars[zone.end]
                clock = known_clock(signal)
                if clock is None or clock.year not in VALIDATION_YEARS:
                    continue
                if not higher.allows_decision(clock):
                    continue
                later = bars[zone.end + 1 : zone.end + 1 + PATH_BARS]
                candles = [
                    ClosedCandle(
                        zone.end + offset,
                        bar.open,
                        bar.high,
                        bar.low,
                        bar.close,
                        session_open=bar.time == "09:15:00",
                        date=bar.date,
                        time=bar.time,
                    )
                    for offset, bar in enumerate(later, start=1)
                ]
                measured = measure_path(
                    scored.entry,
                    zone.uoc_low,
                    zone.uoc_high,
                    signal.close,
                    signal.atr_14,
                    candles,
                    symbol=symbol,
                    ask_when_both=True,
                )
                exit_clock = None
                if measured.finished_index is not None and measured.finished_index < len(bars):
                    exit_bar = bars[measured.finished_index]
                    exit_clock = known_clock(exit_bar) or exit_bar.open_at()
                atr = signal.atr_14 if signal.atr_14 is not None else 0.0
                trades.append(
                    ValidationTrade(
                        symbol=symbol,
                        clock=clock,
                        exit_clock=exit_clock,
                        year=clock.year,
                        probability=scored.probability,
                        entry_py=entry_py_passes(bars, zone, scored.probability),
                        placed=measured.placed,
                        outcome=measured.outcome,
                        behavior=measured.behavior,
                        plan_entry=measured.plan.entry,
                        plan_stop=measured.plan.stop,
                        atr=atr,
                        raw_entry=measured.raw_entry,
                        raw_exit=measured.raw_exit,
                        gap_exit=measured.gap_exit,
                    )
                )
        finally:
            higher.close_stock()
    trades.sort(key=lambda item: (item.clock, item.symbol))
    return len(symbols), tuple(trades)


def independent_r(trade: ValidationTrade, config: BookConfig) -> float | None:
    """R sized as if this zone were the only one, at the starting capital."""
    if trade.outcome not in FILLED or trade.raw_entry is None or trade.raw_exit is None:
        return None
    shares = sized_shares(
        config.starting_capital,
        config.starting_capital,
        trade.plan_entry,
        trade.plan_stop,
        trade.atr,
        trade.raw_entry,
    )
    return r_after_cost(
        trade.plan_entry,
        trade.plan_stop,
        trade.raw_entry,
        trade.raw_exit,
        trade.atr,
        shares,
        config.charge,
        trade.gap_exit,
    )


def summarize(trades: Sequence[ValidationTrade], config: BookConfig) -> dict[int, dict[str, CutReport]]:
    reports: dict[int, dict[str, CutReport]] = {}
    for year in VALIDATION_YEARS:
        reports[year] = {}
        for cut in CUTS:
            chosen = [trade for trade in trades if trade.year == year and _in_cut(trade, cut)]
            reports[year][cut] = _cut_report(chosen, config)
    return reports


def run_book(trades: Sequence[ValidationTrade], config: BookConfig) -> BookResult:
    """One paper account. Flat at the start of 2022. One position at a time."""
    ordered = sorted(trades, key=lambda item: (item.clock, item.symbol))
    equity = config.starting_capital
    peak = equity
    max_drawdown = 0.0
    flat_clock: datetime | None = None
    fills: list[BookFill] = []
    busy_skipped = 0
    masked = 0
    through = {2022: equity, 2023: equity}

    for trade in ordered:
        if trade.year not in VALIDATION_YEARS or not trade.placed:
            continue
        if flat_clock is not None and trade.clock < flat_clock:
            busy_skipped += 1
            continue
        shares = sized_shares(equity, equity, trade.plan_entry, trade.plan_stop, trade.atr, trade.raw_entry)
        if shares < 1:
            masked += 1
            continue
        flat_clock = trade.exit_clock if trade.exit_clock is not None else datetime.max
        pnl = 0.0
        if trade.outcome in FILLED and trade.raw_entry is not None and trade.raw_exit is not None:
            pnl = trade_pnl(
                trade.raw_entry,
                trade.raw_exit,
                trade.atr,
                shares,
                config.charge,
                trade.gap_exit,
            )
        equity = round(equity + pnl, 2)
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, round(peak - equity, 2))
        fills.append(
            BookFill(trade.symbol, trade.clock, trade.exit_clock, shares, trade.outcome, pnl, equity)
        )
        if trade.exit_clock is not None:
            if trade.exit_clock <= _year_end(2022):
                through[2022] = equity
            if trade.exit_clock <= _year_end(2023):
                through[2023] = equity

    return BookResult(
        starting_capital=config.starting_capital,
        ending_equity=equity,
        max_drawdown=max_drawdown,
        fills=tuple(fills),
        busy_skipped=busy_skipped,
        masked=masked,
        equity_through_2022=through[2022],
        equity_through_2023=through[2023],
    )


def report_text(
    trades: Sequence[ValidationTrade],
    config: BookConfig,
    symbols: int,
) -> str:
    """The 2022 and 2023 report. Rendering it twice produces the same text."""
    cuts = summarize(trades, config)
    book = run_book(trades, config)
    lines = [
        "step 11 baseline",
        "plan entryPrice, stop at the UOC low, target 2R",
        "same bar stop and target stops the run and asks",
        f"slippage_atr {SLIPPAGE_ATR:.2f}",
        f"risk_fraction {RISK_FRACTION:.2f}",
        f"starting_capital {_money(config.starting_capital)}",
        *_charge_lines(config),
        f"symbols {symbols}",
    ]
    for year in VALIDATION_YEARS:
        lines.append(f"year {year}")
        for cut in CUTS:
            lines.extend(_cut_lines(cut, cuts[year][cut]))
    lines.extend(
        [
            "book",
            f"orders {len(book.fills)}",
            f"busy_skipped {book.busy_skipped}",
            f"masked {book.masked}",
            f"ending_equity {_money(book.ending_equity)}",
            f"max_drawdown {_money(book.max_drawdown)}",
            f"equity_through_2022 {_money(book.equity_through_2022)}",
            f"equity_through_2023 {_money(book.equity_through_2023)}",
        ]
    )
    return "\n".join(lines) + "\n"


def _drive(
    plan: LockedPlan,
    decision_close: float,
    candles: Sequence[ClosedCandle],
    symbol: str = "",
    ask_when_both: bool = False,
) -> tuple[Walk, ClosedCandle | None]:
    signal_index = candles[0].index - 1 if candles else 0
    walk = begin(
        plan.entry,
        plan.stop,
        plan.target,
        decision_close,
        signal_index,
        ask_when_both=ask_when_both,
        symbol=symbol,
    )
    finished = None
    for candle in candles:
        if walk.phase == "done":
            break
        walk = reveal(walk, candle)
        if walk.phase == "done":
            finished = candle
            break
    return walk, finished


def _behavior(
    candles: Sequence[ClosedCandle],
    uoc_low: float,
    uoc_high: float,
    decision_close: float,
    atr: float | None,
) -> str:
    if atr is None or atr != atr or atr <= 0:
        return UNRESOLVED
    path = [PathCandle(candle.high, candle.low, candle.close) for candle in candles]
    return label_path(path, uoc_low, uoc_high, decision_close, atr).label


def _outcome(result: str) -> str:
    if result == TARGET:
        return "win"
    if result == STOP:
        return "loss"
    if result == TIME_STOP:
        return "time_stop"
    if result in (NO_FILL, EXPIRY, CANCELLED):
        return "no_fill"
    raise ValueError(f"the baseline does not {result}")


def filled_prices(walk: Walk) -> tuple[float | None, float | None]:
    """The entry and exit that R uses. A same-bar stop still entered at the plan entry."""
    return _raw_prices(walk)


def _raw_prices(walk: Walk) -> tuple[float | None, float | None]:
    """A limit fills at the plan entry. A same-bar stop still entered there.

    `fill.py` records that same-bar stop's fill at the stop. The result is
    the stop, and the entry of the R formula stays the plan entry.
    A marketable order fills at the next open, which is the recorded fill.
    """
    if walk.exit_price is None or walk.result in (NO_FILL, EXPIRY, CANCELLED):
        return None, None
    if order_is_marketable(walk.entry, walk.reference_close):
        if walk.fill_price is None:
            return None, None
        return walk.fill_price, walk.exit_price
    return walk.entry, walk.exit_price


def _in_cut(trade: ValidationTrade, cut: str) -> bool:
    if cut == "all":
        return True
    if cut == "entry_py":
        return trade.entry_py
    raise ValueError(cut)


def _bucket(probability: float) -> str:
    if probability < 0.65:
        return "0.55-0.65"
    if probability < 0.75:
        return "0.65-0.75"
    return "0.75+"


def _cut_report(trades: Sequence[ValidationTrade], config: BookConfig) -> CutReport:
    outcomes = {name: 0 for name in ("unarmed", "no_fill", "win", "loss", "time_stop", "unresolved")}
    behaviors = {name: 0 for name in BEHAVIORS}
    grouped: dict[str, list[ValidationTrade]] = {name: [] for name in BUCKETS}
    rs: list[float] = []
    for trade in trades:
        outcomes[trade.outcome] = outcomes.get(trade.outcome, 0) + 1
        behaviors[trade.behavior] = behaviors.get(trade.behavior, 0) + 1
        grouped.setdefault(_bucket(trade.probability), []).append(trade)
        realized = independent_r(trade, config)
        if realized is not None:
            rs.append(realized)
    filled = outcomes["win"] + outcomes["loss"] + outcomes["time_stop"]
    return CutReport(
        offered=len(trades),
        armed=sum(1 for trade in trades if trade.placed),
        unarmed=outcomes["unarmed"],
        no_fill=outcomes["no_fill"],
        win=outcomes["win"],
        loss=outcomes["loss"],
        time_stop=outcomes["time_stop"],
        unresolved=outcomes["unresolved"],
        filled=filled,
        win_rate=(outcomes["win"] / filled) if filled else None,
        average_r=(sum(rs) / len(rs)) if rs else None,
        trade_count=filled,
        r_count=len(rs),
        behaviors=behaviors,
        buckets={name: _bucket_report(grouped.get(name, []), config) for name in BUCKETS},
    )


def _bucket_report(trades: Sequence[ValidationTrade], config: BookConfig) -> BucketReport:
    outcomes = {name: 0 for name in ("no_fill", "win", "loss", "time_stop", "unresolved")}
    rs: list[float] = []
    for trade in trades:
        if trade.outcome in outcomes:
            outcomes[trade.outcome] += 1
        realized = independent_r(trade, config)
        if realized is not None:
            rs.append(realized)
    filled = outcomes["win"] + outcomes["loss"] + outcomes["time_stop"]
    return BucketReport(
        no_fill=outcomes["no_fill"],
        win=outcomes["win"],
        loss=outcomes["loss"],
        time_stop=outcomes["time_stop"],
        unresolved=outcomes["unresolved"],
        filled=filled,
        win_rate=(outcomes["win"] / filled) if filled else None,
        average_r=(sum(rs) / len(rs)) if rs else None,
        trade_count=filled,
        r_count=len(rs),
    )


def _cut_lines(cut: str, report: CutReport) -> list[str]:
    lines = [
        f"cut {cut}",
        f"offered {report.offered}",
        f"armed {report.armed}",
        f"unarmed {report.unarmed}",
        f"no_fill {report.no_fill}",
        f"win {report.win}",
        f"loss {report.loss}",
        f"time_stop {report.time_stop}",
        f"unresolved {report.unresolved}",
        f"filled {report.filled}",
        f"win_rate {_rate(report.win_rate)}",
        f"average_r {_rate(report.average_r)}",
        f"trade_count {report.trade_count}",
        f"r_count {report.r_count}",
    ]
    for name in BEHAVIORS:
        lines.append(f"behavior {name} {report.behaviors.get(name, 0)}")
    for name in BUCKETS:
        bucket = report.buckets[name]
        lines.append(
            " ".join(
                [
                    f"bucket {name}",
                    f"no_fill {bucket.no_fill}",
                    f"win {bucket.win}",
                    f"loss {bucket.loss}",
                    f"time_stop {bucket.time_stop}",
                    f"unresolved {bucket.unresolved}",
                    f"filled {bucket.filled}",
                    f"win_rate {_rate(bucket.win_rate)}",
                    f"average_r {_rate(bucket.average_r)}",
                    f"trade_count {bucket.trade_count}",
                ]
            )
        )
    return lines


def _rate(value: float | None) -> str:
    if value is None:
        return "na"
    return f"{value:.6f}"


def _charge_lines(config: BookConfig) -> list[str]:
    charge = config.charge
    if not charge.delivery:
        return [
            f"flat_rupees {_money(charge.flat_rupees)}",
            f"turnover_rate {charge.turnover_rate:.10f}",
        ]
    return [
        "charge zerodha_delivery_nse",
        "brokerage 0.00",
        "stt_each_side 0.001",
        "exchange_turnover 0.0000307",
        "sebi_turnover 0.000001",
        "stamp_buy 0.00015",
        "gst_on_exchange_and_sebi 0.18",
    ]


def _money(value: float) -> str:
    return f"{value:.2f}"


def _year_end(year: int) -> datetime:
    return datetime(year, 12, 31, 15, 30)
