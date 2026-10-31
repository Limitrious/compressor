# ratecap

A simple, offline, FFmpeg-based tool that fits media into a target file size, with a console interface.

Compress videos, images, and audio files to a target file size with smart quality and size trade-offs. Can also download YouTube videos or audio first.

## Features

* YouTube download: paste a link, pick video or audio, pick quality, optionally compress right after
* Playlist detection with a warning before downloading a whole playlist
* Target file size selection (quick presets + custom)
* Accurate size targeting: output stays at or under the target
* Optional 2-pass encoding (CPU only, higher accuracy)
* Optional GPU encoding (NVENC, MP4 only, faster but less precise)
* Dynamic audio bitrate scaling
* Smarter resolution scaling based on target size
* Output formats grouped by efficiency and compatibility, shown only when they fit your input
* Compression levels: fastest / fast / normal / maximum
* Saturation adjustment (0%–200%) for video and images
* Live progress bar
* Remembers:

  * Output folder
  * 2-pass setting
  * GPU setting
* Creates `compressed_output` folder next to the script by default
* Avoids overwriting files (adds _1, _2, … when needed)
* 100% local - no internet required

## Supported formats

| Input | Output options |
| --- | --- |
| Video | MP4, WebM, AV1 MKV, or audio only (MP3, M4A, OGG) |
| Audio | MP3, M4A, OGG |
| Image | PNG/JPEG, WebP, AVIF |

PNG/JPEG keeps a lossless PNG when it fits the target, otherwise saves a JPEG.

## Requirements

* Python 3.9+
* FFmpeg & ffprobe (add to PATH)

  * Download full build: [https://www.gyan.dev/ffmpeg/builds/](https://www.gyan.dev/ffmpeg/builds/)
  * or run in PowerShell:

    ```bash
    winget install -e --id Gyan.FFmpeg --exact
    ```
* A JavaScript runtime for YouTube downloads (only needed for the YouTube feature)

  * [Deno](https://deno.com) is recommended; yt-dlp uses it automatically
  * Node.js or Bun also work if already installed
* Python packages:

  ```bash
  pip install -r requirements.txt
  ```

## Installation

1. Make sure FFmpeg is in your system PATH
2. Download or clone this repository:

   ```bash
   git clone https://github.com/Limitrious/ratecap
   cd ratecap
   ```
3. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```
4. Run:

   ```bash
   python main.py
   ```

## Workflow

1. **Input file or YouTube link**

   * Drag & drop or paste path
   * Or paste a YouTube link (see [YouTube download](#youtube-download))
   * Press Enter (empty) → change output folder

2. **Output folder**

   * Defaults to `compressed_output` next to the script
   * Can be changed anytime
   * Saved in `compressor_config.json`

3. **Target size**

   * Presets: 1 / 8 / 10 / 20 / 25 / 50 / 100 / 500 MiB
   * Or custom value

4. **Output format**

   * Choose based on compatibility or efficiency

5. **Compression level**

   * fastest / fast / normal / maximum

6. **Encoding options** (video only)

   * GPU encoding (NVENC, MP4 only, shown when available)
   * 2-pass encoding (CPU only, more accurate, slower)

7. **Saturation** (video and images)

   * 0–200%
   * Enter → 100%

8. Wait for compression → output saved in selected folder

## YouTube download

Paste a YouTube link at the first prompt instead of a file path.

1. If the link contains a playlist, you get a warning with the number of videos and a confirm (default: no)
   * **No** → the playlist part is removed from the link and only that video is downloaded
   * **Yes** → every video is downloaded, one by one (a second confirm appears above 50 videos)
   * Links that are a playlist only (no single video in them) go back to the input prompt on No
2. Choose **Video** or **Audio only**
3. Choose quality
   * Video: Best available or a resolution cap (1080p, 720p, ...)
   * Audio: Best, up to 128 kbps, or up to 64 kbps
4. Choose whether to compress it afterwards
   * **No** → saved to the output folder (video as MP4, audio as M4A)
   * **Yes** → the usual size / format / level questions follow, only the compressed file is kept

Playlists are saved into their own subfolder, numbered in playlist order. A video that fails (private, deleted, region-locked) is skipped and the rest continue.

## Example run

![example](https://raw.githubusercontent.com/Limitrious/compressor/refs/heads/main/example.png)

## Notes

* CPU encoding gives the most accurate file size
* GPU encoding (NVENC) is single-pass, faster but less precise
* 2-pass encoding is only effective on CPU encoders
* Very short or already small files may not match the exact target size
* Targets too small for the video's length are rejected, and if the size can't be reached you get a warning
* Audio-only files ignore saturation
* YouTube changes often. If downloads fail, update yt-dlp: `pip install -U "yt-dlp[default]"`
* Live streams are not supported
* Only YouTube links are recognized (youtube.com, music.youtube.com, youtu.be)
* Config is stored in `compressor_config.json`

## License

MIT — feel free to modify and use

Made in Hanoi, 2026
