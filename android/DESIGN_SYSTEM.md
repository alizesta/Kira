# Kira Android Design System

The Android app uses a dedicated `:core:designsystem` module. Feature modules consume
its theme, semantic tokens and reusable Compose components instead of defining local
colors, typography, shapes or one-off controls.

## Foundations
- **Color:** use `MaterialTheme.colorScheme` for semantic roles. Use `KiraPalette` only for brand decoration.
- **Typography:** use the Material 3 type scale from `MaterialTheme.typography`; avoid hard-coded font sizes.
- **Shape:** use `MaterialTheme.shapes` for consistent geometry.
- **Components:** prefer `KiraPrimaryButton`, `KiraSecondaryButton`, `KiraTextField`,
  `KiraCard`, `KiraSectionHeader`, `KiraEmptyState`, `KiraLoadingIndicator`,
  `KiraPeekRow`, `KiraConnectedSteps` and `KiraProgressiveDisclosure`.

## Jakob's Law and Android conventions
Kira should behave like a familiar Android app. Users spend most of their time in
other apps, so navigation and controls should follow established platform patterns.
- Keep 3–5 primary destinations in persistent Material 3 bottom navigation.
- Use conventional app bars, standard back navigation and predictable screen hierarchy.
- Use dialogs or bottom sheets for focused decisions; avoid custom modal behavior.
- Preserve native text selection, clipboard, keyboard/IME actions and system back.
- Use familiar switches, checkboxes, radio controls and text fields for settings.
- Request runtime permissions when a feature needs them and explain why.
- Keep interactive targets at least 48dp; never encode state by color alone.
- Respect font scaling, RTL, accessibility semantics and TalkBack.
- Show clear loading, empty, disabled, success and error states.
- Make destructive actions explicit and confirm them.

## Six interaction and attention principles
- **Closure / continuation cues:** horizontal card collections should use `KiraPeekRow` (or an equivalent partial next-item preview); never imply that a carousel ends when more items exist.
- **Figure–ground:** use native Material 3 `Dialog` or `ModalBottomSheet` for focused tasks so the platform scrim de-emphasizes the background. Avoid custom always-on overlays.
- **Banner blindness:** important status, warnings and primary actions belong in the content hierarchy or a contextual `Snackbar`; do not style them like promotional banners.
- **Parkinson's law:** keep the default path short, prefill known values, and do not ask for information already available. Move genuinely advanced settings behind `KiraProgressiveDisclosure`.
- **Connectedness:** multi-step tasks should use `KiraConnectedSteps` and preserve a clear next/back path; do not split one task into unrelated screens.
- **Choice overload:** show the recommended/common choices first and progressively disclose infrequent options. Do not remove capabilities or silently change saved preferences.

These patterns are reusable primitives, not a mandate to add carousels, steps or collapsible sections where they do not fit the task.

## Module boundaries
`core/designsystem` owns visual foundations and reusable presentation primitives.
It must not depend on app features, repositories, Android services or provider clients.
Feature modules may depend on the design system; the reverse dependency is forbidden.

## Acceptance criteria
- App and design-system modules resolve through Gradle.
- Existing screens keep the `ai.kira.mobile.ui.theme.KiraTheme` API.
- Tokens and shared components are available to feature UI.
- New UI can follow Material 3 conventions without copying style definitions.
