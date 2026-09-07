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
brief and a timestamped transcript of the source footage. Return ONLY a JSON object \
with the cut and styling — no prose, no code fence.

Keys:
- keep: array of [start, end] second pairs into the SOURCE, in playback order. This \
is the cut: drop dead air, filler, false starts, and anything off-brief. If the \
whole thing should stay, return one pair spanning it.
- aspect: "9:16" unless the brief clearly wants square or landscape.
- captions: true unless the brief says no captions.
- caption_style: "bottom" (default), "center", or "top".
- music: the brief's music vibe as a short string, or null if none was asked for.
- target_seconds: the brief's target length in seconds, or null.
- notes: one short sentence for the strategist about what you did.

Honor the brief's hook, keep/cut calls, and length. Keep cuts on clause \
boundaries using the word timings. Never invent footage."""


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
            max_tokens=1500,
            system=SYSTEM,
            messages=[{"role": "user", "content": user}],
        )
        text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text").strip()
        if text.startswith("```"):
            text = text.split("```", 2)[1].lstrip("json").strip()
        return _coerce(json.loads(text), duration)
    except Exception as e:  # planning is best-effort — never fail the job on it
        plan = _default(duration)
        plan["notes"] = f"Planning pass failed ({str(e)[:120]}); kept the full clip."
        return plan
