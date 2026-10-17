# Handoff for a local agent (laptop, then LinuxONE VM)

Branch: `claude/nifty-cori-bqc11z`. Read `PLAN.md`, `docs/SPEC.md` and this file first. The code
is complete and tested on synthetic data (`.venv/bin/python -m pytest -q` → 14 pass). Nothing has
run on real FDNY data yet; that is the job now. Deadline: submit on Hack2skill by **Oct 18 08:30 NY
time** (hard cutoff 10:00).

## Ground rules

- Use `.venv/bin/python` (macOS has no `python`). Run everything from the repo root.
- Don't change the approach or the leakage rules in `docs/SPEC.md`. Fix bugs; report findings.
- Never commit raw data (`data/raw/` is git-ignored). Commit only code and generated docs.
- Report numbers as they come out. If a hypothesis fails, say so in the docs. Don't tune on the
  test window (2026-01 onward).
- Never write "live 911", "saves lives", minutes saved in reality, or that FDNY endorsed this.
- Commit small, with clear messages; push to `claude/nifty-cori-bqc11z`.

## Step 1 — get the data (laptop)

```bash
.venv/bin/pip install -r requirements.txt
.venv/bin/python scripts/fetch_data.py --start 2026-01-01 --end 2026-02-01   # one month first, smoke test
ls data/raw
.venv/bin/python scripts/fetch_data.py --start 2023-01-01                    # full range; resumable
```
If throttled: set `SOCRATA_APP_TOKEN`. If a month fails, re-run (finished months are skipped).
Expect ~1.5M rows/year.

## Step 2 — P0 checks (laptop, minutes). GATE.

```bash
.venv/bin/python scripts/check_raw.py data/raw | tee docs/check_raw_output.txt
.venv/bin/python scripts/performance_audit.py --raw data/raw
```

Check these and write the answers at the top of `docs/performance_audit.md` under "Findings":

1. **Missing months?** Re-fetch any.
2. **Published vs recomputed dispatch seconds:** a mismatch rate above ~5% means the
   timestamp definitions in SPEC §2 are wrong. Stop and report.
3. **Held calls:** the backlog story needs `held` median dispatch ≫ not held (check_raw prints
   OK/CHECK). If CHECK, drop `held_*` features from `rescueflow/features.py` BACKLOG and note it.
4. **Severity codes stable across years?** If the code set changes, restrict to the stable years.
5. **Where is time lost?** `performance_audit.md` §2 and the recommended target
   (`dispatch` / `travel` / `response`). This decides `--target` for training.
6. **Volume vs delay** (§5): rho and within-decile spread. This is the pitch's "demand isn't the
   whole story" evidence, or not.
7. **Latest incident date:** the test window must end before it. If data stops before 2026-03,
   move `--test-start` earlier so the test window has at least 6–8 weeks.

Commit `docs/performance_audit.md`, `docs/check_raw_output.txt`, `submission/where_time_is_lost.png`.

## Step 3 — full run on the laptop (dry run before the VM)

```bash
.venv/bin/python scripts/run_pipeline.py --raw data/raw --val-start 2025-07-01 --test-start 2026-01-01 \
    --target <from step 2> --benchmark
.venv/bin/python scripts/run_policy_lab.py --raw data/raw --seeds 20
.venv/bin/python scripts/write_report.py --art artifacts
.venv/bin/python scripts/find_demo_moments.py --art artifacts
RESCUENYC_ARTIFACTS=artifacts .venv/bin/python -m uvicorn rescueflow.api:app --port 8000   # open localhost:8000
```

Read `docs/evaluation.md` and record in PLAN.md:
- **H1:** does `queue_aware` / full xgboost beat `demand_only` with non-overlapping CIs?
- **H2:** cascade delta CI excludes 0?
- **H3:** onset recall and lead time vs persistence.
- **Gate G3:** if the full model doesn't beat `backlog_logistic` or `demand_only`, the pitch
  becomes "dispatch-stress detection + attribution". Say so in `docs/evaluation.md`.
- **Policy lab:** the AI arm only counts as better if it beats `shock_reactive` (same budget).
  If the shock week chosen by default looks unrepresentative, choose `--eval-week` from the
  test window **before** looking at experiment-2 results, and write down why.

If anything crashes on real data, fix it, add a test, and commit. Likely spots: unexpected
borough names, severity codes outside 1–8, timestamps out of order, memory (pass fewer months).

## Step 4 — LinuxONE VM (one team server)

```bash
git clone -b claude/nifty-cori-bqc11z https://github.com/Cyriellewu/rescueflow-datathon.git /opt/rescuenyc
scp -r data/raw <user>@<vm-ip>:/opt/rescuenyc/data/          # from the laptop
cd /opt/rescuenyc && TARGET=<from step 2> bash scripts/setup_vm.sh
```
`setup_vm.sh` builds the container on the L1CC ML image, runs the audit, pipeline, policy lab,
reports, demo moments, NNPA check, starts the API on port 8000, opens the firewall, and runs
`scripts/verify_linuxone.sh`. If the image tag or `python3` path is wrong, fix the Dockerfile
`BASE` / command and re-run (it skips finished steps; `FORCE=1` redoes them).

Fallbacks: port blocked → `ssh -L 8000:localhost:8000 <user>@<vm-ip>`; Docker unavailable → run
the scripts directly in the image's Python; pandas/xgboost import fails → sklearn fallback is
automatic for the model (HistGradientBoosting).

Then commit the VM-generated `docs/evaluation.md`, `docs/data_audit.md`,
`docs/performance_audit.md` (numbers must come from the VM run that the video shows).
Screenshot into `submission/evidence/`: `uname -m`, container arch, `/health` showing
`computed_on: s390x`, `/benchmark`, `nnpa_bench.json`, both mandatory labs.

## Step 5 — fill the submission

- Replace every `[…]` in `submission/project_description.md` and `submission/demo-script.md` with
  numbers from `docs/evaluation.md` / `docs/performance_audit.md` / `benchmark.json`.
- Re-score `docs/JUDGING.md` with the real results.
- Pick the demo evening from `artifacts/demo_moments.json` (a caught onset, ideally an hour early).
- Update `README.md` "currently SYNTHETIC placeholders" line once real docs are committed.
- Title: `[Team Name]_IBM Z Datathon 2026 Project`. Video ≤ 3:00.

## Report back (short)

After each step, post: what ran, the key numbers, any gate that failed, and what you changed.
