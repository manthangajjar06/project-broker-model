"""Observation vector for Step 15.

The network sees the Step 6 snapshot context plus the Step 12 memory
summary. Missing values are 0. Raw prices stay out.
"""

from __future__ import annotations

from datetime import datetime
from typing import Sequence

import numpy as np

from Model.behavior import (
    BASE_NEVER_TOUCHED,
    COMPLETE_STOP,
    SLIGHT_BREACH,
    UOC_TOUCH,
)
from Model.memory import BEHAVIORS, Memory, MemorySummary, context_of
from Model.snapshot import Snapshot
from entry import Plan


BEHAVIOR_INDEX = {
    COMPLETE_STOP: 0,
    SLIGHT_BREACH: 1,
    UOC_TOUCH: 2,
    BASE_NEVER_TOUCHED: 3,
}

MEMORY_WIDTH = len(BEHAVIORS) * 2
# context_of length is measured once from a real snapshot in tests; the
# pad below covers the memory summary that follows it.
CONTEXT_WIDTH = 85
OBS_WIDTH = CONTEXT_WIDTH + MEMORY_WIDTH


def observation_of(
    snapshot: Snapshot | None,
    plan: Plan | None,
    close: float,
    atr: float | None,
    memory: Memory,
    at: datetime,
) -> np.ndarray:
    """One float vector. Empty snapshot is zeros."""
    if snapshot is None:
        context: tuple[float | None, ...] = (None,) * CONTEXT_WIDTH
    else:
        context = context_of(snapshot, plan, close, atr)
        if len(context) != CONTEXT_WIDTH:
            raise ValueError(f"context width is {len(context)}, expected {CONTEXT_WIDTH}")
    summary = memory.summary(context, at) if snapshot is not None else None
    return np.asarray([*_filled(context), *_memory_values(summary)], dtype=np.float32)


def memory_vector(summary: MemorySummary | None) -> np.ndarray:
    return np.asarray(_memory_values(summary), dtype=np.float32)


def behavior_id(label: str) -> int:
    if label not in BEHAVIOR_INDEX:
        raise ValueError(f"unknown behavior {label}")
    return BEHAVIOR_INDEX[label]


def _memory_values(summary: MemorySummary | None) -> list[float]:
    if summary is None:
        return [0.0] * MEMORY_WIDTH
    rows = (
        summary.complete_stop,
        summary.slight_breach,
        summary.uoc_touch,
        summary.base_never_touched,
    )
    values: list[float] = []
    for row in rows:
        values.append(float(row.share))
        values.append(0.0 if row.average_r is None else float(row.average_r))
    return values


def _filled(values: Sequence[float | None]) -> list[float]:
    return [0.0 if value is None or value != value else float(value) for value in values]
