# GIF and WebP regression baseline

Stage 1 records the current application behaviour before format architecture changes. Inputs remain MP4 only; WebP is the default output and GIF is the other choice.

- Keep the existing two preview panels, control rows, labels, defaults, themes and shortcuts. Quality is visible for WebP only; switching formats preserves the shared controls and the selected WebP quality.
- Keep selection, frame stepping, crop, aspect locking, original size, FPS, speed and sharpness behaviour. GIF uses its fixed palette; WebP uses its selected quality preset.
- The first preview is generated explicitly. Later edits refresh it automatically unless locked. A locked preview remains visible; manual generation applies the current settings without unlocking. Unlocking applies pending changes.
- Export reuses a matching existing preview; otherwise it renders the current settings. The summary uses a measured size only for a matching preview, and otherwise shows an estimate.
- Preserve cancellation, stale-result rejection, error reporting and temporary-file cleanup, including when the source changes or the application closes.

Run `poetry run pytest -q` for the regression suite. The real-render tests require FFmpeg; WebP integration tests need a build with `libwebp_anim` (see README). When changing the UI, also compare the running application at normal and narrow widths and exercise both themes: automated tests do not establish pixel-identical appearance.
