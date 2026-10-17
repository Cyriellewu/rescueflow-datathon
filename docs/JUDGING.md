# RescueNYC — Scoring Ourselves Against the Rubric

Source: the official participant guidebook (standard rubric 4 × 10 = 40, plus the AI Innovation
Excellence rubric 2 × 10 = 20). Scores below are our own estimates from a four-lens review
(judge, data, novelty, delivery), not official. Re-score at every gate (G1–G3) and before
recording.

## Standard rubric

### 1. Value to the community & theme alignment

9–10 band in the guidebook: "Impactful solution to a critical need in the community or society
using Tech for Good; seamless theme integration." Judges ask: what real-world problem, who
benefits, how clearly is the theme reflected.

| | |
|---|---|
| Original idea (hospital allocation, synthetic data) | ~6 |
| Current plan | **8 → 9** |
| Why | Real, quantified, current harm (Comptroller, Oct 16 2026: life-threatening EMS response 9:34 → 13:09, FY21 → FY26); Council found 2024 times rose while call volume flattened, which points at dispatch capacity, exactly what we measure. Named user (shift supervisor). Detect (stress risk) → Decide (dispatch vs travel, which borough) → Respond (alert + briefing). |
| What gets it to 9–10 | Open the video with the human cost in one sentence and the official number; show one concrete decision the supervisor makes ("request mutual aid for Brooklyn dispatch", not "look at the dashboard"); keep "replay", not "live 911". |
| Loses points if | We claim minutes or lives saved; we use Comptroller end-to-end time and FDNY dispatch+travel time on one axis; political tone (rule 7). |

### 2. Novelty & idea originality

9–10 band: "Highly innovative; high originality … breakthrough in concept. Shows strong end-to-end
solution components." 0–3 band: "heavy use of pre-existing solution concepts." Rule 4 bans using
other projects' ideas.

| | |
|---|---|
| Original RescueNYC (demand forecast + staging map) | ~5 (FirstWave, GT Hacklytics 2026, did this on the same dataset) |
| Current plan | **7 → 8** |
| Why | Target is dispatch-queue stress against a trailing baseline, not demand. Real-time signal is the unassigned-call backlog. Testable severity-cascade hypothesis (low-acuity holds pile up before high-acuity delay). Briefing with a verifier that blocks numbers the model didn't produce. |
| What gets it to 9 | A clear, surprising result from the cascade test (lead time in minutes, ΔPR-AUC) shown as one chart; the verifier catching a bad briefing on screen; say plainly in the video how this differs from demand forecasting. |
| Loses points if | The demo looks like "a heatmap of NYC with a chatbot"; we show a demand forecast as a headline. |

### 3. Technical design & use of LinuxONE + AI/ML open source

9–10 band: "Advanced architecture; optimizes LinuxONE Community Cloud platform features with
exceptional exploitation of AI/ML capabilities on LinuxONE and open-source code/packages; fully
exploits security and/or compute." Evidence by screenshots: containerization, security,
scalability, compute. Both mandatory labs completed first.

| | |
|---|---|
| Baseline version (model on laptop, API on VM) | ~5 |
| Current plan | **7 → 8 (9 with measured accelerator use)** |
| Why | Training, calibration, inference and replay all on the s390x VM; API in a container; multi-model chain mirroring both labs; measured replay throughput and p50/p99 latency; leakage-safe pipeline. |
| What gets it to 9–10 | If `grep nnpa /proc/cpuinfo` shows the on-chip AI accelerator: run one model through IBM Z Accelerated / zDNN and show a timed CPU vs accelerator comparison. Security: SSH-key-only, firewall rule, non-root container, only aggregates leave the VM. Scalability: replay at 100× real time and show events/sec. |
| Loses points if | Anything important only runs on a laptop; "LinuxONE" appears only as a hosting box; claims about the accelerator we didn't measure. |

### 4. Execution, delivery & pitch quality

9–10 band: "Clearly demonstrates high-impact solution value and functionality, a highly
professional and well-orchestrated team presentation … compelling solution demo." Hard limit:
3 minutes.

| | |
|---|---|
| Current plan | **7 → 8–9** |
| What gets it to 9–10 | One story: replay a real winter night → Brooklyn backlog builds → alert fires 40+ min before high-acuity delay rises → bottleneck "dispatch pressure" → verified briefing → cut to the VM terminal (`uname -m`, container, `/health` = s390x, benchmark). Evaluation shown honestly against baselines. Under 3:00 with a cut-down script, rehearsed twice. |
| Loses points if | Over time; slides instead of a working demo; numbers on screen don't match `docs/evaluation.md`. |

### Totals

| | Value | Novelty | Technical | Execution | Total |
|---|---|---|---|---|---|
| Original idea | 6 | 5 | 5 | 7 | ~23 |
| Current plan, expected | 8 | 7 | 8 | 8 | **~31** |
| Current plan, if everything lands (cascade finding + measured NNPA + clean demo) | 9 | 8–9 | 9 | 9 | **~35–36** |

## AI Innovation Excellence Awards (extra 20)

Eligibility: high standard score with emphasis on Novelty and Technical. Rewards "the most
compelling, out of the box, or unconventional combination of AI innovation, technical
excellence, and high impact."

- **AI innovation & originality:** our case is the chain itself: backlog-driven predictive model
  → calibrated alert bands that say "insufficient data" instead of guessing → generative briefing
  that is mechanically checked against the model. "AI you can trust in a 911 setting."
- **Transformational impact & technical excellence:** measured s390x performance, the cascade
  finding, and a credible path to adoption (plugs into CAD event streams already on mainframe-class
  systems; cite Columbia/USC's NSF-funded FDNY "digital shadow" project as context, not as ours).

## Pre-recording checklist (each item maps to a rubric line)

- [ ] V: official problem number + named user + one concrete decision in the first 45 s
- [ ] N: one sentence on how this differs from demand forecasting; cascade chart
- [ ] T: VM terminal on screen; container on s390x; benchmark; NNPA result (or "CPU" stated)
- [ ] T: both lab completions in `submission/evidence/`
- [ ] E: ≤ 3:00, demo not slides, numbers match `docs/evaluation.md`
- [ ] All: no lives/minutes-saved claims; "replayed", not "live"

## Past winners and what they tell us

Evidence is thin: search snippets only (source pages were not reachable from our research
environment), placements sometimes disagree between sources, and no project details exist for
the 2025 global winners. Treat this as patterns, not proof.

| Year | Team / placement | Problem | AI / LinuxONE use |
|---|---|---|---|
| 2025 | Guidebook example | Urban Route Safety Index: roads rated Safe / Moderate / Risky from crime + infrastructure data, routing by safety not speed | Risk classification that changes a decision |
| 2025 | Life Aspirant's (1st), Hackasaurs (2nd), Gradient Ascent (3rd) — order per StarHacks; hack2skill differs | not found | not found |
| 2024 | ALX Africa team, 1st (own Medium post) | Electricity/meter theft, South Africa (~R20bn/yr) | Isolation Forest vs Random Forest vs XGBoost (XGBoost best), geospatial map, paper-style write-up on L1CC |
| 2024 | BIG BAD CODERS | Fraud detection | Full pipeline on a LinuxONE instance: train → deploy |
| 2024 (likely) | Team Oasis, GAT Bengaluru | Lake encroachment from satellite/drone images | OpenCV + CNN, Flask REST API on L1CC |
| 2024 | TUT 36, 2nd South Africa | Healthcare access | Image processing |
| 2023 | Code Catalysts, global winner | Hate-speech detection (~25k tweets) | Transformer on an L1CC VM from IBM's Docker AI image; reported <1 s inference; REST API |
| 2023 | unnamed winner | Disease from symptoms | Logistic / linear regression |
| ~2021 | VIT Chennai Team 34, 3rd | Farmer's Friend, agricultural production | ML |

**Patterns:**
1. A local, concrete Tech-for-Good problem with a number attached (R20bn theft, Bengaluru lakes).
   → We have this: Comptroller 9:34 → 13:09.
2. Classical ML with a comparison of several models, not exotic AI. → Our baselines vs xgboost
   table is exactly this; keep it visible.
3. Anomaly / fraud / risk detection is over-represented, and the guidebook's Theme 1 examples
   include System Anomaly Detection. → Dispatch-stress detection fits the winning shape.
4. A risk score that changes a decision (URSI routes by safety; theft detection says where to
   inspect). → Our alert must name the decision.
5. A working end-to-end prototype behind a REST API on the VM. → `/risk`, `/replay` on s390x.
6. Paper-style write-up with honest method. → `docs/evaluation.md`, cascade result.
7. LinuxONE evidence was basic: a VM, often IBM's Docker AI image, train + infer there; only one
   quantitative claim (<1 s inference). **No winner we found used the Telum accelerator, zDNN or
   Snap ML.** → Measured benchmark plus a real NNPA comparison would put us above every past
   winner we could find on the Technical criterion.

**What we take from this:** our scope already matches the winning shape (local problem with a
number, risk detection that drives a decision, model comparison, REST API on the VM). The places
we can beat past winners are the Technical criterion (measured performance, accelerator if
available, security evidence) and Novelty (cascade finding, verified briefing). Don't add exotic
AI for its own sake; past winners didn't need it.
