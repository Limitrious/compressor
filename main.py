# ratecap — compress video / audio / image to a target file size
# Uses FFmpeg + nice console GUI
#
# REQUIREMENTS:
#   pip install rich questionary
#   FFmpeg & ffprobe in PATH (https://www.gyan.dev/ffmpeg/builds/ — full build recommended)

from __future__ import annotations

# Python 3.15+ (PEP 810): these modules load on first use instead of at startup.
# On older Pythons this is just an unused list and everything imports normally,
# so the script runs everywhere (a literal `lazy import` would be a SyntaxError <3.15).
__lazy_modules__ = [
    "json", "re", "shutil", "tempfile", "time", "urllib.parse",
    "questionary",
    "rich.markup", "rich.panel", "rich.progress",
]

import functools
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import questionary
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.progress import (
    BarColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn, TimeElapsedColumn,
)

console = Console()

CONFIG_FILE = Path(__file__).with_name("compressor_config.json")
DEFAULT_OUTPUT_FOLDER = Path(__file__).with_name("compressed_output")

# ──────────────────────────────────────────────────────────────────────────────
# FORMATS — each one only appears for inputs it can actually be made from
#   kind: what the OUTPUT is (video / audio / image)
# ──────────────────────────────────────────────────────────────────────────────
FORMATS = [
    {"name": "MP4",      "ext": ".mp4",  "kind": "video", "group": "Moderate efficiency • Compatible with everything"},
    {"name": "WebM",     "ext": ".webm", "kind": "video", "group": "High efficiency • Good compatibility"},
    {"name": "AV1 MKV",  "ext": ".mkv",  "kind": "video", "group": "Ultra high efficiency (AV1) • Modern (Discord friendly)"},
    {"name": "MP3",      "ext": ".mp3",  "kind": "audio", "group": "Very poor efficiency • Universal"},
    {"name": "M4A",      "ext": ".m4a",  "kind": "audio", "group": "Moderate efficiency • Compatible with everything"},
    {"name": "OGG",      "ext": ".ogg",  "kind": "audio", "group": "High efficiency • Good compatibility"},
    {"name": "PNG/JPEG", "ext": ".png",  "kind": "image", "group": "Moderate efficiency • PNG if it fits, else JPEG"},
    {"name": "WebP",     "ext": ".webp", "kind": "image", "group": "High efficiency • Modern"},
    {"name": "AVIF",     "ext": ".avif", "kind": "image", "group": "Ultra high efficiency (AV1) • Modern browsers"},
]

COMPRESSION_LEVELS = ["fastest", "fast", "normal", "maximum"]

# name -> (video codec, audio codec, family)
VIDEO_CODECS = {
    "MP4":     ("libx264",    "aac",     "x264"),
    "WebM":    ("libvpx-vp9", "libopus", "vp9"),
    "AV1 MKV": ("libsvtav1",  "libopus", "svtav1"),
}
# minimum bits per pixel per frame we want before we start shrinking resolution
MIN_BPP = {"x264": 0.07, "nvenc": 0.09, "vp9": 0.06, "svtav1": 0.05}

# name -> (audio codec, min kbps, max kbps)
AUDIO_CODECS = {
    "MP3": ("libmp3lame", 32, 320),
    "M4A": ("aac",        32, 320),
    "OGG": ("libopus",    24, 256),
}

NULL_DEVICE = "NUL" if os.name == "nt" else "/dev/null"


class FFmpegError(RuntimeError):
    pass


# ──────────────────────────────────────────────────────────────────────────────
# SMALL HELPERS
# ──────────────────────────────────────────────────────────────────────────────

def _float(x, default=None):
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def _int(x, default=None):
    try:
        return int(x)
    except (TypeError, ValueError):
        return default


def ask(question):
    """questionary returns None on Ctrl+C — turn that into a real KeyboardInterrupt."""
    answer = question.ask()
    if answer is None:
        raise KeyboardInterrupt
    return answer


def unique_path(folder: Path, stem: str, ext: str) -> Path:
    p = folder / f"{stem}{ext}"
    n = 1
    while p.exists():
        p = folder / f"{stem}_{n}{ext}"
        n += 1
    return p


def load_config() -> dict:
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_config(data: dict) -> None:
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except OSError:
        console.print("[yellow]Warning: could not save config[/yellow]")


def check_ffmpeg() -> None:
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        console.print("[bold red]FFmpeg / ffprobe not found in PATH[/bold red]")
        console.print("Download full build → https://www.gyan.dev/ffmpeg/builds/")
        sys.exit(1)


@functools.cache
def nvenc_works() -> bool:
    """`ffmpeg -encoders` lists h264_nvenc even with no NVIDIA GPU, so actually try it."""
    try:
        r = subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error",
             "-f", "lavfi", "-i", "color=black:s=256x256:d=0.1",
             "-c:v", "h264_nvenc", "-f", "null", "-"],
            capture_output=True, timeout=30,
        )
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


# ──────────────────────────────────────────────────────────────────────────────
# PROBING
# ──────────────────────────────────────────────────────────────────────────────

def get_media_info(path: Path) -> dict:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=True,
    )
    return json.loads(r.stdout)


def _is_cover(s: dict) -> bool:
    return bool(s.get("disposition", {}).get("attached_pic"))


def video_stream(info: dict) -> dict | None:
    return next((s for s in info.get("streams", [])
                 if s.get("codec_type") == "video" and not _is_cover(s)), None)


def audio_stream(info: dict) -> dict | None:
    return next((s for s in info.get("streams", []) if s.get("codec_type") == "audio"), None)


def detect_type(info: dict) -> str:
    v, a = video_stream(info), audio_stream(info)
    if v is None:
        return "audio" if a else "unknown"      # mp3/m4a with cover art stays "audio"
    if a:
        return "video"
    fmt = info.get("format", {})
    frames = _int(v.get("nb_frames"))
    duration = _float(fmt.get("duration"), 0.0)
    name = fmt.get("format_name", "")
    if frames == 1 or "_pipe" in name or name == "image2" or (frames is None and duration < 0.2):
        return "image"
    return "video"                               # animated gif / silent clip → treated as video


def get_duration(info: dict) -> float:
    d = _float(info.get("format", {}).get("duration"))
    if not d:
        for s in info.get("streams", []):
            d = _float(s.get("duration"))
            if d:
                break
    if not d or d <= 0:
        raise RuntimeError("Could not read the duration of this file")
    return d


def get_fps(v: dict) -> float:
    for key in ("avg_frame_rate", "r_frame_rate"):
        try:
            n, d = str(v.get(key, "0/1")).split("/")
            fps = float(n) / float(d)
            if fps > 0:
                return min(fps, 120.0)
        except (ValueError, ZeroDivisionError):
            pass
    return 30.0


# ──────────────────────────────────────────────────────────────────────────────
# FFmpeg RUNNER (live progress, real error messages)
# ──────────────────────────────────────────────────────────────────────────────

class UI:
    def __init__(self, progress: Progress):
        self.p = progress
        self.t = progress.add_task("Starting", total=100)

    def stage(self, text: str) -> None:
        self.p.update(self.t, description=text, completed=0)

    def tick(self, frac: float) -> None:
        self.p.update(self.t, completed=max(0.0, min(1.0, frac)) * 100)

    def note(self, text: str) -> None:
        self.p.console.print(text)


def run_ffmpeg(args: list, ui: UI | None = None, duration: float | None = None) -> None:
    cmd = ["ffmpeg", "-hide_banner", "-nostdin", "-y", "-loglevel", "error",
           "-nostats", "-progress", "pipe:1", *map(str, args)]
    with tempfile.TemporaryFile("w+", encoding="utf-8", errors="replace") as err:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=err,
                                text=True, encoding="utf-8", errors="replace")
        try:
            for line in proc.stdout:
                if ui and duration and line.startswith("out_time_us="):
                    us = _float(line.split("=", 1)[1])
                    if us is not None:
                        ui.tick(us / 1e6 / duration)
            rc = proc.wait()
        finally:
            if proc.poll() is None:          # Ctrl+C etc. → don't leave ffmpeg running
                proc.kill()
                proc.wait()
        if rc != 0:
            err.seek(0)
            raise FFmpegError(err.read().strip()[-800:] or f"ffmpeg exited with code {rc}")


# ──────────────────────────────────────────────────────────────────────────────
# VIDEO
# ──────────────────────────────────────────────────────────────────────────────

def video_enc_args(family: str, vcodec: str, level: str, kbps: int) -> list:
    i = COMPRESSION_LEVELS.index(level)
    a = ["-c:v", vcodec, "-b:v", f"{kbps}k", "-pix_fmt", "yuv420p"]
    if family == "x264":
        a += ["-preset", ("ultrafast", "veryfast", "medium", "veryslow")[i]]
    elif family == "nvenc":
        a += ["-preset", ("p1", "p3", "p5", "p7")[i], "-rc", "vbr"]
    elif family == "vp9":
        a += ["-deadline", "good", "-cpu-used", str((5, 3, 2, 1)[i]), "-row-mt", "1"]
    else:  # svtav1
        a += ["-preset", str((12, 8, 5, 2)[i])]
    return a


def compress_video(inp: Path, dst_dir: Path, stem: str, target_mib: int, level: str, fmt: dict,
                   info: dict, saturation: float, use_2pass: bool, use_gpu: bool, ui: UI) -> Path:
    v = video_stream(info)
    has_audio = audio_stream(info) is not None
    duration = get_duration(info)
    target_bytes = int(target_mib * 1_048_576)

    # ── bitrate budget (3% kept back for container overhead) ──
    budget_kbps = target_bytes * 8 / 1000 / duration * 0.97
    audio_kbps = min(128, max(32, int(budget_kbps * 0.12))) if has_audio else 0
    video_kbps = int(budget_kbps - audio_kbps)
    if video_kbps < 30:
        raise RuntimeError(f"{target_mib} MiB is too small for {duration:.0f}s of video — pick a bigger target")
    audio_bytes = audio_kbps * 1000 / 8 * duration

    # ── codec ──
    vcodec, acodec, family = VIDEO_CODECS[fmt["name"]]
    if use_gpu and fmt["name"] == "MP4":
        vcodec, family = "h264_nvenc", "nvenc"
    two_pass = use_2pass and family != "nvenc"

    # ── resolution: shrink only as far as needed to keep enough bits per pixel ──
    w, h = _int(v.get("width"), 1920), _int(v.get("height"), 1080)
    fps = get_fps(v)
    factor = math.sqrt(video_kbps * 1000 / (w * h * fps * MIN_BPP[family]))
    factor = min(1.0, max(factor, min(1.0, 240 / min(w, h))))     # never below 240p short side, never upscale
    new_w, new_h = max(2, int(w * factor) // 2 * 2), max(2, int(h * factor) // 2 * 2)

    vf = []
    if (new_w, new_h) != (w, h):
        vf.append(f"scale={new_w}:{new_h}:flags=lanczos")
    if saturation != 100:
        vf.append(f"eq=saturation={saturation / 100:.2f}")
    vf_args = ["-vf", ",".join(vf)] if vf else []

    src = ["-i", str(inp), "-map", "0:v:0", "-map", "0:a:0?", "-sn", "-dn"]
    audio_args = ["-c:a", acodec, "-b:a", f"{audio_kbps}k", "-ac", "2"] if has_audio else []
    mux_args = ["-movflags", "+faststart"] if fmt["ext"] == ".mp4" else []

    with tempfile.TemporaryDirectory(dir=dst_dir, prefix=".tmp_compress_") as td:
        td = Path(td)
        log = str(td / "pass")
        stats_ready = False
        best = smallest = None            # (size, path)
        kbps = video_kbps
        max_tries = 4

        for attempt in range(1, max_tries + 1):
            out_try = td / f"try{attempt}{fmt['ext']}"
            tag = f"Try {attempt}/{max_tries}"

            if two_pass and (not stats_ready or family == "svtav1"):
                ui.stage(f"{tag} · pass 1/2")
                try:
                    run_ffmpeg([*src, *vf_args, *video_enc_args(family, vcodec, level, kbps),
                                "-pass", "1", "-passlogfile", log, "-an", "-f", "null", NULL_DEVICE],
                               ui, duration)
                    stats_ready = True
                except FFmpegError:
                    ui.note("[yellow]2-pass not supported by this encoder/build → using single pass[/yellow]")
                    two_pass = False

            if two_pass:
                ui.stage(f"{tag} · pass 2/2 · {kbps} kbps")
                run_ffmpeg([*src, *vf_args, *video_enc_args(family, vcodec, level, kbps),
                            "-pass", "2", "-passlogfile", log, *audio_args, *mux_args, out_try],
                           ui, duration)
            else:
                ui.stage(f"{tag} · {kbps} kbps")
                run_ffmpeg([*src, *vf_args, *video_enc_args(family, vcodec, level, kbps),
                            *audio_args, *mux_args, out_try], ui, duration)

            size = out_try.stat().st_size
            if smallest is None or size < smallest[0]:
                smallest = (size, out_try)
            if size <= target_bytes and (best is None or size > best[0]):
                best = (size, out_try)
            if target_bytes * 0.93 <= size <= target_bytes:
                break                                   # close enough, under the limit

            # proportional correction on the VIDEO part only (audio + overhead are ~fixed)
            video_bytes = max(size - audio_bytes, 1)
            kbps = int(kbps * (target_bytes * 0.975 - audio_bytes) / video_bytes)
            if kbps < 30:
                break

        chosen = best or smallest
        if best is None:
            ui.note(f"[yellow]Could not get under {target_mib} MiB "
                    f"(best: {chosen[0] / 1_048_576:.2f} MiB) — try a bigger target or lower resolution[/yellow]")
        dst = unique_path(dst_dir, stem, fmt["ext"])
        os.replace(chosen[1], dst)
        return dst


# ──────────────────────────────────────────────────────────────────────────────
# AUDIO
# ──────────────────────────────────────────────────────────────────────────────

def compress_audio(inp: Path, dst_dir: Path, stem: str, target_mib: int, level: str, fmt: dict,
                   info: dict, ui: UI) -> Path:
    duration = get_duration(info)
    target_bytes = int(target_mib * 1_048_576)
    codec, lo, hi = AUDIO_CODECS[fmt["name"]]

    kbps = int(target_bytes * 8 / 1000 / duration * 0.97)
    a = audio_stream(info)
    if a is None:
        raise RuntimeError("This file has no audio stream")
    src_kbps = _float(a.get("bit_rate"))
    if src_kbps:
        kbps = min(kbps, max(lo, int(src_kbps / 1000)))      # no point going above the source
    kbps = max(lo, min(hi, kbps))

    mux = ["-movflags", "+faststart"] if fmt["ext"] == ".m4a" else []
    with tempfile.TemporaryDirectory(dir=dst_dir, prefix=".tmp_compress_") as td:
        out_try = Path(td) / f"out{fmt['ext']}"
        for attempt in range(1, 4):
            ui.stage(f"Encoding · {kbps} kbps")
            run_ffmpeg(["-i", str(inp), "-map", "0:a:0", "-vn", "-sn", "-c:a", codec,
                        "-b:a", f"{kbps}k", *mux, out_try], ui, duration)
            size = out_try.stat().st_size
            if size <= target_bytes:
                break
            new_kbps = max(lo, int(kbps * target_bytes * 0.97 / size))
            if new_kbps >= kbps:                              # already at the codec minimum
                ui.note(f"[yellow]Smallest possible is {size / 1_048_576:.2f} MiB — can't reach {target_mib} MiB[/yellow]")
                break
            kbps = new_kbps
        dst = unique_path(dst_dir, stem, fmt["ext"])
        os.replace(out_try, dst)
        return dst


# ──────────────────────────────────────────────────────────────────────────────
# IMAGE
# ──────────────────────────────────────────────────────────────────────────────

def compress_image(inp: Path, dst_dir: Path, stem: str, target_mib: int, level: str, fmt: dict,
                   info: dict, saturation: float, ui: UI) -> Path:
    target_bytes = int(target_mib * 1_048_576)
    li = COMPRESSION_LEVELS.index(level)
    v = video_stream(info)
    w, h = _int(v.get("width"), 1920), _int(v.get("height"), 1080)
    name = fmt["name"]

    # codec settings: qualities are ordered BEST → WORST
    if name == "WebP":
        ext, qs = ".webp", list(range(100, 4, -3))
        enc = lambda q: ["-c:v", "libwebp", "-quality", str(q), "-compression_level", str((0, 2, 4, 6)[li])]
    elif name == "AVIF":
        ext, qs = ".avif", list(range(10, 64, 2))
        enc = lambda q: ["-c:v", "libaom-av1", "-still-picture", "1", "-cpu-used", str((8, 6, 4, 2)[li]),
                         "-crf", str(q), "-b:v", "0", "-pix_fmt", "yuv420p"]
    else:  # PNG/JPEG → JPEG
        ext, qs = ".jpg", list(range(2, 32))
        enc = lambda q: ["-c:v", "mjpeg", "-q:v", str(q), "-pix_fmt", "yuvj420p"]

    def encode(scale: float, codec_args: list, out: Path) -> int:
        nw, nh = max(2, int(w * scale) // 2 * 2), max(2, int(h * scale) // 2 * 2)
        vf = []
        if (nw, nh) != (w, h):
            vf.append(f"scale={nw}:{nh}:flags=lanczos")
        if saturation != 100:
            vf.append(f"eq=saturation={saturation / 100:.2f}")
        run_ffmpeg(["-i", str(inp), "-map", "0:v:0", "-frames:v", "1",
                    *(["-vf", ",".join(vf)] if vf else []), *codec_args, out])
        return out.stat().st_size

    with tempfile.TemporaryDirectory(dir=dst_dir, prefix=".tmp_compress_") as td:
        td = Path(td)
        n = 0

        def finish(path: Path, final_ext: str) -> Path:
            dst = unique_path(dst_dir, stem, final_ext)
            os.replace(path, dst)
            return dst

        if name == "PNG/JPEG":                      # lossless first — keep it if it already fits
            ui.stage("Trying lossless PNG")
            png = td / "try.png"
            if encode(1.0, ["-c:v", "png"], png) <= target_bytes:
                return finish(png, ".png")

        scale = 1.0
        for round_ in range(1, 8):
            lo_i, hi_i = 0, len(qs) - 1
            best = None
            smallest = None
            while lo_i <= hi_i:
                mid = (lo_i + hi_i) // 2
                n += 1
                ui.stage(f"Round {round_} · scale {scale:.0%} · quality step {mid + 1}/{len(qs)}")
                out_try = td / f"try{n}{ext}"
                size = encode(scale, enc(qs[mid]), out_try)
                smallest = size if smallest is None else min(smallest, size)
                if size <= target_bytes:
                    best = out_try
                    hi_i = mid - 1                  # fits → try better quality
                else:
                    lo_i = mid + 1
            if best:
                return finish(best, ext)
            scale *= max(0.3, min(0.9, math.sqrt(target_bytes / smallest) * 0.95))   # nothing fit → shrink

        raise RuntimeError(f"Could not get the image under {target_mib} MiB")


# ──────────────────────────────────────────────────────────────────────────────
# YOUTUBE DOWNLOAD (yt-dlp)
# ──────────────────────────────────────────────────────────────────────────────

YT_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be"}
VIDEO_HEIGHTS = [2160, 1440, 1080, 720, 480, 360, 240]
BIG_PLAYLIST = 50


class DownloadFailed(RuntimeError):
    pass


def parse_link(raw: str) -> dict | None:
    """Return {url, video_id, list_id} for a YouTube link, else None."""
    raw = raw.strip()
    if raw.lower().startswith(tuple(h + "/" for h in YT_HOSTS)):
        raw = "https://" + raw
    try:
        u = urlparse(raw)
        host = (u.hostname or "").lower()
    except ValueError:
        return None
    if u.scheme not in ("http", "https") or host not in YT_HOSTS:
        return None
    qs = parse_qs(u.query)
    parts = [p for p in u.path.split("/") if p]
    video_id = None
    if host == "youtu.be":
        video_id = parts[0] if parts else None
    elif parts and parts[0] == "watch":
        video_id = (qs.get("v") or [None])[0]
    elif len(parts) >= 2 and parts[0] in ("shorts", "live", "embed", "v"):
        video_id = parts[1]
    list_id = (qs.get("list") or [None])[0]
    if not video_id and not list_id:
        return None
    return {"url": raw, "video_id": video_id, "list_id": list_id}


def single_video_url(link: dict) -> str:
    """The link with the playlist part removed."""
    return f"https://www.youtube.com/watch?v={link['video_id']}"


def _ytdlp():
    try:
        import yt_dlp
        return yt_dlp
    except ImportError:
        return None


class _QuietLogger:
    """yt-dlp would print straight to the terminal and fight the progress bar; we show errors ourselves."""
    def debug(self, msg): pass
    def info(self, msg): pass
    def warning(self, msg): pass
    def error(self, msg): pass


def _ydl_base() -> dict:
    opts = {"quiet": True, "no_warnings": True, "noprogress": True, "logger": _QuietLogger()}
    runtimes = {n: {} for n in ("deno", "node", "bun") if shutil.which(n)}
    if runtimes:
        opts["js_runtimes"] = runtimes
    return opts


def _clean_err(e: Exception) -> str:
    msg = str(e).replace("ERROR: ", "").strip()
    return msg[-500:] + "\n(YouTube changes often — try: pip install -U \"yt-dlp[default]\")"


def fetch_info(url: str, *, playlist: bool = False) -> dict:
    yt = _ytdlp()
    opts = {**_ydl_base(), "skip_download": True, "noplaylist": not playlist}
    if playlist:
        opts["extract_flat"] = "in_playlist"
    try:
        with yt.YoutubeDL(opts) as ydl:
            return ydl.extract_info(url, download=False)
    except yt.utils.YoutubeDLError as e:
        raise DownloadFailed(_clean_err(e)) from None


def fmt_duration(sec) -> str:
    sec = int(sec or 0)
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _res(f: dict) -> int | None:
    w, h = f.get("width"), f.get("height")
    return min(w, h) if w and h else h      # same meaning as YouTube's "1080p" (short side)


def build_selection(plan: dict) -> dict:
    """yt-dlp format options for the chosen mode/quality."""
    if plan["audio_only"]:
        abr = plan["abr"]
        return {"format": f"bestaudio[abr<={abr}]/worstaudio/best" if abr else "bestaudio/best"}
    cap = f"res:{plan['height']}" if plan["height"] else "res"
    return {"format": "bv*+ba/b", "format_sort": [cap, "vcodec:h264", "acodec:aac"]}


def download_one(url: str, dest_dir: Path, prefix: str, plan: dict, ui: UI, label: str) -> Path:
    yt = _ytdlp()
    state = {"downloading": False}

    def on_progress(d):
        if d["status"] == "downloading":
            if not state["downloading"]:
                state["downloading"] = True
                ui.stage(f"{label} · downloading")
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            if total:
                ui.tick(d.get("downloaded_bytes", 0) / total)
        elif d["status"] == "finished":
            state["downloading"] = False

    def on_pp(d):
        if d["status"] == "started":
            ui.stage(f"{label} · processing")
            ui.tick(0.99)

    opts = {
        **_ydl_base(),
        **build_selection(plan),
        "noplaylist": True,
        "paths": {"home": str(dest_dir)},
        "outtmpl": {"default": f"{prefix}%(title).120s.%(ext)s"},
        "windowsfilenames": True,
        "progress_hooks": [on_progress],
        "postprocessor_hooks": [on_pp],
        "merge_output_format": "mkv" if plan["compress"] else "mp4",
    }
    if plan["audio_only"] and not plan["compress"]:
        opts["postprocessors"] = [{"key": "FFmpegExtractAudio", "preferredcodec": "m4a", "preferredquality": "192"}]

    try:
        with yt.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
    except yt.utils.YoutubeDLError as e:
        raise DownloadFailed(_clean_err(e)) from None
    done = (info.get("requested_downloads") or [{}])[0].get("filepath")
    if not done or not Path(done).is_file():
        raise DownloadFailed("Download finished but the file wasn't found")
    return Path(done)


def youtube_flow(link: dict) -> dict | None:
    """Ask everything about a YouTube link. Returns a plan, or None to go back to the input prompt."""
    if _ytdlp() is None:
        console.print('[red]yt-dlp is not installed →[/red] pip install -U "yt-dlp[default]"')
        return None
    if not shutil.which("deno") and not shutil.which("node") and not shutil.which("bun"):
        console.print("[dim]Tip: yt-dlp wants a JavaScript runtime (Deno recommended) for full YouTube support — "
                      "some qualities may be missing without one.[/dim]")

    url = link["url"]
    entries = None          # playlist entries, or None for a single video
    folder = None

    # ── playlist check ───────────────────────────────────────────────────────
    if link["list_id"]:
        try:
            with console.status("[bold green]Reading playlist..."):
                pl = fetch_info(url, playlist=True)
            items = [e for e in (pl.get("entries") or []) if e and e.get("id")]
        except DownloadFailed as e:
            items, pl = [], {}
            if link["video_id"]:
                console.print(f"[yellow]Couldn't read the playlist — downloading just this video.[/yellow]\n[dim]{escape(str(e))}[/dim]")
            else:
                console.print(f"[red]Couldn't read the playlist:[/red] {escape(str(e))}")
                return None

        if items:
            n = len(items)
            title = pl.get("title") or "playlist"
            kind_txt = "auto-generated mix" if link["list_id"].startswith(("RD", "UL")) else "playlist"
            console.print(f"\n[bold yellow]⚠ This link contains a whole {kind_txt}:[/] {escape(title)} — [bold]{n} videos[/]")
            console.print("[yellow]Downloading all of it can take a long time and a lot of disk space.[/yellow]")
            whole = ask(questionary.confirm("Download the WHOLE playlist?", default=False))
            if whole and n > BIG_PLAYLIST:
                whole = ask(questionary.confirm(f"That's {n} videos — are you really sure?", default=False))
            if whole:
                entries = [{"url": f"https://www.youtube.com/watch?v={e['id']}", "title": e.get("title") or e["id"]}
                           for e in items]
                yt = _ytdlp()
                folder = yt.utils.sanitize_filename(title, restricted=False)[:100].strip(" .") or "playlist"
            elif link["video_id"]:
                url = single_video_url(link)
                console.print("→ Playlist removed from the link — downloading just the video")
            else:
                console.print("[yellow]This link is a playlist only, there's no single video in it.[/yellow]")
                return None
        elif link["video_id"]:
            url = single_video_url(link)
        else:
            console.print("[yellow]That playlist looks empty.[/yellow]")
            return None

    # ── single video info ────────────────────────────────────────────────────
    heights = []
    if entries is None:
        try:
            with console.status("[bold green]Reading video info..."):
                info = fetch_info(url)
        except DownloadFailed as e:
            console.print(f"[red]Can't read that video:[/red] {escape(str(e))}")
            return None
        if info.get("is_live"):
            console.print("[yellow]Live streams aren't supported.[/yellow]")
            return None
        title = info.get("title") or "video"
        console.print(f"→ Found: [bold]{escape(title)}[/]  ({fmt_duration(info.get('duration'))})")
        entries = [{"url": url, "title": title}]
        heights = sorted({r for f in info.get("formats", []) if f.get("vcodec") not in (None, "none")
                          for r in [_res(f)] if r})

    # ── questions ────────────────────────────────────────────────────────────
    mode = ask(questionary.select("Download as", choices=[
        questionary.Choice("Video (with audio)", "video"),
        questionary.Choice("Audio only", "audio"),
    ]))
    audio_only = mode == "audio"
    height = abr = None

    if audio_only:
        abr = ask(questionary.select("Audio quality", choices=[
            questionary.Choice("Best available", None),
            questionary.Choice("Standard (up to 128 kbps)", 128),
            questionary.Choice("Small (up to 64 kbps)", 64),
        ]))
    else:
        best = max(heights) if heights else None
        caps = [h for h in VIDEO_HEIGHTS if best is None or h < best]
        best_txt = f"Best available ({best}p)" if best else "Best available"
        suffix = "" if len(entries) == 1 else "  (per video, lower if it has less)"
        height = ask(questionary.select("Video quality", choices=[
            questionary.Choice(best_txt + suffix, None),
            *[questionary.Choice(f"{h}p" + suffix, h) for h in caps],
        ]))

    compress = ask(questionary.confirm("Compress it after downloading?", default=True))
    return {"entries": entries, "folder": folder, "audio_only": audio_only,
            "height": height, "abr": abr, "compress": compress}


# ──────────────────────────────────────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────────────────────────────────────

def allowed_formats(kind: str, has_audio: bool) -> list:
    kinds = {"video"} | ({"audio"} if has_audio else set()) if kind == "video" else {kind}
    return [f for f in FORMATS if f["kind"] in kinds]


def ask_options(kind: str, has_audio: bool, config: dict) -> dict:
    size_choices = [
        questionary.Choice("1 MiB", 1),
        questionary.Choice("8 MiB", 8),
        questionary.Choice("10 MiB   ← most popular for short clips", 10),
        questionary.Choice("20 MiB", 20),
        questionary.Choice("25 MiB", 25),
        questionary.Choice("50 MiB   ← good balance", 50),
        questionary.Choice("100 MiB  ← high quality longer content", 100),
        questionary.Choice("500 MiB", 500),
        questionary.Choice("Custom...", None),
    ]
    target_mib = ask(questionary.select("Target size (MiB)", choices=size_choices))
    if target_mib is None:
        target_mib = int(ask(questionary.text(
            "Custom size (MiB)", default="10",
            validate=lambda t: (t.isdigit() and int(t) > 0) or "Enter a whole number above 0")))
    console.print(f"→ Target: [bold]{target_mib} MiB[/]")

    fmts = allowed_formats(kind, has_audio)
    fmt = ask(questionary.select(
        "Output format", choices=[questionary.Choice(f"{f['name']}  •  {f['group']}", f) for f in fmts]))
    level = ask(questionary.select("Compression level (speed ↔ quality)", choices=COMPRESSION_LEVELS))

    use_gpu = use_2pass = False
    saturation = 100.0

    if fmt["kind"] == "video":
        if fmt["name"] == "MP4" and nvenc_works():
            use_gpu = ask(questionary.confirm("GPU (NVENC) encoding?", default=bool(config.get("gpu", False))))
            config["gpu"] = use_gpu
        if use_gpu:
            console.print("[dim]GPU encoding is single-pass[/dim]")
        else:
            use_2pass = ask(questionary.confirm("2-pass encoding? (slower, more accurate size)",
                                                default=bool(config.get("two_pass", True))))
            config["two_pass"] = use_2pass
        save_config(config)
        console.print(f"→ GPU: [bold]{'ON' if use_gpu else 'OFF'}[/]   2-pass: [bold]{'ON' if use_2pass else 'OFF'}[/]")

    if fmt["kind"] in ("video", "image"):
        raw_sat = ask(questionary.text("Saturation multiplier (%) — press Enter for 100%", default="100")).strip()
        try:
            saturation = max(0.0, min(200.0, float(raw_sat)))
        except ValueError:
            console.print("[yellow]Invalid value → using 100%[/yellow]")
        console.print(f"→ Saturation: [bold]{saturation:g}%[/]")

    return {"target_mib": target_mib, "fmt": fmt, "level": level,
            "use_gpu": use_gpu, "use_2pass": use_2pass, "saturation": saturation}


def compress_one(path: Path, dest: Path, o: dict, info: dict, ui: UI) -> Path:
    fmt, stem = o["fmt"], path.stem + "_compressed"
    if fmt["kind"] == "video":
        return compress_video(path, dest, stem, o["target_mib"], o["level"], fmt, info,
                              o["saturation"], o["use_2pass"], o["use_gpu"], ui)
    if fmt["kind"] == "audio":
        return compress_audio(path, dest, stem, o["target_mib"], o["level"], fmt, info, ui)
    return compress_image(path, dest, stem, o["target_mib"], o["level"], fmt, info, o["saturation"], ui)


def main() -> None:
    check_ffmpeg()

    console.print(Panel.fit(
        "[bold cyan]RATECAP[/]\n"
        "Hit an exact target size with FFmpeg — saturation control, YouTube download\n"
        "[dim]Paste a YouTube link instead of a file to download it first[/dim]",
        border_style="cyan"
    ))

    config = load_config()
    out_folder = Path(config.get("output_folder") or DEFAULT_OUTPUT_FOLDER)
    plan = input_path = info = None

    # ── Input loop (file path or YouTube link) ───────────────────────────────
    while True:
        raw = ask(questionary.path("Input file or YouTube link (press Enter to change output folder)",
                                   default="")).strip().strip("\"'")

        if not raw:
            console.print(f"Current output folder: [bold]{escape(str(out_folder))}[/]")
            new = ask(questionary.text("New output folder path (Enter to keep current)", default="")).strip().strip("\"'")
            if new:
                p = Path(new).expanduser().resolve()
                try:
                    p.mkdir(parents=True, exist_ok=True)
                except OSError as e:
                    console.print(f"[red]Cannot use that folder:[/] {escape(str(e))}")
                else:
                    out_folder = p
                    config["output_folder"] = str(p)
                    save_config(config)
                    console.print(f"→ Output folder updated and saved: [bold]{escape(str(p))}[/]")
            else:
                console.print("[dim]No change[/dim]")
            continue

        link = parse_link(raw)
        if link:
            plan = youtube_flow(link)
            if plan is None:
                continue
            kind = "audio" if plan["audio_only"] else "video"
            break

        input_path = Path(raw).expanduser()
        if not input_path.is_file():
            console.print("[red]File not found — try again[/red]")
            continue
        try:
            info = get_media_info(input_path)
        except (subprocess.CalledProcessError, ValueError):
            console.print("[red]ffprobe can't read that file — is it really media?[/red]")
            continue
        kind = detect_type(info)
        if kind == "unknown":
            console.print("[red]No audio/video/image stream found in that file[/red]")
            continue
        break

    dest = out_folder / plan["folder"] if plan and plan["folder"] else out_folder
    dest.mkdir(parents=True, exist_ok=True)
    console.print(f"→ Using output folder: [bold]{escape(str(dest))}[/]")
    if plan is None:
        console.print(f"→ Detected: [bold]{kind.upper()}[/]")

    # ── Compression options (skipped when just downloading) ──────────────────
    opts = None
    if plan is None or plan["compress"]:
        opts = ask_options(kind, True if plan else audio_stream(info) is not None, config)
        if plan is None and input_path.stat().st_size <= opts["target_mib"] * 1_048_576:
            console.print(f"[yellow]Note: input is already under {opts['target_mib']} MiB — "
                          f"re-encoding may not make it smaller[/yellow]")

    # ── Run ──────────────────────────────────────────────────────────────────
    items = plan["entries"] if plan else [{"url": None, "title": input_path.name}]
    results, failures = [], []
    tmp_root = Path(tempfile.mkdtemp(dir=dest, prefix=".tmp_download_")) if plan and opts else None
    t0 = time.perf_counter()
    progress = Progress(SpinnerColumn("dots12"), TextColumn("[bold green]{task.description}"), BarColumn(),
                        TaskProgressColumn(), TimeElapsedColumn(), console=console, transient=True)
    try:
        with progress:
            ui = UI(progress)
            for i, item in enumerate(items, 1):
                short = escape(item["title"][:40])
                label = f"{i}/{len(items)} · {short}" if len(items) > 1 else short
                try:
                    if plan:
                        prefix = f"{i:02d} - " if len(items) > 1 else ""
                        path = download_one(item["url"], tmp_root or dest, prefix, plan, ui, label)
                        if opts is None:
                            results.append(path)
                            continue
                        file_info = get_media_info(path)
                    else:
                        path, file_info = input_path, info
                    results.append(compress_one(path, dest, opts, file_info, ui))
                    if plan:
                        path.unlink(missing_ok=True)       # keep only the compressed copy
                except (RuntimeError, OSError, ValueError, subprocess.CalledProcessError) as e:
                    failures.append(item["title"])
                    console.print(f"[bold red]Failed:[/] {escape(item['title'][:60])}\n  {escape(str(e))}")
    finally:
        if tmp_root:
            shutil.rmtree(tmp_root, ignore_errors=True)

    # ── Summary ──────────────────────────────────────────────────────────────
    elapsed = time.perf_counter() - t0
    if results:
        console.print(f"\n[bold green]Done![/]   {len(results)} file(s) in {elapsed:.0f}s")
        for r in results[:20]:
            size_mib = r.stat().st_size / 1_048_576
            extra = f"  ({size_mib / opts['target_mib']:.0%} of target)" if opts else ""
            console.print(f"   {size_mib:7.2f} MiB{extra}  → [bold]{escape(str(r))}[/bold]")
        if len(results) > 20:
            console.print(f"   [dim]... and {len(results) - 20} more[/dim]")
    if failures:
        console.print(f"[yellow]{len(failures)} item(s) failed[/yellow]")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        console.print("\n[yellow]Cancelled[/yellow]")
    except Exception as e:
        console.print(f"\n[bold red]Unexpected error:[/] {escape(str(e))}")