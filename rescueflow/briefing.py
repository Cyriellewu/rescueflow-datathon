"""Operator briefing from a /risk borough payload, and a verifier that rejects unsupported numbers.

The template is the default. An LLM (llama.cpp on LinuxONE) may write the note instead, but its
output goes through the same verify() and is dropped if it states anything not in the payload.
"""
import json
import os
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


# ---- optional local LLM (llama.cpp on LinuxONE; big-endian GGUF needed on s390x) ----------
_LLM = {}
PROMPT = ("You write a two-sentence note for an EMS shift supervisor. Use only facts and numbers "
          "from the JSON. Name the borough, the band, the risk as a percent, the bottleneck, and how "
          "many calls are waiting. No advice, no other numbers.")
FIELDS = ["borough", "band", "p_stress", "bottleneck", "pending_high", "pending_low", "held_pending_low",
          "oldest_pending_age_s"]


def llm_available() -> bool:
    return bool(os.environ.get("RESCUENYC_LLM"))


def llm_note(b: dict, max_tokens=90):
    """Return (note, seconds) from the local model, or None if no model is configured."""
    path = os.environ.get("RESCUENYC_LLM")
    if not path:
        return None
    import time
    if "llm" not in _LLM:
        from llama_cpp import Llama
        _LLM["llm"] = Llama(model_path=path, n_ctx=1024, verbose=False)
    facts = {k: b[k] for k in FIELDS}
    facts["risk_percent"] = pct(b["p_stress"])
    t = time.perf_counter()
    out = _LLM["llm"].create_chat_completion(
        messages=[{"role": "system", "content": PROMPT}, {"role": "user", "content": json.dumps(facts)}],
        max_tokens=max_tokens, temperature=0.2)
    return out["choices"][0]["message"]["content"].strip(), time.perf_counter() - t


def note_for(b: dict, use_llm=False) -> dict:
    """Briefing fields for a payload: LLM note if enabled and it passes verify(), else the template."""
    if use_llm and llm_available():
        note, secs = llm_note(b)
        ok, bad = verify(note, {**b, "risk_percent": pct(b["p_stress"])})
        if ok:
            return {"briefing": note, "briefing_verified": True, "briefing_source": "llm", "llm_s": round(secs, 2)}
        fallback = template(b)
        return {"briefing": fallback, "briefing_verified": verify(fallback, b)[0], "briefing_source": "template",
                "llm_rejected": bad}
    note = template(b)
    return {"briefing": note, "briefing_verified": verify(note, b)[0], "briefing_source": "template"}
