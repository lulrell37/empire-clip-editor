"""Entry point: read the issue, edit the clip, comment the result back.

Env: REPO, ISSUE_NUMBER, GH_TOKEN, ANTHROPIC_API_KEY (optional).
"""
import json
import os
import re
import signal
import sys
import traceback

from agent import edit, github, media, plan as planner, probe, transcribe

JOB_RE = re.compile(r"<!--\s*clip-job:\s*(\{.*?\})\s*-->", re.S)

# The ONLY marker that means "this job is finished, don't touch it again" is a
# real result. A bare "clip-status: editing" is just a run that started — if that
# run then dies (a hosted-runner reclaim, a timeout), a retry MUST be free to
# pick the job back up. A "clip-failed" likewise doesn't block a fresh attempt:
# reopening the issue is how you ask for another go.
RESULT_MARKER = "clip-result:"


class Interrupted(Exception):
    """SIGTERM — the hosted runner is being reclaimed or the job timed out."""


def _on_sigterm(_signum, _frame):
    raise Interrupted("runner received SIGTERM (hosted-runner reclaim or job timeout)")


def parse_job(body):
    m = JOB_RE.search(body or "")
    if m:
        try:
            j = json.loads(m.group(1))
            url = (j.get("media_url") or "").strip()
            brief = (j.get("instructions") or "").strip()
            if url:
                return url, brief
        except json.JSONDecodeError:
            pass
    # Fallback: the human-readable body.
    url = ""
    ms = re.search(r"\*\*Source:\*\*\s*(\S+)", body or "")
    if ms:
        url = ms.group(1).strip()
    mb = re.search(r"\*\*Brief:\*\*\s*(.+)", body or "", re.S)
    brief = mb.group(1).strip() if mb else ""
    return url, brief


def already_finished(number):
    """True only if a previous run actually produced a clip (posted a
    clip-result marker). Anything short of that is fair game to (re)run."""
    for c in github.list_comments(number):
        if RESULT_MARKER in (c.get("body") or ""):
            return True
    return False


def hms(seconds):
    seconds = int(round(seconds))
    return f"{seconds // 60}:{seconds % 60:02d}"


def _fail(number, reason, tb=None):
    reason = str(reason).replace("\n", " ")[:280]
    body = f"<!-- clip-failed: {reason} -->\n— R.O.G.U.E. · clip edit failed: {reason} —"
    if tb:
        body += f"\n\n<details><summary>trace</summary>\n\n```\n{tb[-2500:]}\n```\n</details>"
    else:
        body += "\n\n_Reopen the issue to try again._"
    try:
        github.comment(number, body)
    except Exception as post_err:  # nothing left to do but say so in the log
        print(f"could not post failure marker: {post_err}", file=sys.stderr)


def main():
    signal.signal(signal.SIGTERM, _on_sigterm)

    number = int(os.environ["ISSUE_NUMBER"])
    issue = github.get_issue(number)
    issue_url = issue.get("html_url", "")
    url, brief = parse_job(issue.get("body", ""))

    if not url:
        _fail(number, "no media_url on the issue")
        sys.exit(1)

    if already_finished(number):
        print("already finished (clip-result present) — nothing to do")
        return

    github.comment(number, "<!-- clip-status: editing -->\n— R.O.G.U.E. · picked it up, cutting now —")

    try:
        src = media.fetch(url)
        meta = probe.info(src)
        tr = transcribe.run(src) if meta["has_audio"] else transcribe.EMPTY
        plan = planner.make(brief, tr, meta["duration"])
        result = edit.render(src, plan, meta["has_audio"], tr["words"])

        final_len = sum(b - a for a, b in plan["keep"])
        tag = f"clip-{number}"
        notes = f"{issue.get('title','clip')}\n\nSource: {url}\nCut to {hms(final_len)} · {plan['aspect']}"
        download = github.upload_release_asset(
            tag, "clip.mp4", result["path"], title=f"Clip #{number}", notes=notes
        )

        bits = [plan["notes"], f"final cut {hms(final_len)} from {hms(meta['duration'])}"]
        if result["captions_burned"]:
            bits.append("captions burned")
        if result["music_note"]:
            bits.append(result["music_note"])
        summary = " · ".join(b for b in bits if b)

        payload = json.dumps({"download": download, "share": issue_url})
        github.comment(
            number,
            f"— R.O.G.U.E. · clip ready ✂️\n\n{download}\n\n_{summary}_\n\n<!-- clip-result: {payload} -->",
        )
        print("done:", download)

    except Interrupted as e:
        # Killed mid-edit. Leave a marker so nothing downstream waits forever,
        # and exit non-zero so the run shows as failed.
        print(f"interrupted: {e}", file=sys.stderr)
        _fail(number, e)
        sys.exit(1)
    except BaseException as e:  # noqa: BLE001 — a run must ALWAYS leave a marker
        tb = traceback.format_exc()
        print(tb, file=sys.stderr)
        _fail(number, f"{type(e).__name__}: {e}", tb=tb)
        sys.exit(1)


if __name__ == "__main__":
    main()
