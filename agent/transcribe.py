"""Word-level transcript via faster-whisper."""
import subprocess

WAV = "work/audio.wav"


def _extract_audio(src):
    subprocess.run(
        ["ffmpeg", "-y", "-i", src, "-vn", "-ac", "1", "-ar", "16000", WAV],
        check=True, capture_output=True,
    )
    return WAV


def run(src):
    """Return {'text': str, 'words': [{'word','start','end'}], 'segments': [...]}."""
    from faster_whisper import WhisperModel

    _extract_audio(src)
    model = WhisperModel("base", device="cpu", compute_type="int8")
    segments, _ = model.transcribe(WAV, word_timestamps=True, vad_filter=True)

    words, segs, full = [], [], []
    for seg in segments:
        segs.append({"start": seg.start, "end": seg.end, "text": seg.text.strip()})
        full.append(seg.text.strip())
        for w in seg.words or []:
            words.append({"word": w.word.strip(), "start": w.start, "end": w.end})

    return {"text": " ".join(full).strip(), "words": words, "segments": segs}
