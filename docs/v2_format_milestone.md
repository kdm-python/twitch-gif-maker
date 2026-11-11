# V2 format architecture milestone

## Purpose and scope

This document records the current architecture and direction after the initial format-extensibility work. It complements `refactor-baseline.md`, which records the GIF/WebP behaviour to preserve. The application still accepts MP4 input and produces WebP or GIF output. No MP3 or MP4 output has been implemented as part of this work.

The aim is to make additional output formats and processing features easier to add while preserving the current interface and editing workflow. A format should be able to assemble common controls and processing operations and supply its own where needed. This is an internal extension mechanism, not a promise that every format can be added through configuration alone or a third-party plugin system.

## Current flow

1. The source video session opens and probes the MP4, manages source playback and selection, and supplies timeline and crop state.
2. The export controls panel displays the existing controls. It captures the editable values in an immutable `OutputControlValues` snapshot.
3. The render controller combines this snapshot with the selection, crop and chosen format. `resolve_visual_settings` validates the selection and produces immutable `RenderSettings`; `RenderSpec` adds the source path and output format.
4. `RenderService` looks up the format in the explicit `output_formats` registry. The selected renderer builds a validated FFmpeg command using the existing GIF or WebP builder. The render controller launches asynchronous preview and export jobs; synchronous export uses the same command-building route.
5. The render controller coordinates preview revisions, debouncing, locking, cancellation, temporary artifacts and export reuse. It asks `PreviewController` to load and control playback. The default `AnimationPreviewPlayer` displays GIF/WebP using the existing movie and cached-frame behaviour; the crop overlay remains part of the existing preview UI.

The immutable recipe is important: the app can reuse a preview for export only when the source, format and output settings match and the artifact still exists. A stale or locked preview must never silently substitute for current settings.

## Work completed in this conversation

### Baseline

Stage 1 documented the existing workflow in `refactor-baseline.md` and added a format-switch regression test. Existing tests exercise real rendering, timing, crop, format quality, preview locking and reuse. The baseline calls for manual visual comparison as well: passing tests alone does not prove identical appearance.

### Rendering boundary

`services/output_formats.py` defines an explicit registry for GIF and WebP. Each entry supplies a name, extension, command builder and named control groups. `RenderService` uses this boundary for command selection, and preview/export suffixes come from the registry. The existing format-specific FFmpeg command builders remain in `services/gif_export.py`; their encoding choices were preserved. Tests compare registered commands with those existing builders and check unknown formats.

### Settings and controls

The controls panel can return a value snapshot without exposing individual widgets to settings resolution. `resolve_visual_settings` handles selection validation and selects the relevant quality value. GIF continues to use its fixed quality setting, so a hidden WebP quality selection does not affect its render recipe.

The existing widgets are grouped by named capabilities: FPS, size, quality, sharpness and crop. Format definitions select the groups to show. The widgets remain in the same panel and layout; switching formats retains shared controls and the WebP quality choice.

### Preview boundary

A `PreviewPlayer` protocol defines playback operations, and `PreviewController` delegates them to `AnimationPreviewPlayer` by default. Preview artifact cleanup remains with the controller, while render-job orchestration remains in `RenderController`. Tests exercise the controller with a substitute player and cover artifact cleanup. GIF/WebP still use their existing animation preview and crop behaviour.

## What is incomplete

These changes are scaffolding, not a finished general-purpose format architecture:

- `RenderSettings` and `OutputControlValues` still describe visual output. Audio-only recipes cannot yet be represented cleanly without irrelevant dimensions and FPS. Shared selection/timing and format-specific settings still need a more suitable model.
- Control groups are tuples of widgets built inside one panel, not independently composable components. The registry selects visibility, but control creation, layout and much of the signal wiring remain centralised. The format chooser itself is still populated directly by the panel.
- GIF and WebP definitions share one registry module; their builders and common video filters still live in the GIF-named export module. Adding a significantly different renderer requires further extraction. The UI and backend both use the same control-group metadata, so its boundary may need refinement as capabilities grow.
- Asynchronous process execution and its callbacks remain in the render controller; the synchronous runner and common error type remain in the GIF export module. Job execution and errors are not yet fully format-neutral.
- The preview controller defaults to one animation player; there is no player selection or switching by format. The animation player still uses state and callbacks on the main window, and compatibility adapters expose animation-specific operations. Playback and artifact lifecycle are separated only partially.
- Output summaries, file-size estimates, crop handling and parts of the render controller still assume visual animation. Source probing does not yet provide the audio information required by MP3.

Consequently, registering an MP3 renderer alone would not produce a working audio format. These boundaries should be refined against the concrete requirements of that first addition, without changing GIF/WebP behaviour merely to achieve abstraction.

## Direction for future work

Separate shared source selection and timing from visual and audio settings, with format-specific settings where needed. Resolve an immutable recipe containing all and only the values that affect its output. Preserve correct preview matching and validate each format's requirements.

Continue extracting reusable processing operations and a format-neutral job/error boundary. Keep individual format renderers free to use a custom FFmpeg graph when common operations are insufficient. Provide reusable Qt control components and explicit composition points while preserving the existing panel for GIF and WebP. Avoid building a large generic UI framework before real formats require it.

Finish separating the preview player from animation-specific state, and add a safe way to select and switch players while managing playback, failed loads, crop interaction and artifact cleanup. Keep generation, cancellation, locking and export reuse independent of the player type.

MP3 is a useful first extension: it exercises audio detection, audio-only settings, audio rendering and playback without requiring video encoding or audio/video synchronisation. It will need a speaker presentation in the existing preview area, audio quality and speed controls, sensible handling of sources without audio, and FFmpeg encoder checks. The current visual-only recipe, summary and preview assumptions must be addressed as part of that work. MP4 output can later build on both visual processing and audio work, with a video preview and synchronisation.

## Verification and constraints

For every stage, preserve the baseline: appearance, controls and defaults, timeline, crop, shortcuts, playback, preview locking and automatic refresh, matching and export reuse. Run `poetry run pytest -q`, including real FFmpeg renders with a WebP-capable build, and add focused tests for new boundaries and lifecycle failures. Compare the actual UI at normal and narrow widths and in both themes when modifying presentation. Real encodes should be checked for output properties and timing; exact bytes can vary by FFmpeg build.

The latest recorded run during the preview extraction passed 127 existing tests, and the two new preview-controller tests passed separately with the timing test. These are historical results, not a claim that tests were rerun while writing this document. The preview UI was not visually compared during that stage.
