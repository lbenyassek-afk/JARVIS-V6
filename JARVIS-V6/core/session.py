import time

class VoiceSession:
    def __init__(self, timeout=45, wake='hey jarvis', wake_phrases=None):
        phrases = [str(item).casefold().strip() for item in (wake_phrases or [wake]) if str(item).strip()]
        self.timeout = timeout
        self.wake = str(wake).casefold().strip()
        self.wake_phrases = tuple(dict.fromkeys(phrases or [self.wake]))
        self.until = 0

    def accept(self, text, now=None):
        now = time.monotonic() if now is None else now
        text = text.strip()
        lower = text.casefold().strip(' .!?')
        if lower in ('goodbye', 'stop listening', 'go to standby'):
            self.until = 0
            return None
        matched = next((phrase for phrase in self.wake_phrases
                        if lower == phrase or lower.startswith(phrase + " ")), None)
        if matched:
            text = text[len(matched):].lstrip(' ,.!?')
        elif now >= self.until:
            return None
        self.until = now + self.timeout
        return text

    def resolve(self, text, require_wake=True, now=None):
        """Accept natural speech immediately or enforce the wake session."""
        if require_wake:
            return self.accept(text, now)
        now = time.monotonic() if now is None else now
        text = str(text).strip()
        lower = text.casefold().strip(' .!?')
        if lower in ('goodbye', 'stop listening', 'go to standby'):
            self.until = 0
            return None
        matched = next((phrase for phrase in self.wake_phrases
                        if lower == phrase or lower.startswith(phrase + " ")), None)
        if matched:
            text = text[len(matched):].lstrip(' ,.!?')
        self.until = now + self.timeout
        return text
