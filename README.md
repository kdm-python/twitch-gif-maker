# GIF Maker

Install the project and its dependencies with `poetry install`. The application also requires `ffmpeg` and `ffprobe` on your PATH.

WebP previews and exports require an FFmpeg build with the `libwebp_anim` encoder. Check it with `ffmpeg -hide_banner -encoders | grep libwebp_anim`. If your usual FFmpeg lacks it, install a build with libwebp support; on macOS with Homebrew, `brew install ffmpeg-full` is one option. Tell GIF Maker which executable to use before launching it:

```sh
export GIFMAKER_FFMPEG="$(brew --prefix ffmpeg-full)/bin/ffmpeg"
poetry run gifmaker
```

Add the `export` line to your shell's startup file (such as `~/.zshrc`) to keep it for future terminal sessions. `ffprobe` must still be available on PATH. The variable affects GIF Maker, not other programs. Verify your chosen executable with `"$GIFMAKER_FFMPEG" -hide_banner -encoders | grep libwebp_anim`.

Run `poetry run gifmaker`, or use the installed `gifmaker` command when the Poetry environment is on your PATH:

```sh
gifmaker --file /path/to/video.mp4
gifmaker --twitch-clip 'https://clips.twitch.tv/ClipSlug'
```

Use `poetry run gifmaker --help` to see the command-line options. Both arguments validate the input before the application opens. Twitch clips are downloaded to temporary storage and kept for the duration of the application session.

Inside the application, choose **Open Video File** or **Open Twitch Clip**. Their keyboard shortcuts are **Shift+O** and **Shift+L**. Twitch clip downloads require an internet connection and depend on the clip being accessible to yt-dlp.

## Preview workflow

Select the start and end of a clip, adjust the output settings, and choose **Generate Preview** (or **Shift+G**). The output preview is separate from the source video player and uses the selected WebP or GIF format and its render settings, including WebP quality. After the first preview, changes to the selection and output settings update it automatically. Export reuses an identical current preview; otherwise it renders the current settings.

The padlock at the bottom left controls preview updates; press **L** to toggle it from the keyboard. An open lock means live updates are enabled. A closed, coloured lock means the preview is locked: adjust as many settings or crop selections as you like, and the displayed animation keeps playing with its previous settings. Press **Generate Preview** to apply the current settings once; the lock stays closed. Alternatively, unlock it to apply pending changes and resume live updates. Locking before the first preview lets you work entirely with manual generation. The output summary still reflects the current controls, and Export uses the current settings even if the preview is out of date.

The output FPS controls animation cadence: FFmpeg drops or repeats source frames as needed, rather than creating new motion. Choosing a rate above the source FPS will not add detail. The timeline uses the source's average frame rate, so frame stepping and selection boundaries can be approximate for variable-frame-rate video.

For WebP, **Balanced** is the default quality and aims for a useful compromise between detail and size. **Small file** trades some detail for a smaller file; **High quality** retains more detail at a larger size. All three use lossy WebP encoding. Compare them in the output preview at the intended display size: the effect depends on the clip's texture and motion. These choices do not affect GIF output.

The output summary shows a rough size estimate until a preview matches the current settings. It then shows the measured preview file size; hover over the summary for the exact byte count. Changing settings while locked returns the summary to an estimate until the preview is updated. Estimates can be substantially different from the final size because video content affects compression.

## Keyboard-first editing

GIF Maker has a vim-adjacent, keyboard-first workflow: single keys handle frequent editing actions, while Shift combinations open files and trigger larger actions. Use **File → Shortcuts** for the in-app reference, or **File → Documentation** to read this guide inside the app.

| Keys | Action |
| --- | --- |
| Left / Right | Move the source video one frame |
| Space / M | Play or pause the source video / toggle mute |
| Comma / Period | Decrease / increase source playback speed |
| C / Z / X | Set the start to the current frame / nudge it backward / forward |
| V / B / N | Set the end to the current frame / nudge it backward / forward |
| A / R | Apply / reset the crop (in locked mode, generate the preview to see it) |
| [ / ] | Decrease / increase output speed |
| L | Lock / unlock live preview updates |
| Shift+G | Generate the output preview |
| Shift+O / Shift+L | Open a video file / Twitch clip |
| Shift+E | Export GIF or WebP |

If your `gifmaker` shell command wraps Poetry, forward its arguments, for example:

```sh
gifmaker() {
    "$(cd /path/to/gifmaker && poetry env info --path)/bin/gifmaker" "$@"
}
```
