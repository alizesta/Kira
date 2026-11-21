# Kira Desktop UI/UX Principles

The desktop UI keeps the established navy, violet and cyan palette. These rules govern hierarchy and interaction; they are not a reason to add decorative UI.

## Six principles
1. **Closure / continuation:** horizontally browsable collections should expose a meaningful edge of the next card. Do not use a clipped preview when there is no more content.
2. **Figure–ground:** use native modal dialogs for focused decisions and let the active modal/window own focus. Do not stack competing overlays or dim unrelated content manually when Qt's modal behavior already provides the focus boundary.
3. **Banner blindness:** critical status and actions belong beside the task they affect, with clear labels and severity. Do not style them as promotional banners.
4. **Parkinson's law:** prefill known values, remove duplicate questions, and keep the primary path short. Put infrequent controls inside ProgressiveDisclosure.
5. **Connectedness:** multi-step tasks should keep their sequence and next/back actions visible. Use ConnectedSteps where a real multi-step flow exists.
6. **Choice overload:** show the common/recommended choice first; expose advanced or infrequent alternatives progressively. Never remove existing capabilities or silently rewrite a saved selection.

## Reusable components
- kira.ui.components.ux_patterns.ProgressiveDisclosure is for secondary controls.
- kira.ui.components.ux_patterns.ConnectedSteps is for genuine multi-step flows.
- Horizontal card collections should size cards to leave a partial next-card preview.

Use these patterns only where they fit the task. Do not add carousels, wizards or collapsible sections for decoration.
