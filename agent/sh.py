"""Run a subprocess and, on failure, raise with the tail of its stderr."""
import subprocess


def run(cmd, *, capture=True):
    p = subprocess.run(cmd, capture_output=capture, text=True)
    if p.returncode != 0:
        blob = ((p.stderr or "") + (p.stdout or "")).strip().splitlines()
        tail = " / ".join(blob[-15:]) if blob else "(no output)"
        raise RuntimeError(f"{cmd[0]} exit {p.returncode}: {tail}")
    return p
