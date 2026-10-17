#!/usr/bin/env bash
# Platform evidence for the submission. Run on the LinuxONE VM (inside or outside the container).
# Writes submission/evidence/platform.txt; screenshot the terminal as well.
set -u
cd "$(dirname "$0")/.."
mkdir -p submission/evidence
out=submission/evidence/platform.txt
PY=${PY:-python3}
{
  echo "== date";            date -Is
  echo "== uname -m";        uname -m
  echo "== os";              grep PRETTY_NAME /etc/os-release
  echo "== lscpu";           lscpu | grep -Ei 'architecture|model name|machine type|^cpu\(s\)|socket'
  echo "== memory";          free -h | head -2
  echo "== NNPA (on-chip AI accelerator)"
  if grep -qo nnpa /proc/cpuinfo; then echo "nnpa present"; else echo "nnpa NOT listed in /proc/cpuinfo"; fi
  echo "== python packages"
  $PY - <<'EOF'
import importlib, platform
print("python", platform.python_version(), platform.machine())
for mod in ["pandas", "numpy", "sklearn", "xgboost", "fastapi", "uvicorn", "torch", "llama_cpp"]:
    try:
        print(f"{mod:10s}", getattr(importlib.import_module(mod), "__version__", "ok"))
    except Exception as e:
        print(f"{mod:10s} MISSING ({type(e).__name__})")
EOF
  echo "== containers"
  (command -v podman && podman ps) || (command -v docker && docker ps) || echo "no container runtime"
  echo "== image architecture"
  (docker image inspect rescuenyc --format '{{.Architecture}}' 2>/dev/null \
    || podman image inspect rescuenyc --format '{{.Architecture}}' 2>/dev/null) || echo "image not built yet"
  echo "== API health"
  curl -s --max-time 5 http://localhost:8000/health || echo "API not running"
  echo
} 2>&1 | tee "$out"
echo "wrote $out"
