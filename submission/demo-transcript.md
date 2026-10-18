# RescueNYC — demo voice-over (read aloud, about 2:50 at a brisk pace)

Numbers come from docs/METHODS.md, docs/evaluation.md and the dashboard. Every simulation figure is said as "in the simulation".

---

**[0:00 Comptroller chart]**
When a New Yorker calls 911 for a life-threatening emergency, help now takes over thirteen minutes. That is three and a half minutes longer than five years ago. The city's own audit says the time is lost in dispatch and on the road, even though call volume has flattened.

**[0:15 Twenty-one-year chart, then Evidence → "What the record shows": the hour-of-day chart and "where the extra minutes come from"]**
Twenty-one years of FDNY's public records tell the story. Calls rose by a third and the queue never moved. Since 2022 calls are flat and the queue of people waiting for an ambulance to be assigned has grown nine times. Hour by hour, the pattern is the same every year; what changed is how many of those calls now wait, and most of the extra minutes on urgent calls are spent on the road. RescueNYC watches that queue.

**[0:30 Command Center]**
This is a replay of FDNY's record, hour by hour, on 2026 data the model never saw while learning. It is eleven at night on the Fourth of July. Using only what had happened before this hour, the model gives Queens a ninety-six percent chance that less-urgent calls wait longer than normal in the next hour. It says why: fifty-eight calls waiting, thirty-seven of them with no ambulance free. And it suggests one thing: release reserve capacity.

**[0:50 Reveal]**
Did it see it coming? Reveal. Correct warning. A typical call waited thirty minutes against an eight-minute norm. Brooklyn, same hour: ninety-four percent, and it ran at forty-seven minutes against twenty-six. Misses and false alarms show exactly the same way. Nothing is hidden.

**[1:05 Evidence → "Replay & model evaluation": the ZIP map for two seconds, then scroll to the evaluation table]**
Every hour of 2026 is on this map by ZIP code, with real incidents, hospitals and the driving times the simulator uses. On that held-out year the model reaches a precision-recall area of zero point six zero, against zero point four seven for the same model given demand alone, intervals apart. At the default budget it is right sixty-nine percent of the time, with four false alerts a day across the city. Precision is a budget choice: alert on the riskiest three percent of hours and it is right eighty-three percent of the time. We tried five other model families, more years, more features and sub-hour signals. None moved it. The information ceiling is unit availability, which the public record does not contain.

**[1:30 Planner]**
What should the supervisor do? One click runs the simulator on that borough's day three ways: no action, her plan, or waiting for the queue to build, with the same calls and the same random draws. It answers in a sentence, with an interval. She adopts or declines, and her decision is kept with the forecast and, later, with what really happened. Nothing is dispatched from here; ambulances still move through the 911 system.

**[1:50 Parallel Worlds]**
The Simulation Lab plays a whole week twice on the same calls. On the right, reserve ambulances come on duty when the AI warns. Across twenty runs, in the simulation, waiting falls by about a minute per less-urgent call, and timing by the warning beats a fixed schedule and an oracle that knows next hour's arrivals. Moving ambulances between boroughs never helped. The lever is capacity at the right time, not relocation.

**[2:05 Hospital scene and outside check]**
The hospital scene shows the chain reaction. In simulated Brooklyn, the wait is about a minute at a twenty-minute handover, six minutes at thirty, and ninety at forty. We checked our assumptions against real records from New York, San Francisco, Indiana and Riverside County. Scene time, transport time and the share transported match. Hospital time is where our simulator is too kind, and we say so on the page.

**[2:25 LinuxONE terminal]**
All of it runs on IBM LinuxONE: training, calibration, scoring in under two milliseconds a request, replay at three hundred and fifty-eight thousand events per second, and the simulations. Both mandatory labs are done. The accelerator is present; inference is on CPU.

**[2:45 Title card]**
New York is specifying its next EMS dispatch system right now. RescueNYC is the AI layer it could feed: the same five events every dispatch system already emits, turned into a forecast, a tested plan, and an honest scorecard. See the queue before the delay.

---

Do not say: "live 911", "saves lives", a number of minutes saved in real life, or that FDNY endorsed anything. Say "replay" or "backtest", never "live".
