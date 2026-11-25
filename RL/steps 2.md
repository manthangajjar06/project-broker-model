# Implementation steps 2 — LightGBM outcome model

**Contract:** [`implementation plan 2.md`](implementation%20plan%202.md)  
**Plan 1 (unchanged):** [`implementation plan.md`](implementation%20plan.md) · [`steps.md`](steps.md)  
**Status:** A1 dataset path is live (`outcome_rows.csv` / meta). Chart review UI + slim `outcomes.json` exist for label inspection. A2+ not started until A1 is verified complete for the agreed universe. Algorithm = **LightGBM**. Labels = **automatic** (bounce true **and** false). Plan 1 Steps 1–14 stay done.

A Plan 2 step starts only after the previous Plan 2 step is verified. Do not patch a failed check inside a later step. After any change to a finished Plan 2 step, re-verify that step and every Plan 2 step after it.

Code lives under `RL/Model/` (and chart under `RL/RL/`). Reads `RL/data`. Reuses Plan 1 ports. Does not import live indicator, cron, or Telegram. Zone scorer `model.txt` stays frozen (different job from the outcome model).

---

## Foundation (Plan 1 — already done)

Steps 1–14 in [`steps.md`](steps.md): load, clock, zones, features/tree, HTF, snapshot, `entry.py`, one plan, fills, path behaviors, baseline, memory, reward, environment.

**Verified when:** Plan 1 stays green. Plan 2 does not rewrite those steps unless a shared bug forces a fix (then re-verify Plan 1 from that step forward).

---

## Step A1. Automatic outcome dataset

For each accepted zone, one row:

- **Features** at the decision clock: Step 6 snapshot, D/W/M encoding, memory when ready  
- **Plan prices:** locked §15 entry / stop / target (Job 1)  
- **Labels from later candles only:**  
  - `y_bounce` — 1 target-before-stop, 0 otherwise (**include both**)  
  - `behavior` — Step 10 path  
  - `trade_result` — target / stop / no_fill / …  

Include full stops, slight-breach-then-bounce, clean bounces, base-never-touched, no-fill. Do **not** drop losers.

No hand labels except both-touched (Plan 1 ask / answers; temporary stop-first until 1-minute data if needed).

**Split:** train through 2021 · val 2022–2023 · test 2024+ held out.

**Artifacts:** `RL/Model/outcome/outcome_rows.csv`, `outcome_meta.json`. Optional chart slim: `RL/RL/public/outcomes.json`.

**Verified when:**

- Editing a candle after the clock does not change features  
- Labels match fill/behavior rules on hand-checked paths  
- Training rows have no decision year ≥ 2022  
- Both `y_bounce = 1` and `y_bounce = 0` appear in meaningful counts  

**Code (current):** `Model/outcome_dataset.py`, `Model/htf_encode.py`, `Model/run_outcome_dataset.py`, `Model/tests/test_outcome_dataset.py`. Feature width locked in code (snapshot + memory + HTF). Meta logs both-touched policy.

---

## Step A2. Train LightGBM outcome model

Train LightGBM on the train split → P(bounce). Optional second LightGBM for behavior. Hyperparameters locked before the run. No 2024+ rows in fit.

**Verified when:** model file + locked config on disk; train log shows no test-year fitting.

---

## Step A3. Selective threshold on validation

On 2022–2023 only, freeze a cutoff so among `p ≥ cutoff` the bounce rate is in **80–90%** when possible. Report coverage and average R vs Step 11 baseline. If no cutoff lands in band, write that result — do not use test years.

**Verified when:** frozen cutoff + validation bounce / coverage / R reproduce on re-run with no code change.

---

## Step A4. Chart review on `RL/RL`

Review zones one by one: entry / stop / target, labels (`y_bounce`, `behavior`, `trade_result`), and after A2 model probability. Sample must include winners, full stops, slight-breach, and no-fill.

**Already in place for labels:** outcome review mode, `outcomes.json` loader, level drawing on the 2-hour chart. Wire model % after A2.

**Verified when:** user confirms an agreed sample is worth continuing to Job 2 / Job 3.

---

## Step A5. Optional smarter entry / stop (only after A4)

Pick one or more, in order of need:

| Path | What |
|---|---|
| **A5a** | Update `entry.py` (needed-area / small entry buffer, stop buffer) then rebuild dataset |
| **A5b** | Hybrid: human sets entry (optional stop) on chart for selected zones; same features; auto re-simulate labels into outcome rows |
| **A5c** | Learn ATR buffers from near-misses; re-score bounce % before changing the frozen cutoff |

Long-term: machine proposes the Job 2 entry so hybrid clicks shrink over time.

**Verified when:** buffer / hybrid rules are written in Plan 2 wording; a later candle cannot change the entry/stop decided at the clock; labels still auto from path after prices are set.

---

## Step A6. Take / skip and test

Take when `p ≥` frozen cutoff, **or** feed probability into Plan 1 MaskablePPO. Run Step 16-style test walk on 2024+ with memory / weights frozen at end of 2023.

**Verified when:** published test report has one row per test year for the high-confidence subset; frozen artifacts contain no test-year training labels.

---

## Step A7. Optional Jev / Laya (never required)

Side filter or chart assistant only. Same frozen question; own score. Does not replace LightGBM on numeric rows. Skip unless explicitly started after A6 or in parallel as research.

**Verified when:** if used, its role is documented as filter-only and does not change Job 1 train labels.

---

## Order reminder

1. A1 dataset (true + false) → 2. A2 LightGBM → 3. A3 threshold → 4. A4 chart → 5. A5 entry/buffers/hybrid (optional) → 6. A6 take/skip + test → 7. A7 Jev/Laya (optional)

Plan 1 Step 15 PPO remains in [`steps.md`](steps.md) and is not erased by this list.
