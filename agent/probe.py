"""ffprobe helpers."""
import json
import subprocess


def info(path):
    out = subprocess.run(
        [
            "ffprobe", "-v", "error", "-print_format", "json",
            "-show_format", "-show_streams", path,
        ],
        check=True, capture_output=True, text=True,
    ).stdout
    data = json.loads(out)
    v = next((s for s in data["streams"] if s["codec_type"] == "video"), None)
    a = next((s for s in data["streams"] if s["codec_type"] == "audio"), None)
    if not v:
        raise RuntimeError("source has no video stream")
    dur = float(data["format"].get("duration") or v.get("duration") or 0)
    return {
        "duration": dur,
        "width": int(v["width"]),
        "height": int(v["height"]),
        "has_audio": a is not None,
    }
