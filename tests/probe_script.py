"""
Simple CLI script to test running a probe on an mp4 file.
"""

import sys
from gifmaker.video.probe import probe_video

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python probe_script.py <video_file>")
        sys.exit(1)

    video_file = sys.argv[1]
    try:
        video_info = probe_video(video_file)
        print(f"Video Info: {video_info}")
    except Exception as e:
        print(f"Error probing video: {e}")
