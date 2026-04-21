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

def load_config() -> dict:
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
        except Exception:
            pass
    return {}

def save_config(data: dict):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception:
        console.print("[yellow]Warning: could not save config[/yellow]")

def detect_nvenc() -> bool:
    try:
        result = subprocess.run(
            ["ffmpeg", "-encoders"],
            capture_output=True,
            text=True
        )
        return "h264_nvenc" in result.stdout
    except Exception:
        return False

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

IMAGE_CODECS = {
    "png", "mjpeg", "jpeg", "webp", "bmp", "tiff", "gif",
    "dpx", "exr", "pam", "pbm", "pgm", "ppm", "sgi",
}

def detect_type(info: dict) -> str:
    streams = info.get("streams", [])
    video_streams = [s for s in streams if s.get("codec_type") == "video"]
    has_audio     = any(s.get("codec_type") == "audio" for s in streams)

    if not video_streams:
        return "audio" if has_audio else "unknown"

    def is_image_stream(s: dict) -> bool:
        return (
            s.get("codec_name", "").lower() in IMAGE_CODECS
            and int(s.get("nb_frames", "1")) <= 1
        )

    def is_animated_stream(s: dict) -> bool:
        return (
            s.get("codec_name", "").lower() in IMAGE_CODECS
            and int(s.get("nb_frames", "1")) > 1
        )

    if all(is_animated_stream(s) for s in video_streams):
        return "animation"
    if all(is_image_stream(s) for s in video_streams):
        return "image"
    return "video"

def get_preset(level: str, encoder: str) -> str:
    table = {
        "fastest": {"svtav1": "12", "x264": "ultrafast", "vp9": "0", "webp": "100", "avif": "10"},
        "fast":    {"svtav1": "8",  "x264": "veryfast",  "vp9": "1", "webp": "80",  "avif": "8"},
        "normal":  {"svtav1": "5",  "x264": "medium",    "vp9": "2", "webp": "70",  "avif": "6"},
        "maximum": {"svtav1": "2",  "x264": "veryslow",  "vp9": "3", "webp": "50",  "avif": "4"},
    }
    return table.get(level, {}).get(encoder, "medium")

# ──────────────────────────────────────────────────────────────────────────────
# COMPRESSION FUNCTIONS — with saturation support
# ──────────────────────────────────────────────────────────────────────────────

def compress_video_animation(inp, out, target_mib, level, fmt, info, saturation, use_2pass, use_gpu, use_scene):
    duration = float(info["format"].get("duration", 60))
    input_size_mib = Path(inp).stat().st_size / 1_048_576

    total_kbps = int((target_mib * 8192) / duration)
    target_kbps_video = int(total_kbps * 0.88)

    # dynamic audio scaling
    audio_kbps = min(128, max(32, int(total_kbps * 0.12)))
    audio_bitrate = f"{audio_kbps}k"

    # scaling (less aggressive, keeps quality)
    ratio = target_mib / max(input_size_mib, 1)
    scale_factor = min(1.0, ratio ** 0.8)

    v = next((s for s in info["streams"] if s.get("codec_type") == "video"), {})
    w, h = int(v.get("width", 1920)), int(v.get("height", 1080))

    new_w = max(426, int(w * scale_factor / 2) * 2)
    new_h = max(240, int(h * scale_factor / 2) * 2)

    scale_filter = f"scale={new_w}:{new_h}:force_original_aspect_ratio=decrease"
    pad_filter = "pad=ceil(iw/2)*2:ceil(ih/2)*2"

    vf_parts = [scale_filter, pad_filter]
    if saturation != 100:
        vf_parts.append(f"eq=saturation={saturation/100:.2f}")
    vf = ",".join(vf_parts)

    name = fmt["name"]

    # codec selection
    if name == "MP4":
        vcodec = "h264_nvenc" if use_gpu else "libx264"
        acodec = "aac"
    elif name == "WebM":
        vcodec = "libvpx-vp9"
        acodec = "libopus"
    else:
        vcodec = "libsvtav1"
        acodec = "libopus"

    # ─────────────────────────────
    # SCENE COMPLEXITY
    # ─────────────────────────────
    complexity = 1.0
    if use_scene:
        try:
            probe = subprocess.run([
                "ffmpeg", "-i", inp,
                "-vf", "select='gt(scene,0.4)',showinfo",
                "-f", "null", "-"
            ], stderr=subprocess.PIPE, text=True)
            scenes = probe.stderr.count("showinfo")
            complexity = min(2.0, 1 + scenes / 50)
        except Exception:
            pass

    # ─────────────────────────────
    # BINARY SEARCH BITRATE
    # ─────────────────────────────
    target_bytes = target_mib * 1024 * 1024

    low  = int(total_kbps * 0.3)
    high = int(total_kbps * 2.0)

    best_file = None
    best_diff = float("inf")

    temp_out = out + ".temp.mp4"

    BINARY_SEARCH_ITERATIONS = 6

    def encode(kbps: int, pass_mode: bool = False) -> int:
        kbps = int(kbps * complexity)

        if use_2pass and pass_mode:
            null = "NUL" if os.name == "nt" else "/dev/null"

            subprocess.run([
                "ffmpeg", "-y", "-i", inp,
                "-vf", vf,
                "-c:v", vcodec,
                "-b:v", f"{kbps}k",
                "-pass", "1",
                "-an",
                "-f", "matroska",
                null
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

            subprocess.run([
                "ffmpeg", "-y", "-i", inp,
                "-vf", vf,
                "-c:v", vcodec,
                "-b:v", f"{kbps}k",
                "-pass", "2",
                "-c:a", acodec,
                "-b:a", audio_bitrate,
                temp_out
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            subprocess.run([
                "ffmpeg", "-y", "-i", inp,
                "-vf", vf,
                "-c:v", vcodec,
                "-b:v", f"{kbps}k",
                "-c:a", acodec,
                "-b:a", audio_bitrate,
                temp_out
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        return Path(temp_out).stat().st_size

    # binary search loop
    for i in range(BINARY_SEARCH_ITERATIONS):
        mid = (low + high) // 2
        console.print(
            f"[dim]  Binary search pass {i + 1}/{BINARY_SEARCH_ITERATIONS} "
            f"— trying {mid} kbps (range {low}–{high})[/dim]"
        )

        try:
            size = encode(mid, pass_mode=True)
        except Exception:
            break

        size_mib = size / 1_048_576
        diff = abs(size - target_bytes)
        over_or_under = "over" if size > target_bytes else "under"
        console.print(
            f"[dim]    → {size_mib:.2f} MiB ({over_or_under} target by "
            f"{abs(size_mib - target_mib):.2f} MiB)[/dim]"
        )

        if diff < best_diff:
            best_diff = diff
            new_best = temp_out + ".best"
            try:
                shutil.copy(temp_out, new_best)
                if best_file and os.path.exists(best_file) and best_file != new_best:
                    os.remove(best_file)
                best_file = new_best
            except Exception:
                pass

        if size > target_bytes:
            high = mid
        else:
            low = mid

    use_best = best_file and os.path.exists(best_file)
    final_file = best_file if use_best else (temp_out if os.path.exists(temp_out) else None)
    final_size = Path(final_file).stat().st_size if final_file else target_bytes * 2

    if final_size > target_bytes * 1.05:
        console.print("[yellow]Bitrate targeting failed → switching to CRF fallback[/yellow]")

        crf = 28
        while True:
            subprocess.run([
                "ffmpeg", "-y", "-i", inp,
                "-vf", vf,
                "-c:v", "libx264",
                "-crf", str(crf),
                "-preset", get_preset(level, "x264"),
                "-c:a", acodec,
                "-b:a", audio_bitrate,
                temp_out
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

            size = Path(temp_out).stat().st_size

            if size <= target_bytes * 1.02 or crf >= 40:
                shutil.move(temp_out, out)
                break

            crf += 2
    else:
        shutil.move(final_file, out)

    # cleanup best_file if it wasn't the one we moved
    if best_file and os.path.exists(best_file):
        try:
            os.remove(best_file)
        except Exception:
            pass

    # ─────────────────────────────
    # FINAL HARD RETRY
    # ─────────────────────────────
    current_kbps = total_kbps
    for _ in range(3):
        if not os.path.exists(out):
            break

        size = Path(out).stat().st_size / 1_048_576

        if size <= target_mib * 1.02:
            break

        console.print(f"[yellow]Final retry: {size:.2f} MiB → reducing bitrate[/yellow]")

        current_kbps = int(current_kbps * 0.85)

        subprocess.run([
            "ffmpeg", "-y", "-i", inp,
            "-vf", vf,
            "-c:v", vcodec,
            "-b:v", f"{int(current_kbps * complexity)}k",
            "-c:a", acodec,
            "-b:a", audio_bitrate,
            out
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # cleanup
    for f in ("ffmpeg2pass-0.log", "ffmpeg2pass-0.log.mbtree"):
        if os.path.exists(f):
            os.remove(f)

    if os.path.exists(temp_out):
        os.remove(temp_out)


def compress_audio(inp: str, out: str, target_mib: int, level: str, fmt: dict, saturation: float, info: dict):
    duration = float(info["format"].get("duration", 180))
    target_kbps = max(32, int(target_mib * 1024 * 8 / max(duration, 1)))

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

    sat_filter = f"eq=saturation={saturation/100:.2f}" if saturation != 100 else None

    while True:
        vf_parts = [f"scale=iw*{scale:.4f}:ih*{scale:.4f}"]
        if sat_filter:
            vf_parts.append(sat_filter)
        vf = ",".join(vf_parts)

        tmp = None

        if name in ("PNG/JPEG", "PNG"):
            ext = ".jpg" if (q < 70 or target_bytes < 500_000) else ".png"
            tmp = (out if out.endswith(ext) else out.rsplit(".", 1)[0] + ext)
            if ext == ".png":
                cmd = ["ffmpeg", "-i", inp, "-vf", vf, "-c:v", "png", "-y", tmp]
            else:
                cmd = ["ffmpeg", "-i", inp, "-vf", vf, "-c:v", "mjpeg",
                       "-q:v", str(max(2, 15 - q // 6)), "-y", tmp]
        elif name == "WebP":
            cmd = ["ffmpeg", "-i", inp, "-vf", vf, "-c:v", "libwebp",
                   "-quality", str(q), "-y", out]
        elif name == "AVIF":
            cmd = ["ffmpeg", "-i", inp, "-vf", vf, "-c:v", "libaom-av1",
                   "-still-picture", "1", "-crf", str(50 - q // 2), "-y", out]
        else:
            cmd = ["ffmpeg", "-i", inp, "-vf", vf, "-c:v", "mjpeg", "-q:v", "6", "-y", out]

        subprocess.run(cmd, check=True)

        check_path = tmp if tmp else out
        current = Path(check_path).stat().st_size

        if current <= target_bytes * 1.1 or scale < 0.45:
            if tmp and tmp != out:
                shutil.move(tmp, out)
            break

        new_q = max(25, q - 18)
        if new_q <= 30 and q > 30:
            console.print("[yellow]Quality is very low — result may look degraded[/yellow]")

        q = new_q
        scale *= 0.78


# ──────────────────────────────────────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────────────────────────────────────

def compress_one(config: dict) -> dict:
    """Run a single compression job. Returns the (possibly updated) config."""

    remembered_folder = config.get("output_folder")

    # ── Input file loop ──────────────────────────────────────────────────────
    while True:
        inp_raw = questionary.path(
            "Input file (press Enter to change output folder)",
            default=""
        ).ask().strip().strip('"').strip("'")

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

    output_folder = Path(remembered_folder) if remembered_folder else DEFAULT_OUTPUT_FOLDER
    output_folder.mkdir(parents=True, exist_ok=True)
    console.print(f"→ Using output folder: [bold]{output_folder}[/]")

    info = get_media_info(str(input_path))
    kind = detect_type(info)
    console.print(f"→ Detected: [bold]{kind.upper()}[/]")

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
        return config

    if "Custom" in choice:
        target_mib = IntPrompt.ask("Custom size (MiB)", default=10)
    else:
        match = re.search(r'\d+', choice)
        target_mib = int(match.group(0)) if match else 10

    console.print(f"→ Target: [bold]{target_mib} MiB[/]")

    fmt_choices = [f"{f['name']}  •  {f['group']}" for f in FORMATS]
    fmt_str = questionary.select("Output format", choices=fmt_choices).ask()
    if fmt_str is None:
        return config
    fmt_name = fmt_str.split("  •  ")[0]
    fmt = next(f for f in FORMATS if f["name"] == fmt_name)

    level = questionary.select(
        "Compression level (speed ↔ quality)",
        choices=COMPRESSION_LEVELS
    ).ask()
    if level is None:
        return config

    two_pass_raw = questionary.text(
        f"2-pass encoding? (Y/n) [default: {'Y' if config.get('two_pass') else 'N'}]",
        default="y" if config.get("two_pass") else "n"
    ).ask().strip().lower()

    use_2pass = (two_pass_raw != "n")
    config["two_pass"] = use_2pass
    console.print(f"→ 2-pass: [bold]{'ON' if use_2pass else 'OFF'}[/]")

    gpu_raw = questionary.text(
        f"GPU encoding? (y/N) [default: {'Y' if config.get('gpu') else 'N'}]",
        default="y" if config.get("gpu") else "n"
    ).ask().strip().lower()

    nvenc_available = detect_nvenc()

    if gpu_raw == "y" and not nvenc_available:
        console.print("[yellow]NVENC not available → falling back to CPU[/yellow]")
        use_gpu = False
    else:
        use_gpu = (gpu_raw == "y")

    config["gpu"] = use_gpu

    if use_gpu and use_2pass:
        console.print("[yellow]GPU encoding does not support true 2-pass → disabling 2-pass[/yellow]")
        use_2pass = False
        config["two_pass"] = False
        console.print(f"→ 2-pass: [bold]OFF[/]")

    console.print(f"→ GPU: [bold]{'ON' if use_gpu else 'OFF'}[/]")

    scene_raw = questionary.text(
        f"Scene complexity detection? (Y/n) [default: {'Y' if config.get('scene_detect') else 'N'}]",
        default="y" if config.get("scene_detect") else "n"
    ).ask().strip().lower()

    use_scene = (scene_raw != "n")
    config["scene_detect"] = use_scene
    console.print(f"→ Scene complexity detection: [bold]{'ON' if use_scene else 'OFF'}[/]")

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

    # Save all config changes in one go
    save_config(config)

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

    console.print("[bold green]Compressing...[/bold green]")

    try:
        if kind in ("video", "animation"):
            compress_video_animation(
                str(input_path), str(out), target_mib, level,
                fmt, info, saturation, use_2pass, use_gpu, use_scene
            )
        elif kind == "audio":
            compress_audio(str(input_path), str(out), target_mib, level, fmt, saturation, info)
        elif kind == "image":
            compress_image(str(input_path), str(out), target_mib, level, fmt, saturation)
        else:
            console.print("[yellow]Unsupported type — copying[/yellow]")
            shutil.copy(input_path, out)
    except Exception as e:
        console.print(f"[bold red]Failed:[/] {e}")
        return config

    if out.is_file():
        size_mb = out.stat().st_size / 1_048_576
        console.print(f"\n[bold green]Done![/]   Size: [bold]{size_mb:.2f} MiB[/]")
        console.print(f"   → [bold]{out}[/bold]")

    return config


def main():
    check_ffmpeg()

    console.print(Panel.fit(
        "[bold cyan]OFFLINE MEDIA COMPRESSOR[/]\n"
        "Smart FFmpeg compressor — target size + saturation control",
        border_style="cyan"
    ))

    config = load_config()
    config.setdefault("two_pass", True)
    config.setdefault("gpu", False)
    config.setdefault("scene_detect", True)
    save_config(config)

    while True:
        config = compress_one(config)

        console.print()
        again = questionary.text(
            "Compress another file? (Y/n)",
            default="y"
        ).ask()

        if again is None or again.strip().lower() == "n":
            console.print("[dim]Goodbye![/dim]")
            break

        console.print()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        console.print("\n[yellow]Cancelled[/yellow]")
    except Exception as e:
        console.print(f"\n[bold red]Unexpected error:[/] {e}")
