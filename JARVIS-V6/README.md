# JARVIS V6

**Created by Reda Benyassek**  
Copyright © 2026 Reda Benyassek.

JARVIS V6 is the next-generation Windows personal intelligence built from the
tested V5.3 codebase. V6 has an independent application profile, encrypted
memory, credentials, executable, installer, update channel and prerelease track.

## V6 target

- Minimal cinematic HUD with responsive natural voice.
- Gemini intelligence with a useful local core and provider-ready architecture.
- Organized, editable memory for identity, preferences, relationships, projects,
  businesses, goals, decisions, routines and notes.
- Plan-then-execute desktop control with allowlisted actions, permission tiers,
  emergency stop and sensitive-action audit.
- Verified research and unified School, Personal and Business workspaces.
- Secure plugin manifests and an authenticated companion transport for iPhone.

## Alpha 1 foundation

- Original V6 satin-titanium J-reactor icon with arctic-blue energy, transparent
  edges and ten Windows sizes from 16 to 256 pixels.
- Five persistent presence designs: Energy Orb, Reactor Core, HUD Face, Hybrid
  and Minimal Assistant, selectable directly from the main window or Settings.
- Six coordinated minimal colour themes plus an optional custom accent. Theme
  changes recolour the HUD, panels, controls, waveform and presence visual together.
- Voice customization for multilingual neural voices, preview, speed, pitch,
  volume, capture engine, activation behaviour and microphone selection.
- Four one-click voice styles—Cinematic, Fast Operator, Deep British and Natural
  British—plus fully custom voice, speed, pitch and volume controls.
- Multilingual intelligence for English, French, Arabic, Spanish, German, Italian
  and Portuguese, with automatic reply-language detection, language-specific free
  speech recognition and matching Edge neural voices.
- Fast, Adaptive and Thorough intelligence profiles with configurable tone and
  response length, multilingual research routing and resilient Gemini requests.
- Unicode-aware encrypted memory and conversation retrieval, including older
  relevant exchanges in any supported language without copying the full history.
- Desktop Mission Control for goal-based allowlisted plans, mouse-position capture,
  step reordering, live progress, emergency cancellation and encrypted action history.
- Windows app-aware control using accessibility names for windows, buttons, menu items
  and text fields, with an active-app scanner and coordinate fallback.
- Encrypted reusable Desktop Routines that remain locally validated when loaded again.
- Fast typed or spoken desktop commands for approved apps, window switching, desktop,
  volume, media, scrolling and screenshots, routed through the same permission system.
- `/desktop control` starts a session-only natural command mode. Multi-step spoken or
  typed goals are compiled by Gemini into structured steps and validated against the
  local action/value allowlist before approval or execution. `/desktop off` exits.
- Guided Gemini registration with live key-format feedback, stored-key retesting,
  explicit test/save states and Windows Credential Manager storage.
- Five-stage Gemini registration diagnostics for key format, Google connectivity,
  compatible model discovery, live generation and Windows Credential Manager storage.
  Successful setup stays visible until the user presses Done and explains why the
  key field was cleared.
- Structured Gemini voice understanding with transcript confidence, language metadata,
  background-audio rejection, adaptive end-of-speech timing and model fallback when a
  specific Flash model reaches its quota.
- Smarter answer continuity and self-checking for names, dates, quantities, assumptions
  and next actions, plus transparent recovery from temporary Gemini server failures.
- A full Capabilities screen reports ready, setup-required, disabled and future
  components without presenting unfinished integrations as working features.
- Eighteen bounded desktop actions including approved applications, Unicode text,
  named Windows controls, window focus and layout, clipboard, fixed shortcuts,
  pointer actions, scrolling, media, screenshots and waits. Sensitive actions
  still require explicit approval.
- Independent `%APPDATA%\JARVIS-V6` profile and `JARVIS-V6` Credential Manager service.
- Separate `JARVIS V6.exe`, installer identity and prerelease workflow.
- Local offline core for time, date, status, local memory search and capability help.
- Structured execution-plan validation against the desktop action allowlist.
- Complete mission preflight before the first side effect, dependency-aware
  execution graphs, encrypted crash checkpoints and blocked-step propagation.
- Postcondition verification for supported desktop actions, with bounded retries
  only where repeating the operation is safe.
- Reviewed desktop and no-execution simulation profiles selectable in Settings.
- Typed plugin operation and adapter contracts with exact domain allowlists and
  optional SHA-256 payload integrity checks.
- Hybrid encrypted memory retrieval that combines exact multilingual relevance
  with a lightweight local related-memory signal.
- A repeatable offline reliability benchmark available from Performance Monitor
  or with `python benchmark.py`.
- V6 memory metadata for importance, pinning, source and update history.
- Authenticated local companion command inbox. It queues commands for the main
  permission system and never executes desktop actions by itself.

Alpha builds are development previews. Stable V6 will ship only after Windows
hardware, clean-install, migration, voice, Gemini, recovery, performance and
desktop-control acceptance tests pass.

## Development

Run `python -m unittest discover -s tests -v`, `python benchmark.py`, then
`python main.py`.
Windows packaging is handled by `.github/workflows/build-jarvis-v6.yml`.

See [V7_PRODUCT_MAP.md](V7_PRODUCT_MAP.md) for the visual architecture, current
evidence, release gates and the recommended V7 sequence.
