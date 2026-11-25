# Media Catcher
 
A browser extension plus a small local app that downloads video and audio (HLS, DASH, direct files,
and anything yt-dlp supports) while keeping the user's own logged-in session.
 
```
extension/   Browser extension (Manifest V3): detects media requests and sends them to the local app
local_app/   Local app: server.py (FastAPI + yt-dlp) and app.py (tray icon, settings, automatic updates)
installer/   Windows installer build (build.bat) - see installer/README.md
tools/       package_extension.py builds the store zips (Edge, Firefox)
RELEASE.md   How to publish the installer so the extension can download it
PUBLISHING.md  How to publish the extension in the free stores
PRIVACY.md   Privacy policy (the stores ask for its URL)
```
 
## For users
1. Install the extension. A welcome page opens, downloads the helper app and detects it automatically.
2. Open a page with a video, play it for a few seconds, click the extension icon and press **Download**.
3. Finished downloads show a **Show in folder** link, and the tray icon shows a notification.
## Settings
Right-click the tray icon (near the clock) -> **Settings**:
- **Change download folder...** (default: `Downloads\MediaCatcher`)
- **Default quality**: what the quality drop-down starts with in the extension. Changing it in the popup
  affects that download only.
- **Notify when a download finishes**
They are saved in `%LOCALAPPDATA%\MediaCatcher\settings.json`. **Advanced** has the extension install link
and the log file.
 
## Security
The local app listens on `127.0.0.1:8765` only, and:
- accepts requests only from browser extensions: pages on the web are refused (CORS plus an `Origin` check),
- refuses any request whose `Host` header is not localhost (blocks DNS-rebinding attacks),
- requires the extension's `Origin` for every request that changes something (download, cancel, show in folder),
- only downloads `http` and `https` links (never `file://`).
Optional hardening: after the stores assign your extension its id, list the Chromium ids in
`CHROMIUM_EXTENSION_IDS` in `local_app/server.py` so no other extension can use the app. Firefox gives every
install a random id, so it cannot be pinned (see PUBLISHING.md).
 
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
 
## Publish
Installer: [RELEASE.md](RELEASE.md). Extension: [PUBLISHING.md](PUBLISHING.md).
 
> DRM-protected content is not supported. Users are responsible for the rights to what they download.
 
## License
This project is licensed under the **GNU General Public License v3.0 (GPLv3)** — see the [LICENSE](LICENSE) file for details.
Third-party tools bundled or invoked by the helper app (`yt-dlp`, `FFmpeg`, `Deno`) remain subject to their respective licenses.