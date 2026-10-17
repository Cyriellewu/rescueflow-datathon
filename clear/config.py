"""Every number that defines the experiment, in one place."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"          # incidents_YYYY-MM.csv from scripts/fetch_data.py
OUT = Path(__file__).resolve().parent / "results"

# Severity: FDNY initial_severity_level_code, 1 = most critical. 9 and missing are dropped.
HIGH_ACUITY = [1, 2, 3]
LOW_ACUITY = [4, 5, 6, 7, 8]

# Durations outside (0, 3 h] are treated as data errors and ignored.
MAX_SECONDS = 3 * 3600

# --- What "stressed" (堵) means -------------------------------------------------------------
# Hour T in borough B is stressed if the median dispatch wait of LOW-acuity calls created in
# [T, T+1h) is above the 80th percentile of the same statistic for the same borough and the same
# hour-of-week over the previous 8 weeks. Fewer than 5 such calls -> not judged (no label).
LABEL_QUANTILE = 0.8
TRAILING_WEEKS = 8
MIN_TRAILING_WEEKS = 4
MIN_CALLS_FOR_LABEL = 5

# --- Chronological split ---------------------------------------------------------------------
VAL_START = "2025-07-01"   # train: everything before
TEST_START = "2026-01-01"  # validation: [VAL_START, TEST_START); test: from TEST_START on

# --- Alerts ----------------------------------------------------------------------------------
# Every method may alert on the same share of hours (its own top 10% on validation), so no
# method can look better just by alerting more often.
ALERT_RATE = 0.10

BOOTSTRAP_REPS = 200
SEED = 0
