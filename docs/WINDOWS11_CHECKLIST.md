# Items to Test on a Real Windows 11 System

Install: `install.bat` → `start_kira.bat`. Run tests with `run_tests.bat`.

- [ ] The app starts and the model indicator appears at the bottom beside the message field (including RTL layout).
- [ ] Previous 1.5.0/1.4.x settings load: API keys stay in place and Route order remains unchanged (keys decrypt with DPAPI).
- [ ] Mouse drag-and-drop reorders the Route list and the order persists after restart.
- [ ] Real Groq key: **Test Connection** succeeds; streaming chat displays text incrementally; Stop works.
- [ ] Invalid key returns 401 and triggers failover; internet/VPN disconnection triggers failover to Ollama.
- [ ] Real repeated 429 responses trigger cooldown and move to the next Route.
- [ ] Real Ollama: `qwen3.5:4b` streams; **Discover Ollama Models** works; Benchmark reports GPU utilization for RX 6600 XT.
- [ ] Stop Ollama mid-response (End Task): partial text is preserved without duplication and the error is readable.
- [ ] During gaming, the model unloads after Keep-alive and game FPS does not remain degraded.
- [ ] Persian right-to-left layout in the streaming chat bubble is correct.
- [ ] Face, lip sync, desktop character, audio, and microphone work as before. Their code was not changed, but they still require a new Windows validation run.
- [ ] Run 20+ consecutive conversations and inspect Task Manager for memory growth.
- [ ] Open `logs/provider_telemetry.jsonl`; it must contain neither keys nor conversation text.
- [ ] Test a custom Provider (for example, LM Studio at `localhost:1234`).
