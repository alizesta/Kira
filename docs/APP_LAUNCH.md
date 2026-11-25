# Application Discovery and Launch (`open_app` / `find_app`)

Code: `kira/tools/appcatalog.py` (discovery) and `kira/tools/apps.py` (launch). There is no shell and no command assembled from model text; the model supplies only an application name.

## Discovery sources (priority order)

1. **Start Menu and Desktop:** `.lnk` shortcuts and Steam shortcuts (`.url` files containing `steam://rungameid/<number>`; other `.url` files are ignored).
2. **Steam libraries:** `libraryfolders.vdf` and `appmanifest_*.acf` on all drives (for example, Wallpaper Engine, App ID 431960). Launch uses `steam://rungameid/<appid>`.
3. **Windows installed apps** (Uninstall registry keys) and **App Paths:** installation folder, `DisplayIcon`, and executable path.
4. **Store apps:** queried only if none of the preceding sources found a match, using a fixed `Get-StartApps` query (no user or model text is passed to it). Launch uses `shell:AppsFolder\<AUMID>`.

If the same name is found in multiple sources, it is treated as one application. If the name is ambiguous (several close matches), nothing is launched and Kira asks the user to choose.

Common Persian names and pronunciations are supported (for example, Opera GX, Chrome, Edge, Discord, Telegram, Windscribe, Steam, Spotify, Hotspot Shield, and Wallpaper Engine). Command wording such as “open Opera” is separated from the application name before searching; the user does not need to provide the English name on first use.

## Detect current state before launch

- **Processes** are identified using the full executable path. A process belongs to an application when its executable is the application executable or is inside its installation directory (for example, `wallpaper64.exe` or `ui64.exe`). The process name is only a secondary hint.
- **Windows owned by those processes:** both visible windows (including minimized windows) and hidden primary windows belonging to tray applications are checked.
- The executable path is read from the shortcut (target, relative path, icon, environment variables), installed-app metadata, or the installation folder itself.

## Launch behavior

1. If a visible window already exists, restore and foreground that same instance. Do not create another instance.
2. If only a hidden tray window exists, show that existing window.
3. If a background process exists without a window, issue one normal launch (as a Start Menu or Steam click would) so the application can expose its existing instance; then check again. Do not launch when the executable path is only guessed.
4. If the application is not running, try methods in this order: shortcut → Steam → known executable → Store. Try the next method only when the previous method returns an **error**, not merely because a window has not appeared; this prevents duplicate instances.
5. After launch, check for a new window or process for up to 8 seconds (Steam: up to 20 seconds). Warn about a possible second instance if the number of processes for the main executable increases unexpectedly.

## Reported errors

The actual Windows error code is reported for conditions such as a missing file or shortcut target, access denied, elevation required (740), UAC cancellation (1223), Steam not installed or registered (1155), security blocking (1260), or a launch request accepted without a subsequent window or process. In the last case, Kira reports that the result is unconfirmed; it does not claim that the application opened.

## Limitations

- Windows does not allow a non-elevated Kira process to control the window of an application running as Administrator. This is reported.
- A tray application with **no** hidden window that also ignores a second launch cannot be shown externally.
- Only the application itself is launched. Signing in, connecting a VPN, or changing wallpaper is not performed. Wallpaper Engine requires Steam to be running.
- Portable applications without installation metadata or a shortcut may not be discovered. Store discovery requires PowerShell; Store apps are unavailable when PowerShell is blocked.
- The original change note states that this feature had not been run on real Windows; development took place on Linux and only syntax checks were performed.

## Fallback for a broken shortcut

A Start Menu shortcut is eligible for launch only when the shortcut file exists and, if it exposes an executable target, at least one target executable file actually exists. Missing shortcuts or shortcuts with deleted targets are excluded so Kira can use a registered executable path or controlled discovery inside the installation directory instead. Safety rules and the blocked executable list remain unchanged.
