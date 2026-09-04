"""
src/speech_to_text.py
----------------------
Step 2: Voice -> Text (Speech-to-Text)

Takes an audio file (worker or employer voice note) and returns the
transcribed Urdu text using a local Whisper model. No API key needed —
runs fully offline once the model is downloaded (first run only).

Requires ffmpeg to be installed on the system (used internally by
Whisper to decode .m4a/.mp3/.ogg files). Confirm with: ffmpeg -version

Usage (standalone test):
    python src/speech_to_text.py audio_samples/test_clips/worker1.m4a
"""

import sys
import os
from faster_whisper import WhisperModel

# ---------------------------------------------------------
# Model size: "tiny" | "base" | "small" | "medium" | "large"
# Kept on "small" — Urdu is a lower-resource language for Whisper, and
# "base" produces noticeably noisier transcripts on Urdu (garbled
# digits, dropped/merged words) than on English. "small" gives
# meaningfully better accuracy.
#
# Switched the engine from the original `openai-whisper` package to
# `faster-whisper` (CTranslate2 backend) — same model weights, same
# accuracy, but noticeably faster inference on CPU, especially with
# int8 quantization below. This directly cuts down the time the voice
# step is stuck processing, which was contributing to the app feeling
# hung/disconnected.
#
# Bump to "medium" instead if accuracy still isn't good enough on your
# real recordings and load time isn't a concern.
# ---------------------------------------------------------
MODEL_SIZE = "small"

# int8 = fastest + lowest memory on CPU, with a very small accuracy
# trade-off vs float32. Switch to "int8_float16" or "float16" if you
# later run this on a GPU machine.
COMPUTE_TYPE = "int8"

_model = None  # cached so we don't reload on every call (plain-Python fallback,
                # see get_model_cached() below for the Streamlit-safe version)


def get_model():
    """Load the Whisper model once and reuse it (loading is slow).
    Use this directly for standalone/CLI use. In app.py (Streamlit),
    prefer get_model_cached() instead — see note below."""
    global _model
    if _model is None:
        print(f"[speech_to_text] Loading Whisper '{MODEL_SIZE}' model (faster-whisper, {COMPUTE_TYPE})...")
        _model = WhisperModel(MODEL_SIZE, device="cpu", compute_type=COMPUTE_TYPE)
        print("[speech_to_text] Model loaded.")
    return _model


def get_model_cached():
    """
    Streamlit-safe version of get_model().

    Plain global-variable caching (get_model() above) usually works
    fine in Streamlit too, since the module stays loaded in memory —
    but st.cache_resource is the officially supported way Streamlit
    guarantees a heavy object like an ML model is loaded exactly once
    per session instead of on every rerun. Use this one from app.py.

    If streamlit isn't installed (e.g. running this file standalone
    from the command line), this quietly falls back to get_model().
    """
    try:
        import streamlit as st
    except ImportError:
        return get_model()

    @st.cache_resource
    def _load():
        print(f"[speech_to_text] Loading Whisper '{MODEL_SIZE}' model (cached, faster-whisper, {COMPUTE_TYPE})...")
        return WhisperModel(MODEL_SIZE, device="cpu", compute_type=COMPUTE_TYPE)

    return _load()


def transcribe_audio(audio_path: str) -> str:
    """
    Convert an audio file to Urdu text.

    Input:
        audio_path: path to a .mp3 / .wav / .m4a / .ogg file (5-15 sec ideal)

    Output:
        Plain transcript string (Urdu, possibly mixed with English words
        like "AC fitting" — Whisper handles code-mixing reasonably well).

    Raises:
        FileNotFoundError if audio_path doesn't exist.
        ValueError if the audio is empty/silent/too short/unreadable
        (caller should show a friendly "please try recording again"
        message rather than crashing) — this covers Whisper's own
        errors on silent audio AND lower-level failures like a
        missing/broken ffmpeg install or an unsupported/corrupt audio
        format, which do NOT always come back as RuntimeError.
    """
    if not os.path.exists(audio_path):
        raise FileNotFoundError(f"Audio file not found: {audio_path}")

    # Quick sanity check: reject empty/near-empty files before ever
    # calling Whisper. A 0-byte or tiny file means the mic captured
    # nothing (e.g. recording stopped instantly) — Whisper crashes on
    # zero-length audio, so we catch this case ourselves first.
    if os.path.getsize(audio_path) < 2000:
        raise ValueError("Recording appears to be empty or too short.")

    model = get_model_cached()

    try:
        # language="ur" tells Whisper to expect Urdu — improves accuracy
        # vs letting it auto-detect, especially on short/noisy clips.
        # faster-whisper returns a generator of segments + info instead
        # of a single dict, so we join the segment texts ourselves.
        segments, _info = model.transcribe(audio_path, language="ur")
        transcript = " ".join(segment.text.strip() for segment in segments).strip()
    except Exception as e:
        # Deliberately broad (not just RuntimeError): Whisper's failure
        # modes on bad input aren't consistent — silent/empty audio
        # tends to raise from a low-level tensor/decoding op, but a
        # missing/broken ffmpeg install, an unsupported container, or a
        # corrupted file can raise FileNotFoundError, subprocess errors,
        # or other exception types entirely. Catching broadly here means
        # ANY of these turns into one friendly, catchable ValueError for
        # the UI instead of an unhandled crash mid-demo.
        raise ValueError(
            f"Could not process this recording (it may be silent, too short, "
            f"or in an unsupported format): {e}"
        )

    if not transcript:
        raise ValueError("No speech was detected in the recording.")

    return transcript


# ---------------------------------------------------------
# Standalone test — run this file directly to try it out
# ---------------------------------------------------------
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python src/speech_to_text.py <path_to_audio_file>")
        sys.exit(1)

    audio_file = sys.argv[1]
    print(f"[speech_to_text] Transcribing: {audio_file}")

    text = transcribe_audio(audio_file)

    print("\n--- TRANSCRIPT ---")
    print(text)
    print("------------------")