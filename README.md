# GIF Maker

Install the project and its dependencies with `poetry install`. The application also requires `ffmpeg` and `ffprobe` on your PATH.

Run `poetry run gifmaker`, or use the installed `gifmaker` command when the Poetry environment is on your PATH:

```sh
gifmaker --file /path/to/video.mp4
gifmaker --twitch-clip 'https://clips.twitch.tv/ClipSlug'
```

Use `poetry run gifmaker --help` to see the command-line options. Both arguments validate the input before the application opens. Twitch clips are downloaded to temporary storage and kept for the duration of the application session.

Inside the application, choose **Open Video File** or **Open Twitch Clip**. Their keyboard shortcuts are **Shift+O** and **Shift+L**. Twitch clip downloads require an internet connection and depend on the clip being accessible to yt-dlp.

If your `gifmaker` shell command wraps Poetry, forward its arguments, for example:

```sh
gifmaker() {
    "$(cd /path/to/gifmaker && poetry env info --path)/bin/gifmaker" "$@"
}
```
