"""Hand call when one 2-hour candle trades both the stop and the target.

Training does not guess. The CMD prints the zone and waits for stop or
target. Answers are stored so a later pass on the same candle does not ask
again. After the model is built, temporary 1-minute data replaces these
calls and is what justifies which price printed first.
"""

from __future__ import annotations

import json
from pathlib import Path

from Model.fill import STOP, TARGET, BothTouched


ANSWERS_PATH = Path(__file__).with_name("both_touched_answers.json")


def answer_key(hit: BothTouched) -> str:
    """One key per candle and plan. Re-asks when the prices differ."""
    return (
        f"{hit.symbol}|{hit.date}|{hit.time}|"
        f"{hit.entry:.6f}|{hit.stop:.6f}|{hit.target:.6f}"
    )


def load_answers(path: Path | None = None) -> dict[str, str]:
    file = path or ANSWERS_PATH
    if not file.is_file():
        return {}
    raw = json.loads(file.read_text(encoding="utf-8"))
    return {str(key): _normalize(value) for key, value in raw.items()}


def save_answers(answers: dict[str, str], path: Path | None = None) -> None:
    file = path or ANSWERS_PATH
    ordered = {key: answers[key] for key in sorted(answers)}
    file.write_text(json.dumps(ordered, indent=2) + "\n", encoding="utf-8")


def resolve_both(
    hit: BothTouched,
    answers: dict[str, str] | None = None,
    path: Path | None = None,
    ask=None,
) -> str:
    """Return stop or target. Ask once in CMD when this candle is new."""
    store = answers if answers is not None else load_answers(path)
    key = answer_key(hit)
    if key in store:
        return store[key]

    prompt = (
        f"\nBOTH TOUCHED\n"
        f"  stock   {hit.symbol}\n"
        f"  date    {hit.date}\n"
        f"  time    {hit.time}\n"
        f"  entry   {hit.entry}\n"
        f"  stop    {hit.stop}\n"
        f"  target  {hit.target}\n"
        f"Which printed first? type stop or target: "
    )
    reader = ask if ask is not None else input
    while True:
        raw = reader(prompt)
        choice = _normalize(raw)
        if choice in (STOP, TARGET):
            store[key] = choice
            save_answers(store, path)
            print(f"saved {choice} for {hit.symbol} {hit.date} {hit.time}", flush=True)
            return choice
        print("type stop or target", flush=True)


class BatchBothTouched:
    """Resolve both-touched from the answers file without blocking on CMD.

    Hand answers win. Missing keys take the Plan 1 stop-first default used by
    the locked baseline when the walk does not ask. Those keys are listed so
    a later 1-minute pass can replace them. They are not written into the
    hand-answer file.
    """

    def __init__(self, path: Path | None = None):
        self.path = path
        self.answers = load_answers(path)
        self.stop_first: list[str] = []

    def __call__(self, hit: BothTouched) -> str:
        key = answer_key(hit)
        if key in self.answers:
            return self.answers[key]
        if key not in self.stop_first:
            self.stop_first.append(key)
            print(
                f"both-touched stop-first (no hand answer): "
                f"{hit.symbol} {hit.date} {hit.time}",
                flush=True,
            )
        return STOP


def _normalize(value: str) -> str:
    text = str(value).strip().lower()
    if text in ("sl", "stop", "stop_loss", "stoploss"):
        return STOP
    if text in ("tp", "target", "tgt"):
        return TARGET
    return text
