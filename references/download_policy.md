# Source Download Policy

Always download the highest-quality directly available source before transcription, frame selection or rendering. Do not use a browser preview, thumbnail, screenshot, low-resolution convenience format or a video-only DASH stream as the working source.

Use the deterministic selector below and merge the best video and best audio streams:

```bash
yt-dlp --no-playlist \
  --format 'bestvideo*+bestaudio/best' \
  --format-sort 'res,fps,vcodec,acodec,abr' \
  --merge-output-format mkv \
  --write-info-json \
  --output 'source.%(ext)s' URL
```

After download, run `scripts/download_source.py` or record an equivalent `source_download.json`. The manifest must include the source URL, direct-download mode, selector, `quality_rank=best_available`, `is_best_available=true`, merged media path, SHA-256, duration, file size, video/audio streams, codec, resolution, frame rate, bitrate, requested format IDs and download metadata.

The quality requirement means **the highest quality the source actually exposes to the downloader at that time**. It does not mean inventing a higher resolution or upscaling a low-resolution source. If the highest stream has no audio, download the best video and best audio separately and merge them; a video-only file does not pass the audio gate.

If yt-dlp cannot expose the highest source, the file is truncated, the source is region/permission restricted, or the selected stream differs from the subtitle version, stop and tell the user. Do not silently fall back to a preview and do not call the result final.
