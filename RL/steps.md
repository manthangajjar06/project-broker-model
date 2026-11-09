# RL Zone Agent — Implementation Steps Tracker

**Source plan:** [`rl_architecture_plan_v2.md`](rl_architecture_plan_v2.md)  
**Rule:** Move to the next step only when the previous step is **complete** and its gate is **passed**.  
**Rule:** Do not start any step’s implementation until the user explicitly approves that step.

| Field | Value |
|-------|-------|
| Overall status | **Awaiting approval to begin Step 0** |
| Current step | — |
| Last completed | — |
| Last updated | 2026-11-08 |

---

## How to use this file

1. User reviews the step and says **approve Step N** (or equivalent).
2. Agent implements only that step, then updates Status / Gate / Notes here.
3. User reviews the gate evidence; if passed, approve the next step.
4. If a gate fails: stop, fix data/features/definitions, do **not** add model complexity.

**Status values:** `not started` | `awaiting approval` | `in progress` | `complete` | `blocked` | `skipped`

---

## Step index

| Step | Phase | Title | Status | Gate |
|------|-------|-------|--------|------|
| 0.0 | 0 | Write root `architecture.md` from plan v2 | not started | Doc reviewed & accepted |
| 0.1 | 0 | Package skeleton + YAML config schema (frozen §6 defaults) | not started | Schema validates; definitions frozen in config |
| 0.2 | 0 | Leakage / look-ahead unit tests (fail-first) | not started | Tests exist and pass on stubs |
| 0.3 | 0 | Historical zone dataset build (detect → Parquet + version hashes) | not started | Dataset versioned; counts reviewable |
| 0.4 | 0 | Outcome labeler (§6.2–6.4) | not started | Label counts & base rates reviewed |
| 0.5 | 0 | Phase 0 gate review | not started | Labels + leakage + leakage tests all pass |
| 1.1 | 1 | Multi-TF features (closed-bar D/W/M only) | not started | Truncation tests pass |
| 1.2 | 1 | Structure features (leg-in / UOC / leg-out) | not started | Features join cleanly to zone rows |
| 1.3 | 1 | Volume / CVD proxies (phase-1) | not started | Ablation-ready columns present |
| 1.4 | 1 | Calibrated OOF probability head (LightGBM) | not started | Beats “take every zone”; calibration OK |
| 1.5 | 1 | Phase 1 gate review + SHAP report | not started | Gate criteria met on OOS |
| 2.1 | 2 | Rule-based attribution tagger | not started | Tag list frozen in config |
| 2.2 | 2 | Multi-label attribution model + SHAP + clustering | not started | Manual sample review of losers |
| 2.3 | 2 | Phase 2 gate review | not started | Tags accepted on reviewed sample |
| 3.1 | 3 | Fill / slippage / gap / cost simulator | not started | Same-bar & gap rules verified by tests |
| 3.2 | 3 | `ZoneApproachEnv` (Gymnasium) | not started | Episodes run end-to-end on sample data |
| 3.3 | 3 | Baseline policies (fixed plan + `p_accept` filter) | not started | Metrics logged in MLflow |
| 3.4 | 3 | Grid-searched static plan (Optuna, validation only) | not started | Best static plan on walk-forward |
| 3.5 | 3 | Contextual bandit plan policy | not started | Bandit beats best static plan (WF) |
| 3.6 | 3 | Phase 3 gate review | not started | Bandit > static on walk-forward |
| 4.1 | 4 | MaskablePPO plan-selection (gated) | not started | Beats bandit under §10.4 |
| 4.2 | 4 | PPO management actions (hold / exit / BE) | not started | Beats plan-only PPO under §10.4 |
| 4.3 | 4 | Phase 4 gate review | not started | Acceptance criteria met |
| 5.1 | 5 | FastAPI `/rl/decide` + `/rl/outcome` | not started | Endpoints smoke-tested |
| 5.2 | 5 | Tampermonkey RL entry/SL/TP overlay | not started | Chart lines match API decisions |
| 5.3 | 5 | Paper-trade loop + experience logging | not started | ≥ 3 months; consistent with backtest |
| 5.4 | 5 | Phase 5 gate review | not started | Paper ≈ backtest within tolerance |
| 6.1 | 6 | Retrain / champion–challenger / promotion | not started | Promotion process proven offline |
| 6.2 | 6 | Drift monitoring + kill switch + rollback | not started | Alerts & kill switch tested |
| 6.3 | 6 | Optional small live (only if 6.1–6.2 pass) | not started | Explicit user go-live approval |

---

## Phase 0 — Foundations (frozen definitions, data, leakage)

### Step 0.0 — Write root `architecture.md`

| | |
|--|--|
| **Status** | `not started` |
| **Depends on** | Plan v2 accepted |
| **Deliverable** | [`architecture.md`](../architecture.md) at project root covering §§14 of the plan (goals, stack, contracts, eval, roadmap) |
| **Gate** | User reviews and accepts the architecture doc |
| **Approval** | pending |
| **Notes** | Design only — no training code |

### Step 0.1 — Package skeleton + config schema

| | |
|--|--|
| **Status** | `not started` |
| **Depends on** | 0.0 complete |
| **Deliverable** | `rl_zone_agent/` package layout (`data/`, `features/`, `labels/`, `sim/`, `models/`, `env/`, `policies/`, `eval/`, `serve/`, `configs/`, `tests/`) + pydantic-validated YAML with frozen §6 defaults (`approach_k`, `touch_rule`, `bounce_min_r`, outcomes, attribution tag list, costs) |
| **Gate** | Config loads; changing a frozen definition requires a new experiment id |
| **Approval** | pending |
| **Notes** | |

### Step 0.2 — Leakage / look-ahead tests

| | |
|--|--|
| **Status** | `not started` |
| **Depends on** | 0.1 complete |
| **Deliverable** | pytest suite: closed-bar HTF truncation equality; `availability_time <= decision_time`; zone usable only after leg-out confirmed; purged/embargo split helpers |
| **Gate** | All leakage tests pass |
| **Approval** | pending |
| **Notes** | |

### Step 0.3 — Versioned historical zone dataset

| | |
|--|--|
| **Status** | `not started` |
| **Depends on** | 0.2 complete |
| **Deliverable** | Parquet (+ DuckDB or extend `zone_store`) of zones from full history via reused `detect_once` / `build_zones`; dataset version hash; instrument coverage report |
| **Gate** | Dataset version recorded; row counts by instrument/year reviewable |
| **Approval** | pending |
| **Notes** | Prefer Kite Connect historical 2h; do not rely on scraper for training |

### Step 0.4 — Outcome labeler

| | |
|--|--|
| **Status** | `not started` |
| **Depends on** | 0.3 complete |
| **Deliverable** | Labeler implementing lifecycle + terminal outcomes (`early_bounce`, `uoc_success`, `uoc_stop`, `timeout`, `never_approached`); stores `mae_r`, `mfe_r`, `r_multiple`, fill fields; same-bar stop-first + gap-at-open rules |
| **Gate** | Label counts and base rates reviewed with user |
| **Approval** | pending |
| **Notes** | Definitions must stay frozen after this gate |

### Step 0.5 — Phase 0 gate

| | |
|--|--|
| **Status** | `not started` |
| **Depends on** | 0.0–0.4 complete |
| **Deliverable** | Short gate report: label base rates, leakage test status, dataset version |
| **Gate** | User accepts Phase 0 → unlock Phase 1 |
| **Approval** | pending |
| **Notes** | |

---

## Phase 1 — Features + probability head

### Step 1.1 — Multi-TF features

| | |
|--|--|
| **Status** | `not started` |
| **Depends on** | Phase 0 gate passed |
| **Deliverable** | EMA20/50, ATR regime, trend vectors for 2h/D/W/M using **last fully closed** HTF bars only |
| **Gate** | Truncation tests pass for every HTF feature |
| **Approval** | pending |
| **Notes** | |

### Step 1.2 — Structure features

| | |
|--|--|
| **Status** | `not started` |
| **Depends on** | 1.1 complete |
| **Deliverable** | Leg-in / UOC / leg-out size, speed, body-to-range, candle count, UOC/ATR, wick & volume vs average |
| **Gate** | Features join 1:1 to labeled zone rows with no look-ahead |
| **Approval** | pending |
| **Notes** | Optional CNN/GRU encoder is later — not this step |

### Step 1.3 — Volume / CVD proxies

| | |
|--|--|
| **Status** | `not started` |
| **Depends on** | 1.2 complete |
| **Deliverable** | Phase-1 proxies (volume buckets, delta/CVD if tick available); documented as proxies not true footprints |
| **Gate** | Columns present and ablatable |
| **Approval** | pending |
| **Notes** | |

### Step 1.4 — Calibrated OOF probability head

| | |
|--|--|
| **Status** | `not started` |
| **Depends on** | 1.3 complete |
| **Deliverable** | LightGBM + isotonic/Platt; time-aware CV; **out-of-fold** `p_accept` only; MLflow run |
| **Gate** | Beats “take every zone” OOS; calibration (Brier / ECE) under configured threshold |
| **Approval** | pending |
| **Notes** | Never feed in-fold `p_accept` into env later |

### Step 1.5 — Phase 1 gate + SHAP

| | |
|--|--|
| **Status** | `not started` |
| **Depends on** | 1.4 complete |
| **Deliverable** | SHAP report + gate summary vs baseline |
| **Gate** | User accepts Phase 1 → unlock Phase 2 |
| **Approval** | pending |
| **Notes** | |

---

## Phase 2 — Attribution (“why”)

### Step 2.1 — Rule-based attribution tagger

| | |
|--|--|
| **Status** | `not started` |
| **Depends on** | Phase 1 gate passed |
| **Deliverable** | Multi-label tags from §6.6 written at episode end; tag list frozen in config |
| **Gate** | Tag frequencies reviewed |
| **Approval** | pending |
| **Notes** | |

### Step 2.2 — Attribution model + SHAP + clustering

| | |
|--|--|
| **Status** | `not started` |
| **Depends on** | 2.1 complete |
| **Deliverable** | Multi-label model; SHAP; HDBSCAN on losers; candidate new rules documented |
| **Gate** | Manual review of a sample of losing zones |
| **Approval** | pending |
| **Notes** | |

### Step 2.3 — Phase 2 gate

| | |
|--|--|
| **Status** | `not started` |
| **Depends on** | 2.1–2.2 complete |
| **Deliverable** | Review notes + accepted tag set |
| **Gate** | User accepts Phase 2 → unlock Phase 3 |
| **Approval** | pending |
| **Notes** | |

---

## Phase 3 — Simulator, env, baselines → bandit

### Step 3.1 — Fill / slippage / gap / cost simulator

| | |
|--|--|
| **Status** | `not started` |
| **Depends on** | Phase 2 gate passed |
| **Deliverable** | Shared simulator (§11): limit fills, gaps at open, slippage, costs; same-bar stop-first |
| **Gate** | Property/unit tests cover fill edge cases |
| **Approval** | pending |
| **Notes** | Same module for backtest, env, and paper later |

### Step 3.2 — `ZoneApproachEnv`

| | |
|--|--|
| **Status** | `not started` |
| **Depends on** | 3.1 complete |
| **Deliverable** | Gymnasium env; discrete plans (§8); obs = 31 + multi-TF + structure + approach + OOF `p_accept` + position state; reward = net R after costs |
| **Gate** | Sample episodes resolve with correct outcomes |
| **Approval** | pending |
| **Notes** | Management actions not yet |

### Step 3.3 — Baseline policies

| | |
|--|--|
| **Status** | `not started` |
| **Depends on** | 3.2 complete |
| **Deliverable** | (1) take every zone fixed plan; (2) `p_accept`-filtered; walk-forward metrics in MLflow |
| **Gate** | Metrics reproducible from logged config |
| **Approval** | pending |
| **Notes** | |

### Step 3.4 — Grid-searched static plan

| | |
|--|--|
| **Status** | `not started` |
| **Depends on** | 3.3 complete |
| **Deliverable** | Optuna over plan grid on validation only; evaluate on walk-forward |
| **Gate** | Best static plan recorded; no test-set tuning |
| **Approval** | pending |
| **Notes** | |

### Step 3.5 — Contextual bandit

| | |
|--|--|
| **Status** | `not started` |
| **Depends on** | 3.4 complete |
| **Deliverable** | Contextual bandit over discrete plan set |
| **Gate** | Bandit beats best static plan on walk-forward |
| **Approval** | pending |
| **Notes** | If gate fails → stop; do not start PPO |

### Step 3.6 — Phase 3 gate

| | |
|--|--|
| **Status** | `not started` |
| **Depends on** | 3.5 gate passed |
| **Deliverable** | Comparison table: baselines vs bandit |
| **Gate** | User accepts Phase 3 → unlock Phase 4 |
| **Approval** | pending |
| **Notes** | |

---

## Phase 4 — Gated PPO

### Step 4.1 — MaskablePPO plan selection

| | |
|--|--|
| **Status** | `not started` |
| **Depends on** | Phase 3 gate passed |
| **Deliverable** | sb3-contrib MaskablePPO over discrete plans; eval callbacks; MLflow |
| **Gate** | Beats bandit under §10.4 (expectancy CI, ≥300 OOS trades, hold-outs) |
| **Approval** | pending |
| **Notes** | Skip/abort if sample size insufficient |

### Step 4.2 — PPO management actions

| | |
|--|--|
| **Status** | `not started` |
| **Depends on** | 4.1 gate passed |
| **Deliverable** | Add hold / exit / move-to-breakeven after plan validated |
| **Gate** | Beats plan-only PPO under §10.4 |
| **Approval** | pending |
| **Notes** | |

### Step 4.3 — Phase 4 gate

| | |
|--|--|
| **Status** | `not started` |
| **Depends on** | 4.1–4.2 complete |
| **Deliverable** | Full eval report vs all baselines |
| **Gate** | User accepts Phase 4 → unlock Phase 5 |
| **Approval** | pending |
| **Notes** | Optional d3rlpy only if logged trajectories are large enough — separate approval |

---

## Phase 5 — Serve + paper trade

### Step 5.1 — FastAPI RL endpoints

| | |
|--|--|
| **Status** | `not started` |
| **Depends on** | Phase 4 gate passed |
| **Deliverable** | `/rl/decide`, `/rl/outcome` following `unified_server_fixed` patterns |
| **Gate** | Smoke tests pass |
| **Approval** | pending |
| **Notes** | |

### Step 5.2 — Tampermonkey RL overlay

| | |
|--|--|
| **Status** | `not started` |
| **Depends on** | 5.1 complete |
| **Deliverable** | Entry / SL / TP lines on chart from RL decisions |
| **Gate** | Visual match with API output |
| **Approval** | pending |
| **Notes** | |

### Step 5.3 — Paper-trade loop

| | |
|--|--|
| **Status** | `not started` |
| **Depends on** | 5.2 complete |
| **Deliverable** | Live data paper loop; same simulator; experience store logging; min **3 months** |
| **Gate** | Paper results consistent with backtest within configured tolerance |
| **Approval** | pending |
| **Notes** | |

### Step 5.4 — Phase 5 gate

| | |
|--|--|
| **Status** | `not started` |
| **Depends on** | 5.3 complete |
| **Deliverable** | Paper vs backtest report |
| **Gate** | User accepts Phase 5 → unlock Phase 6 |
| **Approval** | pending |
| **Notes** | |

---

## Phase 6 — Continuous learning & optional live

### Step 6.1 — Retrain + champion/challenger

| | |
|--|--|
| **Status** | `not started` |
| **Depends on** | Phase 5 gate passed |
| **Deliverable** | Scheduled retrain; promote only if challenger beats champion on rolling hold-out + §10.4 |
| **Gate** | Promotion process demonstrated offline |
| **Approval** | pending |
| **Notes** | |

### Step 6.2 — Drift, kill switch, rollback

| | |
|--|--|
| **Status** | `not started` |
| **Depends on** | 6.1 complete |
| **Deliverable** | Feature/calibration/expectancy monitors; kill switch; champion rollback path |
| **Gate** | Simulated breach triggers kill + rollback |
| **Approval** | pending |
| **Notes** | |

### Step 6.3 — Optional small live

| | |
|--|--|
| **Status** | `not started` |
| **Depends on** | 6.1–6.2 complete + explicit go-live approval |
| **Deliverable** | Small-size live with kill switch armed |
| **Gate** | User explicit go-live approval only |
| **Approval** | pending |
| **Notes** | Out of scope until demand long-only is validated; supply still out of scope |

---

## Decision log

| Date | Decision | By |
|------|----------|----|
| 2026-11-08 | Created this tracker from plan v2; no implementation until Step 0.0 approved | Agent + user pending |

---

## Next action

**Waiting for your approval to start Step 0.0** (write root `architecture.md` from plan v2 — design only, no training code).

Reply with e.g. `approve Step 0.0` to begin, or request changes to this step breakdown first.
