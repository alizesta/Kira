[فارسی](DEPENDENCY_LOCKS_FA.md) — [Installation guide](USER_GUIDE.md)

# Reproducible dependency locks

Kira targets Windows 11 x86-64 with CPython 3.11 and 3.12. The source requirement files remain the human-maintained compatibility ranges; generated lock files record the complete transitive resolution and SHA-256 hashes for each installation group and Python target.

## Generate or refresh the locks

Run these commands from the repository root on a Windows machine with access to a Python package index:

```powershell
py -3.12 -m pip install --upgrade uv
py -3.12 scripts/generate_dependency_locks.py
```

The generator resolves all groups for both supported Python versions against `x86_64-pc-windows-msvc`. It writes the results under `dependency-locks/windows-x86_64/python311/` and `dependency-locks/windows-x86_64/python312/`.

If the default Python Package Index is unreachable but an approved mirror is available, pass its PEP 503 simple-index URL:

```powershell
py -3.12 scripts/generate_dependency_locks.py --index-url https://<approved-mirror>/simple
```

The same setting can be supplied through `KIRA_PYPI_INDEX`. Do not put credentials in committed files or command transcripts. The generator passes the index to uv through its environment and replaces uv's generated command header with the script name.

Each generated file contains exact package versions and hashes. The generator stages every group first and publishes the new lock directory only after all resolutions succeed. A failed resolution leaves the existing lock directory unchanged. The Kitten engine group intentionally uses `--no-deps`, matching Kira's decision not to install the engine's optional PyTorch dependencies.

## Groups

| Lock name | Source requirements |
|---|---|
| `core` | `requirements.txt` |
| `system-optional` | `requirements-system-optional.txt` |
| `ocr` | `requirements-ocr.txt` |
| `audio` | `requirements-audio.txt` |
| `dev` | `requirements-dev.txt` |
| `voice-local` | `requirements-voice-local.txt` |
| `voice-kitten` | `requirements-voice-kitten.txt` |
| `voice-kitten-engine` | `requirements-voice-kitten-engine.txt` |

The generated `dependency-locks/` directory is local build output and is intentionally ignored by Git. `install.bat` and the updater install uv and regenerate all target lock files automatically before installing any dependency group. Do not hand-edit generated pins or hashes; change the source requirements/constraints and rerun setup instead.

Once the generated files are committed, `install_deps.py` automatically selects the matching Windows x64/Python lock and asks pip to enforce all recorded hashes with `--require-hashes`. Until a matching lock exists, the installer keeps using the original requirement and constraint files.

The generated locks are target-specific. A different operating system, CPU architecture, or Python version requires its own resolver target and lock set.
