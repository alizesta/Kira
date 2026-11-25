# Move Ollama Model Storage to Drive A

Ollama chat models are stored separately from Kira's internal cache. To keep them alongside Kira's data:

1. Make sure drive A is available.
2. Fully quit Ollama from its System Tray icon.
3. Run `configure_ollama_storage.bat` from the Kira root folder and confirm the operation.
4. The script **copies** existing models from their current location to:

```text
A:\Project KIRA\Kira Attachments\ollama\models
```

5. It sets the Windows user environment variable `OLLAMA_MODELS` to that path.
6. Start Ollama again from the Start Menu and use `ollama list` to verify that the models are visible.

**Source files are not deleted.** The operation uses copying so the original models remain available if an error occurs. After confirming that Ollama reads models from the new location, you may delete the old folder yourself.

If the Ollama Desktop version has a separate **Model location** setting, set it to the same path. It must match `OLLAMA_MODELS`. Fully close and restart Ollama after changing the location.

The script supports the default `%USERPROFILE%\.ollama\models` path and the path indicated by the current `OLLAMA_MODELS` variable. Kira settings and caches, Qwen, Piper, PyTorch, and Hugging Face data are stored separately in the same A-drive data directory through `KIRA_DATA_DIR`.
