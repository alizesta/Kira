# Reproducible dependency locks

Kira targets Windows 11 x86-64 with CPython 3.11 and 3.12. Human-maintained requirement files define compatibility ranges; generated locks capture the complete resolver output, exact versions and SHA-256 hashes for each dependency group and Python target.

## Core and optional dependency boundaries

- `requirements.txt` is the mandatory Core runtime.
- `requirements-*.txt` files describe independently installed optional features.
- `requirements-dev.txt` contains development-only tooling.
- `constraints.txt` and `constraints-voice.txt` express compatibility decisions shared by the relevant groups.

The Core lock is resolved first for each supported Python version. Every optional lock is then resolved against that exact Core lock as an additional constraint. This prevents an optional group from silently selecting a different version of a Core dependency. Optional groups are resolved independently: a conflict or unavailable package in one optional group is reported and omits only that group's lock. It does not prevent Core lock publication or Core installation. The installer can still attempt an unlocked optional group through its normal resolver preflight, and marks that feature unavailable if resolution fails.

The Core requirement intentionally keeps `google-genai<3`; `constraints.txt` currently pins the supported 2.x SDK line. Gemini Live imports `google.genai` from this Core dependency and does not depend on optional local speech packages. The Kitten engine remains a separate `--no-deps` group to avoid pulling its optional PyTorch dependency tree.

## Generate or refresh the locks

Normal setup runs the generator before installing dependencies. Maintainers can run it from the repository root on a machine with access to a Python package index:

```powershell
py -3.12 -m pip install --upgrade uv
py -3.12 scripts/generate_dependency_locks.py

# Intentional dependency upgrade only:
py -3.12 scripts/generate_dependency_locks.py --refresh --snapshot-cutoff 2026-12-01T00:00:00Z
```

The generator targets `x86_64-pc-windows-msvc` and writes under `dependency-locks/windows-x86_64/python311/` and `python312/`. Use `--python-versions 3.11` or `--python-versions 3.12` to regenerate one target. An approved PEP 503 mirror can be selected with `--index-url` or `KIRA_PYPI_INDEX`; credentials must not be committed.

Resolver behavior is made explicit: highest compatible versions within a fixed publication cutoff, hash generation, no machine-local uv configuration, and no index or find-links URLs in emitted lock files. The generator stores an input fingerprint with the locks. Normal setup reuses matching locks and does not silently upgrade project dependencies. To intentionally refresh dependencies, run the generator with `--refresh` and advance `--snapshot-cutoff` to the desired publication date. All output is staged. Core resolution or validation failure preserves the previous lock directory. Optional failures are reported separately and do not block Core.

Each generated package pin must be unique and have its own SHA-256 hash. A matching input fingerprint lets ordinary installs reuse the same lock set; optional locks that were unavailable remain omitted until inputs change or a maintainer explicitly refreshes them. The installer selects a matching Windows x64/Python lock when present and uses pip's `--require-hashes`. If an optional lock is absent, that optional group uses the normal requirement/constraint resolver and remains subject to preflight and rollback.

The generated `dependency-locks/` directory is local build output and is intentionally ignored by Git. Do not hand-edit generated pins or hashes; update the source requirement/constraint files and regenerate instead. These locks are target-specific; another OS, architecture, or Python version needs a separately defined resolver target.
