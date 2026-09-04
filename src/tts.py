# src/tts.py
#
# Text-to-speech for the "Suniye" button - reads a listing back out loud
# in Urdu. Uses gTTS (Google Text-to-Speech), which is free but requires
# internet (it's an HTTP call under the hood, not a local model like
# Whisper). This is a real limitation for this app's user base, so every
# caller MUST treat this as best-effort and fail gracefully - the button
# should just show a friendly "audio not available right now" instead of
# crashing the page if the user has no connection.
#
# Usage: python src/tts.py "koi Urdu text yahan"

import sys
import io

from gtts import gTTS


def text_to_speech_audio(text: str, lang: str = "ur") -> bytes:
    """
    Converts text to speech and returns raw mp3 bytes (so app.py can
    hand this straight to st.audio() without touching the filesystem).

    Raises:
        ValueError - covers every way this can fail: no internet, gTTS's
        translate endpoint being unreachable, empty text, rate limiting,
        etc. Deliberately broad (same reasoning as speech_to_text.py's
        exception handling) because gTTS's own exception types aren't
        consistent and the caller shouldn't need to know the difference
        between "no wifi" and "google blocked this request" - both just
        mean "can't play audio right now."
    """
    if not text or not text.strip():
        raise ValueError("Sunane ke liye koi text nahi hai.")

    try:
        tts = gTTS(text=text, lang=lang)
        buffer = io.BytesIO()
        tts.write_to_fp(buffer)
        buffer.seek(0)
        return buffer.read()
    except Exception as e:
        # covers no internet, DNS failure, gTTS endpoint down, rate
        # limiting, unsupported text, etc - all of it becomes one
        # friendly error the UI can catch the same way it already
        # catches transcription failures
        raise ValueError(f"Awaz taiyar nahi ho saki (internet check karein): {e}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print('Usage: python src/tts.py "kuch Urdu text"')
        sys.exit(1)

    input_text = sys.argv[1]
    print(f"[tts] Converting to speech: {input_text}")

    try:
        audio_bytes = text_to_speech_audio(input_text)
    except ValueError as e:
        print(f"[tts] Failed: {e}")
        sys.exit(1)

    out_path = "tts_test_output.mp3"
    with open(out_path, "wb") as f:
        f.write(audio_bytes)

    print(f"[tts] Saved {len(audio_bytes)} bytes to {out_path}")