#!/usr/bin/env bash
# One-command setup on the team's LinuxONE VM. Safe to re-run: finished steps are skipped.
#
#   cd /opt/rescuenyc && git pull && bash scripts/setup_vm.sh
#
# Env: VAL_START (default 2025-07-01), TEST_START (2026-01-01), SEEDS (20), PORT (8000),
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
if command -v docker >/dev/null; then RT=docker; elif command -v podman >/dev/null; then RT=podman; else
  echo "no docker or podman found"; exit 1; fi
SUDO=""; $RT ps >/dev/null 2>&1 || SUDO=sudo
echo "container runtime: $SUDO $RT"

say "data"
ls data/raw/incidents*.csv >/dev/null 2>&1 || { echo "no data/raw/incidents*.csv — scp them from the laptop first"; exit 1; }
echo "$(ls data/raw/incidents*.csv | wc -l) monthly files, $(du -sh data/raw | cut -f1)"

say "image"
if ! $SUDO $RT image inspect $IMG >/dev/null 2>&1 || [ "${FORCE:-0}" = 1 ]; then
  $SUDO $RT build -t $IMG .
fi
$SUDO $RT image inspect $IMG --format 'architecture: {{.Architecture}}'

# run a pipeline step in the container with the repo mounted, as the current user so files stay ours
run() { $SUDO $RT run --rm -u "$(id -u):$(id -g)" -e HOME=/tmp -v "$PWD":/app -w /app $IMG python3 "$@"; }

say "features, model, evaluation, benchmark (on this machine)"
if [ ! -f artifacts/meta.json ] || [ "${FORCE:-0}" = 1 ]; then
  run scripts/run_pipeline.py --raw data/raw --val-start "$VAL_START" --test-start "$TEST_START" --benchmark \
    | tee artifacts_pipeline.log
else echo "artifacts/meta.json exists, skipped (FORCE=1 to redo)"; fi

say "policy lab"
if [ ! -f artifacts/policy_lab.json ] || [ "${FORCE:-0}" = 1 ]; then
  run scripts/run_policy_lab.py --raw data/raw --seeds "$SEEDS" ${EVAL_WEEK:+--eval-week "$EVAL_WEEK"} \
    | tee artifacts_policy_lab.log
else echo "artifacts/policy_lab.json exists, skipped"; fi

say "reports and demo moments"
run scripts/write_report.py --art artifacts
run scripts/find_demo_moments.py --art artifacts || true

say "accelerator check (NNPA vs CPU on a small MLP; claims only what ran)"
run scripts/nnpa_bench.py --art artifacts || echo "nnpa_bench failed; pitch says CPU inference"

say "API"
$SUDO $RT rm -f $IMG-api >/dev/null 2>&1 || true
$SUDO $RT run -d --name $IMG-api --restart unless-stopped -p "$PORT":8000 \
  -v "$PWD":/app:ro $IMG   # repo mounted: after git pull, just re-run this script
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
