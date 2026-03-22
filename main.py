# Smart offline media compressor (video / audio / image)
# Uses FFmpeg + nice console GUI

# REQUIREMENTS:
# pip install rich questionary
# FFmpeg & ffprobe in PATH (https://www.gyan.dev/ffmpeg/builds/ — full build recommended)

import os
import subprocess
import json
import shutil
import re
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.prompt import IntPrompt
import questionary

console = Console()

CONFIG_FILE = Path(__file__).parent / "compressor_config.json"
DEFAULT_OUTPUT_FOLDER = Path(__file__).parent / "compressed_output"

# ──────────────────────────────────────────────────────────────────────────────
# FORMATS (grouped by efficiency & compatibility)
# ──────────────────────────────────────────────────────────────────────────────
FORMATS = [
    {"name": "GIF",      "ext": ".gif",   "group": "Very poor efficiency • Legacy"},
    {"name": "MP3",      "ext": ".mp3",   "group": "Very poor efficiency • Universal"},
    {"name": "MP4",      "ext": ".mp4",   "group": "Moderate efficiency • Compatible with everything"},
    {"name": "M4A",      "ext": ".m4a",   "group": "Moderate efficiency • Compatible with everything"},
    {"name": "PNG/JPEG", "ext": ".png",   "group": "Moderate efficiency • Compatible with everything"},
    {"name": "APNG",     "ext": ".apng",  "group": "Moderate efficiency • Modern browsers"},
    {"name": "WebM",     "ext": ".webm",  "group": "High efficiency • Good compatibility"},
    {"name": "OGG",      "ext": ".ogg",   "group": "High efficiency • Good compatibility"},
    {"name": "WebP",     "ext": ".webp",  "group": "High efficiency • Modern"},
    {"name": "AV1 MKV",  "ext": ".mkv",   "group": "Ultra high efficiency (AV1) • Modern (Discord friendly)"},
    {"name": "AVIF",     "ext": ".avif",  "group": "Ultra high efficiency (AV1) • Modern browsers"},
]

COMPRESSION_LEVELS = ["fastest", "fast", "normal", "maximum"]

# ──────────────────────────────────────────────────────────────────────────────
# CONFIG HELPERS
# ──────────────────────────────────────────────────────────────────────────────

def load_config():
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_config(data):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except:
        console.print("[yellow]Warning: could not save config[/yellow]")

# ──────────────────────────────────────────────────────────────────────────────
# FFmpeg & MEDIA HELPERS
# ──────────────────────────────────────────────────────────────────────────────

def check_ffmpeg():
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        console.print("[bold red]FFmpeg / ffprobe not found in PATH[/bold red]")
        console.print("Download full build → https://www.gyan.dev/ffmpeg/builds/")
        exit(1)

def get_media_info(path: str) -> dict:
    cmd = ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams", path]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return json.loads(result.stdout)

def detect_type(info: dict) -> str:
    has_video = any(s["codec_type"] == "video" for s in info["streams"])
    has_audio = any(s["codec_type"] == "audio" for s in info["streams"])
    is_image = any(s["codec_type"] == "video" and "duration" not in s for s in info["streams"])
    is_animated = is_image and any(int(s.get("nb_frames", "1")) > 1 for s in info["streams"])

    if is_animated: return "animation"
    if has_video:   return "video"
    if has_audio and not has_video: return "audio"
    if is_image:    return "image"
    return "unknown"

def get_preset(level: str, encoder: str) -> str:
    table = {
        "fastest": {"svtav1": "12", "x264": "ultrafast", "vp9": "0",   "webp": "100", "avif": "10"},
        "fast":    {"svtav1": "8",  "x264": "veryfast",  "vp9": "1",   "webp": "80",  "avif": "8"},
        "normal":  {"svtav1": "5",  "x264": "medium",    "vp9": "2",   "webp": "70",  "avif": "6"},
        "maximum": {"svtav1": "2",  "x264": "veryslow",  "vp9": "3",   "webp": "50",  "avif": "4"},
    }
    return table.get(level, {}).get(encoder, "medium")

# ──────────────────────────────────────────────────────────────────────────────
# COMPRESSION FUNCTIONS — with saturation support
# ──────────────────────────────────────────────────────────────────────────────

def compress_video_animation(inp: str, out: str, target_mib: int, level: str, fmt: dict, info: dict, saturation: float):
    duration = float(info["format"].get("duration", 60))
    target_kbps_video = max(150, int((target_mib * 0.85) * 8192 / duration))
    audio_bitrate = "64k" if target_mib <= 20 else "96k"

    v = next((s for s in info["streams"] if s["codec_type"] == "video"), {})
    w, h = int(v.get("width", 1920)), int(v.get("height", 1080))
    scale_factor = min(1.0, (target_mib / max(Path(inp).stat().st_size / 1_048_576, 1)) ** 0.5)
    new_w = max(320, int(w * scale_factor / 2) * 2)
    new_h = max(180, int(h * scale_factor / 2) * 2)
    scale_filter = f"scale={new_w}:{new_h}:force_original_aspect_ratio=decrease,pad=ceil(iw/2)*2:ceil(ih/2)*2" if scale_factor < 0.95 else "null"

    sat_filter = f"eq=saturation={saturation/100:.2f}" if saturation != 100 else "null"
    vf = f"{scale_filter},{sat_filter}" if scale_filter != "null" or sat_filter != "null" else "null"

    name = fmt["name"]
    if name == "AV1 MKV":
        cmd = ["ffmpeg", "-i", inp, "-vf", vf, "-c:v", "libsvtav1", "-preset", get_preset(level, "svtav1"), "-crf", "34" if level == "normal" else "30",
               "-b:v", f"{target_kbps_video}k", "-c:a", "libopus", "-b:a", audio_bitrate, "-y", out]
    elif name == "MP4":
        cmd = ["ffmpeg", "-i", inp, "-vf", vf, "-c:v", "libx264", "-preset", get_preset(level, "x264"), "-crf", "26" if level == "normal" else "23",
               "-b:v", f"{target_kbps_video}k", "-c:a", "aac", "-b:a", audio_bitrate, "-y", out]
    elif name == "WebM":
        cmd = ["ffmpeg", "-i", inp, "-vf", vf, "-c:v", "libvpx-vp9", "-b:v", f"{target_kbps_video}k",
               "-c:a", "libopus", "-b:a", audio_bitrate, "-y", out]
    else:  # GIF / APNG
        fps = "12" if target_mib <= 8 else "15" if target_mib <= 15 else "24"
        cmd = ["ffmpeg", "-i", inp, "-vf", f"fps={fps},{scale_filter},{sat_filter}", "-loop", "0", "-y", out]

    subprocess.run(cmd, check=True)

def compress_audio(inp: str, out: str, target_mib: int, level: str, fmt: dict, saturation: float):
    # saturation doesn't apply to audio → ignore
    target_kbps = max(32, int(target_mib * 1024 * 8 / 180))
    name = fmt["name"]
    if name == "MP3":
        cmd = ["ffmpeg", "-i", inp, "-c:a", "libmp3lame", "-b:a", f"{target_kbps}k", "-y", out]
    elif name == "M4A":
        cmd = ["ffmpeg", "-i", inp, "-c:a", "aac", "-b:a", f"{target_kbps}k", "-y", out]
    elif name == "OGG":
        cmd = ["ffmpeg", "-i", inp, "-c:a", "libopus", "-b:a", f"{target_kbps}k", "-y", out]
    else:
        cmd = ["ffmpeg", "-i", inp, "-c:a", "copy", "-y", out]
    subprocess.run(cmd, check=True)

def compress_image(inp: str, out: str, target_mib: int, level: str, fmt: dict, saturation: float):
    target_bytes = target_mib * 1024 * 1024
    name = fmt["name"]
    q = 85 if level == "normal" else 92
    scale = 1.0
    sat_filter = f"eq=saturation={saturation/100:.2f}" if saturation != 100 else "null"

    while True:
        vf_parts = [f"scale=iw*{scale}:ih*{scale}"]
        if sat_filter != "null":
            vf_parts.append(sat_filter)
        vf = ",".join(vf_parts) if vf_parts else "null"

        if name in ("PNG/JPEG", "PNG"):
            ext = ".jpg" if q < 70 or target_bytes < 500_000 else ".png"
            tmp = out if out.endswith(ext) else out.rsplit(".", 1)[0] + ext
            if ext == ".png":
                cmd = ["ffmpeg", "-i", inp, "-vf", vf, "-c:v", "png", "-y", tmp]
            else:
                cmd = ["ffmpeg", "-i", inp, "-vf", vf, "-c:v", "mjpeg", "-q:v", str(max(2, 15 - q//6)), "-y", tmp]
        elif name == "WebP":
            cmd = ["ffmpeg", "-i", inp, "-vf", vf, "-c:v", "libwebp", "-quality", str(q), "-y", out]
        elif name == "AVIF":
            cmd = ["ffmpeg", "-i", inp, "-vf", vf, "-c:v", "libaom-av1", "-still-picture", "1", "-crf", str(50 - q//2), "-y", out]
        else:
            cmd = ["ffmpeg", "-i", inp, "-vf", vf, "-c:v", "mjpeg", "-q:v", "6", "-y", out]

        subprocess.run(cmd, check=True)
        current = Path(tmp if 'tmp' in locals() else out).stat().st_size

        if current <= target_bytes * 1.1 or scale < 0.45:
            if 'tmp' in locals() and tmp != out:
                shutil.move(tmp, out)
            break

        q = max(25, q - 18)
        scale *= 0.78

# ──────────────────────────────────────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────────────────────────────────────

def main():
    check_ffmpeg()

    console.print(Panel.fit(
        "[bold cyan]OFFLINE MEDIA COMPRESSOR[/]\n"
        "Smart FFmpeg compressor — target size + saturation control",
        border_style="cyan"
    ))

    config = load_config()
    remembered_folder = config.get("output_folder")

    # ── Input file loop ──────────────────────────────────────────────────────
    while True:
        inp_raw = questionary.path(
            "Input file (press Enter to change output folder)",
            default=""
        ).ask().strip()

        if inp_raw == "":
            current = remembered_folder or str(DEFAULT_OUTPUT_FOLDER)
            console.print(f"Current output folder: [bold]{current}[/]")

            new_folder = questionary.text(
                "New output folder path (Enter to keep current)",
                default=remembered_folder or ""
            ).ask().strip()

            if new_folder:
                path = Path(new_folder).resolve()
                try:
                    path.mkdir(parents=True, exist_ok=True)
                    remembered_folder = str(path)
                    config["output_folder"] = remembered_folder
                    save_config(config)
                    console.print(f"→ Output folder updated and saved: [bold]{remembered_folder}[/]")
                except Exception as e:
                    console.print(f"[red]Cannot use that folder:[/] {e}")
            else:
                console.print("[dim]No change[/dim]")
            continue

        inp_path = Path(inp_raw)
        if not inp_path.is_file():
            console.print("[red]File not found — try again[/red]")
            continue

        break

    input_path = Path(inp_path)

    # Decide output folder
    if remembered_folder:
        output_folder = Path(remembered_folder)
    else:
        output_folder = DEFAULT_OUTPUT_FOLDER

    output_folder.mkdir(parents=True, exist_ok=True)
    console.print(f"→ Using output folder: [bold]{output_folder}[/]")

    info = get_media_info(str(input_path))
    kind = detect_type(info)
    console.print(f"→ Detected: [bold]{kind.upper()}[/]")

    # Target size
    size_choices = [
        "1 MiB",
        "8 MiB",
        "10 MiB   ← most popular for short clips",
        "20 MiB",
        "25 MiB",
        "50 MiB   ← good balance",
        "100 MiB  ← high quality longer content",
        "500 MiB",
        "Custom...",
    ]

    choice = questionary.select("Target size (MiB)", choices=size_choices).ask()
    if choice is None:
        console.print("[yellow]Cancelled[/yellow]")
        return

    if "Custom" in choice:
        target_mib = IntPrompt.ask("Custom size (MiB)", default=10)
    else:
        match = re.search(r'\d+', choice)
        target_mib = int(match.group(0)) if match else 10

    console.print(f"→ Target: [bold]{target_mib} MiB[/]")

    # Format
    fmt_choices = [f"{f['name']}  •  {f['group']}" for f in FORMATS]
    fmt_str = questionary.select("Output format", choices=fmt_choices).ask()
    if fmt_str is None:
        return
    fmt_name = fmt_str.split("  •  ")[0]
    fmt = next(f for f in FORMATS if f["name"] == fmt_name)

    # Compression level
    level = questionary.select(
        "Compression level (speed ↔ quality)",
        choices=COMPRESSION_LEVELS
    ).ask()
    if level is None:
        return

    # ── NEW: Saturation adjustment ───────────────────────────────────────────
    saturation_raw = questionary.text(
        "Saturation multiplier (%) — press Enter for 100%",
        default="100"
    ).ask().strip()

    try:
        saturation = float(saturation_raw)
        saturation = max(0.0, min(200.0, saturation))
    except ValueError:
        console.print("[yellow]Invalid value → using 100%[/yellow]")
        saturation = 100.0

    console.print(f"→ Saturation: [bold]{saturation}%[/]")

    # Output path
    base_name = input_path.stem + "_compressed"
    out = output_folder / (base_name + fmt["ext"])

    counter = 1
    while out.exists():
        out = output_folder / f"{base_name}_{counter}{fmt['ext']}"
        counter += 1

    if counter > 1:
        console.print(f"→ File exists → using: [bold]{out.name}[/]")
    else:
        console.print(f"→ Saving as: [bold]{out.name}[/]")

    # Compress
    with console.status("[bold green]Compressing... (may take a while)", spinner="dots8Bit"):
        try:
            if kind in ("video", "animation"):
                compress_video_animation(str(input_path), str(out), target_mib, level, fmt, info, saturation)
            elif kind == "audio":
                compress_audio(str(input_path), str(out), target_mib, level, fmt, saturation)
            elif kind == "image":
                compress_image(str(input_path), str(out), target_mib, level, fmt, saturation)
            else:
                console.print("[yellow]Unsupported type — copying[/yellow]")
                shutil.copy(input_path, out)
        except Exception as e:
            console.print(f"[bold red]Failed:[/] {e}")
            return

    if out.is_file():
        size_mb = out.stat().st_size / 1_048_576
        console.print(f"\n[bold green]Done![/]   Size: [bold]{size_mb:.2f} MiB[/]")
        console.print(f"   → [bold]{out}[/bold]")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        console.print("\n[yellow]Cancelled[/yellow]")
    except Exception as e:
        console.print(f"\n[bold red]Unexpected error:[/] {e}")