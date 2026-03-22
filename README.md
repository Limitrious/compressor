# Smart Auto Media Compressor

A simple, offline, FFmpeg-based media compressor with a beautiful console interface.

Compress videos, images, GIFs, and audio files to a target file size with smart quality/size trade-offs.

Features:
- Target file size selection (quick presets + custom)
- Output formats grouped by efficiency & compatibility (AV1, WebP, MP4, GIF, etc.)
- Compression levels: fastest / fast / normal / maximum
- Saturation adjustment (0%–200%)
- Remembers your preferred output folder
- Creates `compressed_output` folder next to the script by default
- Avoids overwriting files (adds _1, _2, … when needed)
- 100% local — no internet required

## Requirements

- Python 3.8+
- FFmpeg & ffprobe (add to PATH)
  - Download full build: https://www.gyan.dev/ffmpeg/builds/
  - or simply run this in powershell
      ```bash
      winget install -e --id Gyan.FFmpeg --exact
      ```
- Python packages:
  ```bash
  pip install rich questionary
  ```

## Installation

1. Make sure FFmpeg is in your system PATH
2. Install dependencies:
   ```bash
   pip install rich questionary
   ```
3. Download or clone this repository
    ```bash
    git clone https://github.com/Limitrious/compressor
    cd compressor
    ```
4. Run it
    ```bash
    python main.py
    ```

### Workflow

1. **Input file**  
   - Drag & drop or paste path  
   - Press Enter (empty) → change output folder setting

2. **Output folder**  
   - First time: defaults to `compressed_output` next to the script  
   - Can be changed at any time by pressing Enter on input prompt  
   - Remembered for next runs (saved in `compressor_config.json`)

3. **Target size**  
   - Quick picks: 1 / 8 / **10** / 20 / 25 / **50** / **100** / 500 MiB  
   - Or Custom

4. **Output format**  
   - Grouped options (AV1 MKV, WebP, MP4, GIF, etc.)

5. **Compression level**  
   - fastest / fast / normal / maximum

6. **Saturation**  
   - Enter % (0–200)  
   - Press Enter → 100% (no change)

7. Wait for compression → result saved in chosen folder

## Example run

```
OFFLINE MEDIA COMPRESSOR
Smart FFmpeg compressor — target size + saturation control

Input file (press Enter to change output folder): video.mp4
→ Using output folder: C:\projects\compressed_output

→ Detected: VIDEO

Target size (MiB): 10 MiB   ← most popular for short clips
→ Target: 10 MiB

Output format: MP4  •  Moderate efficiency • Compatible with everything

Compression level (speed ↔ quality): normal

Saturation multiplier (%) — press Enter for 100%: 120
→ Saturation: 120.0%

→ Saving as: video_compressed.mp4

[green]Compressing...[/green]

Done!   Size: 9.84 MiB
   → C:\projects\compressed_output\video_compressed.mp4
```

## Notes

- Size control is approximate — very short clips or already small files may end up slightly larger/smaller.
- GIF/APNG use palette-based compression (limited color control).
- Audio-only files ignore saturation setting.
- Config is saved in `compressor_config.json` next to the script.

## License

MIT — feel free to modify and use.

Made with love in Hanoi, 2026