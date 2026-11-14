# Source-loading backend

`gifmaker.sources.load_source(path)` prepares a supported source and returns a `LoadedSource`. This interface is backend-only: it is not connected to the current file picker, player, render command or CLI. Those continue to accept MP4 as before.

The caller owns the returned object and must close it when no longer in use, preferably with `with load_source(path) as source:`. Failed preparation cleans up its temporary directory. Closing is idempotent and never deletes the original input. Prepared frame paths are valid only until close; a future GUI integration must keep the source alive until playback and all preview/export jobs using it have stopped.

- MP4 is probed using the existing probe; `original_path` and `media_path` identify the original and `frames` is empty.
- Animated WebP is decoded by Qt into a temporary directory of full-canvas PNG frames. `original_path` remains the original, `media_path` is `None`, and `frames` contains ordered paths, cumulative start times and frame delays in integer milliseconds. The lossless frame sequence plus timing is the prepared input for a future renderer or player, not an FFmpeg input URL or a media file that the existing renderer can already consume. Qt's decoded canvas preserves alpha in the tested fixtures.
- `info` contains dimensions, duration, codec and average FPS for display; the average is not a timing source. `frame_at(ms)` uses frame timestamps, including the documented endpoint behaviour. The timeline and render code must use actual timestamps rather than average FPS.

Qt's effective frame delays are used, and unknown frame counts, unreadable, static and incompletely decoded animations are rejected. Decoders can normalise short frame delays; their policy is not yet specified. Preparation is currently synchronous, writes all decoded frames to disk, has no cancellation or storage limit, and is intended for backend evaluation. A future application integration needs asynchronous preparation, explicit cancellation and resource management. An animation renderer still needs a timestamp-aware bridge and must be tested for trim boundaries, speed, alpha and final-frame duration before claiming WebP-to-WebP editing works.

## Prepared animation playback

`AnimationSourcePlayer` in `gifmaker.sources.animation_player` plays a prepared animation source using its actual frame timestamps. It exposes Qt signals for the displayed image, position, duration, play state and errors, plus play, pause, seek, playback rate and clear operations. It stops at the end of one cycle; playing again from the endpoint restarts at zero. Seeks are clamped to the source duration, with the last frame displayed at the endpoint. Playback uses a monotonic clock so a delayed timer can skip to the correct frame instead of accumulating drift.

The player borrows the `LoadedSource`: it does not close it. Stop or clear the player and finish any render jobs before closing the source. The player reports missing frames or a source closed during playback as errors. It is not yet connected to the source panel or timeline; frame stepping, markers, UI lifecycle and WebP rendering remain later integration work.
