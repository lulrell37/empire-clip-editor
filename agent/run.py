"""Entry point: read the issue, edit the clip, comment the result back.

Env: REPO, ISSUE_NUMBER, GH_TOKEN, ANTHROPIC_API_KEY (optional).
"""
import json
import os
import re
import sys
import traceback

from agent import edit, github, media, plan as planner, probe, transcribe

JOB_RE = re.compile(r"<!--\s*clip-job:\s*(\{.*?\})\s*-->", re.S)
DONE_MARKERS = ("clip-status: editing", "clip-result:", "clip-failed:")


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


def already_handled(number):
    for c in github.list_comments(number):
        if any(k in (c.get("body") or "") for k in DONE_MARKERS):
            return True
    return False


def hms(seconds):
    seconds = int(round(seconds))
    return f"{seconds // 60}:{seconds % 60:02d}"


def main():
    number = int(os.environ["ISSUE_NUMBER"])
    issue = github.get_issue(number)
    issue_url = issue.get("html_url", "")
    url, brief = parse_job(issue.get("body", ""))

    if not url:
        github.comment(number, "<!-- clip-failed: no media_url on the issue -->\n"
                               "— R.O.G.U.E. · couldn't find a clip link on this job —")
        sys.exit(1)

    if already_handled(number):
        print("already handled — nothing to do")
        return

    github.comment(number, "<!-- clip-status: editing -->\n— R.O.G.U.E. · picked it up, cutting now —")

    try:
        src = media.fetch(url)
        meta = probe.info(src)
        tr = transcribe.run(src)
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

    except Exception as e:
        tb = traceback.format_exc()
        print(tb, file=sys.stderr)
        reason = f"{type(e).__name__}: {e}".replace("\n", " ")[:280]
        github.comment(
            number,
            f"<!-- clip-failed: {reason} -->\n— R.O.G.U.E. · clip edit failed: {reason} —\n\n"
            f"<details><summary>trace</summary>\n\n```\n{tb[-2500:]}\n```\n</details>",
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
