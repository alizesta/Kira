# Shared Skills

## Purpose
Shared Skills are reusable, installable instruction bundles. One library is used by Kira, Ren, Mika and custom characters. A Skill is not copied into a character profile and does not depend on the active persona.

## Package format
A Skill directory or ZIP contains `manifest.json` and `SKILL.md`. Only the instruction file is loaded; bundled executables and code are never imported or run.

## Architecture and ownership
- `kira/skills/registry.py` owns safe package discovery, validation, installation and removal.
- `kira/skills/service.py` owns the character-neutral enablement policy and bounded prompt contribution.
- `kira/app/shared_skills_application.py` owns application use cases, settings persistence and service lifecycle.
- `kira/app/feature_modules.py` registers the application service as a lifecycle-managed module.
- `kira/ui/bootstrap.py` resolves and injects the service into MainWindow.
- `kira/ui/main_window_composition.py` only accepts the injected application contract; it does not construct the service.
- `kira/ui/main_window_character_settings.py` adapts page events to application use cases. The page receives read-only application queries and emits intents; it does not mutate settings or call the domain service.
- Chat prompt composition obtains the active character's bounded Skill instructions through the application contract.

## Runtime and storage
The library is stored at `DATA_DIR/skills`. Global enablement applies to all characters unless a character has an explicit disable override. Character-only enablement does not leak into other characters. Every settings mutation is persisted by the application service.

## Safety boundaries
- ZIP traversal, absolute paths, Windows drive/backslash paths, symlinks, excessive file counts and oversized packages are rejected.
- The library has a 200-Skill limit; each package is limited to 64 files, 256 KiB per file and 1 MiB total.
- Prompt contribution is capped at 20,000 characters.
- Skill content is untrusted guidance and cannot override system/developer policy, user intent, safety checks or tool permission checks.
- Installing a Skill does not grant shell, filesystem, network or other tool capabilities and does not automatically enable it.

## UI
The manager is available under Settings → General → Skills. It supports ZIP/folder installation, global and per-character enablement, and uninstall.
