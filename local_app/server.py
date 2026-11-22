"""Local app: receives the URL + headers from the extension and downloads it with yt-dlp.

For end users it is started through app.py (tray icon) by the installer.
For development:  pip install fastapi uvicorn "yt-dlp[default]"
                  uvicorn server:app --host 127.0.0.1 --port 8765
It looks for ffmpeg and deno next to this file, then in the bin folder, then in PATH.
"""
import importlib.util
import os
import queue
import re
import shutil
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Optional

import yt_dlp
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

APP_VERSION = "0.4.2"  # the extension compares this with minAppVersion in extension/config.js

BASE_DIR = (
    Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
)
DOWNLOAD_DIR = Path.home() / "Downloads" / "MediaCatcher"
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)


# The bin folder (placed by the installer) holds ffmpeg and deno: add it to PATH so yt-dlp finds them
BIN_DIRS = [BASE_DIR / "bin", BASE_DIR.parent / "bin"]
for _d in BIN_DIRS:
    if _d.is_dir():
        os.environ["PATH"] = str(_d) + os.pathsep + os.environ.get("PATH", "")


def find_ffmpeg_dir() -> Optional[str]:
    for d in (BASE_DIR, *BIN_DIRS):
        for name in ("ffmpeg.exe", "ffmpeg"):
            if (d / name).exists():
                return str(d)
    return None


FFMPEG_DIR = find_ffmpeg_dir()
HAS_FFMPEG = bool(FFMPEG_DIR or shutil.which("ffmpeg"))
# YouTube needs an external JavaScript runtime (Deno is enabled by default in yt-dlp), otherwise it fails with error 403
HAS_DENO = bool(shutil.which("deno"))
# Without the crypto library yt-dlp falls back to ffmpeg for encrypted HLS (AES-128), and no progress is reported
HAS_CRYPTO = any(importlib.util.find_spec(m) for m in ("Cryptodome", "Crypto"))

QUALITIES = {"best", "2160", "1440", "1080", "720", "480", "360", "240", "audio"}


def format_for(quality: str) -> str:
    if quality == "audio":
        return "ba/b"
    # Without ffmpeg nothing can be merged: take a single ready-made file
    return "bv*+ba/b" if HAS_FFMPEG else "b"


def sort_for(quality: str) -> list:
    """Format sort order. res = the smaller dimension (width or height), so the cap also works for vertical video.
    h264 + m4a plays almost everywhere, unlike AV1 + Opus."""
    if quality not in QUALITIES:
        quality = "best"
    fields = []
    if quality.isdigit():
        fields.append(f"res:{quality}")  # best quality that does not exceed this number
    elif quality == "best":
        fields.append("res")
    if quality != "audio":
        fields.append("vcodec:h264")
    fields.append("ext:mp4:m4a")
    return fields

app = FastAPI()
# Only browser-extension origins are allowed, so web pages cannot talk to the app
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^(chrome|moz)-extension://.*$",
    allow_methods=["*"],
    allow_headers=["*"],
)

jobs: dict = {}
tasks: "queue.Queue" = queue.Queue()
# Cleared while yt-dlp is being updated, so no job starts while files are being replaced
accepting = threading.Event()
accepting.set()

class Cancelled(Exception):
    pass


class DownloadReq(BaseModel):
    url: str
    headers: dict = {}
    title: Optional[str] = ""  # empty = use the video title that yt-dlp extracts
    page_url: Optional[str] = ""
    quality: Optional[str] = "best"  # best | 2160 | 1080 | 720 | 480 | 360 | 240 | audio


ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def clean_error(e: Exception) -> str:
    return ANSI_RE.sub("", str(e)).strip()[:300]


def safe_name(s: Optional[str]) -> str:
    return re.sub(r'[\\/:*?"<>|%\n\r]', "_", s or "").strip()[:100] or "video"


def unique_path(path: Path) -> Path:
    """Never overwrite an existing file: Title.mp4, then Title (2).mp4"""
    if not path.exists():
        return path
    for i in range(2, 1000):
        cand = path.with_name(f"{path.stem} ({i}){path.suffix}")
        if not cand.exists():
            return cand
    return path


def new_job() -> dict:
    return {
        "status": "queued", "percent": None, "speed": None, "eta": None,
        "streams_done": 0, "no_audio": False, "cancel": False, "file": None, "error": None, "started_at": None, "height": None,
    }


def update_progress(job: dict, d: dict) -> None:
    """Computes the overall percentage. Video and audio may be two separate files, so their stages are combined."""
    if job.get("cancel"):
        raise Cancelled()
    if d.get("status") == "finished":
        job["streams_done"] += 1
        return
    if d.get("status") != "downloading":
        return

    n_streams = max(1, len((d.get("info_dict") or {}).get("requested_formats") or []))
    total = d.get("total_bytes") or d.get("total_bytes_estimate")
    if total:
        frac = (d.get("downloaded_bytes") or 0) / total
    elif d.get("fragment_count"):  # HLS/DASH: no total size, use the fragment count
        frac = (d.get("fragment_index") or 0) / d["fragment_count"]
    else:
        frac = None

    job["status"] = "downloading"
    job["speed"] = d.get("speed")
    job["eta"] = d.get("eta")
    if frac is not None:
        pct = (job["streams_done"] + min(frac, 1.0)) / n_streams * 100
        job["percent"] = round(min(max(pct, job["percent"] or 0), 99), 1)


def run_job(job_id: str, req: DownloadReq) -> None:
    job = jobs[job_id]
    if job["cancel"]:  # cancelled while it was still waiting
        job["status"] = "cancelled"
        return
    job["status"] = "downloading"  # work has really started (before the first progress update)
    job["started_at"] = time.time()

    def pp_hook(d):
        if d.get("status") == "started":  # merge stage, after the download has finished
            job.update(status="processing", percent=99, speed=None, eta=None)

    name = safe_name(req.title) if req.title else "%(title)s"
    q = req.quality if req.quality in QUALITIES else "best"
    if q != "best":  # a different name per quality, so yt-dlp never skips the file as "already downloaded"
        name += f" [{q}p]" if q.isdigit() else f" [{q}]"
    # Every job works in its own temp folder. When extracting audio, yt-dlp deletes the original file it
    # downloaded - and if that file were a video downloaded earlier under the same name, it would be deleted!
    # Isolating each job prevents this completely.
    work_dir = DOWNLOAD_DIR / ".tmp" / job_id
    work_dir.mkdir(parents=True, exist_ok=True)
    opts = {
        "outtmpl": f"{name}.%(ext)s",
        "paths": {"home": str(work_dir)},
        "http_headers": req.headers,
        # Without ffmpeg audio and video cannot be merged, so take the best ready-made file that has both
        "format": format_for(req.quality or "best"),
        "merge_output_format": "mp4",
        # Prefer mp4 + m4a so both picture and sound work in every player
        "format_sort": sort_for(req.quality or "best"),
        "hls_prefer_native": True,           # download HLS natively so progress is reported
        "concurrent_fragment_downloads": 4,  # four fragments in parallel = faster
        "progress_hooks": [lambda d: update_progress(job, d)],
        "postprocessor_hooks": [pp_hook],
        "noplaylist": True,
        "quiet": True,
    }
    if FFMPEG_DIR:
        opts["ffmpeg_location"] = FFMPEG_DIR
    if req.quality == "audio" and HAS_FFMPEG:
        opts["postprocessors"] = [
            {"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}
        ]

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(req.url, download=True)
        files = (info or {}).get("requested_downloads") or []
        first = files[0] if files else {}

        src = Path(first["filepath"]) if first.get("filepath") else None
        if not (src and src.exists()):  # fallback: take the largest file in the temp folder
            cands = [f for f in work_dir.iterdir() if f.is_file() and f.suffix not in (".part", ".ytdl")]
            src = max(cands, key=lambda f: f.stat().st_size) if cands else None
        if src is None:
            raise RuntimeError("yt-dlp did not produce any file")
        dst = unique_path(DOWNLOAD_DIR / src.name)  # never overwrite an existing file
        shutil.move(str(src), str(dst))

        job["file"] = dst.name
        sides = [v for v in (first.get("width"), first.get("height")) if v]
        job["height"] = min(sides) if sides else None
        job["no_audio"] = req.quality != "audio" and first.get("acodec") in (None, "none")
        print(f"[{job_id}] format={first.get('format_id')} {job['height']}p "
              f"v={first.get('vcodec')} a={first.get('acodec')} -> {job['file']}")
        job.update(status="done", percent=100, speed=None, eta=None)
    except Exception as e:  # noqa: BLE001
        if job["cancel"]:
            job["status"] = "cancelled"
        else:
            job.update(status="error", error=clean_error(e))
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
        try:
            (DOWNLOAD_DIR / ".tmp").rmdir()  # removed if empty
        except OSError:
            pass


def worker():
    while True:
        job_id, req = tasks.get()
        accepting.wait()
        run_job(job_id, req)
        tasks.task_done()


threading.Thread(target=worker, daemon=True).start()


@app.get("/health")
def health():
    return {"ok": True, "version": APP_VERSION, "ffmpeg": HAS_FFMPEG, "deno": HAS_DENO, "crypto": HAS_CRYPTO, "ytdlp": yt_dlp.version.__version__}


@app.post("/download")
def download(req: DownloadReq):
    job_id = uuid.uuid4().hex[:8]
    jobs[job_id] = new_job()
    tasks.put((job_id, req))
    return {"id": job_id}


@app.get("/jobs/{job_id}")
def job(job_id: str):
    return jobs.get(job_id, {"status": "unknown"})


@app.delete("/jobs/{job_id}")
def remove_job(job_id: str):
    """Finished job: removed from memory. Running or waiting job: cancelled."""
    j = jobs.get(job_id)
    if j is None:
        return {"ok": True}
    if j["status"] in ("done", "error", "cancelled"):
        jobs.pop(job_id, None)
    else:
        j["cancel"] = True
    return {"ok": True}


def active_jobs() -> int:
    """Number of jobs that have not finished yet (waiting or running)."""
    return sum(1 for j in jobs.values() if j["status"] in ("queued", "downloading", "processing"))
