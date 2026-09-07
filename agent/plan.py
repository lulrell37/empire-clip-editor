"""Turn the brief + transcript into an edit plan.

Plan shape:
  {
    "keep": [[start, end], ...],   # seconds into the source, in order = the cut
    "aspect": "9:16" | "1:1" | "16:9",
    "captions": bool,
    "caption_style": "bottom" | "center" | "top",
    "music": None | "<vibe words>",
    "target_seconds": float | None,
    "notes": "<one line back to R.O.G.U.E.>"
  }
"""
import json
import os

MODEL = "claude-sonnet-5"

SYSTEM = """You are the planning pass of an automated clip editor. You get an edit \
brief and a timestamped transcript of the source footage, and you call submit_plan \
with the cut and styling.

- keep: [start, end] second pairs into the SOURCE, in playback order. This is the \
cut: drop dead air, filler, false starts, and anything off-brief. To keep the whole \
thing, return one pair spanning it.
- Honor the brief's hook, keep/cut calls, and target length. Put cuts on clause \
boundaries using the word timings. Never invent footage."""

PLAN_TOOL = {
    "name": "submit_plan",
    "description": "Submit the edit plan for this clip.",
    "input_schema": {
        "type": "object",
        "properties": {
            "keep": {
                "type": "array",
                "items": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 2,
                    "maxItems": 2,
                },
                "description": "[start, end] second spans into the source, in playback order.",
            },
            "aspect": {"type": "string", "enum": ["9:16", "1:1", "16:9"]},
            "captions": {"type": "boolean"},
            "caption_style": {"type": "string", "enum": ["bottom", "center", "top"]},
            "music": {
                "type": ["string", "null"],
                "description": "The brief's music vibe, or null if none was asked for.",
            },
            "target_seconds": {"type": ["number", "null"]},
            "notes": {"type": "string", "description": "One short sentence on what you did."},
        },
        "required": ["keep", "aspect", "captions", "caption_style", "notes"],
    },
}


def _default(duration):
    return {
        "keep": [[0.0, round(duration, 2)]],
        "aspect": "9:16",
        "captions": True,
        "caption_style": "bottom",
        "music": None,
        "target_seconds": None,
        "notes": "No planning key set — kept the full clip, reframed vertical, burned captions.",
    }


def _coerce(plan, duration):
    out = _default(duration)
    if not isinstance(plan, dict):
        return out
    keep = []
    for pair in plan.get("keep") or []:
        try:
            a, b = float(pair[0]), float(pair[1])
        except (TypeError, ValueError, IndexError):
            continue
        a = max(0.0, min(a, duration))
        b = max(0.0, min(b, duration))
        if b - a >= 0.2:
            keep.append([round(a, 2), round(b, 2)])
    if keep:
        keep.sort()
        out["keep"] = keep
    if plan.get("aspect") in ("9:16", "1:1", "16:9"):
        out["aspect"] = plan["aspect"]
    if isinstance(plan.get("captions"), bool):
        out["captions"] = plan["captions"]
    if plan.get("caption_style") in ("bottom", "center", "top"):
        out["caption_style"] = plan["caption_style"]
    m = plan.get("music")
    out["music"] = m.strip() if isinstance(m, str) and m.strip() else None
    try:
        out["target_seconds"] = float(plan["target_seconds"]) if plan.get("target_seconds") else None
    except (TypeError, ValueError):
        pass
    if isinstance(plan.get("notes"), str) and plan["notes"].strip():
        out["notes"] = plan["notes"].strip()[:280]
    return out


def make(brief, transcript, duration):
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return _default(duration)

    try:
        import anthropic

        client = anthropic.Anthropic(api_key=key)
        segs = "\n".join(
            f"[{s['start']:.1f}-{s['end']:.1f}] {s['text']}" for s in transcript["segments"]
        )[:12000]
        user = (
            f"SOURCE DURATION: {duration:.1f}s\n\n"
            f"BRIEF:\n{brief}\n\n"
            f"TRANSCRIPT (source timestamps):\n{segs or '(no speech detected)'}"
        )
        resp = client.messages.create(
            model=MODEL,
            max_tokens=2000,
            system=SYSTEM,
            tools=[PLAN_TOOL],
            tool_choice={"type": "tool", "name": "submit_plan"},
            messages=[{"role": "user", "content": user}],
        )
        print("planner stop_reason:", getattr(resp, "stop_reason", "?"))
        call = next(
            (b for b in resp.content if getattr(b, "type", "") == "tool_use"), None
        )
        if call is None:
            raise RuntimeError(f"no tool_use in response: {resp.content!r}"[:300])
        print("planner plan:", json.dumps(call.input)[:600])
        return _coerce(call.input, duration)
    except Exception as e:  # planning is best-effort — never fail the job on it
        plan = _default(duration)
        plan["notes"] = f"Planning pass failed ({type(e).__name__}: {str(e)[:150]}); kept the full clip."
        return plan
