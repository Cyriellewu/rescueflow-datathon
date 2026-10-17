"""Print nearest-vs-optimized metrics for a 15-case surge in ZIP 10029 (East Harlem).

Hospital capacity and travel times are SIMULATED. Run from the repo root:
    .venv/bin/python scripts/demo_compare.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rescueflow.evaluate import compare, summary_table  # noqa: E402
from rescueflow.hospitals import SIMULATED  # noqa: E402
from rescueflow.scenarios import make_surge  # noqa: E402

if __name__ == "__main__":
    scenario = make_surge(15, "10029", seed=1)
    print(f"{scenario.label}  [hospital capacity SIMULATED={SIMULATED}]\n")
    result = compare(scenario)
    print(summary_table(result))
    print("\nper-hospital load (nearest → optimized):")
    for a, b in zip(result["nearest"]["per_hospital"], result["optimized"]["per_hospital"]):
        print(f"  {a['name']:<34} open={a['open_beds']:>2}  load {a['load']:>2} → {b['load']:>2}"
              f"   excess {a['excess']:>2} → {b['excess']:>2}")
