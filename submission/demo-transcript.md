# RescueNYC — demo voice-over, ordered by the judging rubric (about 2:50)

Four chapters, one per rubric line. Put the chapter name on screen as a small caption for its first two seconds so a judge
knows which box the next forty seconds speak to. Numbers come from docs/METHODS.md, docs/evaluation.md and the dashboard;
every simulation figure is said as "in the simulation".

---

## Chapter 1 · Community value & theme alignment (0:00–0:40)

**[0:00 Comptroller chart]**
When a New Yorker calls 911 for a life-threatening emergency, help now takes over thirteen minutes, three and a half minutes longer than five years ago. The city's own audit says the time is lost in dispatch and on the road, while call volume has flattened.

**[0:15 Twenty-one-year chart, then Evidence → What the record shows]**
Twenty-one years of FDNY's public records: calls rose a third and the queue never moved. Since 2022 calls are flat and the queue of people waiting for an ambulance to be assigned has grown nine times. Hour by hour the pattern repeats every year; what changed is how many calls now wait.

**[0:30 Command Center, top of page, sidebar visible]**
RescueNYC is for one person: the EMS shift supervisor. It answers her question every hour: which borough is about to run late, why, and what she can do about it. Tech for good, in the plainest sense: fewer people waiting for an ambulance because someone saw the queue forming an hour earlier.

## Chapter 2 · Novelty & originality (0:40–1:30)

**[0:40 Command Center card]**
Everyone forecasts demand. We forecast the queue. It is eleven at night on the Fourth of July, 2026, data the model never saw while learning. From what had happened before this hour, it gives Queens a ninety-six percent chance that calls wait longer than normal, and says why: fifty-eight waiting, thirty-seven with no ambulance free.

**[0:55 Reveal; then Brooklyn, Reveal]**
Did it see it coming? Reveal. Correct: a typical call waited thirty minutes against an eight-minute norm. Brooklyn, ninety-four percent, forty-seven against twenty-six. Misses and false alarms show the same way.

**[1:05 Plan reserves dialog; Adopt]**
The second thing nobody else does: the forecast comes with a tested plan. One click runs a simulator on that borough's day three ways, no action, her plan, or waiting for the queue to build, and answers in a sentence with an interval. She adopts or declines; the decision is kept beside the forecast and, later, the real outcome. The human stays in the loop and gets scored too.

**[1:20 Evidence → Replay & model evaluation: map, then the evaluation fold]**
And we show our nulls: five model families, more years, more features, sub-hour signals; none beat the queue-aware model. PR-AUC zero point six zero against zero point four seven for demand alone, sixty-nine percent precision at four false alerts a day.

## Chapter 3 · Technical design & LinuxONE AI/ML (1:30–2:25)

**[1:30 Simulation Lab, Parallel Worlds, Jump to the biggest gap]**
Under the forecast is a discrete-event simulation of all five borough queues, calibrated to FDNY's own waits and checked against real ambulance records from four places. The Simulation Lab plays a week twice on the same calls; on the right, reserve ambulances come on when the AI warns. Across twenty runs, in the simulation, waiting falls by about a minute per call. The edge over a fixed schedule showed in one run and not in the replication, so we claim the first result, not the second. Every dot is one simulated unit following its own timeline.

**[1:55 More → hospital scene, 20 → 30 → 40]**
The hospital scene shows the chain reaction: one minute of waiting at a twenty-minute handover, six at thirty, ninety at forty.

**[2:05 VM terminal: uname -m, /health, /benchmark; dashboard badge "scored live on s390x"]**
All of it runs on IBM LinuxONE: training, calibration, replay, the simulations, and the dashboard you just saw, served from the s390x machine. One request is scored in about two milliseconds; replay runs two million times faster than the city's real event stream, a year of New York in fourteen seconds, so twenty-seed protocols and a twenty-one-year audit are interactive. Both mandatory labs are done. The AI accelerator is on the chip, but the Community Cloud VM does not expose its library, so inference runs on CPU; we tried it and the result is in the evidence folder.

## Chapter 4 · Execution & pitch (2:25–3:00)

**[2:25 Command Center again: forecast → plan → reveal, fast, no narration gaps]**
Forecast. Plan. Decide. Reveal. That is the whole product, four clicks, running end to end on real records.

**[2:40 Title card: Evergreen Labs, repo link, "replayed backtest · not a live feed · not clinical dispatch"]**
New York is specifying its next EMS dispatch system right now. RescueNYC is the AI layer it could feed: the five events every dispatch system already emits, turned into a forecast, a tested plan, and an honest scorecard. See the queue before the delay.

---

Do not say: "live 911", "saves lives", minutes saved in real life, or that FDNY endorsed anything. Say "replay" or "backtest", never "live".
Snap ML was tried on the VM: it ran on CPU; the zDNN accelerator path is not exposed on the Community Cloud VM. Do not claim an accelerator speed-up.
