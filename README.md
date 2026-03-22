# Smart Media Compressor

A simple, offline, FFmpeg-based media compressor with a console interface.

Compress videos, images, GIFs, and audio files to a target file size with smart quality and size trade-offs.

**Now also available as a standalone EXE** — no Python, FFmpeg installation, or other dependencies required. Just download and run.

[**Release**](https://github.com/Limitrious/compressor/releases/tag/v1)

## Features

* Target file size selection (quick presets + custom)
* Accurate size targeting using bitrate search
* CRF fallback when bitrate targeting is not sufficient
* Final retry pass to reduce overshoot
* Optional 2-pass encoding (CPU only, higher accuracy)
* Optional GPU encoding (NVENC, faster but less precise)
* Scene complexity detection
* Dynamic audio bitrate scaling
* Smarter resolution scaling based on target size
* Output formats grouped by efficiency and compatibility (AV1, WebP, MP4, GIF, etc.)
* Compression levels: fastest / fast / normal / maximum
* Saturation adjustment (0%–200%)
* Remembers:

  * Output folder
  * 2-pass setting
  * GPU setting
  * Scene detection
  * Motion detection
* Creates `compressed_output` folder next to the script by default
* Avoids overwriting files (adds _1, _2, … when needed)
* 100% local — no internet required

## Requirements

* Python 3.8+
* FFmpeg & ffprobe (add to PATH)

  * Download full build: [https://www.gyan.dev/ffmpeg/builds/](https://www.gyan.dev/ffmpeg/builds/)
  * or run in PowerShell:

    ```bash
    winget install -e --id Gyan.FFmpeg --exact
    ```
* Python packages:

  ```bash
  pip install rich questionary
  ```

## Installation

1. Make sure FFmpeg is in your system PATH
2. Install dependencies:

   ```bash
   pip install rich questionary
   ```
3. Download or clone this repository:

   ```bash
   git clone https://github.com/Limitrious/compressor
   cd compressor
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

6. **Encoding options**

   * 2-pass encoding (more accurate, slower)
   * GPU encoding (faster, less accurate)
   * Scene complexity detection
   * Motion analysis (optional, slower but better for action content)

7. **Saturation**

   * 0–200%
   * Enter → 100%

8. Wait for compression → output saved in selected folder

## Example run

![example](https://raw.githubusercontent.com/Limitrious/compressor/refs/heads/main/example.png)

## Notes

* CPU encoding (libx264) gives the most accurate file size
* GPU encoding (NVENC) is faster but less precise
* 2-pass encoding is only effective on CPU encoders
* Very short or already small files may not match the exact target size
* GIF/APNG use limited color palettes
* Audio-only files ignore saturation
* Config is stored in `compressor_config.json`

## License

MIT — feel free to modify and use

Made in Hanoi, 2026
