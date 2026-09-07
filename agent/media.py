"""Fetch the source clip from whatever kind of link the brief carried."""
import os
import re
import subprocess
import urllib.request

WORK = "work"

_SOCIAL = re.compile(
    r"(youtube\.com|youtu\.be|tiktok\.com|instagram\.com|twitter\.com|x\.com|facebook\.com|fb\.watch|vimeo\.com)",
    re.I,
)
_DRIVE = re.compile(r"drive\.google\.com|docs\.google\.com", re.I)


def _run(cmd):
    subprocess.run(cmd, check=True)


def _drive_id(url):
    m = re.search(r"/d/([A-Za-z0-9_-]{20,})", url) or re.search(r"[?&]id=([A-Za-z0-9_-]{20,})", url)
    return m.group(1) if m else None


def fetch(url):
    """Download `url` into work/ and return the local path."""
    os.makedirs(WORK, exist_ok=True)

    if _DRIVE.search(url):
        import gdown

        fid = _drive_id(url)
        out = os.path.join(WORK, "source.mp4")
        gdown.download(id=fid, output=out, quiet=False) if fid else gdown.download(
            url, out, quiet=False, fuzzy=True
        )
        if not os.path.exists(out) or os.path.getsize(out) < 1024:
            raise RuntimeError("Google Drive download failed — is the link set to 'Anyone with the link'?")
        return out

    if _SOCIAL.search(url):
        out_tmpl = os.path.join(WORK, "source.%(ext)s")
        _run([
            "yt-dlp",
            "-f", "bv*[height<=1920]+ba/b[height<=1920]/b",
            "--merge-output-format", "mp4",
            "--no-playlist",
            "-o", out_tmpl,
            url,
        ])
        for ext in ("mp4", "mkv", "webm", "mov"):
            p = os.path.join(WORK, f"source.{ext}")
            if os.path.exists(p):
                return p
        raise RuntimeError("yt-dlp produced no file")

    # Plain direct link.
    out = os.path.join(WORK, "source.mp4")
    req = urllib.request.Request(url, headers={"User-Agent": "empire-clip-editor"})
    with urllib.request.urlopen(req, timeout=120) as resp, open(out, "wb") as fh:
        while True:
            chunk = resp.read(1 << 20)
            if not chunk:
                break
            fh.write(chunk)
    if os.path.getsize(out) < 1024:
        raise RuntimeError("direct download was empty")
    return out
