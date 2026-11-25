"""
Media Catcher - Browser extension and local helper app for downloading media
Copyright (C) 2026 Yuonos-alesrawi

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program. If not, see <https://www.gnu.org/licenses/>.
"""

"""Local app: receives the URL + headers from the extension and downloads it with yt-dlp.

For end users it is started through app.py (tray icon) by the installer.
For development:  pip install fastapi uvicorn "yt-dlp[default]"
                  uvicorn server:app --host 127.0.0.1 --port 8765
It looks for ffmpeg and deno next to this file, then in the bin folder, then in PATH.
"""
import importlib.util
import json
import os
import hashlib
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse, urlsplit

import sitefilter
import yt_dlp
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

APP_VERSION = "0.6.0"  # the extension compares this with minAppVersion in extension/config.js

BASE_DIR = (
    Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
)

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

# ---------------------------------------------------------------- settings (download folder, default quality, notifications)
DATA_DIR = Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".media-catcher") / "MediaCatcher"
SETTINGS_FILE = DATA_DIR / "settings.json"
DEFAULT_DOWNLOAD_DIR = Path.home() / "Downloads" / "MediaCatcher"
_settings_lock = threading.Lock()
# Optional lists the user can edit (one domain per line): blocked_sites.txt are always refused,
# allowed_sites.txt are trusted (they skip the keyword and unsafe-link checks).
BLOCKED_FILE = DATA_DIR / "blocked_sites.txt"
ALLOWED_FILE = DATA_DIR / "allowed_sites.txt"
RESUME_KEEP_DAYS = 7  # unfinished downloads older than this are deleted at startup


def _read_settings() -> dict:
    s = {"download_dir": str(DEFAULT_DOWNLOAD_DIR), "default_quality": "best", "notify": True}
    try:
        data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return s
    if isinstance(data.get("download_dir"), str) and data["download_dir"].strip():
        s["download_dir"] = data["download_dir"].strip()
    if data.get("default_quality") in QUALITIES:
        s["default_quality"] = data["default_quality"]
    if isinstance(data.get("notify"), bool):
        s["notify"] = data["notify"]
    return s


def _ensure_writable_dir(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".write-test"
        probe.write_text("ok")
        probe.unlink()
        return True
    except OSError:
        return False


_settings = _read_settings()
DOWNLOAD_DIR = Path(_settings["download_dir"])
if not _ensure_writable_dir(DOWNLOAD_DIR):  # the saved folder vanished or is not writable: use the default
    DOWNLOAD_DIR = DEFAULT_DOWNLOAD_DIR
    _settings["download_dir"] = str(DOWNLOAD_DIR)
    _ensure_writable_dir(DOWNLOAD_DIR)


def get_settings() -> dict:
    with _settings_lock:
        return dict(_settings)


def set_settings(**changes) -> dict:
    """Validates and saves settings. Unknown keys are ignored. Raises ValueError for a bad value."""
    global DOWNLOAD_DIR
    with _settings_lock:
        new = dict(_settings)
        if "download_dir" in changes:
            p = Path(str(changes["download_dir"]).strip())
            if not p.is_absolute():
                raise ValueError("The download folder must be a full path.")
            if not _ensure_writable_dir(p):
                raise ValueError("Cannot write to that folder.")
            new["download_dir"] = str(p)
        if "default_quality" in changes:
            if changes["default_quality"] not in QUALITIES:
                raise ValueError("Unknown quality.")
            new["default_quality"] = changes["default_quality"]
        if "notify" in changes:
            new["notify"] = bool(changes["notify"])
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            SETTINGS_FILE.write_text(json.dumps(new, indent=2), encoding="utf-8")
        except OSError:
            pass  # keep working with the in-memory settings
        _settings.update(new)
        DOWNLOAD_DIR = Path(new["download_dir"])
        return dict(new)



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

# --- Who may talk to this app -------------------------------------------------------------------
# Only the browser extension: web pages are refused, and so are requests whose Host header is not localhost
# (that is what a DNS-rebinding attack looks like).
ALLOWED_HOSTS = {"127.0.0.1", "localhost", "[::1]"}
# After the stores give your extension its id (Edge / Chrome / Opera), list the ids here to accept only them.
# Empty = any Chromium extension. Firefox cannot be pinned: it gives every install a random moz-extension id.
CHROMIUM_EXTENSION_IDS: list = []


def origin_allowed(origin: str) -> bool:
    if origin.startswith("moz-extension://"):
        return True
    if origin.startswith("chrome-extension://"):
        return not CHROMIUM_EXTENSION_IDS or origin[len("chrome-extension://"):].rstrip("/") in CHROMIUM_EXTENSION_IDS
    return False


def check_request(method: str, host: Optional[str], origin: Optional[str]) -> Optional[str]:
    """Returns the reason to refuse a request, or None when it may go on."""
    h = (host or "").strip().lower()
    name = h[:h.rindex(":")] if ":" in h and not h.endswith("]") else h  # drop the port
    if name not in ALLOWED_HOSTS:
        return "Invalid Host header"
    if origin is None:
        # Browsers always send Origin on cross-origin POST/DELETE, so a state-changing request without it is not ours
        return None if method in ("GET", "HEAD") else "Missing Origin header"
    if not origin_allowed(origin):
        return "Origin not allowed"
    return None


app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^(chrome|moz)-extension://.*$",
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")  # added after CORS, so it runs first
async def guard(request, call_next):
    reason = check_request(request.method, request.headers.get("host"), request.headers.get("origin"))
    if reason:
        return JSONResponse({"detail": reason}, status_code=403)
    return await call_next(request)


jobs: dict = {}
_submit_lock = threading.Lock()
tasks: "queue.Queue" = queue.Queue()
# Cleared while yt-dlp is being updated, so no job starts while files are being replaced
accepting = threading.Event()
accepting.set()
# Functions called as fn(job_id, job) when a job finishes or fails (the tray app uses this for notifications)
job_listeners: list = []


def _emit(job_id: str, job: dict) -> None:
    for fn in list(job_listeners):
        try:
            fn(job_id, job)
        except Exception as e:  # noqa: BLE001
            print("job listener failed:", e)


class Cancelled(Exception):
    pass


class DownloadReq(BaseModel):
    url: str
    headers: dict = {}
    title: Optional[str] = ""  # empty = use the video title that yt-dlp extracts
    page_url: Optional[str] = ""
    tab_url: Optional[str] = ""  # the page the user is on; checked by the site filter
    quality: Optional[str] = "best"  # best | 2160 | 1080 | 720 | 480 | 360 | 240 | audio


ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def clean_error(e: Exception) -> str:
    return ANSI_RE.sub("", str(e)).strip()[:300]


# (substrings to look for in the lower-cased error, message shown to the user). The first match wins,
# so network problems are checked before anything else: their raw text also contains "unable to download".
_ERROR_RULES = [
    (("getaddrinfo failed", "failed to resolve", "name or service not known", "temporary failure in name resolution",
      "nodename nor servname", "network is unreachable", "no route to host"),
     "No internet connection. Check your connection and try again."),
    (("timed out", "timeout"), "The connection timed out. Check your internet connection and try again."),
    (("connection reset", "connection aborted", "remote end closed", "connection broken", "incompleteread"),
     "The connection was interrupted. Try again."),
    (("confirm you", "not a bot"), "YouTube asks you to sign in to prove you are not a bot. Try again later."),
    (("unsupported url",), "This page is not supported directly. Play the video and use one of the detected files below."),
    (("private video", "video is private"), "This video is private."),
    (("members-only", "members only", "join this channel"), "This video is for channel members only."),
    (("age-restricted", "confirm your age", "age restricted"), "This video is age-restricted. Sign in to the site first."),
    (("not available in your country", "geo restrict", "geo-restrict", "geoblock"), "This video is not available in your country."),
    (("video unavailable", "is unavailable", "has been removed", "no longer available"), "This video is unavailable."),
    (("live event will begin", "premieres in", "will begin in"), "This live stream has not started yet."),
    (("drm",), "This video is protected by DRM and cannot be downloaded."),
    (("requested format is not available",), "That quality is not available for this video. Choose another quality."),
    (("no space left", "errno 28"), "Your disk is full."),
    (("permission denied",), "The app cannot write to the download folder (permission denied)."),
]


def friendly_error(raw: str) -> str:
    """Turns a raw yt-dlp error into a short sentence a normal user can act on."""
    low = raw.lower()
    for needles, message in _ERROR_RULES:
        if any(n in low for n in needles):
            return message
    m = re.search(r"http error (\d{3})", low)
    if m:
        code = int(m.group(1))
        if code == 401:
            return "This video needs you to sign in."
        if code == 403:
            return ("The site refused the download (HTTP 403). Play the video on the page and try again; "
                    "if the site needs a login, sign in first.")
        if code in (404, 410):
            return f"The video link no longer works (HTTP {code}). Reload the page, play the video again and retry."
        if code == 429:
            return "Too many requests (HTTP 429). Wait a few minutes and try again."
        if code >= 500:
            return f"The site had a problem (HTTP {code}). Try again later."
    if "ffmpeg" in low and ("not found" in low or "not installed" in low):
        return "ffmpeg is missing, so audio and video cannot be merged."
    short = re.sub(r"^error:\s*", "", raw.strip(), flags=re.I)
    return short[:200] or "The download failed."


def describe_error(e: Exception) -> tuple:
    """Returns (friendly message, technical details)."""
    raw = ANSI_RE.sub("", str(e)).strip()
    return friendly_error(raw), raw[:600]


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


def site_check(req: "DownloadReq", resolved: Optional[dict] = None) -> Optional[str]:
    """Returns the reason to refuse this download (adult / unsafe site), or None. Lists are re-read each time,
    so edits to blocked_sites.txt / allowed_sites.txt apply immediately."""
    extra_blocked = sitefilter.load_domain_list(BLOCKED_FILE)
    allowed = sitefilter.load_domain_list(ALLOWED_FILE)
    if resolved is None:
        return sitefilter.check_download(req.url, tab_url=req.tab_url or "", page_url=req.page_url or "",
                                         headers=req.headers, extra_blocked=extra_blocked, allowed=allowed)
    # The page yt-dlp really resolved: a video on a neutral CDN may belong to an adult page
    for key in ("webpage_url", "original_url"):
        page = resolved.get(key)
        if page:
            why = sitefilter.check_download("", page_url=page, extra_blocked=extra_blocked, allowed=allowed)
            if why:
                return why
    return None


def resume_key(req: "DownloadReq", quality: str) -> str:
    """Same video + same quality = same key. Pressing Download again after a failure finds the partial files
    of the earlier attempt. For a detected file the query string is ignored (the signature changes every time);
    for a page link (no title) the whole link counts, because the video id lives in the query (watch?v=...)."""
    if req.title:
        parts = urlsplit(req.url)
        ident = f"{parts.scheme}://{parts.netloc}{parts.path}|{req.title}"
    else:
        ident = req.url
    return hashlib.sha1(f"{ident}|{quality}".encode("utf-8")).hexdigest()[:16]


def cleanup_old_partials() -> None:
    """Deletes leftovers of failed downloads that nobody resumed."""
    tmp = DOWNLOAD_DIR / ".tmp"
    try:
        for d in tmp.iterdir():
            if d.is_dir() and time.time() - d.stat().st_mtime > RESUME_KEEP_DAYS * 86400:
                shutil.rmtree(d, ignore_errors=True)
        tmp.rmdir()  # only works when empty
    except OSError:
        pass


def new_job() -> dict:
    return {
        "status": "queued", "percent": None, "speed": None, "eta": None,
        "streams_done": 0, "no_audio": False, "cancel": False, "file": None, "path": None, "error": None, "error_detail": None, "started_at": None, "height": None, "resumed": False,
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
    # Every download works in its own temp folder. When extracting audio, yt-dlp deletes the original file it
    # downloaded - and if that file were a video downloaded earlier under the same name, it would be deleted!
    # Isolating each download prevents this completely.
    # The folder is named after the video (not the job), so after a failure the partial files are still there
    # and pressing Download again continues where it stopped.
    dl_dir = DOWNLOAD_DIR  # the folder chosen when this job started
    work_dir = dl_dir / ".tmp" / resume_key(req, q)
    job["resumed"] = work_dir.is_dir() and any(work_dir.iterdir())
    keep_partial = False
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
        "continuedl": True,        # continue a half-downloaded file instead of starting over
        "nopart": False,           # keep the .part file while downloading (this is what makes resuming possible)
        "retries": 10,             # network hiccups are retried inside the same download
        "fragment_retries": 10,
        "file_access_retries": 3,
    }
    if FFMPEG_DIR:
        opts["ffmpeg_location"] = FFMPEG_DIR
    if req.quality == "audio" and HAS_FFMPEG:
        opts["postprocessors"] = [
            {"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}
        ]

    try:
        work_dir.mkdir(parents=True, exist_ok=True)
        with yt_dlp.YoutubeDL(opts) as ydl:
            # Resolve first, check the real page, and only then download
            resolved = ydl.extract_info(req.url, download=False)
            why = site_check(req, resolved or {})
            if why:
                raise sitefilter.Blocked(why)
            info = ydl.process_ie_result(resolved, download=True)
        files = (info or {}).get("requested_downloads") or []
        first = files[0] if files else {}

        src = Path(first["filepath"]) if first.get("filepath") else None
        if not (src and src.exists()):  # fallback: take the largest file in the temp folder
            cands = [f for f in work_dir.iterdir() if f.is_file() and f.suffix not in (".part", ".ytdl")]
            src = max(cands, key=lambda f: f.stat().st_size) if cands else None
        if src is None:
            raise RuntimeError("yt-dlp did not produce any file")
        dst = unique_path(dl_dir / src.name)  # never overwrite an existing file
        shutil.move(str(src), str(dst))

        job["file"] = dst.name
        job["path"] = str(dst)
        sides = [v for v in (first.get("width"), first.get("height")) if v]
        job["height"] = min(sides) if sides else None
        job["no_audio"] = req.quality != "audio" and first.get("acodec") in (None, "none")
        print(f"[{job_id}] format={first.get('format_id')} {job['height']}p "
              f"v={first.get('vcodec')} a={first.get('acodec')} -> {job['file']}")
        job.update(status="done", percent=100, speed=None, eta=None)
    except sitefilter.Blocked as e:
        job.update(status="error", error=str(e), error_detail="blocked by the site filter")
    except Exception as e:  # noqa: BLE001
        if job["cancel"]:
            job["status"] = "cancelled"
        else:
            friendly, detail = describe_error(e)
            job.update(status="error", error=friendly, error_detail=detail)
            keep_partial = True  # the next Download press for the same video continues from here
    finally:
        if not keep_partial:
            shutil.rmtree(work_dir, ignore_errors=True)
        try:
            (dl_dir / ".tmp").rmdir()  # removed if empty
        except OSError:
            pass
    if job["status"] in ("done", "error"):
        _emit(job_id, job)


def worker():
    while True:
        job_id, req = tasks.get()
        accepting.wait()
        try:
            run_job(job_id, req)
        except Exception as e:  # noqa: BLE001 - a bug in one job must never kill the worker
            print(f"[{job_id}] unexpected error:", repr(e))
            jobs[job_id].update(status="error", error="Unexpected error in the app.", error_detail=repr(e)[:600])
        tasks.task_done()


cleanup_old_partials()
threading.Thread(target=worker, daemon=True).start()


@app.get("/health")
def health():
    return {"ok": True, "version": APP_VERSION, "ffmpeg": HAS_FFMPEG, "deno": HAS_DENO, "crypto": HAS_CRYPTO, "ytdlp": yt_dlp.version.__version__}


@app.post("/download")
def download(req: DownloadReq):
    if urlparse(req.url).scheme not in ("http", "https"):  # never let yt-dlp read local files (file://)
        raise HTTPException(status_code=400, detail="Only http and https links are supported.")
    req.headers = {str(k): str(v) for k, v in (req.headers or {}).items() if "\n" not in str(v) and "\r" not in str(v)}
    why = site_check(req)  # adult / unsafe sites are refused before anything is queued
    if why:
        raise HTTPException(status_code=403, detail=why)
    q = req.quality if req.quality in QUALITIES else "best"
    key = resume_key(req, q)
    with _submit_lock:
        # The same video is already waiting or downloading: do not start a second copy writing the same files
        for jid, j in jobs.items():
            if j.get("key") == key and j["status"] in ("queued", "downloading", "processing") and not j["cancel"]:
                return {"id": jid, "existing": True}
        job_id = uuid.uuid4().hex[:8]
        jobs[job_id] = new_job()
        jobs[job_id]["key"] = key
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


def reveal_in_folder(path: Path) -> None:
    if os.name == "nt":
        subprocess.Popen(f'explorer /select,"{path}"')  # one string: explorer needs /select,"path" as a single token
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-R", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path.parent)])


@app.post("/jobs/{job_id}/reveal")
def reveal_job(job_id: str):
    """Opens the folder with the finished file selected. Only files this app produced can be shown."""
    j = jobs.get(job_id)
    if not j or j["status"] != "done" or not j.get("path"):
        raise HTTPException(status_code=404, detail="Nothing to show for this job.")
    path = Path(j["path"])
    if not path.exists():
        raise HTTPException(status_code=404, detail="The file was moved or deleted.")
    reveal_in_folder(path)
    return {"ok": True}


@app.get("/settings")
def read_settings():
    return get_settings()
