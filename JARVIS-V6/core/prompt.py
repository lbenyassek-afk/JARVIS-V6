from __future__ import annotations

from pathlib import Path

from .config import load_config
from .memory import prompt_block
from .instructions import load as load_instructions
from .manager_prompt import load as load_manager_prompt


PROMPT_PATH = Path(__file__).with_name("prompt.txt")


def protected_prompt() -> str:
    text = PROMPT_PATH.read_text(encoding="utf-8").strip()
    if len(text) < 500:
        raise RuntimeError("Protected prompt is missing or incomplete")
    return text


def system_messages(user_text: str) -> list[dict]:
    full = load_config()
    cfg = full["assistant"]
    prompt = protected_prompt().replace("{assistant_name}", cfg["name"])
    serious = (
        "SERIOUS MODE IS ACTIVE. Be concise, operational and exact. Confirm the "
        "objective, identify dependencies, report blockers plainly, and never "
        "claim a desktop step succeeded without its execution result."
        if cfg.get("serious_mode") else
        "Serious Mode is inactive. Do not imply that desktop actions are enabled."
    )
    settings = (
        "[CURRENT ASSISTANT SETTINGS]\n"
        f"User preferred name: {cfg['user_name'] or 'not configured'}\n"
        f"Language: {cfg['language']}\nTone: {cfg['tone']}\n"
        f"Intelligence profile: {cfg.get('intelligence_profile', 'adaptive')}\n"
        f"Active context: {cfg.get('active_mode', 'personal')}\n"
        f"Response length: {cfg['response_length']}\n"
        f"Current daily focus: {cfg.get('daily_focus') or 'not configured'}\n"
        f"Focus session: {full.get('planning', {}).get('focus_session_minutes', 50)} minutes\n"
        f"Maximum daily priorities: {full.get('planning', {}).get('max_daily_priorities', 3)}\n"
        f"{serious}"
    )
    custom = load_instructions()
    custom_block = f"\n\n[USER CUSTOM INSTRUCTIONS]\n{custom}" if custom else ""
    manager = load_manager_prompt() if cfg.get("manager_enabled", True) else ""
    manager_block = f"\n\n[MANAGER PROMPT]\n{manager}" if manager else ""
    messages = [{"role": "system", "content": prompt + "\n\n" + settings + manager_block + custom_block}]
    memory = prompt_block(user_text, int(full["memory"].get("prompt_budget", 1800))) \
        if full["memory"].get("enabled", True) else ""
    if memory:
        messages.append({"role": "system", "content": memory})
    return messages
