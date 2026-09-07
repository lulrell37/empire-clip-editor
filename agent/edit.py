"""FFmpeg: cut to the plan, reframe, burn captions, optionally score with music."""
import json
import os
import subprocess

WORK = "work"
SRT = os.path.join(WORK, "caps.srt")
CUT = os.path.join(WORK, "cut.mp4")
OUT = os.path.join(WORK, "out.mp4")

_DIMS = {"9:16": (1080, 1920), "1:1": (1080, 1080), "16:9": (1920, 1080)}
_ALIGN = {"bottom": 2, "center": 5, "top": 8}
_MARGIN = {"bottom": 90, "center": 40, "top": 90}


def _run(cmd):
    subprocess.run(cmd, check=True, capture_output=True, text=True)


# --- captions -------------------------------------------------------------
def _ts(t):
    if t < 0:
        t = 0
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = int(t % 60)
    ms = int(round((t - int(t)) * 1000))
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _remap_words(words, keep):
    """Words that fall inside the kept spans, retimed onto the new timeline."""
    out, offset = [], 0.0
    for a, b in keep:
        for w in words:
            mid = (w["start"] + w["end"]) / 2
            if a <= mid < b:
                out.append({
                    "word": w["word"],
                    "start": max(0.0, w["start"] - a) + offset,
                    "end": max(0.0, w["end"] - a) + offset,
                })
        offset += b - a
    out.sort(key=lambda w: w["start"])
    return out


def _cues(words):
    cues, buf = [], []
    for w in words:
        buf.append(w)
        text = " ".join(x["word"] for x in buf)
        if len(buf) >= 5 or w["word"][-1:] in ".?!," or len(text) >= 32:
            cues.append((buf[0]["start"], buf[-1]["end"], text.strip(" ,")))
            buf = []
    if buf:
        cues.append((buf[0]["start"], buf[-1]["end"], " ".join(x["word"] for x in buf).strip(" ,")))
    return [c for c in cues if c[2]]


def _write_srt(words, keep):
    cues = _cues(_remap_words(words, keep))
    if not cues:
        return False
    with open(SRT, "w") as fh:
        for i, (start, end, text) in enumerate(cues, 1):
            end = max(end, start + 0.4)
            fh.write(f"{i}\n{_ts(start)} --> {_ts(end)}\n{text}\n\n")
    return True


# --- filters -------------------------------------------------------------
def _reframe_filter(aspect):
    w, h = _DIMS.get(aspect, _DIMS["9:16"])
    return (
        f"scale={w}:{h}:force_original_aspect_ratio=increase,"
        f"crop={w}:{h},setsar=1"
    )


def _subtitles_filter(style):
    align = _ALIGN.get(style, 2)
    margin = _MARGIN.get(style, 90)
    force = (
        f"FontName=DejaVu Sans,Fontsize=15,Bold=1,"
        f"PrimaryColour=&H00FFFFFF,OutlineColour=&H00101010,BorderStyle=1,"
        f"Outline=3,Shadow=0,Alignment={align},MarginV={margin},MarginL=40,MarginR=40"
    )
    return f"subtitles={SRT}:force_style='{force}'"


# --- music -------------------------------------------------------------
def _pick_track(vibe):
    idx = os.path.join("music", "index.json")
    if not vibe or not os.path.exists(idx):
        return None
    try:
        tracks = json.load(open(idx)).get("tracks", [])
    except (json.JSONDecodeError, OSError):
        return None
    vibe_l = vibe.lower()
    best = None
    for t in tracks:
        hay = f"{t.get('vibe','')} {' '.join(t.get('tags', []))}".lower()
        score = sum(1 for word in vibe_l.split() if word in hay)
        if score and (best is None or score > best[0]):
            best = (score, t)
    if best is None and tracks:
        best = (0, tracks[0])
    if best is None:
        return None
    track = best[1]
    path = os.path.join("music", track["file"])
    return {"path": path, "gain_db": track.get("gain_db", -16)} if os.path.exists(path) else None


# --- the two passes ----------------------------------------------------
def _cut_and_style(src, plan, has_audio, words):
    keep = plan["keep"]
    has_caps = plan["captions"] and _write_srt(words, keep)

    parts, vlabels, alabels = [], [], []
    for i, (a, b) in enumerate(keep):
        parts.append(f"[0:v]trim=start={a}:end={b},setpts=PTS-STARTPTS[v{i}]")
        vlabels.append(f"[v{i}]")
        if has_audio:
            parts.append(f"[0:a]atrim=start={a}:end={b},asetpts=PTS-STARTPTS[a{i}]")
            alabels.append(f"[a{i}]")

    n = len(keep)
    if n > 1:
        parts.append("".join(vlabels) + f"concat=n={n}:v=1:a=0[vcat]")
        vsrc = "[vcat]"
        if has_audio:
            parts.append("".join(alabels) + f"concat=n={n}:v=0:a=1[acat]")
    else:
        vsrc = vlabels[0]

    vchain = _reframe_filter(plan["aspect"])
    if has_caps:
        vchain += "," + _subtitles_filter(plan["caption_style"])
    parts.append(f"{vsrc}{vchain}[vout]")

    cmd = ["ffmpeg", "-y", "-i", src, "-filter_complex", ";".join(parts), "-map", "[vout]"]
    if has_audio:
        cmd += ["-map", "[acat]" if n > 1 else alabels[0], "-c:a", "aac", "-b:a", "160k"]
    else:
        cmd += ["-an"]
    cmd += ["-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
            "-movflags", "+faststart", CUT]
    _run(cmd)
    return has_caps


def _add_music(track, has_audio):
    """Mix a looped music bed under the cut."""
    gain = track["gain_db"]
    if has_audio:
        fc = (
            f"[1:a]volume={gain}dB[bed];"
            f"[0:a][bed]amix=inputs=2:duration=first:dropout_transition=0,dynaudnorm[aout]"
        )
    else:
        fc = f"[1:a]volume={gain}dB[aout]"
    _run([
        "ffmpeg", "-y", "-i", CUT, "-stream_loop", "-1", "-i", track["path"],
        "-filter_complex", fc,
        "-map", "0:v", "-map", "[aout]",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "160k",
        "-shortest", "-movflags", "+faststart", OUT,
    ])


def render(src, plan, has_audio, words):
    os.makedirs(WORK, exist_ok=True)
    burned = _cut_and_style(src, plan, has_audio, words)

    track = _pick_track(plan.get("music"))
    music_note = None
    if plan.get("music"):
        if track:
            _add_music(track, has_audio)
            music_note = f"scored with {os.path.basename(track['path'])}"
        else:
            os.replace(CUT, OUT)
            music_note = f"music '{plan['music']}' skipped — no matching track in music/"
    else:
        os.replace(CUT, OUT)

    return {"path": OUT, "captions_burned": burned, "music_note": music_note}
