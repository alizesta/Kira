# Local Runtime Setup

Kira installation has three independent states: the application and its Python dependencies; the optional Ollama engine; and model weights. The engine is installed only after explicit consent. A model is pulled only after the user enters its exact Ollama model ID and confirms the registry size, disk-space check, and hardware assessment.

Run interactive setup or recovery with:

~~~powershell
.venv\Scripts\python.exe -m kira.setup_manager --interactive
~~~

Run read-only diagnostics with:

~~~powershell
.venv\Scripts\python.exe -m kira.setup_manager --status
~~~

Diagnostics expose a state-machine snapshot with independent installation, service, connection, version, model-catalog, selected-model, and inference states. A failure reading `/api/tags` no longer hides a successful `/api/version` connection; a failed generation probe is reported separately from model installation. Each stage carries its own status and actionable error where available. The executable, server reachability, version, installed model names, configured model, resolved installed alias, and real local generation probe remain independently observable. An installed model is not automatically selected, and a configured model is not ready until it can execute independently.

Before pulling, Setup Manager reads the Ollama Registry manifest, sums layer sizes, reserves 10% for metadata/recovery, and checks free space on the model-store volume. It refuses to start when space is insufficient; it does not guess sizes from a static table. Windows RAM is read from the operating system and NVIDIA VRAM from nvidia-smi when available. Hardware fit is advisory, not a speed guarantee.

Ollama's pull API retains partial layers and resumes them when the same model is pulled again. An interrupted transfer does not change the configured route. After a successful download, a separate confirmation is required before selecting the model as Kira's local chat model. Existing models are never removed and caches are never cleared.

If winget is unavailable, install Ollama with its official Windows installer, start the server, and rerun interactive setup.
