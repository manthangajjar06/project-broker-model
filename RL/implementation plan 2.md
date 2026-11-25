# LightGBM outcome model — implementation plan 2

**Status:** Active build path. Plan 1 ([`implementation plan.md`](implementation%20plan.md) / [`steps.md`](steps.md)) stays the MaskablePPO contract and is not deleted. Plan 2 does not replace Plan 1.
**Target:** From an accepted zone and context knowable at its close, LightGBM predicts the chance the locked plan reaches **target before stop**. On validation, a selective cutoff aims for **80–90%** bounce on kept trades only. Coverage may be low. No live 80–90% is guaranteed.
**Data:** `RL/data`, Nifty 100, 2-hour bars. Daily / weekly / monthly built from those bars up to the decision clock.
**Date locked:** 2026-11-23
**Steps:** [`steps 2.md`](steps%202.md)

Shared foundation (do not rebuild): Plan 1 Steps 1–14 — loaders, zones, frozen zone scorer `model.txt`, clock, HTF builders, `entry.py`, fills, behaviors, memory, baseline, paper costs.

**Two different LightGBMs**

| Model | Job | Labels |
|---|---|---|
| Zone scorer `model.txt` (frozen) | Is this zone accepted? | Historical zone quality (not Plan 2) |
| Plan 2 outcome model (this file) | Will the locked plan bounce? | Auto from later candles |

---

## 1. What Plan 2 builds

### Job 1 — bounce probability (first)

- **Inputs (decision clock only):** zone + 2-hour snapshot + D/W/M encoding + memory of past resolved zones  
- **Labels (automatic from later candles):**  
  - `y_bounce = 1` → target before stop (**true / bounce**)  
  - `y_bounce = 0` → stop first, no-fill, expiry, etc. (**false**)  
  - `behavior` → complete stop, slight breach, UOC touch, base never touched, unresolved  
  - `trade_result` → target, stop, no_fill, …  
- **Both classes are required.** Training on winners only is not allowed.  
- **Model:** LightGBM (not XGBoost on this path).  
- **Entry / stop / target for Job 1:** locked Plan 1 §15 / `entry.py`. The model does not invent prices in Job 1.

### Job 2 — smarter entry / stop (after chart trust)

Optional, after Job 1 review shows systematic misses (e.g. bounce from slightly above entry → `no_fill`):

1. **Rule update** in `entry.py` (needed-area / small upside entry buffer, stop buffer), or  
2. **Hybrid rows:** same feature columns as the outcome CSV; human sets entry (and optionally stop) on the chart; code re-simulates the path and writes labels automatically; or  
3. **Buffer model:** learn entry/stop shift in ATR from near-misses, then re-score bounce %.

Hybrid does **not** mean hand-labeling every feature. Features stay automatic. Only the price(s) may be human for selected zones (prefer `no_fill` / near-miss first). Long-term goal: machine proposes that entry without clicking every zone.

### Job 3 — take / skip (after Jobs 1–2 are trusted)

Take when bounce probability ≥ frozen cutoff (simple rule), or feed that probability into Plan 1 MaskablePPO. Then test 2024+ with weights / memory frozen at end of 2023.

### Optional later — Jev / Laya

External decision models may be used only as an **extra filter or chart assistant** (same frozen question, own probability). They do not replace LightGBM on the numeric outcome rows and are not required for Jobs 1–3.

The React app in `RL/RL` is the review surface (outcome levels on the 2-hour chart). It is not the trainer.

---

## 2. Shared rules (from Plan 1)

- Decision clock / no future bars: Plan 1 §2–§3  
- Zones / acceptance: Plan 1 §4  
- Default entry / stop / target: Plan 1 §15 and `RL/entry.py`  
- Fill / both-touched / time stop: Plan 1 §7  
- Path behaviors: Plan 1 §9  
- Costs / capital: Plan 1 §10  
- Baseline: Plan 1 §12 / `RL/Model/baseline_report.txt`  

---

## 3. Daily, weekly, monthly

Same partial-bar rule as Plan 1 §3. At a zone’s clock the model may use every D/W/M bar closed at or before that clock. Truncated windows are encoded scale-free (no raw rupee identity). Encoding is fixed before the first Plan 2 train and not tuned on test years.

---

## 4. Automatic dataset

One row per accepted zone whose path can be labeled. Artifact: `RL/Model/outcome/outcome_rows.csv` (+ `outcome_meta.json`). Chart slim copy: `RL/RL/public/outcomes.json`.

| Group | Source |
|---|---|
| Features | Snapshot + HTF encoding + memory (decision time only) |
| `plan_entry`, `plan_stop`, `plan_target` | Locked plan (or hybrid human entry when Job 2 hybrid is used) |
| `y_bounce` | 1 if target before stop; else 0 |
| `behavior`, `trade_result` | Path / fill from later candles |
| `symbol`, `decided_at`, `resolved_at`, `split` | Keys and train/val/test |

**Includes:** clean bounces, full stops, slight-breach-then-bounce, base-never-touched, no-fill, and related results. True and false labels both stay in the file.

**Split:** train through **2021**, validation **2022–2023**, test **2024+** (no fitting on test).

**Manual only:** both-touched bars (hand answer or temporary stop-first until 1-minute data). Not full hand-labeling of bounce for every zone.

No future bar may change features. A later candle may only affect labels.

---

## 5. Training (LightGBM)

- Binary LightGBM → P(bounce)  
- Optional second LightGBM → path behavior  
- Hyperparameters locked before the run; not searched on 2024+  
- Memory neighbors: only records already resolved  

**Selective threshold (validation only):** freeze a minimum `p` so kept validation trades bounce in **80–90%** when possible. Report coverage and average R vs baseline. If no cutoff lands in band, say so — do not use test years to force a pass.

---

## 6. Chart review

On `RL/RL`, outcome review mode:

- Jump zone by zone  
- Draw entry / stop / target  
- Show `y_bounce`, `behavior`, `trade_result`, split  

User confirms before Job 2 buffers/hybrid or Job 3 take/skip. Chart review of labels can start once rows exist; model % appears after Job 1 train.

---

## 7. Build order

See [`steps 2.md`](steps%202.md).

1. Reuse Plan 1 Steps 1–14 (done)  
2. Automatic outcome dataset (true + false)  
3. Train LightGBM + freeze validation threshold  
4. Chart review  
5. Optional Job 2: `entry.py` tweak / hybrid human entry / buffer model  
6. Take/skip + test 2024+  
7. Optional Jev/Laya filter (never required)  

---

## 8. What Plan 2 does not do

- Delete Plan 1 or Steps 1–14  
- Train the first outcome model on winners only  
- Invent entry/stop/target in Job 1 (locked plan unless Job 2 says otherwise)  
- Guarantee 80–90% live  
- Tune on test years  
- Replace numeric LightGBM with Jev/Laya as the core model  
