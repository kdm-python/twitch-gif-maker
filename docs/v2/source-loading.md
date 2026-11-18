# Source-loading backend

`gifmaker.sources.load_source(path)` prepares a supported source and returns a `LoadedSource`. Animated WebP can be opened from the file picker, the source-panel drop target and `--file`. Preparation runs in a worker thread. The editor displays the resulting frames and uses their timestamps for playback and marker selection. WebP preview and export use the prepared frames and the current render settings.

The caller owns the returned object and must close it when no longer in use, preferably with `with load_source(path) as source:`. Failed preparation cleans up its temporary directory. Closing is idempotent and never deletes the original input. Prepared frame paths are valid only until close; a future GUI integration must keep the source alive until playback and all preview/export jobs using it have stopped.

- MP4 is probed using the existing probe; `original_path` and `media_path` identify the original and `frames` is empty.
- Animated WebP is decoded by libwebpdemux into a temporary directory of full-canvas PNG frames. `original_path` remains the original, `media_path` is `None`, and `frames` contains ordered paths, cumulative start times and frame delays in integer milliseconds. The lossless frame sequence plus timing is the prepared input for a future renderer or player, not an FFmpeg input URL or a media file that the existing renderer can already consume. The decoded canvas preserves alpha in the tested fixtures.
- `info` contains dimensions, duration, codec and average FPS for display; the average is not a timing source. `frame_at(ms)` uses frame timestamps, including the documented endpoint behaviour. The timeline and render code must use actual timestamps rather than average FPS.

The libwebp animation decoder supplies frame timestamps. Missing libraries, unreadable, static and incompletely decoded animations are rejected. Decoders can normalise short frame delays; their policy is not yet specified. Preparation writes decoded frames to disk, has no storage limit, and cannot interrupt a decode already in progress. A newer load supersedes the result of an earlier one, and closing the window waits for preparation to finish and cleans up its temporary files.

## Prepared animation playback

`AnimationSourcePlayer` in `gifmaker.sources.animation_player` plays a prepared animation source using its actual frame timestamps. It exposes Qt signals for the displayed image, position, duration, play state and errors, plus play, pause, seek, playback rate and clear operations. It stops at the end of one cycle; playing again from the endpoint restarts at zero. Seeks are clamped to the source duration, with the last frame displayed at the endpoint. Playback uses a monotonic clock so a delayed timer can skip to the correct frame instead of accumulating drift.

The player borrows the `LoadedSource`: it does not close it. Stop or clear the player and finish any render jobs before closing the source. The player reports missing frames or a source closed during playback as errors. The session controller connects it to the source panel and owns the prepared source.

## Animation timeline adapter

`AnimationTimeline` derives frame boundaries and the exclusive cycle endpoint from a live prepared source. It maps timestamps to actual frames, steps by frame index and converts boundary-index selections to half-open time intervals. `AnimationTimelineController` connects that model and the source player to `MarkerSeekSlider`: its slider values are milliseconds, while its markers use boundary indices and are positioned by elapsed time. A one-frame selection and selection through the end of the final frame are supported.

The main window uses the adapter for animation sources and restores the MP4 slider when changing back to video. Render jobs sample these timestamps and retain their own links to prepared frames, allowing an export to finish after another source is loaded.
