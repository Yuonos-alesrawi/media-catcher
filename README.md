# Media Catcher

A browser extension plus a small local app that downloads video and audio (HLS, DASH, direct files,
and anything yt-dlp supports) while keeping the user's own logged-in session.

```
extension/   Browser extension (Manifest V3): detects media requests and sends them to the local app
local_app/   Local app: server.py (FastAPI + yt-dlp) and app.py (tray icon + automatic updates)
installer/   Windows installer build (build.bat) - see installer/README.md
RELEASE.md   How to publish the installer so the extension can download it
```

## For users
1. Install the extension. A welcome page opens, downloads the helper app and detects it automatically.
2. Open a page with a video, play it for a few seconds, click the extension icon and press **Download**.

## For developers (no installer)
```
cd local_app
pip install -r requirements.txt
python app.py --no-tray        # or: uvicorn server:app --host 127.0.0.1 --port 8765
```
Put `ffmpeg` and `deno` in `local_app/bin/` or on your PATH. Then in the browser:
`chrome://extensions` -> Developer mode -> Load unpacked -> the `extension` folder.

Health check: <http://127.0.0.1:8765/health>

## Build the Windows installer
See [installer/README.md](installer/README.md).

> DRM-protected content is not supported. Users are responsible for the rights to what they download.
