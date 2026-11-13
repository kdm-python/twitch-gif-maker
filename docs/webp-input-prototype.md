# Animated WebP input prototype

This is an investigation, not an implemented import feature. The application still accepts MP4 input only. The intended eventual scope is animated WebP input and WebP output; the existing GIF output remains available for MP4 sources.

## Reproducing the experiment

Use an FFmpeg build with `libwebp_anim` (see README), then run:

```sh
QT_QPA_PLATFORM=offscreen GIFMAKER_FFMPEG=/path/to/ffmpeg \
  poetry run python scripts/prototype_webp_input.py /path/to/animation.webp
```

The prototype reads composited frames sequentially with Qt, writes temporary PNG frames and an FFmpeg concat manifest with their individual delays, and asks FFmpeg to encode a temporary animated WebP. It then reads the output with Qt and reports frame counts and delays. All intermediate files are removed on exit; the input is never modified. This is deliberately a feasibility experiment, not production code or a proposed final storage design.

## Observations from luddy.webp

On the tested machine, Qt read the supplied 400×432 animated WebP as 152 frames, with 102 delays of 33 ms and 50 of 34 ms, totalling 5.066 seconds. Qt returned images with an alpha channel; this does not establish that any pixels are transparent. A 500 ms offscreen QMovie playback showed frames advancing. Immediate `jumpToFrame` attempts for later frames returned false, so random-access seeking needs a different strategy or further investigation.

The FFprobe on PATH reported zero width and height and no duration, while both the standard FFmpeg and Homebrew ffmpeg-full 8.1.2 failed to decode this animated WebP. The latter did successfully encode a new WebP from the Qt-decoded PNGs. The resulting animation had the same 152 frames and the same distribution and total of frame delays. Temporary PNGs occupied about 29.6 MB for a 2.4 MB input; peak memory, preparation time on larger inputs and total disk usage need further study.

This experiment verifies frame counts and timing only. It does not establish pixel equivalence, transparency preservation, exact trim boundaries, crop correctness, speed changes or reliable playback in the application's source panel. The output is re-encoded, and lossy encoding can change pixels. Qt image support and FFmpeg build capabilities can vary between installations.

## Next investigation and implementation

- Compare composited frames and alpha with transparent and partial-frame animations; determine how to handle transparency through both the existing processing filters and the chosen intermediate.
- Prototype timestamp-based scrubbing and frame stepping, including variable delays and the last frame. Avoid assuming QMovie can directly seek to any frame. A frame index or cache can use substantial memory; consider bounded or disk-backed approaches.
- Test selected start/end boundaries, crop, resizing and speed through the actual render path. Preserve the full duration of the final frame and ensure source playback and output use the same interpretation of frame timing.
- Design a source-loader interface and an asynchronous preparation lifecycle, including cancellation, failed loads, temporary-file cleanup and returning to an existing source. Avoid binding the UI to the prototype's temporary PNG strategy.
- When a WebP source is active, limit output to WebP while retaining GIF output for MP4. Restore the appropriate output choice on switching source, and protect the original from accidental overwrite.
- Test corrupt, static, large and unusual-timing WebPs and verify platform/decoder dependencies. Preserve the existing MP4 workflow and look.
