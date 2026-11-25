# Audio Manager (Windows Audio Control)

The audio module is part of the Windows Control Layer: `AudioModule` in `kira/tools/winmodules.py`, implemented in `kira/tools/audio.py`. It does not depend on a Provider or model. Hybrid Brain and Tool Registry are unchanged, and the layer's existing safety rules (risk level, explicit request, and Journal recording) remain in effect.

## Tools

| Tool | Level | Function |
|---|---|---|
| `audio_get_volume` | READ | Actual volume (%), mute state, default output and input devices |
| `audio_set_volume(percent)` | ACTION | Set volume to an exact value from 0 to 100 |
| `audio_change_volume(direction, amount)` | ACTION | Increase/decrease by `amount` percentage points (default 10) |
| `audio_mute` / `audio_unmute` | ACTION | Mute or unmute the speaker/output |
| `audio_list_apps` | READ | Applications with audio sessions (Volume Mixer): volume, mute, and playback state; likely games are marked |
| `audio_set_app_volume(app, percent)` | ACTION | Set an application's volume |
| `audio_change_app_volume(app, direction, amount)` | ACTION | Increase/decrease an application's volume |
| `audio_set_app_mute(app, muted)` | ACTION | Mute or unmute an application |
| `audio_list_devices(kind)` | READ | Connected and disconnected input/output devices and the current default for each kind |
| `audio_set_default_device(kind, device)` | ACTION | Change the default Windows input or output device |

ACTION tools run only when the **current user message** explicitly requests a change (for example, “volume” plus “set/increase/decrease”, “mute it”, or “set headphones as output”). If the model decides to make a change that the user did not request, the tool is rejected, nothing changes, and the rejection is recorded in the Journal. Questions such as “What is the volume?” activate read-only tools only.

## Implementation and result verification

- **API:** Windows Core Audio (`IMMDeviceEnumerator`, `IAudioEndpointVolume`, `IAudioSessionManager2`, `ISimpleAudioVolume`), the same APIs used by the Windows volume slider and Volume Mixer. It runs through Windows PowerShell 5.1 using **one fixed script** (a C# class loaded with `Add-Type`). No new Python dependency was added; `requirements.txt` was not changed. PowerShell 5.1 and .NET Framework are part of Windows 10/11.
- **Default-device changes:** Windows has no public API for this operation; the implementation uses `IPolicyConfig`, also used by tools such as SoundSwitch, EarTrumpet, and AudioDeviceCmdlets. Console, Multimedia, and Communications roles are all set.
- **Read-back verification:** after every change, the actual state is read again using fresh COM objects, with a wait of about 1.5–3 seconds. A result is reported as successful only when the real value matches the request (driver rounding of ±1% is accepted for volume). Otherwise, the actual state and an error are returned.
- **Security:** user/model text is never inserted into the script. Data is passed through the `KIRA_AUDIO_REQ` JSON environment variable. Numbers are range-checked, `op` and `mode` are closed allowlists, device IDs must come from Windows itself (not model-generated text), and session IDs must come from the live device list. The shared runner is `kira/tools/winrunner.py`.

## Examples

- “What is the current Windows volume?” → `audio_get_volume`
- “Set volume to 50 percent” → `audio_set_volume(percent=50)`
- “Lower volume by 20 percent” → `audio_change_volume(direction=down, amount=20)` (20 percentage points; for example, 70% → 50%)
- “Mute the system” / “Unmute” → `audio_mute` / `audio_unmute`
- “Lower Discord's volume” → `audio_change_app_volume(app=Discord, direction=down)`
- “Lower the game's volume” → allowed only when exactly one likely game has an audio session; otherwise Kira asks which game.
- “Set the output device to headphones” → `audio_set_default_device(kind=output, device=headphones)`
- “Show audio input devices” → `audio_list_devices(kind=input)`

## Application and device matching (no guessing)

- Application names are matched against process names and audio-session display names. Common Persian/English names (browser, Chrome, Discord, Spotify, music, etc.) are mapped. If more than one application matches, Kira makes no change and asks the user.
- A “game” is an application whose executable path is inside common game directories (`steamapps\common`, Epic Games, Riot Games, GOG, Xbox, EA, Ubisoft, Battle.net, or `\Games\`). The path is used only for this marker and is not sent to the model.
- Devices are found by full name, partial name, or type (headphones, headset, speakers, monitor/HDMI, microphone, based on Windows form factor). Disconnected or inactive devices cannot be selected; Kira reports when a device is registered but disconnected.

## Known errors and messages

The implementation reports the actual cause when an output/input device is inactive, a device is disconnected during an operation, access is denied, Windows Audio is stopped, a device has no software volume control (some HDMI/S/PDIF devices), an application has no audio session, a session closes during the operation, or `Add-Type` is blocked by AppLocker or Constrained Language Mode. It does not report an unverified operation as successful.

## Limitations

- **Not tested in the original development note:** no tests (old or new) were run and the C# script was not compiled in that environment; only static review and Python syntax checks were performed. The first run on real Windows is the actual runtime test. If script compilation fails, the tool returns the `Add-Type` error details without changing anything.
- Each PowerShell invocation and C# compilation takes about 1–3 seconds.
- Volume/mute control applies only to the **default output**. Microphone volume or mute is not implemented; input devices can only be listed or selected as the default.
- Per-app volume applies to sessions for active output devices. An application that has not played audio may not yet appear in Windows Volume Mixer. All sessions of a multi-session application (such as a browser) change together. A session created later is not affected.
- Per-application output routing (Windows “App volume and device preferences”) is not supported.
- Game detection is heuristic and based on installation path. A game installed elsewhere may not be marked; name it explicitly.
- `IPolicyConfig` is not a public Windows API and may change in a future Windows version.
- The Journal is in memory and is cleared when the application closes, like the rest of this layer.
