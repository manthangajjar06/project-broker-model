# Implementation steps

**Contract:** [`implementation plan.md`](implementation%20plan.md)
**Status:** Step 15's training contract is in `RL/Model/train.py`. No checkpoint is trained yet. A 2-hour candle that trades both the stop and the target stops the baseline and names the stock, the date, and the time. The goal is unchanged.

The model is built in this order. A step starts only after the previous step is implemented, verified, and confirmed working. A later step is not started to save time, and a failed check is not patched inside a later step.

A small change in an early step changes the zones, the prices, and the reward the policy learns from. After any change to a finished step, that step is verified again, and every step after it is verified again before new work continues.

Code for these steps lives under `RL/Model/`. The trainer reads `RL/data` and `RL/RL/src/model/model.txt`. It does not import or run the live indicator, the cron job, or the Telegram bot. LightGBM stays frozen.

## Step 1. Load one 2-hour file

Read one CSV from `RL/data`, including `buy_volume`, `sell_volume`, `delta`, and `footprint`.

**Verified when:** Reliance loads in time order, the column set matches §2 of the plan, and a footprint cell splits into price, buy, and sell. Empty early indicator cells stay empty. They are not filled with zeros.

## Step 2. Decision clock

The timestamp on a row is the candle open. The candle is knowable at its close: 09:15 at 11:15, 11:15 at 13:15, 13:15 at 15:15, and 15:15 at 15:30. The 15:15 close is the daily close.

**Verified when:** a fixed set of Reliance rows, one of each open time, maps to those four closes, and a zone ending on the 09:15 candle cannot see the 13:15 or 15:15 bars of that day.

## Step 3. Port the zone detector

Port `singleCandidates` and `superCandidates` from `RL/RL/src/model/zones.js`. The base candle is the UOC. Its low and its high are the zone. Keep one zone per pattern and start, the higher probability, and SUPER when the probabilities tie. That rule is `markersFrom` in `RL/RL/src/chart/zonePrimitive.js`. The probability is not available yet, so this step checks the geometry only: pattern, start, end, and UOC high and low.

**Verified when:** the Reliance zones from this port match the chart’s zone times and UOC bounds. `buildZone`’s future fresh-or-worked walk is not an input.

## Step 4. Port the features and the tree

Port `featuresFor` and `entryPrice` from `zones.js`, and `loadModel`, `predictProbability`, and `scoreLabel` from `RL/RL/src/model/predict.js`. The probability uses the same true-range ATR path as `zones.js`, not the CSV `atr_14` alone. Accepted is `p_accept >= 0.55`. Rejected is `p_accept <= 0.45`. Everything else is uncertain.

**Verified when:** on Reliance, the same zones as the chart, and the same probabilities to about `1e-6`. The accepted set is the only set later steps are allowed to act on.

## Step 5. Daily, weekly, and monthly bars

Build the daily, weekly, and monthly series from that stock’s 2-hour bars, for the stock in use. Do not build them ahead for the Nifty 100, and do not write them to disk.

Opening that stock’s daily chart builds the daily series only. Opening the weekly chart builds the weekly series only. Opening the monthly chart builds the monthly series only. While the model is running on that stock, build all three, because the decision reads all three. When that stock is closed, drop the series that were built for it. Closing the chart drops the series of the chart that was open. When the model leaves the stock, drop its three series.

A bar is included only when its close is at or before the decision clock. The current day, week, and month stay partial. A partial bar may update a live EMA for the current input and is not written back into the completed series.

EMA 20 and EMA 50 are computed on each timeframe’s own closes. ATR is the 14-period average of that timeframe’s true range. Daily volume uses the prior 14 completed sessions. Weekly volume uses the last 14 completed weeks. Monthly volume uses the last 14 completed months. Monthly EMA 50 is absent until about 50 completed months exist.

**Verified when:** opening the Reliance daily chart builds the daily series and does not build the weekly or the monthly series. The weekly chart and the monthly chart each build only their own series. A model run on Reliance builds all three. Closing Reliance drops those series, and no daily, weekly, or monthly file is left behind. A Reliance decision at 11:15 sees a partial day through the 09:15 candle only, a partial week through that day, and a partial month through that day. The same decision on a later date still shows the same completed bars it showed the first time. Short files such as Hyundai and VAML emit no decision until they have an EMA-50 warmup and about a year of bars.

## Step 6. Footprint summaries and the snapshot

Compute the scale-free snapshot in §8 of the plan. The network never receives the raw footprint string or a raw price. Include the body and wick percentages of the leg-in, the UOC, and the leg-out, and the 2-hour EMA distances. The memory summary is not part of this step. It is added in Step 12.

**Verified when:** every value in a Reliance snapshot at a decision clock can be recomputed from bars that have already closed. A bar after that clock changes none of those values.

## Step 7. Request the conditions, then write `entry.py`

Stop here. Do not invent the conditions, and do not write `RL/entry.py` from the plan’s examples.

Ask the user for the entry conditions, the stop-loss conditions, and the target conditions that apply to each zone. Wait until the user provides them. Then write `RL/entry.py` so that, for one zone and one candidate plan, it accepts or rejects that plan using only those conditions. Each condition must be decidable at the zone’s close, from the snapshot in Step 6 and the zone prices.

Copy the conditions into §15 of `implementation plan.md` in the user’s wording, then encode that wording in `entry.py`. The two must say the same thing. An empty reply means no extra filter, and `entry.py` accepts every geometrically valid plan. Once the first training run starts, the file is frozen.

**Verified when:** the user has supplied the conditions or has confirmed that the list is empty, `entry.py` returns the same pass or fail as those conditions on a handful of Reliance zones, and a condition cannot see a candle after the decision clock.

Steps 8 through 16 do not start until this step is confirmed.

## Step 8. The one plan

At the decision clock the action is skip, or the one plan from `entry.py` and §15: one entry, one stop, and one target. Prices are computed from the leg-in, the UOC, and the leg-out at that clock. The plan is masked when `entry.py` rejects it, and when the stop is not strictly below the entry. The chosen prices are then fixed.

**Verified when:** on one Reliance zone, the plan’s entry, stop, and target match §15, a rejected zone is masked, and changing a later candle does not change the plan.

## Step 9. Reveal candles and fill the order

After a take, reveal 2-hour candles one close at a time. Apply the fill, stop, and exit rules in §7 of the plan. A bar that hits both stop and target is a loss. An exit fills at the next open. A working limit can be kept or cancelled. Cancel and expiry score 0. The position is forced flat 40 bars after the signal. The entry, stop, and target from Step 8 do not move. Hold, cancel, and exit are the only actions left. With each take, record the chance from §6: the share of already-resolved similar plans that reached the target before the stop.

**Verified when:** a scripted Reliance path, including a same-bar stop and target, a marketable entry, an expiry, and an early exit, produces the fills the plan describes. The policy is not called in this step. The path is driven by hand.

## Step 10. Path behaviors

Label every accepted zone with one behavior from §9 of the plan: complete stop, slight breach then reversal, UOC touch and bounce, down but the base never touched, or unresolved. The label uses the reference stop just beyond the UOC low, including for a skip. A taken trade also stores no-fill, stop, target, early exit, or time stop, and the realized R against the stop the plan actually placed.

**Verified when:** five hand-built paths, one for each label, are classified as that label, and a skip still receives a label without the policy being shown those candles.

## Step 11. Baseline report

Before any policy is trained, arm every accepted zone on the validation years 2022–2023 with the locked plan: `entryPrice`, stop just beyond the UOC low, target 2R, stop wins if one bar hits both. Write no-fill, win, and loss, the five path behaviors, and the probability buckets 0.55–0.65, 0.65–0.75, and above 0.75.

Report win rate, average R after the locked cost, and trade count twice: on every armed zone, and on the zones `entry.py` also passes. The rupee charge used in that R, and the starting capital of the paper book, are the figures the user supplies for this report. Both are written into the training config and into the plan. They are not chosen to improve the report. The baseline is also run through that paper book, with the stop risking 1% of current equity, so the equity path exists before any policy is trained.

**Verified when:** the report exists for 2022 and for 2023 separately, the two cuts are both present, and rerunning it without a code change reproduces the same counts.

A later bar that trades both the stop and the target stops that run. The report on disk is the earlier stop-first run. It is replaced only after those candles are decided by hand.

## Step 12. Experience memory

Write one record per resolved accepted zone. The context is the Step 6 snapshot plus the plan, without the memory summary itself. A later decision may read a record only when that record’s outcome time is already past. Neighbors are the 16 closest past records. Until 16 exist, the summary is empty. On every pass the memory is rebuilt in time order.

**Verified when:** a decision in 2018 on Reliance can see a resolved 2016 record and cannot see a 2019 record. Rebuilding the memory reproduces the same neighbors.

## Step 13. Reward and the paper book

The book is paper. No order is sent to a broker. Before this step, the user supplies the starting capital. The stop risks 1% of current equity. Shares are a whole number. A plan that one share cannot fit inside that risk, or inside the cash, is masked.

R is `(exit − entry) / (entry − stop)` after the locked cost: slippage of `0.05 * atr_14` on the entry fill and again on the exit fill, plus the round-trip charge locked in Step 11. The reward the policy learns from is the change in paper equity divided by equity at the decision. Skip, cancel, and expiry score 0. There is no bonus for a zone that looks good.

**Verified when:** the hand paths from Step 9 produce that R and that equity change, including a winner, a full stop near a 1% equity loss, and a skip that leaves the balance unchanged. A second loss on a smaller balance buys fewer shares than the first. A stated chance of 85% on a hand of similar past plans equals the share of those plans that reached the target before the stop.

## Step 14. The environment

Wrap Steps 8 through 13 as one calendar walked forward on one paper account. A step occurs only at an event: an accepted zone closes while the account is flat, a working limit fills or is cancelled or expires, a bar closes while a trade is open, or the stop, the target, or the time stop ends the trade. One position at a time. Names that signal at the same close are offered in symbol order. Illegal actions cannot be sampled. The balance carries across symbols inside the split.

**Verified when:** one training-window walk, even if limited to a few names, moves the same paper balance from name to name, never reads a future bar into the snapshot, and the action mask matches Step 8 at every decision.

## Step 15. Train

Train MaskablePPO and the behavior head on the years through 2021. The network is two layers of width 128, plus the behavior head. The behavior loss weight is 0.1. Discount 0.99, GAE lambda 0.95, clip 0.2, entropy coefficient 0.01, learning rate `3e-4`. Each pass walks the training years in time order and rebuilds the memory as it goes.

Select the checkpoint whose 2022–2023 trades, the ones it rated at 80–90% for the entry, stop, and target it named, did bounce at a rate inside that range, and whose average R beats the Step 11 baseline. Entropy stays on. The test years are not read during training.

**Verified when:** the saved checkpoint’s stated 80–90% calls bounced inside that range on validation, its average R beats the baseline, the training log contains no decision dated 2024 or later, and the behavior-head weight in the saved config is 0.1.

## Step 16. Test and the trade list

Walk 2024 through the latest bar once. The published score uses weights and a memory frozen at the end of 2023. Report win rate, average R, and trade count per year for the trades the model rated at 80–90%, against the Step 11 baseline. Those calls should bounce at a rate inside that range in each test year. A second walk may append each test zone after it resolves. That second walk is labeled separately and is not the published score.

The test walk starts again at the starting capital. Report ending equity and maximum drawdown beside the R figures.

Write the trade list: signal time, entry, stop, target, the chance the model stated, shares, exit time, exit price, R, rupee result, equity after the trade, and the path behavior.

**Verified when:** the published report has one row per test year, the frozen memory contains no test-year outcome, the test account started at the locked capital, and the trade list rows match the fills from Step 9’s rules on a sampled handful of trades.

The chart drawing of that list is the review surface. It is a separate change, and it starts only after this report is confirmed.
