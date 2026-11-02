from __future__ import annotations

from .metrics import measure


class OfflineSpeechError(RuntimeError):
    pass


def transcribe_offline(pcm_bytes: bytes, sample_rate: int) -> str:
    """Transcribe mono 16-bit PCM entirely on the computer with PocketSphinx."""
    if not pcm_bytes or int(sample_rate) < 8_000:
        return ""
    try:
        import speech_recognition as sr
    except ImportError as exc:
        raise OfflineSpeechError("The free offline speech component is not installed.") from exc
    recognizer = sr.Recognizer()
    audio = sr.AudioData(bytes(pcm_bytes), int(sample_rate), 2)
    try:
        with measure("voice.offline_transcription"):
            text = recognizer.recognize_sphinx(audio, language="en-US")
    except sr.UnknownValueError:
        return ""
    except Exception as exc:
        raise OfflineSpeechError(f"Offline speech recognition failed: {exc}") from exc
    return " ".join(str(text).strip().split())[:2_000]


def transcribe_fast_free(pcm_bytes: bytes, sample_rate: int) -> str:
    """Use the no-key Google speech endpoint, then fall back to local speech.

    This is speech recognition rather than an AI model. Gemini remains the
    only language model and receives text after transcription.
    """
    if not pcm_bytes or int(sample_rate) < 8_000:
        return ""
    try:
        import speech_recognition as sr
    except ImportError as exc:
        raise OfflineSpeechError("The speech component is not installed.") from exc
    recognizer = sr.Recognizer()
    audio = sr.AudioData(bytes(pcm_bytes), int(sample_rate), 2)
    try:
        with measure("voice.fast_free_transcription"):
            text = recognizer.recognize_google(audio, language="en-GB")
    except sr.UnknownValueError:
        return ""
    except sr.RequestError:
        return transcribe_offline(pcm_bytes, sample_rate)
    except Exception as exc:
        raise OfflineSpeechError(f"Fast speech recognition failed: {exc}") from exc
    return " ".join(str(text).strip().split())[:2_000]
