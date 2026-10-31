# Smart Media Compressor

A simple, offline, FFmpeg-based media compressor with a console interface.

Compress videos, images, and audio files to a target file size with smart quality and size trade-offs.

## Features

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
* 100% local — no internet required

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
* Python packages:

  ```bash
  pip install -r requirements.txt
  ```

## Installation

1. Make sure FFmpeg is in your system PATH
2. Download or clone this repository:

   ```bash
   git clone https://github.com/Limitrious/compressor
   cd compressor
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

1. **Input file**

   * Drag & drop or paste path
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

## Example run

![example](https://raw.githubusercontent.com/Limitrious/compressor/refs/heads/main/example.png)

## Notes

* CPU encoding gives the most accurate file size
* GPU encoding (NVENC) is single-pass, faster but less precise
* 2-pass encoding is only effective on CPU encoders
* Very short or already small files may not match the exact target size
* Targets too small for the video's length are rejected, and if the size can't be reached you get a warning
* Audio-only files ignore saturation
* Config is stored in `compressor_config.json`

## License

MIT — feel free to modify and use

Made in Hanoi, 2026
