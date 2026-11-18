# WebP render bridge experiments

This records backend rendering experiments. The application now uses the same sampling approach for WebP preview and export in `gifmaker.services.webp_render`. The optional user-supplied `tests/fixtures/luddy.webp` is used when present. Disk budgets remain a later integration task.

## Candidate rendering method

Decode the animation to composited PNG frames and timing data. For each output-frame time, select the source frame at `selection_start + output_time × speed`, stopping before the exclusive selection end. The experiment creates a numbered sequence of symlinks to prepared PNGs, then FFmpeg reads it at the selected constant output FPS and applies the existing crop, scale and sharpness filters before WebP encoding. Speed is already reflected in sampling and must not be applied again. Rational arithmetic avoids accumulated sampling error; duration rounds up to the next output-frame interval.

Each render job retains hard links to prepared frames and samples them through a temporary sequence. The application cancels the worker and its child process together and cleans up the job directory. Symlinks and hard links have been exercised on macOS. Resource limits and broader platform coverage remain future work.

## Unchanged selections and short durations

FFmpeg's `libwebp_anim` collapses a fully unchanged selection into a still image, losing animation duration. The experiment detects this and uses `webpmux` to wrap the encoded still in two identical timed frames; it replaces the result only after a successful mux. This passed tests for a 400 ms selection and very short selections including a one-output-frame 60 FPS render, as well as transparent content. If `webpmux` is missing or fails, the experiment reports an error and does not replace the still with a false success. This is a tested candidate, not a production solution: `webpmux` is not currently a declared app dependency, and WebP decoders may interpret frame delays of 10 ms or less differently. Tool provisioning and compatibility must be decided before integration.

## Partial-frame decoding: confirmed blocker

A fixture generated using cwebp/webpmux has an opaque red canvas, a blue partial frame with disposal to background, and a semitransparent green partial frame blended at the same position. The spec requires disposal before blending the next frame. Qt’s image reader leaves the blue pixels behind and produces opaque cyan; the libwebp animation decoder produces the expected semitransparent green. This was independently confirmed with a small C program using the official libwebp animation API. The source loader now uses the libwebp animation decoder, and the fixture is decoded correctly.

`scripts/webp_reference_decoder.py` is an experimental alternative using the installed libwebpdemux shared library via ctypes. It decodes this fixture correctly and the prepared-frame FFmpeg bridge retains its tested colours and alpha. It also agrees pixel-for-pixel with Qt at four sampled timestamps of `luddy.webp` on this machine. It is not a production dependency or a portable packaging strategy: library availability, ABI compatibility, malformed inputs, frame timing normalisation and memory/resource limits need attention. The source loader now uses this decoder approach; deployment, ABI compatibility and dependency availability still need to be handled before shipping.

## Other tested behaviour

`poetry run pytest -q tests/test_webp_render_experiment.py` exercises real FFmpeg rendering when a `libwebp_anim` encoder is available. It checks full and partial selections, known colours and final-frame duration, fps 12/15/24/30/60, speeds 0.25/1/3, crop, transparent edges, and lossy `luddy.webp` output at sampled timestamps. It compares the animation source player's emitted colours with rendered frames at matching source times. Encoder-not-found, encoder failure, missing or failed mux and cancellation of an experimental subprocess are tested; a temporary-directory context demonstrates cleanup on cancellation. These tests do not establish correct cleanup or cancellation in the app's asynchronous `QProcess` implementation.

Fixture generation and the static-image workaround need the external `cwebp`/`webpmux` executables; libwebp decoding requires a discoverable libwebpdemux shared library. Tests for optional tools skip where unavailable. `luddy.webp` is optional and is not modified. Resource limits and wider platform coverage remain outstanding.
