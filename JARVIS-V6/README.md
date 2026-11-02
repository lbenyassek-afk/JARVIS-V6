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

- Original V6 titanium-and-amber J-reactor icon with Windows sizes from 16 to 256 pixels.
- Five persistent presence designs: Energy Orb, Reactor Core, HUD Face, Hybrid
  and Minimal Assistant, selectable directly from the main window or Settings.
- Six coordinated minimal colour themes plus an optional custom accent. Theme
  changes recolour the HUD, panels, controls, waveform and presence visual together.
- Voice customization for British voice, preview, speed, pitch, volume, capture
  engine, activation behaviour and microphone selection.
- Independent `%APPDATA%\JARVIS-V6` profile and `JARVIS-V6` Credential Manager service.
- Separate `JARVIS V6.exe`, installer identity and prerelease workflow.
- Local offline core for time, date, status, local memory search and capability help.
- Structured execution-plan validation against the desktop action allowlist.
- V6 memory metadata for importance, pinning, source and update history.
- Authenticated local companion command inbox. It queues commands for the main
  permission system and never executes desktop actions by itself.

Alpha builds are development previews. Stable V6 will ship only after Windows
hardware, clean-install, migration, voice, Gemini, recovery, performance and
desktop-control acceptance tests pass.

## Development

Run `python -m unittest discover -s tests -v`, then `python main.py`.
Windows packaging is handled by `.github/workflows/build-jarvis-v6.yml`.
