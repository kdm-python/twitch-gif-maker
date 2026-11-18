# Version 3 architecture overview

Version 3 is a desktop clip editor built with Python and PySide6. It accepts MP4 video and animated WebP sources. MP4 sources can produce GIF or WebP. Animated WebP sources are decoded into editable frames and produce WebP output.

The project is organised around a clear split between source handling, user-interface state, immutable render recipes, and rendering. That split exists so a new format can add its own source loader, playback implementation or renderer without requiring a rewrite of the existing MP4, GIF and WebP behaviour.

## Main parts of the application

`gifmaker.main` is the command-line entry point. It validates `--file` input, accepts MP4 and WebP paths, creates the Qt application and opens the requested source. Twitch clips are downloaded as temporary MP4 files before going through the normal MP4 path.

`gui.main_window.MainWindow` creates and owns the widgets and long-lived UI state. It deliberately exposes established widget attributes to controllers while the presentation is composed from smaller panels. It does not contain the source-loading or rendering rules itself.

`controllers.video_session_controller.VideoSessionController` owns source loading, source playback, timeline selection, source changes, and source cleanup. `controllers.render_controller.RenderController` owns the render recipe, preview lifecycle, preview caching, asynchronous render processes, save operations, cancellation, and errors.

`models.render_settings` represents render state outside Qt widgets. `RenderSettings` combines three smaller settings groups.

- `SharedSettings` contains the selected start and end times and output speed.
- `VisualSettings` contains output FPS, dimensions, crop and sharpness.
- `WebPSettings` and `GIFSettings` contain format-specific options.

`RenderSpec` is the complete immutable recipe for one render. It combines the original source path, selected output format and `RenderSettings`. It is used for both the generated preview and final export. Two identical recipes describe the same output, allowing the application to reuse a preview safely.

`services.output_formats` is a small output-format registry. Each format declares its suffix, visual control groups and command builder. The current registry contains `WebP` and `GIF`. This is the first place to add an output format that can use the regular MP4/FFmpeg rendering path.

## Source architecture

`sources.loader.load_source` selects a loader from the input suffix. It returns a `LoadedSource`, which owns any temporary representation of the source and has an explicit `close()` lifecycle.

MP4 uses `Mp4SourceLoader`. It calls `video.probe.probe_video`, returns source metadata and retains the direct MP4 path as `media_path`. Qt's `QMediaPlayer` plays that file and FFmpeg receives that file for export.

Animated WebP uses `WebpSourceLoader` and `sources.webp_decoder`. The decoder calls the libwebp animation decoder through `ctypes`, reading a full composited RGBA canvas for every WebP frame. Each canvas is written as a lossless PNG in a temporary directory. The result contains these records.

```text
LoadedSource
  original_path      The original WebP, kept for display and safe naming
  info               Width, height, duration, codec and average FPS
  frames[]
    path             Full-canvas temporary PNG
    start_ms          Frame start in the source animation cycle
    duration_ms       Frame display duration
```

The important detail is that `start_ms` and `duration_ms` are authoritative. Animated WebP files can have unequal frame delays. The average FPS only exists for display and compatibility with the wider UI. It never decides which WebP frame belongs at a timestamp.

libwebp is used because it correctly applies frame composition, blending, disposal and alpha rules. In testing, Qt's image reader produced an incorrect result for a valid partial-frame disposal fixture. FFmpeg installed on the development environment could not reliably decode the same animated WebP inputs directly. Decoding once into composited PNG frames avoids both issues for editing.

Source preparation runs on a worker thread. The existing source remains available until the new source has prepared successfully. A failed or unsupported input leaves the current source intact and reports the error. A later request supersedes an earlier asynchronous load. Closing a source deletes its temporary PNG directory.

## Source preview and timeline

The source panel contains a stack with the existing `QVideoWidget` for MP4 and an `AnimationSurface` for decoded WebP frames. The surrounding controls and layout are shared.

MP4 uses `QMediaPlayer`, its normal position reporting and the original frame-based slider behaviour.

WebP uses `sources.animation_player.AnimationSourcePlayer`. It displays prepared PNGs, seeks by integer milliseconds and advances with a monotonic clock. It stops at the end of the source cycle. Its `frameChanged`, `positionChanged` and playback-state signals update the same controls used by MP4.

`sources.animation_timeline.AnimationTimeline` converts a WebP source into frame boundaries. `gui.animation_timeline_controller.AnimationTimelineController` connects those boundaries to `MarkerSeekSlider`.

For WebP, slider values are milliseconds while marker values are boundary indices. A selection is always half-open.

```text
[start, end)

start is included
end is excluded
the final source boundary is a valid end marker
```

This makes a one-frame selection possible and makes the last frame's display duration selectable. Frame stepping moves through the actual source frames rather than by an approximation derived from FPS.

When a WebP source is active, the output selector chooses WebP and disables GIF. When the user returns to an MP4 source, the previous format choice is restored.

## Rendering paths

There are two rendering paths because the underlying source representations differ.

### MP4 source rendering

For MP4, `RenderController` asks `RenderService` for a command. `RenderService` resolves the chosen item from `output_formats`.

- GIF uses FFmpeg filter-complex palette generation and palette use.
- WebP uses FFmpeg's `libwebp_anim` encoder.

`services.gif_export` holds shared FFmpeg request validation, quality presets, sharpness presets and filter construction. Its shared visual filter sequence applies timing adjustment, output FPS, scale, optional sharpness and optional crop. The MP4 path performs trim and output speed within FFmpeg.

`GIFMAKER_FFMPEG` can select a particular FFmpeg executable. This is useful where the system FFmpeg has no `libwebp_anim` encoder.

### Animated WebP source rendering

Animated WebP rendering lives in `services.webp_render`. It reuses the same `RenderSpec`, quality presets and visual FFmpeg filters as MP4 rendering, while taking prepared PNG frames as input.

When a preview or export begins, `prepare_job()` creates a render workspace and hard-links each prepared source PNG into it. The hard links retain the source image data even if the user loads another source while the render is still running. The workspace contains a JSON manifest with the immutable frame timing and requested output settings.

The render worker runs as a separate Python process. It samples the requested source selection at a constant output cadence.

```text
source time = selection start + output frame time × output speed
```

For each output frame, it finds the prepared source frame whose actual timestamp contains that source time. It creates a numbered symlink sequence that points at the hard-linked PNG snapshots. FFmpeg reads that sequence at the selected output FPS and applies crop, scale, sharpness and WebP quality settings. Output speed is represented by sampling, so the FFmpeg filter chain deliberately does not apply speed a second time.

The output duration is quantised to the requested output frame cadence. It rounds up to include the selected interval. That means an output may differ from the mathematical duration by up to one output-frame interval. This is expected constant-FPS animation behaviour.

Some FFmpeg versions encode a sequence of identical frames as a still WebP. `webp_render` detects that result and, when necessary, invokes `webpmux` to make a two-frame animation with the intended total duration. `GIFMAKER_WEBPMUX` can select its executable. If it is unavailable or fails, the job fails visibly and does not present a still image as a successful animated output.

The worker writes its result inside the workspace. The main process copies that result to the preview file or export destination only after the worker succeeds. A preview and final export therefore use the same sampler and filters.

## Preview, export and file safety

Preview rendering happens in a temporary output file. `PreviewController` and `AnimationPreviewPlayer` load the completed file and play the generated animation in the output preview. It uses cached frames and their returned frame delays where that provides more reliable playback than a `QMovie` path.

The render controller compares the current `RenderSpec` with the preview's stored spec. If they match, Export copies the preview instead of rendering again. If controls or source differ, it creates a new render.

WebP exports default to `<source name>-edited.webp`. The controller rejects any destination that resolves to the source path or the same underlying file through a hard link. The final copy goes via a temporary sibling file and `os.replace`, preventing an incomplete write from becoming the visible export.

Rendering uses Qt `QProcess`, leaving the interface responsive. FFmpeg and worker errors are captured, logged and shown in the status control. Preview jobs become stale when their recipe changes and are discarded when they finish. Cancelling a WebP job terminates the worker, which terminates its active encoder, then cleans up the workspace. The original source's temporary frames are cleaned only when its session is released.

## UI composition

`gui.views.video_preview_panel` owns the source preview surface and shared playback controls. `gui.views.export_controls_panel` owns output controls, with format definitions deciding which control groups are visible. `gui.views.marker_seek_slider` draws and interacts with range markers. `gui.views.crop_overlay_label` owns crop interaction on the generated output preview. `gui.preview_controller` owns output preview playback.

The main window is intentionally a composition root. It creates panels, exposes stable references used by existing controllers and routes controller methods through its compatibility adapter. This retained the established GIF/WebP visual layout while moving behaviour into dedicated modules.

## Future work and extension points

A new source format usually needs three decisions.

1. Add a loader that returns `LoadedSource` or extend the source model where a different representation is required.
2. Supply playback and timeline behaviour that follows the format's timing semantics. A constant-rate video can use the MP4 approach. Frame-timed animation can reuse `AnimationSourcePlayer` and `AnimationTimelineController`.
3. Add a renderer that consumes `RenderSpec` and produces the chosen output. A direct FFmpeg-readable input may only need a new `OutputFormat`. A decoded or synthetic source can follow the WebP worker pattern.

MP3 would use the direct-file path but needs an audio player, audio-only timeline and an output-format definition with audio settings rather than visual controls. It does not need the prepared-frame renderer.

Subtitles fit naturally as a future visual render layer. They should become immutable subtitle data in `RenderSpec`, expressed in source-time coordinates. The WebP sampler already maps each output frame back to a source timestamp, providing the correct input for deciding which caption is visible. Subtitle drawing should occur after crop and scale decisions have been made, in a shared visual composition stage used by both preview and export. That preserves preview/export identity and permits MP4 and WebP sources to share subtitle logic.

The main remaining operational concern is resource policy. Decoding WebP creates one full RGBA PNG per source frame, and rendering creates a short-lived workspace. This is acceptable for the intended short clips, but a future release should calculate estimated decoded storage, set a configurable ceiling, and explain rejection before writing an unusually large temporary sequence.

## Research terms and dependencies

Useful areas for further research include animated WebP frame composition and disposal, libwebp `WebPAnimDecoder`, FFmpeg image-sequence demuxing, FFmpeg `libwebp_anim`, WebP muxing with `webpmux`, constant-frame-rate resampling, Qt `QMediaPlayer`, Qt `QProcess`, and atomic file replacement.

The relevant external tools are FFmpeg and FFprobe, libwebpdemux, and `webpmux` for identical-frame duration preservation. Tests cover timing fixtures, alpha, partial-frame disposal, cancellation, stale previews, source changes during a render, source protection, real `luddy.webp` rendering when present, and MP4 regressions.
