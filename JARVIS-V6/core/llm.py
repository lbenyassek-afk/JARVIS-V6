from __future__ import annotations

import base64
import io
import json
import re
import time
import wave

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .config import load_config
from .conversation import relevant_messages, remember_exchange
from .prompt import system_messages
from .secrets import get_secret
from .providers import select as select_provider
from .metrics import measure
from .tasks import Step
from .language import normalize_language, normalized_text


class LLMError(RuntimeError):
    pass


_AVAILABLE_MODELS: set[str] = set()


def normalize_gemini_key(value: str) -> str:
    text = str(value or "").strip()
    match = re.search(r"AIza[A-Za-z0-9_-]{20,}", text)
    return match.group(0) if match else text.strip("`'\" ")


def valid_gemini_key_format(value: str) -> bool:
    return bool(re.fullmatch(r"AIza[A-Za-z0-9_-]{20,}", normalize_gemini_key(value)))


def route_mode(user_text: str, profile: str = "adaptive") -> str:
    """Choose the lightest mode that can answer the request reliably."""
    text = normalized_text(user_text)
    research_phrases = (
        "latest", "today", "current", "news", "source", "research", "compare prices", "who is", "when did",
        "dernier", "aujourd hui", "actuel", "actualite", "source", "recherche", "compare les prix",
        "ultimo", "hoy", "actual", "noticias", "fuente", "investiga", "comparar precios",
        "aktuell", "heute", "nachrichten", "quelle", "recherchiere",
        "ultimo", "oggi", "attuale", "notizie", "fonte", "ricerca",
        "hoje", "atual", "noticias", "fonte", "pesquisa",
        "احدث", "أحدث", "اليوم", "حالي", "اخبار", "أخبار", "مصدر", "ابحث", "اسعار", "أسعار",
    )
    reflection_phrases = (
        "decide", "decision", "strategy", "trade offs", "analyse", "analyze", "reflect", "plan my", "risk", "pros and cons",
        "decider", "decision", "strategie", "analyser", "risque", "avantages et inconvenients",
        "decidir", "decision", "estrategia", "analizar", "riesgo", "ventajas y desventajas",
        "entscheiden", "entscheidung", "strategie", "analysieren", "risiko", "vor und nachteile",
        "decidere", "decisione", "strategia", "analizzare", "rischio", "pro e contro",
        "decidir", "decisao", "estrategia", "analisar", "risco", "pros e contras",
        "قرر", "قرار", "استراتيجية", "حلل", "مخاطر", "ايجابيات وسلبيات", "إيجابيات وسلبيات",
    )
    def contains(phrase: str) -> bool:
        if " " in phrase:
            return bool(re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", text, re.UNICODE))
        for token in text.split():
            if token == phrase:
                return True
            if len(phrase) >= 5 and token.startswith(phrase):
                if token[len(phrase):] in ("s", "e", "es", "er", "ere", "eres"):
                    return True
        return False
    if any(contains(phrase) for phrase in research_phrases):
        return "deep_search"
    if any(contains(phrase) for phrase in reflection_phrases):
        return "reflection"
    if profile == "thorough" and len(text.split()) >= 18 and "?" not in str(user_text):
        return "reflection"
    return "chat"


def _api_error(response) -> str:
    try:
        message = str(response.json().get("error", {}).get("message", "")).strip()
    except Exception:
        message = ""
    message = re.sub(r"AIza[A-Za-z0-9_-]{12,}", "[redacted Gemini key]", message)
    message = re.sub(r"\b(token|secret|password)\s*[:=]\s*\S+", r"\1=[redacted]", message, flags=re.I)
    return message[:300]


def _network_error(exc: Exception) -> str:
    if isinstance(exc, requests.Timeout):
        return "Gemini timed out. Check your internet connection, VPN, or firewall."
    if isinstance(exc, requests.exceptions.SSLError):
        return ("Gemini's secure connection failed. Check that Windows date and time are correct, "
                "then check antivirus HTTPS scanning.")
    return ("Cannot reach Google Gemini. Check the internet connection and allow JARVIS V6 "
            "through Windows Firewall or antivirus.")


def _gemini_rejection(response, stage: str) -> LLMError:
    detail = _api_error(response)
    lower = detail.casefold()
    if response.status_code in (400, 401) or "api key not valid" in lower or "api_key_invalid" in lower:
        return LLMError("Google rejected this API key. Create a new Gemini key in Google AI Studio and paste only the AIza key.")
    if response.status_code == 403:
        return LLMError(
            "Google received the key but denied Gemini access. In Google AI Studio, create a key "
            "for the Gemini API and remove incompatible application restrictions. " + detail)
    if response.status_code == 429:
        return LLMError("The key reached Gemini, but its current free quota is exhausted. Wait and retry, or use another project key.")
    return LLMError(f"Gemini {stage} failed (HTTP {response.status_code}). {detail}".strip())


def inspect_gemini_connection(key: str, verify_generation: bool = True) -> dict:
    """Validate one key without exposing it and return stage-by-stage diagnostics."""
    started = time.perf_counter()
    key = normalize_gemini_key(key)
    if not key:
        raise LLMError("Paste a Gemini API key first.")
    if not valid_gemini_key_format(key):
        raise LLMError("The key format is incomplete. Gemini API keys begin with AIza; paste the complete key from Google AI Studio.")
    try:
        response = requests.get(
            "https://generativelanguage.googleapis.com/v1beta/models",
            params={"key": key, "pageSize": 100},
            headers={"User-Agent": "JARVIS-V6/6.0"}, timeout=(12, 60),
        )
    except requests.RequestException as exc:
        raise LLMError(_network_error(exc)) from exc
    if response.status_code >= 400:
        raise _gemini_rejection(response, "model discovery")
    try:
        models = response.json().get("models", [])
    except ValueError as exc:
        raise LLMError("Gemini returned an invalid connection-test response.") from exc
    supported = {
        str(model.get("name", "")).removeprefix("models/")
        for model in models
        if "generateContent" in model.get("supportedGenerationMethods", [])
    }
    if not supported:
        raise LLMError("The key connected, but Gemini text generation is not enabled for it.")
    _AVAILABLE_MODELS.clear()
    _AVAILABLE_MODELS.update(supported)
    model = _supported_model("gemini-flash-latest")
    generation_state = "not_requested"
    message = f"Gemini connected successfully with {model}."
    if verify_generation:
        try:
            generated = requests.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                params={"key": key}, headers={"User-Agent": "JARVIS-V6/6.0"},
                json={"contents": [{"role": "user", "parts": [{"text": "Reply with exactly: CONNECTED"}]}],
                      "generationConfig": {"temperature": 0, "maxOutputTokens": 12}},
                timeout=(12, 60),
            )
        except requests.Timeout:
            generation_state = "timeout"
            message = (f"Gemini key verified with {model}. The optional generation test timed out, "
                       "so the key can still be saved; use Fast Chat to retry.")
        except requests.RequestException as exc:
            generation_state = "network_deferred"
            message = (f"Gemini key verified with {model}. The optional generation test could not finish "
                       f"({_network_error(exc)}); the key can still be saved.")
        else:
            if generated.status_code == 429:
                generation_state = "quota_limited"
                message = (f"Gemini key verified with {model}, but Google reports that its current free quota "
                           "is exhausted. The key can be saved for later use.")
            elif generated.status_code >= 400:
                raise _gemini_rejection(generated, "generation test")
            else:
                try:
                    text = generated.json()["candidates"][0]["content"]["parts"][0]["text"]
                except Exception as exc:
                    raise LLMError("Gemini connected but returned an unreadable test response.") from exc
                if "CONNECTED" not in str(text).upper():
                    raise LLMError("Gemini connected but did not complete its generation test.")
                generation_state = "ready"
    return {
        "message": message,
        "model": model,
        "model_count": len(supported),
        "generation": generation_state,
        "latency_ms": round((time.perf_counter() - started) * 1000),
    }


def validate_gemini_key(key: str, verify_generation: bool = False) -> str:
    """Compatibility wrapper used by startup checks and existing integrations."""
    return str(inspect_gemini_connection(key, verify_generation)["message"])


def _supported_model(preferred: str) -> str:
    if not _AVAILABLE_MODELS or preferred in _AVAILABLE_MODELS:
        return preferred
    for candidate in ("gemini-3.5-flash-lite", "gemini-3.5-flash",
                      "gemini-3-flash", "gemini-2.5-flash"):
        if candidate in _AVAILABLE_MODELS:
            return candidate
    flash = [name for name in _AVAILABLE_MODELS if "flash" in name]
    def rank(name: str):
        match = re.search(r"gemini-(\d+)(?:\.(\d+))?", name)
        version = (int(match.group(1)), int(match.group(2) or 0)) if match else (0, 0)
        return version + ("lite" in name, "latest" in name, "preview" not in name)
    return max(flash, key=rank) if flash else preferred


def _voice_fallback_model(current: str) -> str | None:
    """Choose one different audio-capable Flash model after a model quota 429."""
    priority = (
        "gemini-3.5-flash-lite", "gemini-3.5-flash", "gemini-3-flash",
        "gemini-2.5-flash-lite", "gemini-2.5-flash",
    )
    for candidate in priority:
        if candidate != current and candidate in _AVAILABLE_MODELS:
            return candidate
    candidates = sorted(name for name in _AVAILABLE_MODELS if "flash" in name and name != current)
    return candidates[0] if candidates else None


def _parse_voice_response(raw: str) -> dict:
    raw = str(raw or "").strip()
    if not raw:
        raise LLMError("Gemini returned an empty voice response.")
    try:
        data = json.loads(raw.removeprefix("```json").removesuffix("```").strip())
    except (ValueError, TypeError):
        data = None
    if isinstance(data, dict):
        status = str(data.get("status", "")).strip().casefold()
        transcript = str(data.get("transcript", "")).strip()
        answer = str(data.get("answer", "")).strip()
        language = str(data.get("detected_language", "")).strip()[:20]
        try:
            confidence = max(0.0, min(1.0, float(data.get("confidence", 1))))
        except (TypeError, ValueError):
            confidence = 0.0
        if status not in ("ok", "no_speech", "non_english", "standby"):
            raise LLMError("Gemini returned an unknown voice status.")
        if status != "ok" or confidence < .35:
            return {"status": status if status != "ok" else "no_speech", "transcript": "",
                    "answer": "", "language": language, "confidence": confidence}
        if not transcript or not answer:
            raise LLMError("Gemini did not return a complete transcript and answer.")
        return {"status": "ok", "transcript": transcript, "answer": answer,
                "language": language, "confidence": confidence}
    # Compatibility with responses created by builds before structured voice JSON.
    status_match = re.search(r"<status>\s*([^<]+)\s*</status>", raw, re.I)
    transcript_match = re.search(r"<transcript>(.*?)</transcript>", raw, re.I | re.S)
    answer_match = re.search(r"<answer>(.*?)</answer>", raw, re.I | re.S)
    if not status_match and not transcript_match and not answer_match:
        raise LLMError("Gemini returned an unreadable voice response.")
    status = status_match.group(1).strip().lower() if status_match else "ok"
    if status in ("no_speech", "non_english", "standby"):
        return {"status": status, "transcript": "", "answer": "", "language": "", "confidence": 1.0}
    transcript = transcript_match.group(1).strip() if transcript_match else ""
    answer = answer_match.group(1).strip() if answer_match else ""
    if not transcript or not answer:
        raise LLMError("Gemini did not return a complete transcript and answer.")
    return {"status": "ok", "transcript": transcript, "answer": answer,
            "language": "", "confidence": 1.0}


class LLMClient:
    def __init__(self):
        # Session history stays in memory. Persisted history is retrieved only
        # when the corresponding privacy setting is enabled.
        self.history: list[dict] = []
        # Keep TLS and HTTP connections warm between turns. Reopening a new
        # connection for every sentence adds latency without improving answers.
        self.session = requests.Session()
        retry = Retry(total=1, connect=1, read=1, backoff_factor=.2,
                      status_forcelist=(502, 503, 504), allowed_methods=frozenset({"POST"}))
        self.session.mount("https://", HTTPAdapter(max_retries=retry))

    def _post(self, url, **kwargs):
        response = self.session.post(url, **kwargs)
        if response.status_code == 404:
            old = url.split('/models/')[1].split(':')[0]
            validate_gemini_key(get_secret("gemini_api_key"))
            _AVAILABLE_MODELS.discard(old)
            replacement = _supported_model("gemini-flash-latest")
            if replacement != old and replacement in _AVAILABLE_MODELS:
                response = self.session.post(url.replace('/models/' + old + ':', '/models/' + replacement + ':'), **kwargs)
        return response

    def clear(self) -> None:
        self.history.clear()

    def record_exchange(self, user_text: str, answer: str) -> None:
        self.history.extend((
            {"role": "user", "content": str(user_text)},
            {"role": "assistant", "content": str(answer)},
        ))
        if load_config()["memory"].get("chat_history_enabled", True):
            remember_exchange(str(user_text), str(answer))

    def chat(self, user_text: str, mode: str = "chat") -> str:
        cfg = load_config()
        context_limit = int(cfg["memory"].get("chat_context_messages", 24))
        context = (
            relevant_messages(user_text, context_limit, 6)
            if cfg["memory"].get("chat_history_enabled", True)
            else self.history[-context_limit:]
        )
        messages = system_messages(user_text) + context + [
            {"role": "user", "content": user_text}
        ]
        with measure(f"gemini.{mode}"):
            answer = self._gemini(messages, cfg, mode)
        self.record_exchange(user_text, answer)
        return answer

    def plan_desktop(self, goal: str, registry) -> tuple[str, list[Step]]:
        """Convert a natural goal into a strictly allowlisted desktop plan."""
        key = get_secret("gemini_api_key")
        if not key:
            raise LLMError("Connect Gemini before using natural Desktop Control planning.")
        actions = []
        for action in registry.actions.values():
            item = {"name": action.name, "description": action.description}
            if action.values:
                item["allowed_values"] = list(action.values)
            actions.append(item)
        instruction = (
            "You are a desktop plan compiler. Convert the user's goal into the smallest reliable "
            "sequence using only the supplied actions. Never invent an action, executable, URL, "
            "shell command or value outside allowed_values. Add a short wait after opening an app "
            "when a later step needs that app ready. Prefer focus_window, invoke_control and "
            "set_control_text with accessible names over fragile screen coordinates. For "
            "set_control_text, format the value exactly as Control name || text. Coordinates must "
            "be explicit x,y values; if "
            "coordinates or another required fact are missing, return needs_clarification with one "
            "short question and no steps. Return JSON only."
        )
        schema = {
            "type": "OBJECT",
            "properties": {
                "goal": {"type": "STRING"},
                "needs_clarification": {"type": "BOOLEAN"},
                "question": {"type": "STRING"},
                "steps": {"type": "ARRAY", "maxItems": 20, "items": {
                    "type": "OBJECT",
                    "properties": {"action": {"type": "STRING"}, "value": {"type": "STRING"}},
                    "required": ["action", "value"],
                }},
            },
            "required": ["goal", "needs_clarification", "question", "steps"],
        }
        cfg = load_config(); model = _supported_model(cfg["llm"].get("fast_model", "gemini-3.5-flash-lite"))
        payload = {
            "system_instruction": {"parts": [{"text": instruction}]},
            "contents": [{"role": "user", "parts": [{"text":
                "AVAILABLE ACTIONS:\n" + json.dumps(actions, ensure_ascii=False) +
                "\n\nUSER GOAL:\n" + str(goal)[:2000]}]}],
            "generationConfig": {
                "temperature": 0,
                "maxOutputTokens": 900,
                "responseMimeType": "application/json",
                "responseSchema": schema,
            },
        }
        try:
            response = self._post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                params={"key": key}, json=payload, timeout=(8, 45),
            )
        except requests.Timeout as exc:
            raise LLMError("Desktop planning timed out. Try a shorter instruction.") from exc
        except requests.RequestException as exc:
            raise LLMError("Desktop planning could not reach Gemini.") from exc
        if response.status_code >= 400:
            raise _gemini_rejection(response, "desktop planning")
        try:
            raw = "".join(
                part.get("text", "")
                for part in response.json()["candidates"][0]["content"]["parts"])
            data = json.loads(raw)
        except Exception as exc:
            raise LLMError("Gemini returned an invalid desktop plan.") from exc
        if data.get("needs_clarification"):
            question = " ".join(str(data.get("question", "Please clarify the desktop task.")).split())
            raise LLMError("CLARIFY: " + question[:300])
        steps = [Step(str(item.get("action", "")), str(item.get("value", "")))
                 for item in data.get("steps", []) if isinstance(item, dict)]
        if not steps:
            raise LLMError("Gemini could not create a desktop plan from that instruction.")
        # The existing planner performs the final action/value allowlist check.
        return (" ".join(str(data.get("goal") or goal).split())[:300], steps)

    def chat_audio(self, pcm_bytes: bytes, sample_rate: int, mode: str = "chat",
                   english_only: bool = False, require_wake: bool = False,
                   wake_phrase: str = "hey jarvis") -> dict:
        """Understand one voice turn and answer it in a single Gemini request."""
        key = get_secret("gemini_api_key")
        if not key:
            raise LLMError("Gemini API key is missing. Open Settings and test your key.")
        if int(sample_rate) < 8_000 or not pcm_bytes:
            return {"status": "no_speech", "transcript": "", "answer": "", "confidence": 0.0}
        duration = len(pcm_bytes) / (2 * int(sample_rate))
        if duration < .16:
            return {"status": "no_speech", "transcript": "", "answer": "", "confidence": 0.0}
        if duration > 30:
            raise LLMError("That voice turn was longer than 30 seconds. Pause briefly and try a shorter request.")
        cfg = load_config()
        mode = mode if mode in ("auto", "chat", "deep_search", "reflection") else "auto"
        messages = system_messages("")
        system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
        mode_rule = {
            "auto": "Use the fastest direct answer unless current sources or careful analysis are truly needed.",
            "chat": "Answer quickly, directly and naturally.",
            "deep_search": "Research with Google Search, compare reliable sources and cite them.",
            "reflection": "Think carefully about assumptions and tradeoffs before recommending an action.",
        }[mode]
        selected_language = normalize_language(cfg["assistant"].get("language", "auto"))
        language_rule = (
            "If the speech is not English, return <status>non_english</status>."
            if english_only else
            f"Understand the spoken language and answer in configured language '{selected_language}'."
            if selected_language != "auto" else
            "Understand the spoken language and answer in that same language."
        )
        structured = mode != "deep_search"
        system += (
            "\n\n[VOICE TURN]\n" + mode_rule + " " + language_rule +
            " Detect near-field human speech and ignore music, television, keyboard noise and distant voices. "
            "If speech is unclear, never guess. Keep the spoken answer natural and compact unless the user asks for detail. "
            "Avoid tables and long raw URLs in the spoken answer. "
            + (f"The speech must begin with the wake phrase '{wake_phrase}'. If it does not, "
               "use status standby. If it does, omit the wake phrase from the transcript. "
               if require_wake else "") +
            ("Return only the required JSON object with the exact transcript, answer, detected language and "
             "a confidence from 0 to 1. Use status no_speech when there is no clear human speech."
             if structured else
             "Return exactly <status>ok</status><transcript>the user's exact words</transcript>"
             "<answer>your complete answer</answer>. Use status no_speech when needed. Never invent a transcript.")
        )
        wav = io.BytesIO()
        with wave.open(wav, "wb") as stream:
            stream.setnchannels(1); stream.setsampwidth(2); stream.setframerate(sample_rate)
            stream.writeframes(pcm_bytes)
        contents = []
        context_limit = int(cfg["memory"].get("chat_context_messages", 24))
        voice_context = (
            relevant_messages("", context_limit, 0)
            if cfg["memory"].get("chat_history_enabled", True)
            else self.history[-context_limit:]
        )
        for message in voice_context:
            role = "model" if message["role"] == "assistant" else "user"
            contents.append({"role": role, "parts": [{"text": message["content"]}]})
        contents.append({"role": "user", "parts": [
            {"text": "Listen to this voice command and respond using the required tags."},
            {"inline_data": {"mime_type": "audio/wav",
                             "data": base64.b64encode(wav.getvalue()).decode("ascii")}},
        ]})
        preferred = cfg["llm"].get("fast_model" if mode in ("auto", "chat") else "smart_model",
                                   "gemini-3.5-flash-lite")
        model = _supported_model(preferred)
        profile = cfg["assistant"].get("intelligence_profile", "adaptive")
        response_length = cfg["assistant"].get("response_length", "balanced")
        voice_budget = {"concise": 320, "balanced": 650, "detailed": 1100}.get(response_length, 650)
        if profile == "fast": voice_budget = min(voice_budget, 450)
        generation = {"temperature": .25, "maxOutputTokens": voice_budget if mode in ("auto", "chat") else 1900}
        if mode == "reflection":
            generation["thinkingConfig"] = {"thinkingBudget": 768 if profile == "fast" else 1536}
        if structured:
            generation.update({
                "responseMimeType": "application/json",
                "responseSchema": {
                    "type": "OBJECT",
                    "properties": {
                        "status": {"type": "STRING", "enum": ["ok", "no_speech", "non_english", "standby"]},
                        "transcript": {"type": "STRING"}, "answer": {"type": "STRING"},
                        "detected_language": {"type": "STRING"},
                        "confidence": {"type": "NUMBER", "minimum": 0, "maximum": 1},
                    },
                    "required": ["status", "transcript", "answer", "detected_language", "confidence"],
                },
            })
        payload = {
            "system_instruction": {"parts": [{"text": system}]},
            "contents": contents,
            "generationConfig": generation,
        }
        # Search grounding is expensive and unnecessary for ordinary voice
        # turns. The user can select Deep Search explicitly when current
        # sources are required.
        if mode == "deep_search":
            payload["tools"] = [{"google_search": {}}]
        try:
            response = self._post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                params={"key": key}, json=payload, timeout=(8, 55),
            )
            if response.status_code == 429:
                if not _AVAILABLE_MODELS:
                    try:
                        validate_gemini_key(key)
                    except LLMError:
                        pass
                fallback = _voice_fallback_model(model)
                if fallback:
                    response = self._post(
                        f"https://generativelanguage.googleapis.com/v1beta/models/{fallback}:generateContent",
                        params={"key": key}, json=payload, timeout=(8, 55),
                    )
        except requests.Timeout as exc:
            raise LLMError("Voice response timed out. Check your internet and try again.") from exc
        except requests.RequestException as exc:
            raise LLMError("Voice could not reach Gemini. Check your internet connection.") from exc
        if response.status_code in (400, 401, 403):
            raise LLMError("Gemini rejected the voice request. Open Settings and test your key. "
                           + _api_error(response))
        if response.status_code == 429:
            raise LLMError(
                "Gemini's free voice quota is temporarily exhausted. "
                "JARVIS will pause voice capture briefly; typed chat may still work."
            )
        if response.status_code >= 400:
            raise LLMError(f"Voice request failed (HTTP {response.status_code}). {_api_error(response)}".strip())
        try:
            parts = response.json()["candidates"][0]["content"]["parts"]
            raw = "".join(part.get("text", "") for part in parts).strip()
        except Exception as exc:
            raise LLMError("Gemini returned an invalid voice response.") from exc
        return _parse_voice_response(raw)

    def _gemini(self, messages: list[dict], cfg: dict, mode: str) -> str:
        provider = select_provider(cfg, mode)
        if provider.provider_id != "gemini":
            raise LLMError(f"The selected provider '{provider.name}' is not installed yet.")
        key = get_secret("gemini_api_key")
        if not key:
            raise LLMError("Gemini API key is missing. Open Settings → AI Provider.")
        system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
        mode = mode if mode in ("auto", "chat", "deep_search", "reflection") else "auto"
        if mode == "auto":
            latest = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
            mode = route_mode(latest, cfg["assistant"].get("intelligence_profile", "adaptive"))
        mode_rules = {
            "chat": (
                "[CHAT MODE] Answer quickly and directly. Resolve the user's intent from "
                "the current message, relevant memory and recent conversation. Ask only when "
                "a missing fact makes a correct answer impossible."
            ),
            "deep_search": (
                "[DEEP SEARCH MODE] Research the question using the supplied Google Search "
                "tool. Compare independent credible sources, distinguish current facts from "
                "inference, include relevant dates, surface meaningful disagreement, and give "
                "a structured evidence-based answer. Never invent a citation."
            ),
            "reflection": (
                "[REFLECTION MODE] Think carefully about assumptions, tradeoffs, second-order "
                "effects and failure modes. Give a practical recommendation after the analysis."
            ),
        }
        system += "\n\n" + mode_rules[mode] + (
            "\n\n[ANSWER QUALITY] Resolve references using the relevant conversation and memory. "
            "Do not repeat information the user already knows. Check names, dates, units and assumptions "
            "before answering. When uncertainty changes the recommendation, state it briefly. End with a "
            "clear next action when the user is planning or deciding."
        )
        contents = []
        for message in messages:
            if message["role"] == "system":
                continue
            role = "model" if message["role"] == "assistant" else "user"
            contents.append({"role": role, "parts": [{"text": message["content"]}]})
        model = (cfg["llm"].get("fast_model", "gemini-3.5-flash-lite")
                 if mode == "chat" else
                 cfg["llm"].get("smart_model", "gemini-3.5-flash-lite"))
        model = _supported_model(model)
        profile = cfg["assistant"].get("intelligence_profile", "adaptive")
        length = cfg["assistant"].get("response_length", "balanced")
        token_budget = {"concise": 500, "balanced": 900, "detailed": 1600}.get(length, 900)
        if profile == "fast":
            token_budget = min(token_budget, 650)
        elif profile == "thorough":
            token_budget = max(token_budget, 1300)
        generation = {
            "temperature": .25 if mode == "deep_search" else .4,
            "maxOutputTokens": token_budget if mode == "chat" else max(1800, token_budget),
        }
        if mode == "reflection":
            thinking = {"fast": 1024, "adaptive": 2048, "thorough": 3072}.get(profile, 2048)
            generation["thinkingConfig"] = {"thinkingBudget": thinking}
        payload = {
            "system_instruction": {"parts": [{"text": system}]},
            "contents": contents,
            "generationConfig": generation,
        }
        if mode == "deep_search":
            payload["tools"] = [{"google_search": {}}]
        try:
            response = self._post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                params={"key": key}, json=payload,
                timeout=(12, 120 if mode != "chat" else 75),
            )
            if response.status_code == 429:
                if not _AVAILABLE_MODELS:
                    try:
                        validate_gemini_key(key)
                    except LLMError:
                        pass
                fallback = _voice_fallback_model(model)
                if fallback:
                    response = self._post(
                        f"https://generativelanguage.googleapis.com/v1beta/models/{fallback}:generateContent",
                        params={"key": key}, json=payload,
                        timeout=(12, 120 if mode != "chat" else 75),
                    )
        except requests.Timeout as exc:
            raise LLMError("Gemini took too long to answer. Check your internet and try again.") from exc
        except requests.RequestException as exc:
            raise LLMError("Cannot reach Gemini. Check your internet connection and try again.") from exc
        if response.status_code in (400, 401, 403):
            detail = _api_error(response)
            raise LLMError(
                "Gemini rejected the request. Open Settings and use Save & Test Gemini. "
                + detail
            )
        if response.status_code == 404:
            raise LLMError("This Gemini model is unavailable for your key. Open Settings and test Gemini again.")
        if response.status_code == 429:
            raise LLMError("Gemini rate limit reached. Wait briefly and try again.")
        if response.status_code >= 500:
            raise LLMError("Gemini is temporarily unavailable. Your conversation is safe; try again shortly.")
        response.raise_for_status()
        try:
            data = response.json()
            candidate = data["candidates"][0]
            if not candidate.get("content", {}).get("parts"):
                reason = str(candidate.get("finishReason", "unknown reason")).replace("_", " ").lower()
                raise LLMError(f"Gemini could not complete that answer ({reason}). Rephrase the request and try again.")
            parts = candidate["content"]["parts"]
            answer = "".join(part.get("text", "") for part in parts).strip()
            if not answer:
                raise ValueError("empty answer")
            if mode == "deep_search":
                chunks = candidate.get("groundingMetadata", {}).get("groundingChunks", [])
                sources = []
                for chunk in chunks:
                    web = chunk.get("web") if isinstance(chunk, dict) else None
                    if not isinstance(web, dict) or not web.get("uri"):
                        continue
                    item = (str(web.get("title") or "Source").strip(), str(web["uri"]).strip())
                    if item not in sources:
                        sources.append(item)
                if sources:
                    answer += "\n\nSources:\n" + "\n".join(
                        f"- {title}: {url}" for title, url in sources[:8]
                    )
            return answer
        except LLMError:
            raise
        except Exception as exc:
            raise LLMError("Gemini returned a malformed response.") from exc


def transcribe_pcm(pcm_bytes: bytes, sample_rate: int = 16_000,
                   english_only: bool = False) -> str:
    """Transcribe a microphone turn with Gemini without storing the recording."""
    key = get_secret("gemini_api_key")
    if not key:
        raise LLMError("Gemini API key is required for voice transcription.")
    wav = io.BytesIO()
    with wave.open(wav, "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(sample_rate)
        stream.writeframes(pcm_bytes)
    model = load_config()["llm"].get("fast_model", "gemini-3.5-flash-lite")
    model = _supported_model(model)
    instruction = (
        "Classify and transcribe this microphone segment. "
        "If it is background noise, music, silence, television, or unclear speech, "
        "return exactly [NO_SPEECH]. If the spoken language is not English, return "
        "exactly [NON_ENGLISH]. Otherwise transcribe the English speech exactly and "
        "return only the spoken words. Do not translate."
        if english_only else
        "Transcribe this speech exactly. Return only the spoken words. If it contains "
        "no intelligible speech, return exactly [NO_SPEECH]."
    )
    try:
        response = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            params={"key": key},
            json={"contents": [{"role": "user", "parts": [
                {"text": instruction},
                {"inline_data": {"mime_type": "audio/wav",
                                 "data": base64.b64encode(wav.getvalue()).decode("ascii")}},
            ]}]},
            timeout=(8, 45),
        )
    except requests.RequestException as exc:
        raise LLMError("Voice could not reach Gemini. Check your internet connection.") from exc
    if response.status_code >= 400:
        detail = _api_error(response)
        raise LLMError(f"Voice transcription failed (HTTP {response.status_code}). {detail}".strip())
    try:
        return response.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
    except Exception as exc:
        raise LLMError("Gemini returned an invalid transcription.") from exc
