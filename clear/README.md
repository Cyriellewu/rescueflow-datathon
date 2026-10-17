# RescueNYC: the early-warning model, explained step by step

A clean, self-contained rewrite of the RescueNYC prediction pipeline. It answers one question,
with real FDNY data, and shows its work:

> **At the top of each hour, for each borough: will the ambulance dispatch queue be "stressed"
> in the next hour?**

Everything here runs in about 30 seconds with one command, and every number below comes from
[`results/results.md`](results/results.md) (generated, not typed by hand).

**中文简介：**每个整点、每个区，模型读入 20 个“此刻已知”的数字，比如正在等车的呼叫数、
最近一小时的呼叫量、最近一小时的派车延误，然后输出“下一小时这个区会不会堵”的概率。
“堵”的定义是：这一小时轻症呼叫的派车等待中位数，超过该区过去 8 周同一时段的第 80 百分位。
我们用 2026 年 1–9 月模型没见过的真实数据考试，并和几种不用模型的简单方法比较，
每种方法的报警次数都一样多。结论：模型明显比所有简单方法准，报警 10 次约 7 次是对的；
但对“刚开始堵”的情况抓得不好。

---

## 1. The data

FDNY **EMS Incident Dispatch Data** (NYC Open Data, dataset
[`76xm-jjuj`](https://data.cityofnewyork.us/Public-Safety/EMS-Incident-Dispatch-Data/76xm-jjuj)).
**One row = one 911 medical call**, with timestamps for each step:

```
call created → unit assigned → unit on scene → arrived at hospital → call closed
```

plus initial severity (1 = most critical … 8 = least), borough, and whether the call was
**held** (no unit available, so it waited in a queue).

| | |
|---|---|
| Calls used | 6,065,043 (2023-01-01 → 2026-09-30) |
| Calls that were held | 19.8% |
| Median dispatch wait, held vs not held | **506 s vs 23 s** |
| Median dispatch wait, high-acuity (1–3) vs low-acuity (4–8) | 23 s vs 37 s |

FDNY dispatches by priority, so the queue mostly lands on low-acuity calls. When there aren't
enough units, calls get held and waits jump from seconds to minutes. That queue is what we try to
predict.

## 2. What "stressed" (堵) means

For borough **B** and hour **T** (e.g. Brooklyn, Friday 20:00–21:00):

1. Take every **low-acuity** call created in that hour and its FDNY dispatch wait. Use the **median**.
2. Take the same median for the **same borough, same weekday and hour, over the previous 8 weeks**.
   Their **80th percentile** is the threshold.
3. **Stressed = this hour's median is above the threshold.** Fewer than 5 calls means not judged.

Each borough is compared with **its own** recent normal for **that** hour, so a quiet Staten Island
night and a busy Bronx evening are both judged fairly. Real examples:

| Brooklyn, Friday 20:00 | Previous 8 Fridays (s) | Threshold | This hour | Answer |
|---|---|---|---|---|
| 2026-09-11 | 190, 64, 16, 26, 29, 27, 281, 136 | 168 s | 115 s | normal |
| 2026-09-18 | 64, 16, 26, 29, 27, 281, 136, 115 | 128 s | **889 s** | **stressed** |
| 2026-09-25 | 16, 26, 29, 27, 281, 136, 115, 889 | 223 s | **848 s** | **stressed** |

About **27%** of borough-hours come out stressed.

## 3. The model: input and output

**Input: one row, 20 numbers, all known at time T** (nothing from after T):

| Group | Inputs | Example (Brooklyn, Thu 2026-02-12 19:00) |
|---|---|---|
| **Queue now** (7) | calls waiting for a unit (high / low acuity), of those held (high / low), low-acuity waiting > 10 min, > 30 min, units at hospitals | 60 low-acuity waiting (53 held), 51 over 10 min, 28 units at hospitals |
| **Call volume** (5) | calls in the last 1 h / 3 h / 24 h, high-acuity calls last 1 h, usual calls for this hour | |
| **Recent delays** (5) | median dispatch wait of units assigned in the last hour (low / high), high-acuity travel time, low-acuity wait vs usual, "stressed right now" | last hour low-acuity wait 19.4 min (5.7x usual) |
| **When / where** (3) | hour of day, day of week, borough | 19:00, Thursday, Brooklyn |

**Output: one number between 0 and 1**, the risk that the next hour is stressed (that example:
**90%**).

**How it learns:** gradient-boosted decision trees (scikit-learn `HistGradientBoostingClassifier`,
the same idea as XGBoost, 300 small trees). Trained on Jan 2023 to Jun 2025, about 93,000
borough-hours, each one "20 inputs → stressed or not".

**From risk to alert:** the top 10% riskiest hours (cut-off set on Jul–Dec 2025) become an
**alert**. Then a template writes the note a supervisor would see:

> _Brooklyn Thu 19:00 — stress risk next hour 90% (ALERT). Waiting for a unit now: 60 low-acuity
> (53 held), 2 high-acuity; 51 waiting > 10 min; 28 units at hospitals. Last hour low-acuity
> dispatch median 19.4 min (5.7x usual). Suggest: prepare cross-borough support / reserve units;
> a supervisor decides._

The model does not dispatch anything. It ranks boroughs by risk and explains why, and a
human decides.

## 4. How we judge whether it is any good

**The test:** pretend it's Jan–Sep 2026, which the model has never seen. Every hour, every borough,
each method makes a call, and we compare it with what actually happened (28,777 borough-hours).

**The competition:** the model only earns its place if it beats simple methods that need no model:

| Method | What it does |
|---|---|
| Usual for this hour | "How often was Brooklyn, Thursday 19:00 stressed in the past?" |
| **Stressed now → stressed next** | The supervisor's rule of thumb: "it's bad now, so it'll stay bad" |
| Queue length only | Logistic regression on the 7 queue inputs |
| Call volume only | Same trees, but only call volume + time (what a demand forecast knows) |
| **Full model** | All 20 inputs |

**Fair rules:** every method may alert on the same share of hours (its own top 10%), so nobody
wins by simply alerting more.

## 5. Results (test months Jan–Sep 2026, real data)

| Method | PR-AUC (95% CI) | Alert precision | Alert recall | Onset recall | False alerts / day |
|---|---|---|---|---|---|
| Usual for this hour | 0.267 (0.248–0.287) | 0.27 | 0.10 | 0.10 | 7.8 |
| Stressed now → stressed next | 0.367 (0.341–0.389) | 0.48 | 0.17 | 0.00 | 5.3 |
| Queue length only | 0.445 (0.413–0.474) | 0.50 | 0.32 | 0.26 | 9.2 |
| Call volume only | 0.475 (0.447–0.503) | 0.57 | 0.23 | 0.18 | 4.9 |
| **Full model** | **0.597 (0.565–0.620)** | **0.68** | **0.32** | 0.10 | **4.2** |

How to read the columns:
- **PR-AUC:** how well the method ranks truly stressed hours above normal ones. A coin flip scores
  the base rate (0.27); 1.0 is perfect.
- **Alert precision:** of the alerts it raised, the share that were right. The full model is right
  about **7 times out of 10**.
- **Alert recall:** of all stressed hours, the share it alerted on.
- **Onset recall:** of hours that were normal **now** but stressed **next**, the share it caught.
  This is the true "early warning" case.
- **False alerts / day:** across all 5 boroughs.

**What the model relies on** (PR-AUC drop when one input is shuffled): low-acuity wait vs usual
(0.157), calls waiting now (0.125), usual calls for this hour (0.064), last-hour low-acuity wait
(0.054), calls in the last hour (0.054), held calls waiting (0.023). The queue and recent delays
lead. Day of week and borough barely matter. That fits the idea.

### What it looks like hour by hour

![Brooklyn, two weeks of September 2026](results/brooklyn_sep_2026.png)

Orange = the hour really was stressed; red dots = model alerts. **Long episodes (Sep 14–16, 18) are
caught hour after hour. Short one- or two-hour spikes are mostly missed.**

[`results/results.md`](results/results.md) has three real hour-by-hour tables: a new episode the
model caught, one it missed, and a false alarm, each with the briefing it would have produced.

## 6. What we can and cannot claim

**Supported by the numbers:**
- **The queue predicts dispatch stress better than call volume.** 0.597 vs 0.475 PR-AUC; the
  confidence intervals do not overlap.
- The full model beats every simple method, and its alerts are right about 68% of the time, with
  about 4 false alerts a day citywide.

**Not supported, and we say so:**
- **It is weak at the very start of a new episode** (onset recall 0.10). It is best at "stressed and
  staying stressed", and at saying *why*. Even the queue-only model catches more onsets (0.26), so
  this is the place to improve next.
- **The label is noisy hour to hour.** Thresholds for neighbouring hours can differ a lot (e.g. 482 s
  at 03:00 vs 32 s at 07:00 on the same Sunday), so the answer can flip between adjacent hours.
- **Replay, not live.** The queue is rebuilt from published timestamps after the fact. A live CAD feed
  would provide the same events in real time, but we have not tested one. The `held` flag is assumed
  known while the call is waiting.
- **No real-world "minutes saved" claim.** Whether acting on alerts helps is a separate simulation
  question (the policy lab on `main`), not something this evaluation shows.

## 7. Run it

```bash
python3 -m venv .venv && .venv/bin/pip install pandas numpy scikit-learn matplotlib pytest
.venv/bin/python scripts/fetch_data.py --start 2023-01-01      # → data/raw/ (≈1.1 GB, resumable)
.venv/bin/python -m clear.run                                   # → clear/results/ in ~30 s
.venv/bin/python -m pytest -q clear/test_clear.py
```

On the LinuxONE VM, the Ubuntu image already has pandas, scikit-learn and matplotlib, so no install
is needed:

```bash
python3 -m clear.run --raw /opt/rescuenyc/data/raw
```

The results in this folder were produced on a laptop (`arm64`); rerun on the VM for the s390x
evidence.

## 8. Files

| File | What it does |
|---|---|
| [`config.py`](config.py) | Every setting in one place: label rule, split dates, alert budget |
| [`load.py`](load.py) | Raw CSV → one clean row per call (times, severity, held, dispatch wait) |
| [`table.py`](table.py) | Calls → borough × hour table: the 20 inputs at T and the answer for [T, T+1h) |
| [`models.py`](models.py) | Full model and the four simple methods |
| [`evaluate.py`](evaluate.py) | Same-budget alerts, PR-AUC with day-level bootstrap CI, onset recall |
| [`examples.py`](examples.py) | Real label examples, hour-by-hour segments, briefing, chart |
| [`run.py`](run.py) | Runs everything and writes `results/` |
| [`test_clear.py`](test_clear.py) | Hand-checked cases for queue counting and the label |

How the queue is counted: a call is "waiting at T" if it was created before T and got a unit (or was
closed) at or after T. For each borough this is `#(created < T) − #(left queue < T)`, computed for
every hour at once with sorted arrays. The same trick counts units at hospitals and calls waiting
more than 10 or 30 minutes.
