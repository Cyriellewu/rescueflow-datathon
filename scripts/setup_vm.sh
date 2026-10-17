#!/usr/bin/env bash
# One-command setup on the team's LinuxONE VM. Safe to re-run: finished steps are skipped.
#
#   cd /opt/rescuenyc && git pull && bash scripts/setup_vm.sh
#
# Env: VAL_START (default 2025-07-01), TEST_START (2026-01-01), SEEDS (20), PORT (8000), TARGET (from audit),
#      EVAL_WEEK (optional Monday for the policy lab), FORCE=1 to redo training and the lab.
set -euo pipefail
cd "$(dirname "$0")/.."
VAL_START=${VAL_START:-2025-07-01}
TEST_START=${TEST_START:-2026-01-01}
SEEDS=${SEEDS:-20}
PORT=${PORT:-8000}
IMG=rescuenyc

say() { printf '\n\033[1m== %s\033[0m\n' "$*"; }

say "platform"
uname -m
[ "$(uname -m)" = "s390x" ] || echo "warning: not s390x — fine for a dry run, but evidence must come from the VM"
NATIVE=${NATIVE:-0}
PY=python3
if [ "$NATIVE" != 1 ] && command -v docker >/dev/null; then RT=docker
elif [ "$NATIVE" != 1 ] && command -v podman >/dev/null; then RT=podman
else
  NATIVE=1; RT=""
  echo "no docker or podman: NATIVE mode (system python3; install with: sudo apt-get install -y podman)"
fi
SUDO=""; [ -n "$RT" ] && { $RT ps >/dev/null 2>&1 || SUDO=sudo; echo "container runtime: $SUDO $RT"; }

say "data"
ls data/raw/incidents*.csv >/dev/null 2>&1 || { echo "no data/raw/incidents*.csv — scp them from the laptop first"; exit 1; }
echo "$(ls data/raw/incidents*.csv | wc -l) monthly files, $(du -sh data/raw | cut -f1)"

if [ "$NATIVE" = 1 ]; then
  say "native python (no container): apt packages are the only s390x binaries for pandas/sklearn"
  if ! python3 -c "import pandas, sklearn, matplotlib, scipy, requests" 2>/dev/null; then
    sudo apt-get update -qq && sudo apt-get install -y -qq python3-pandas python3-sklearn python3-matplotlib \
      python3-scipy python3-requests python3-pip python3-venv python3-full
  fi
  # PEP 668: the system python refuses pip; a venv that can see the apt packages takes the pure-python extras
  [ -x .venv-vm/bin/python ] || python3 -m venv --system-site-packages .venv-vm
  PY=$PWD/.venv-vm/bin/python
  $PY -c "import fastapi, uvicorn, httpx" 2>/dev/null || $PY -m pip install --quiet fastapi uvicorn httpx
  $PY -c "import xgboost" 2>/dev/null || $PY -m pip install --quiet xgboost 2>/dev/null \
    || echo "xgboost unavailable: sklearn HistGradientBoosting fallback is automatic"
  $PY -c "import pandas, sklearn; print('python', __import__('sys').version.split()[0], 'pandas', pandas.__version__, 'sklearn', sklearn.__version__)"
else
  say "image"
  if ! $SUDO $RT image inspect $IMG >/dev/null 2>&1 || [ "${FORCE:-0}" = 1 ]; then
    $SUDO $RT build -t $IMG .
  fi
  $SUDO $RT image inspect $IMG --format 'architecture: {{.Architecture}}'
fi

# run a pipeline step in the container with the repo mounted, as the current user so files stay ours
run() {
  if [ "$NATIVE" = 1 ]; then "$PY" "$@"
  else $SUDO $RT run --rm -u "$(id -u):$(id -g)" -e HOME=/tmp -v "$PWD":/app -w /app $IMG python3 "$@"; fi
}

say "P0 performance audit: where is time lost? (sets the label target unless TARGET is given)"
if [ ! -f artifacts/performance_audit.json ] || [ "${FORCE:-0}" = 1 ]; then
  run scripts/performance_audit.py --raw data/raw --art artifacts | tee artifacts_audit.log
fi
# team decision (PLAN.md, Oct 17): the low-acuity dispatch queue is where FDNY's queueing lands; the audit's
# own pick (travel) and the high-acuity dispatch label are run below as sensitivity targets
TARGET=${TARGET:-dispatch_low}
echo "label target: $TARGET"

say "features, model, evaluation, benchmark (on this machine)"
if [ ! -f artifacts/meta.json ] || [ "${FORCE:-0}" = 1 ]; then
  run scripts/run_pipeline.py --raw data/raw --val-start "$VAL_START" --test-start "$TEST_START" --benchmark \
    --target "$TARGET" \
    | tee artifacts_pipeline.log
else echo "artifacts/meta.json exists, skipped (FORCE=1 to redo)"; fi

say "label-target sensitivity (same run, other targets)"
for t in dispatch_low dispatch travel response; do
  [ "$t" = "$TARGET" ] && continue
  if [ ! -f "artifacts_$t/meta.json" ] || [ "${FORCE:-0}" = 1 ]; then
    run scripts/run_pipeline.py --raw data/raw --val-start "$VAL_START" --test-start "$TEST_START" \
      --target "$t" --out "artifacts_$t" | tee "artifacts_pipeline_$t.log"
  fi
done

say "policy lab (historical demand, then the 1.5x stress scenario)"
if [ ! -f artifacts/policy_lab.json ] || [ "${FORCE:-0}" = 1 ]; then
  run scripts/run_policy_lab.py --raw data/raw --seeds "$SEEDS" ${EVAL_WEEK:+--eval-week "$EVAL_WEEK"} \
    | tee artifacts_policy_lab.log
else echo "artifacts/policy_lab.json exists, skipped"; fi
if [ ! -f artifacts/policy_lab_stress.json ] || [ "${FORCE:-0}" = 1 ]; then
  run scripts/run_policy_lab.py --raw data/raw --seeds "$SEEDS" ${EVAL_WEEK:+--eval-week "$EVAL_WEEK"} \
    --demand-factor 1.5 --out artifacts_lab15 | tee artifacts_policy_lab_stress.log
  cp artifacts_lab15/policy_lab.json artifacts/policy_lab_stress.json
fi

say "reports and demo moments"
run scripts/write_report.py --art artifacts --alt-targets artifacts_travel artifacts_response artifacts_dispatch artifacts_dispatch_low
run scripts/find_demo_moments.py --art artifacts || true

say "accelerator check (NNPA vs CPU on a small MLP; claims only what ran)"
run scripts/nnpa_bench.py --art artifacts || echo "nnpa_bench failed; pitch says CPU inference"

say "API"
if [ "$NATIVE" = 1 ]; then
  pkill -f "uvicorn rescueflow.api:app" 2>/dev/null || true
  RESCUENYC_ARTIFACTS=$PWD/artifacts nohup "$PY" -m uvicorn rescueflow.api:app --host 0.0.0.0 --port "$PORT" \
    > api.log 2>&1 &
  echo "uvicorn started natively (log: api.log); restart by re-running this script"
else
  $SUDO $RT rm -f $IMG-api >/dev/null 2>&1 || true
  $SUDO $RT run -d --name $IMG-api --restart unless-stopped -p "$PORT":8000 \
    -v "$PWD":/app:ro $IMG   # repo mounted: after git pull, just re-run this script
fi
for i in $(seq 1 20); do curl -fs "localhost:$PORT/health" && break; sleep 1; done; echo

say "firewall"
if command -v iptables >/dev/null && ! sudo iptables -C INPUT -p tcp --dport "$PORT" -j ACCEPT 2>/dev/null; then
  sudo iptables -I INPUT -p tcp --dport "$PORT" -j ACCEPT && echo "opened tcp/$PORT"
else echo "port rule present or iptables unavailable"; fi
IP=$(curl -fs --max-time 3 ifconfig.me 2>/dev/null || hostname -I | awk '{print $1}')
echo "dashboard: http://$IP:$PORT   (fallback: ssh -L $PORT:localhost:$PORT <user>@$IP, then http://localhost:$PORT)"

say "evidence"
bash scripts/verify_linuxone.sh
echo "done. Commit docs/evaluation.md and docs/data_audit.md; screenshot this terminal."
