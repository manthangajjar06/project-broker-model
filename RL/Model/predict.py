"""Step 4. The frozen LightGBM tree, ported from `predict.js`.

The file `RL/RL/src/model/model.txt` is not modified. A missing feature follows
the same decision bits the chart uses.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path


MODEL_PATH = Path(__file__).resolve().parent.parent / "RL" / "src" / "model" / "model.txt"

ACCEPT_AT = 0.55
REJECT_AT = 0.45


@dataclass(frozen=True)
class Tree:
    feature: tuple[int, ...]
    threshold: tuple[float, ...]
    decision: tuple[int, ...]
    left: tuple[int, ...]
    right: tuple[int, ...]
    leaf: tuple[float, ...]
    cat_boundaries: tuple[int, ...]
    cat_threshold: tuple[int, ...]


@dataclass(frozen=True)
class Model:
    trees: tuple[Tree, ...]


def load_model(text: str) -> Model:
    trees = []
    for chunk in re.split(r"\r?\nTree=", text)[1:]:
        block = re.split(r"\r?\n", chunk)
        cat_count = _named_float(block, "num_cat")
        trees.append(Tree(
            feature=_integers(block, "split_feature"),
            threshold=_numbers(block, "threshold"),
            decision=_integers(block, "decision_type"),
            left=_integers(block, "left_child"),
            right=_integers(block, "right_child"),
            leaf=_numbers(block, "leaf_value"),
            cat_boundaries=_integers(block, "cat_boundaries") if cat_count else (0,),
            cat_threshold=_integers(block, "cat_threshold") if cat_count else (),
        ))
    return Model(tuple(trees))


_MODEL_CACHE: dict[str, tuple[int, Model]] = {}


def load_frozen_model(path: Path | None = None) -> Model:
    """Load the frozen zone scorer. Cached by path + mtime for fast repeated saves."""
    target = Path(path or MODEL_PATH).resolve()
    key = str(target)
    mtime_ns = target.stat().st_mtime_ns if target.exists() else -1
    hit = _MODEL_CACHE.get(key)
    if hit is not None and hit[0] == mtime_ns:
        return hit[1]
    model = load_model(target.read_text(encoding="utf-8"))
    _MODEL_CACHE[key] = (mtime_ns, model)
    return model


def predict_probability(model: Model, features: list[float]) -> float:
    margin = 0.0
    for tree in model.trees:
        margin += _tree_score(tree, features)
    return 1 / (1 + math.exp(-margin))


def score_label(probability: float) -> str:
    if probability >= ACCEPT_AT:
        return "accepted"
    if probability <= REJECT_AT:
        return "rejected"
    return "uncertain"


def _tree_score(tree: Tree, features: list[float]) -> float:
    node = 0
    limit = len(tree.feature)
    while 0 <= node < limit:
        child = tree.left[node] if _goes_left(tree, node, _feature_at(features, tree.feature[node])) else tree.right[node]
        if child < 0:
            return tree.leaf[-child - 1]
        node = child
    return 0.0


def _goes_left(tree: Tree, node: int, value: float | None) -> bool:
    decision = tree.decision[node]
    categorical = (decision & 1) != 0
    default_left = (decision & 2) != 0
    missing_type = (decision >> 2) & 3
    missing = value is None or value != value

    if categorical:
        if missing or value < 0:
            return default_left
        index = _js_int32(tree.threshold[node])
        start = tree.cat_boundaries[index] if 0 <= index < len(tree.cat_boundaries) else 0
        end = tree.cat_boundaries[index + 1] if 0 <= index + 1 < len(tree.cat_boundaries) else start
        return _bit_set(tree.cat_threshold[start:end], _js_int32(value))

    feature = 0.0 if value is None else value
    if missing:
        if missing_type == 2:
            return default_left
        feature = 0.0
    return feature <= tree.threshold[node]


def _feature_at(features: list[float], index: int) -> float | None:
    if index < 0 or index >= len(features):
        return None
    return features[index]


def _bit_set(bits: tuple[int, ...], position: int) -> bool:
    word = _urshift(position, 5)
    if word >= len(bits):
        return False
    return (_urshift(bits[word], position & 31) & 1) == 1


def _urshift(value: int, bits: int) -> int:
    return (value & 0xFFFFFFFF) >> bits


def _js_int32(value: float) -> int:
    if value != value or value in (float("inf"), float("-inf")):
        return 0
    truncated = math.trunc(value)
    return (truncated + 2**31) % 2**32 - 2**31


def _numbers(block: list[str], name: str) -> tuple[float, ...]:
    line = _line(block, name)
    if line is None:
        return ()
    text = line[len(name) + 1:].strip()
    if not text:
        return ()
    return tuple(float(part) for part in text.split())


def _integers(block: list[str], name: str) -> tuple[int, ...]:
    return tuple(_js_int32(value) for value in _numbers(block, name))


def _named_float(block: list[str], name: str) -> float:
    line = _line(block, name)
    if line is None:
        return 0.0
    return float(line.split("=", 1)[1])


def _line(block: list[str], name: str) -> str | None:
    prefix = f"{name}="
    for row in block:
        if row.startswith(prefix):
            return row
    return None
