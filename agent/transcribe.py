"""Word-level transcript via faster-whisper."""
import os

from agent import sh

WAV = "work/audio.wav"
EMPTY = {"text": "", "words": [], "segments": []}


def _extract_audio(src):
    sh.run(["ffmpeg", "-y", "-i", src, "-vn", "-ac", "1", "-ar", "16000", WAV])
    return WAV


def run(src):
    """Return {'text', 'words':[{word,start,end}], 'segments':[{start,end,text}]}.

    Returns EMPTY on any failure — a missing transcript costs captions, not the
    whole edit.
    """
    try:
        from faster_whisper import WhisperModel

        _extract_audio(src)
        if not os.path.exists(WAV) or os.path.getsize(WAV) < 1024:
            return EMPTY

        model = WhisperModel("base", device="cpu", compute_type="int8")
        segments, _ = model.transcribe(WAV, word_timestamps=True, vad_filter=True)

        words, segs, full = [], [], []
        for seg in segments:
            text = seg.text.strip()
            segs.append({"start": seg.start, "end": seg.end, "text": text})
            full.append(text)
            for w in seg.words or []:
                words.append({"word": w.word.strip(), "start": w.start, "end": w.end})

        return {"text": " ".join(full).strip(), "words": words, "segments": segs}
    except Exception as e:
        print(f"transcription failed, continuing without captions: {e}")
        return EMPTY
