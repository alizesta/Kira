# Idle and startup performance policy

## Avatar update cadence

The shared PNG avatar animator tracks every live `AvatarView` through weak references.

- If at least one avatar view is visible in a non-minimized top-level window, the animator targets **60 FPS** (16 ms Qt timer interval).
- If all avatar views are hidden, or their windows are minimized, it targets **5 FPS** (200 ms interval).
- Showing or hiding a view updates the timer immediately. The timer also rechecks visibility each tick to catch minimize/restore transitions.
- When several views share the same animator, one visible view keeps the animator at 60 FPS; hidden sibling views do not incorrectly throttle the visible one.

The previous fixed 30 FPS timer produced about 30 animation callbacks per second even when every avatar was hidden. The new hidden policy schedules 5 callbacks per second, an **83.3% reduction in avatar timer callbacks** during that state. This is a reduction in scheduled animation work, not a claim that total process CPU falls by the same percentage.

## Mood indicator rendering

The UI continues to poll mood state on its existing schedule, but it now compares a signature containing character, emotion, intensity, behavior, energy and secondary emotions. If the signature is unchanged, it skips rebuilding icons and pixmaps and avoids reapplying stylesheets and tooltips.

## Worker import boundaries

The main chat, voice and lifecycle controllers no longer import worker implementations through their support-module import lists. Their worker classes are loaded from the owning action/factory only when that capability is used. The shared worker module no longer imports Web Search, attachment parsing or provider probing at module import time; those dependencies are loaded inside the corresponding worker execution path.

## Validation

Run these focused tests with Qt available:

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
python -m unittest tests.test_face_animation_fps tests.test_mood_indicator_cache tests.test_startup_deferred_loading -v
```

For a real Windows idle-CPU comparison, use the same build and profile, keep the avatar views hidden/minimize the application, allow warm-up, and sample the Kira process CPU for at least 60 seconds. Repeat with a visible avatar and compare the same process, power profile and workload. The timer-rate tests validate the scheduling policy; actual Windows CPU percentages must be measured on the target PC and are not inferred from callback counts.

- All visible views sharing one animator now reuse the same tile and face-anchor rig transforms for each animation tick. This avoids repeating the NumPy deformation/Jacobian calculations when the chat-card avatar and floating companion are visible together; pose ticks and character-art changes invalidate the cache.
