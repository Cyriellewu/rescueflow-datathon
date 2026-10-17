"""Operator briefing from a /risk borough payload, and a verifier that rejects unsupported numbers.

The template is the default. An LLM (llama.cpp on LinuxONE) may write the note instead, but its
output goes through the same verify() and is dropped if it states anything not in the payload.
"""
import re

NUMBER = re.compile(r"-?\d+(?:\.\d+)?")
BOROUGHS = ["BRONX", "BROOKLYN", "MANHATTAN", "QUEENS", "RICHMOND / STATEN ISLAND", "STATEN ISLAND"]


def pct(p: float) -> int:
    """Half-up rounding, matching the dashboard's toFixed(0)."""
    return int(p * 100 + 0.5)


def template(b: dict) -> str:
    name = b["borough"].title()
    if b["band"] == "insufficient_data":
        return f"{name}: not enough high-acuity calls to judge."
    where = "no dispatch or travel pressure" if b["bottleneck"] == "normal" else b["bottleneck"]
    lines = [f"{name}: {b['band']}, stress risk {pct(b['p_stress'])}%, {where}."]
    if b["held_pending_low"] or b["pending_high"]:
        lines.append(f"Waiting for a unit: {b['pending_high']} high-acuity, {b['pending_low']} low-acuity "
                     f"({b['held_pending_low']} low-acuity held); oldest {round(b['oldest_pending_age_s'] / 60)} min.")
    return " ".join(lines)


def allowed_numbers(b: dict) -> set:
    vals = set()
    for k, v in b.items():
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            vals |= {round(v, 1), round(v), round(v * 100), pct(v), round(v / 60)}
    for f in b.get("top_factors", []):
        if f.get("value") is not None:
            vals |= {round(f["value"], 1), round(f["value"])}
    return vals


def verify(note: str, b: dict) -> tuple[bool, list]:
    """True if every number and borough named in the note is backed by the payload."""
    allowed = allowed_numbers(b)
    bad = [n for n in NUMBER.findall(note) if round(float(n), 1) not in allowed and round(float(n)) not in allowed]
    upper = note.upper()
    bad += [x for x in BOROUGHS if x in upper and x not in b["borough"].upper()
            and not (x == "STATEN ISLAND" and "STATEN ISLAND" in b["borough"].upper())]
    return not bad, bad
