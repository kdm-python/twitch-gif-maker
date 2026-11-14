# Animated WebP source timing: proposed contract

This is the intended contract for the future WebP source backend, not a description of current application behaviour. The application does not yet accept WebP input. It uses one animation cycle as its editable source regardless of the source loop count.

## Timeline and frame boundaries

- Read composited frames in file order and retain their effective per-frame delays as integer milliseconds. Frame 0 starts at 0; each later frame starts at the sum of all previous delays. The source duration is the sum of all frame delays, including the final one.
- A frame is visible from its start, inclusive, until the next frame's start, exclusive. A timestamp exactly at a boundary refers to the next frame. The timeline's end is a valid selection endpoint but is not itself a frame; when visually parked there, show the last frame.
- For the fixture with delays 100, 250 and 400 ms, red is visible on [0, 100), green on [100, 350), and blue on [350, 750). The end of the source is 750 ms.
- Frame stepping moves by actual frame index, not by average FPS, and clamps at the first and last frame. Seeking within a frame shows that frame. Playback advances according to the same timestamps.
- Zero or very short WebP delays can be interpreted differently by decoders. First characterise the chosen decoder and specify a consistent effective-delay policy; reject a source with a clear error if timing cannot be resolved reliably. Do not silently assume a 25 FPS default. Corrupt and static files must receive an explanatory error.

## Selection and rendering

- A selection is a non-empty half-open time interval [start, end), bounded by 0 and the source duration. The start is included and the end excluded. The full source is [0, duration). The actual UI's frame-marker mapping must preserve these rules and be tested.
- If a boundary falls within a frame, retain only the portion of that frame inside the selection. For example [50, 500) from the fixture contains 50 ms red, 250 ms green and 150 ms blue, for 450 ms total before speed adjustment. A selection starting at 100 ms begins with green; one ending at 350 ms excludes blue.
- Output speed changes the selected duration by dividing by the speed. Output FPS then samples the resulting timeline at the selected cadence. This can drop or repeat frames and quantise the final duration to the output frame grid. Tests must define tolerances and verify boundary pictures as well as durations; they must not imply source timing is preserved exactly after constant-FPS conversion.
- Preview and export must use the same source, selection, transformations and output settings. Do not use the average source frame rate to decide what a timestamp means. Ensure the final frame's duration is represented in any intermediate and avoid introducing a duplicate frame at the end.

## Source and output behaviour

- A WebP source permits WebP output only. GIF remains available for MP4 input. Source changes must update the choice without silently exporting in a disabled format; the exact restoration behaviour for previous choices should be specified when the UI is designed.
- Keep the original input distinct from any temporary editing representation. Never overwrite it during preparation, preview or rendering. An export to the same path must be prevented or require an explicit safe overwrite workflow.
- Keep the existing MP4 controls and behaviour intact. The preparation and playback design must handle loading failures and cancellation without losing the current source.

## Fixture data

`tests/fixtures/webp_input/variable_delays.webp` is a 16×16 lossless animation with opaque red, green and blue frames. `transparent.webp` has a coloured 4×8 rectangle at a different horizontal position in each frame and transparent pixels elsewhere. Both contain 100, 250 and 400 ms delays, infinite loop metadata, and full-canvas frames configured to replace and dispose to background. The latter tests transparency and disposal; it does not yet exercise sub-rectangle frame offsets or blending.

Regenerate with `poetry run python scripts/generate_webp_test_fixtures.py`; this requires the `cwebp` and `webpmux` command-line tools in addition to project dependencies. The checked-in files allow tests to run without those tools. `tests/test_webp_input_fixtures.py` checks WebP frame headers and Qt-decoded colours, alpha and timing. It verifies fixture properties, not the future editing backend.

The fixtures intentionally use delays above 10 ms to avoid decoder-specific handling of zero or very short delays. Further fixtures should exercise partial-frame blending, invalid or truncated files and decoder-specific timing edge cases. Transparency preservation versus flattening in output remains a product/implementation decision; the transparent fixture exists to make either behaviour testable.
