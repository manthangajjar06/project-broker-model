# PPO zone agent — implementation plan

**Status:** Ready to implement. No training code yet.
**Target:** On a high-quality zone the model names the entry, the stop, and the target, and states an 80–90% chance, drawn from similar zones that have already resolved, that price bounces from those prices.
**Data:** `RL/data`, Nifty 100, 2-hour bars with footprint.
**Date locked:** 2026-11-15

This is the contract for the trading agent. Thresholds and costs written here stay fixed once the first training run starts. They are not moved to improve a result.

Section 15 is the remaining input. The entry, stop, and target conditions, and the rupee charge, are filled there before the first training run. The build order in §14 can start without them. An empty condition list means no extra mask.

## 1. What is being built

LightGBM stays frozen. It keeps finding demand zones and scoring them. PPO never retrains it, never edits `RL/RL/src/model/model.txt`, and never changes the 0.55 acceptance cutoff.

PPO’s job starts after a zone is accepted. Before it commits, it uses the current market and its past zone experiences to set the entry, the stop, and the target, including a buffer on any of the three. It then skips or takes that adjusted plan. After that choice is locked, later candles arrive one at a time and the policy may only manage the order it already placed. Those candles are the 2-hour closes. They are not an input from a finer bar.

Training is Python and reads `RL/data` directly. The React chart in `RL/RL` is the viewer. It is not the trainer.

One shared policy covers the whole Nifty 100 universe. A separate model per symbol will memorize that symbol. Every input is scale-free, so a move in IDEA and a move in RELIANCE are comparable. Raw prices never enter the network.

Every accepted zone leaves a record once its path has resolved. The record keeps the context that was knowable at the decision, and the outcome that followed. A later zone can use records whose outcome was already known. It cannot use a record of a zone that has not resolved yet. The behaviors and the record are in §9.

## 2. The files

`RL/data` holds one 2-hour CSV per symbol. Each row is one candle. The columns are:

`interval`, `date`, `time`, `open`, `high`, `low`, `close`, `volume`, `upper_wick_pct`, `lower_wick_pct`, `body_pct`, `tr`, `atr_14`, `datr_14`, `avg_volume_14d`, `ema_20`, `ema_50`, `buy_volume`, `sell_volume`, `delta`, `footprint`

The footprint cell is `price=buy/sell` levels separated by `;`. The chart already parses it in `RL/RL/src/data/csv.js`. The network never sees that string. It sees the summaries in §8.

Daily, weekly, and monthly bars are not files in `RL/data`. They are built for the stock in use, as §3 describes, and they are dropped when that stock is closed.

Reliance runs from 2 February 2015 through 13 November 2026. Shorter files stay out of decisions until they have an EMA-50 warmup and about a year of bars. Hyundai starts in October 2024. VAML starts in June 2026. Those names wait.

The 2-hour timestamp is the candle’s open. The candle is knowable only at its close:

| Open on the row | Knowable at |
|---|---|
| 09:15 | 11:15 |
| 11:15 | 13:15 |
| 13:15 | 15:15 |
| 15:15 | 15:30, and this close is the daily close |

## 3. What the policy is allowed to know

The decision clock is the close of the zone’s last 2-hour candle. A zone whose last candle opened at 09:15 is decided at 11:15. The 13:15 and 15:15 bars of that same day are still hidden.

Daily, weekly, and monthly bars are built from that stock’s 2-hour bars, and only for the stock in use. They are not built ahead for the Nifty 100, and they are not written to disk.

Opening that stock’s daily chart builds the daily series only. Opening the weekly chart builds the weekly series only. Opening the monthly chart builds the monthly series only. While the model is running on that stock, all three series are built, because the decision reads all three.

When that stock is closed, the series built for it are dropped. Closing the chart drops the series of the chart that was open. When the model leaves the stock, its three series are dropped. Nothing from them remains.

Only bars whose close is at or before the decision clock are used.

- **Daily.** Every earlier session is complete. The signal session is included only through the candle that just closed. The daily bar is complete only when the signal is the 15:15 candle.
- **Weekly.** Every earlier Monday–Friday week is complete. The current week is a partial bar through the signal.
- **Monthly.** Every earlier calendar month is complete. The current month is a partial bar through the signal.

A partial week or month may update a live EMA for the current input. That partial update is not written back into the completed series. The next completed bar starts from the last completed bar’s EMA.

“Access up to the signal” is the information set. The network receives a fixed snapshot of it, described in §8. It does not receive the growing raw history.

Candles after the decision exist only inside the simulator. They fill the limit, hit the stop, or hit the target, and they become the reward.

## 4. Zones

The Python port copies these functions from the chart and checks them against Reliance before any training:

- `singleCandidates` and `superCandidates` in `RL/RL/src/model/zones.js`
- `featuresFor` and `entryPrice` in the same file
- `loadModel`, `predictProbability`, and `scoreLabel` in `RL/RL/src/model/predict.js`
- the one-zone-per-base rule in `markersFrom` in `RL/RL/src/chart/zonePrimitive.js`

Patterns:

The base candle is the UOC. Its low and its high are the zone.

- **SINGLE.** Three candles: leg-in, UOC, leg-out. Pattern is DBR or RBR.
- **SUPER.** Five candles. Leg-out mode is SUPER.

A zone is knowable at the close of its last candle (`zone.end`). The 31 features include that candle, so the agent cannot act earlier.

Labels, from `scoreLabel`:

- `p_accept >= 0.55` → accepted
- `p_accept <= 0.45` → rejected
- otherwise → uncertain

PPO acts only on accepted zones. Rejected and uncertain zones are not actions.

Where several candidates share a pattern and a start, keep the higher probability, and keep SUPER when the probabilities tie. That is the set the chart draws. Overlapping copies of the same base would let the agent trade one base twice.

`buildZone` walks forward to mark a zone fresh or worked. That future touch is for drawing. It is not an input.

The probability must be computed with the same ATR path `zones.js` uses, including its own true-range ATR. Using only the CSV `atr_14` will make the accepted set disagree with the arrows on the chart.

The match check on Reliance: same zone times, and the same probabilities to about `1e-6`.

`model.txt` does not record the dates it was trained on. Tree 0 was fit on about 2,246 zones. A score on the early years is an upper bound until that cutoff is known.

## 5. The walk

Each symbol is one episode, walked from its first stored day to its last. Zones are offered in the order their last candle closes.

A step happens only at an event:

- an accepted zone has just closed, and the account is flat
- a working limit fills, is cancelled, or expires
- a 2-hour bar closes while a trade is open
- the stop, the target, or the time stop ends the trade

Bars with nothing to decide are skipped inside the environment.

One position at a time. A new accepted zone while a trade or a working order is open is not a new entry.

**Paper account.** The model trades a paper book in rupees. The money is real in the book: a starting capital, a whole number of shares, costs deducted in rupees, and a balance that is smaller after a loss. No order is sent to a broker. The book is filled by the same candles as the simulator.

The loss at the stop is 1% of current paper equity. Share count is that rupee risk divided by the distance from entry to stop, rounded down to a whole share. If those shares cost more than the cash, the count is reduced to what the cash can buy. If one share would risk more than 1% of equity, or costs more than the cash, that take is masked and the model can only skip. A wider stop buys fewer shares. A loss leaves less equity, so the next trade is smaller. That is the reason the model has to be careful.

The starting capital is written in the training config before Step 11 of `steps.md`, and then frozen. Training carries one account from the first training date through the end of 2021. Validation starts again at the starting capital. The test walk starts again at the starting capital. Inside a split the balance carries across symbols. It is not reset for each name. When several names signal at the same close and the account is flat, they are offered in symbol order and the model may take only one.

The training walk ends at the close of 2021. Validation is 2022–2023. The test walk is 2024 through the latest bar. The test walk does not update the policy. A zone in the test period cannot teach the decision being scored.

## 6. The first decision

At the decision clock the policy sees the snapshot in §8, including the similar past zones from §9. Later candles are still hidden. The entry, the stop, and the target are the one plan in §15. They are fixed here, before the order exists. A later candle cannot move them.

**Skip.** Reward 0. No later candles are shown to the policy. The trainer still follows the path on its own and, once a behavior in §9 is knowable, writes the experience record. The walk moves to the next zone. A skipped zone stays in that record. If the plan would have reached the target, the miss is learned. If the plan would have hit the stop, the skip is learned. The account does not move.

**Take.** The model takes the one plan from §15, or it skips. It does not choose a different entry, stop, or target. The three prices are then fixed.

The plan is masked when §15 gives no entry, and when the stop is not strictly below the entry. If the entry is at or above the close at the decision clock, the order is marketable and the fill price is the next candle’s open, provided that open is still above the stop. An open already through the stop does not open the trade, and the reward is 0.

Below the decision-clock close, the order is a limit. It fills only if a later bar trades the entry. The fill is the entry price. An open that has already printed below the entry is not the fill. If that same bar later trades the entry, the buy is still the entry, and the low before that buy is not a stop. If price never comes back before the time limit in §7, the order expires and the reward is 0.

**The chance it states.** With a take, the model names the entry, the stop, and the target, and it states the chance that price bounces from those three prices: the target is reached before the stop. That chance comes from similar zones whose outcome is already known and whose plan was the same kind of entry, stop, and target. It is the share of those resolved plans that reached the target before the stop. A high-quality call is one the model puts at 80–90%. The chance is a report of experience. It is not a change to the fill rules or to the reward.

**Your conditions.** The entry, the stop, and the target are written in §15. A zone that fails them is skipped. The model takes that one plan, or it skips. The conditions use only information known at the decision clock. Once the first training run starts, they stay as written.

The conditions are the quality cut. The report in §12 shows the zones that were offered and the zones the plan allows, and the average R of each. The count falling is the cut doing its job. The average R is what shows the kept trades paid.

## 7. After the decision

On a take, each following 2-hour candle is revealed at its close. Candles after the one just revealed stay hidden.

While the limit is working, the policy may keep it or cancel it. Cancel scores 0.

On each revealed 2-hour candle the environment applies these rules, in order:

1. A working limit fills when the bar trades the entry, at the entry price. If the bar opened above the entry and also trades the stop, the result is the stop. If the bar opened below the entry and then traded it, the buy is the entry and the low before that buy is not a stop.
2. An open trade on the first candle of the day, the 09:15 candle: an open below the stop sells at that open, and an open above the target sells at that open. That exit does not take another slippage. A later candle the same day that trades the stop sells at the stop, and one that trades the target sells at the target.
3. An open trade whose bar reaches both the stop and the target stops the run. It reports the stock, the date, and the time, and waits. It does not guess which printed first.
4. If the trade is still open at the 2-hour close, the policy may hold or leave. Leaving fills at the next candle’s open. It cannot fill at the low or the high of the candle just seen.

The entry, stop, and target chosen in §6 do not change on these steps. Hold, cancel, and exit are the only actions left. A new buffer is not applied after a candle arrives.

The position is forced flat 40 bars after the signal, about two weeks of 2-hour candles, at that bar’s close. Forty bars is also the expiry of a working limit.

Daily, weekly, and monthly context update on these later steps with the same partial-bar rule, using the new candle’s close as the clock.

## 8. The snapshot

Prices stay out. Distances are divided by ATR so the scale is shared.

**The zone, known at the decision clock.**

- the 31 features from `featuresFor`
- frozen `p_accept`
- body, upper-wick, and lower-wick percentages of the leg-in, the UOC, and the leg-out
- 2-hour `(close − EMA 20) / atr_14` and `(EMA 20 − EMA 50) / atr_14`
- zone height / `atr_14`
- `datr_14` / `atr_14`
- order state when this snapshot is a later step: flat, working, or in a trade
- unrealized R, bars since the signal, bars in the trade, distance to the stop, distance to the target
- paper equity divided by starting capital, unrealized rupee result divided by equity, and the fraction of equity the stop would lose

**Footprint summaries.** Computed from bars already closed. The raw `footprint` string is not an input.

- `delta / volume` on the base and on the leg-out
- where the heaviest level sits, `(poc − low) / (high − low)`
- buy share in the lower third of the bar versus the upper third
- the share of levels where one side is at least 3× the other

The same four summaries on the retest bar are available only at a hold-or-exit step. They are absent at the first decision.

**Daily context.**

- `(close − EMA 20) / ATR`
- `(EMA 20 − EMA 50) / ATR`
- true range / ATR
- volume so far against the average volume of the prior 14 completed sessions

ATR is the 14-period average of that timeframe’s true range. A session that has not finished is scaled by the fraction of the session that has elapsed, so a morning bar is not read as a no-volume day. `avg_volume_14d` stays a daily figure.

**Weekly context.** Distances and true range are measured in daily ATR. Volume is compared with the average of the last 14 completed weeks.

**Monthly context.** The same pattern, against the last 14 completed months. Monthly EMA 50 needs about 50 completed months before it is present. Until then that input is absent. EMA 20 on the monthly series is still used.

## 9. What is retained from every zone

The decision at a zone uses only the snapshot in §8. The outcome is written afterward, when the path has made it knowable. That write is how the model keeps the experience of the zone.

The stored context is the decision-time snapshot, without the memory summary described at the end of this section:

- body, upper-wick, and lower-wick percentages of the leg-in, the UOC, and the leg-out
- 2-hour EMA 20 and EMA 50, as the scale-free distances in §8
- the daily, weekly, and monthly indicators in §8
- the 31 features, `p_accept`, the footprint summaries, and the plan that was chosen, including skip

The outcome attached to that context is one path behavior, plus the trade result when a trade was taken. The behavior is judged against the zone itself, so a skipped zone can be labeled too. The reference stop for the label is just beyond the UOC low. The slight-breach distance is `0.25 * atr_14` past that stop. A stop placed `0.50 * atr_14` beyond the UOC low still holds through that breach. A stop at `0.25 * atr_14` holds a breach shorter than that distance.

The path is the candles from the first bar after the decision clock through 40 bars. The first matching behavior wins:

1. **Complete stop.** A candle closes beyond the reference stop, or its low goes more than `0.25 * atr_14` past that stop. The class stays a complete stop if price later rallies. The record also stores how far past the stop the low went, in ATR.
2. **Slight breach, then reversal.** A candle's low goes past the reference stop by no more than `0.25 * atr_14`, a later candle closes back above that stop, and a later close is back above the UOC high.
3. **UOC touch and bounce.** A candle trades into the UOC area, its low does not pass the reference stop, and a later close is above the UOC high.
4. **Down, but the base is never touched.** Some later low is below the close at the decision, every low stays above the UOC high, and a later close is back above the close at the decision.
5. **Unresolved.** The 40 bars end without one of the four.

When a trade was taken, the record also stores the trade result: no fill, stop, target, early exit, or time stop, and the realized R. A target and a stop each close the record with the full context above. The trade's own stop can differ from the reference stop. The behavior label uses the reference stop. The R uses the stop the policy actually placed.

A later decision sees this record only if the outcome time is already past. On every training pass the memory is rebuilt in time order. A zone in 2018 can recall a zone from 2016 that has already resolved. It cannot recall a zone from 2019. The neighbors are the 16 closest past records by distance on that stored context. Until 16 records exist, the memory summary is empty and the decision stands on the zone alone.

The summary added to the snapshot is, for each of the four behaviors: the share of those 16 neighbors, and the average R of the taken trades among them.

The same network has a second head that predicts the behavior from the decision-time context. It is trained on resolved records. Its loss weight is 0.1, fixed before the first run and not tuned on the test years. The trading reward remains realized R. The behavior head is how a skipped zone, and a zone that never touched the base, still teach the model.

The published test score uses weights and a memory frozen at the end of 2023. Test zones do not teach that score. A second walk may append each test zone after it resolves and use it only for later test zones. That second walk is reported separately and is not the number in §12.

## 10. Reward

R is `(exit − entry) / (entry − stop)`.

The reward the policy learns from is the change in paper equity from the decision to the flat close, divided by equity at the decision. A full stop is about a 1% loss of the book. A 2R win is about a 2% gain, after costs. Skip, cancel, and expiry score 0. There is no bonus for a zone that looks good. The only teacher is the later candles, marked to market in the paper book.

Average R stays the published comparison with the baseline. The paper book adds ending equity and the maximum drawdown. The stated chance in §6 is recorded with the trade. It is not a substitute for this reward.

Cost, locked before the first training run and not tuned afterward:

- slippage of `0.05 * atr_14` on the entry fill and again on a normal exit fill
- a 09:15 open through the stop or the target sells at that open, and that exit does not take the slippage again
- Zerodha delivery equity on the NSE. Brokerage is 0. STT is 0.1% of the buy and 0.1% of the sell. The exchange charge is 0.00307% of the buy plus the sell. SEBI is 0.0001% of the buy plus the sell. Stamp duty is 0.015% of the buy. GST is 18% of the exchange charge and the SEBI charge. On a buy of ₹10,00,000 and a sell of ₹11,00,000 the charge is ₹2,328.55.

The starting capital is ₹1,00,000. The charge above is the rupee schedule. Both are part of this contract once written.

The decision is not shown how that same zone ends. Skip still scores 0. Once the path has resolved, the outcome is attached to the stored context, and the policy is updated from that record. Later zones use those records through the memory in §9. A stop and a target both close a record. So do the four path behaviors, including a zone the policy skipped.

## 11. Training

Algorithm: MaskablePPO, Stable-Baselines3 with an action mask. Illegal actions cannot be sampled.

Network: two layers, width 128, plus the behavior head from §9. The input width is the snapshot in §8 plus the memory summary.

Starting hyperparameters:

- discount 0.99
- GAE lambda 0.95
- clip 0.2
- entropy coefficient 0.01
- learning rate `3e-4`

Training stops when, on the validation years, the trades the model rated at 80–90% did bounce from the entry, stop, and target it named at a rate inside that same range, and their average R beats the baseline. Entropy stays on, because two bad policies both look stable: always skip, and always take the 2R plan. A checkpoint whose stated chances do not land in that range is not selected.

Each training pass walks the training years in time order and rebuilds the memory as it goes. A resolved zone teaches two things: the realized R of a trade that was taken, and the path behavior of every accepted zone, taken or skipped. Both updates use only outcomes that have already happened on that pass.

## 12. The baseline, before PPO

Before any policy is trained, arm every accepted zone on the validation years with one locked plan:

- entry from `entryPrice`
- stop just beyond the base low
- target 2R
- the order inside a bar is the 1-minute sequence in §7

The report already written in `RL/Model/baseline_report.txt` used the 2-hour bar alone: if that bar hit both the stop and the target, the stop won. That report is replaced when the same baseline is run again under §7. The selection rule does not change. The kept trades still have to beat that baseline’s average R.

Split the results into no-fill, win, and loss, and count the five path behaviors from §9. Also split by probability bucket: 0.55–0.65, 0.65–0.75, and above 0.75.

The baseline is every accepted zone on the locked 2R plan. The model is selected on the trades it rates at 80–90% for the entry, stop, and target it names. On the test years those trades should bounce at a rate inside that same range, in each year, not only in a pooled average, and their average R has to be higher than the baseline’s.

Report three numbers per year, on filled trades only: win rate, average R after the locked cost, and trade count. Report them twice: on every accepted zone armed with the locked plan, and again on the trades the model rated at 80–90%.

Training in §11 stops on the validation run whose kept book is inside that band and whose average R beats the baseline. A checkpoint outside the band is not the selected model.

## 13. What the chart shows

Training writes a trade list per symbol: signal time, entry, stop, target, the chance the model stated, shares, exit time, exit price, R, rupee result, equity after the trade, and the path behavior. The existing chart draws those levels the same way it already draws zone arrows. That list is the review surface. The learning copy of the same record is the memory in §9.

## 14. Build order

The sequence and the verification for each step are in [`steps.md`](steps.md). A step starts only after the previous step is verified. The list below is the same work, in short.

1. Port the zone detector, the 31 features, `entryPrice`, and the tree scorer to Python.
2. Match Reliance to the chart: same zones, probabilities within about `1e-6`.
3. Build the daily, weekly, and monthly series for the stock in use, with the partial-bar rule, and drop them when that stock is closed. Build the footprint summaries.
4. Run the locked 2R baseline on the validation years and write the no-fill / win / loss report.
5. Build the environment: masked actions, one-candle reveal, fill rules, reward.
6. Classify the path behaviors and write the experience record for every accepted zone. The memory a decision can read contains only records already resolved.
7. Train MaskablePPO and the behavior head on the years through 2021. Select on 2022–2023 expectancy. Report 2024 through the latest bar once, with memory frozen at the end of 2023.
8. Write the trade list for the chart.

The trainer reads `RL/data` and `model.txt`. It does not import or run the live indicator, the cron job, or the Telegram bot.

## 15. The one plan

These rules are the decision in §6. `entry.py` says the same thing. Each rule is decidable at the zone’s close, from the leg-in, the UOC, and the leg-out. A later candle is not read. They are frozen before the first training run.

**No entry.**

- The zone is rejected or uncertain. Entry is allowed only when `p_accept` is 0.55 or above. A rejected zone stays rejected.
- The session is one of the first five from the zone’s last candle. That candle is day 1. Entry is allowed on day 6 or later. Days are the sessions in the file, and a later session is not counted early.
- DBR: the leg-in low equals its close.
- RBR: the leg-in high equals its close.
- The UOC has no DATR. That happens in a stock’s first days, which are already outside the decision window.

**Entry.**

- The leg-out is green. If its open equals its low, the entry is that open. Nothing is added.
- If the leg-out has a tail under its open, the entry is the UOC open when the UOC is red, and the UOC close when the UOC is green. Then add 10% of the UOC’s DATR. An entry of 100 with a DATR of 20 becomes 102.
- If that tail exists and the UOC’s upper wick reaches the leg-out body, the entry is the leg-out low. Nothing is added. This wins over the UOC open or close.

**Stop.**

- RBR: start at the UOC low.
- DBR: start at the UOC low, or at the leg-in’s lower wick when that wick is lower.
- Then subtract 10% of the UOC’s DATR. A stop of 90 with a DATR of 20 becomes 88.

**Target.**

- One leg-out: that candle’s close.
- Super: the close of the last candle of the pattern.

**Paper account.**

- Starting capital is ₹1,00,000. The stop risks 1% of current equity. That 1% is the share count, not the stop price.
- The charge is the Zerodha delivery schedule in §10. Brokerage is 0.

**Anything else.**

-
