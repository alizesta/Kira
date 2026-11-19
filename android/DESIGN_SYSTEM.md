# Kira Android design system

The app uses familiar Material 3 interaction patterns: bottom navigation for top-level
destinations, standard cards and dialogs for actions, and platform text-field and button
behavior for chat and forms.

## Visual tokens

The current Android experience uses a dark Kira palette. Colors, typography and corner
radii are centralized in `ui/theme/KiraTheme.kt`. Feature screens should consume
`MaterialTheme.colorScheme` or `KiraPalette` rather than introducing new hex values.

## Interaction rules

- Keep top-level destinations stable and visible.
- Use standard Android back behavior for nested screens.
- Preserve platform keyboard and IME actions.
- Keep touch targets large enough for one-handed use.
- Make disabled, loading and error states explicit.
- Do not use color as the only indicator of state.
