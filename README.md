# GIF Maker

Install the project and its dependencies with `poetry install`. The application also requires `ffmpeg` and `ffprobe` on your PATH.

Run `poetry run gifmaker`, or use the installed `gifmaker` command when the Poetry environment is on your PATH:

```sh
gifmaker --file /path/to/video.mp4
gifmaker --twitch-clip 'https://clips.twitch.tv/ClipSlug'
```

Use `poetry run gifmaker --help` to see the command-line options. Both arguments validate the input before the application opens. Twitch clips are downloaded to temporary storage and kept for the duration of the application session.

Inside the application, choose **Open Video File** or **Open Twitch Clip**. Their keyboard shortcuts are **Shift+O** and **Shift+L**. Twitch clip downloads require an internet connection and depend on the clip being accessible to yt-dlp.

## Preview workflow

Select the start and end of a clip, adjust the output settings, and choose **Generate Preview** (or **Shift+G**). The GIF preview is separate from the source video player. After the first preview, changes to the selection and output settings update the GIF preview automatically.

The padlock at the bottom left controls preview updates; press **L** to toggle it from the keyboard. An open lock means live updates are enabled. A closed, coloured lock means the preview is locked: adjust as many settings or crop selections as you like, and the displayed GIF keeps playing with its previous settings. Press **Generate Preview** to apply the current settings once; the lock stays closed. Alternatively, unlock it to apply pending changes and resume live updates. Locking before the first preview lets you work entirely with manual generation. The output summary still reflects the current controls, and Export uses the current settings even if the preview is out of date.

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
| L | Lock / unlock live GIF preview updates |
| Shift+G | Generate the GIF preview |
| Shift+O / Shift+L | Open a video file / Twitch clip |
| Shift+E | Export GIF or WebP |

If your `gifmaker` shell command wraps Poetry, forward its arguments, for example:

```sh
gifmaker() {
    "$(cd /path/to/gifmaker && poetry env info --path)/bin/gifmaker" "$@"
}
```
