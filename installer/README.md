# Building the installer
 
**Requirements (Windows 10/11):** an internet connection and [Inno Setup 6.3+](https://jrsoftware.org/isinfo.php).
Inno Setup is needed only on the machine that builds the installer, never on the users' machines.
 
```
installer\build.bat
```
 
Output in `dist\`:
- `MediaCatcher-Setup-<version>.exe`
- `MediaCatcher-Setup.exe` (the same file with a fixed name, the one to upload to a release)
Older installers are moved to `dist\old`.
 
## Caching (nothing is downloaded twice)
- The first build downloads everything and saves a ready runtime in `build\cache`
  (Python with all packages, ffmpeg, deno).
- Later builds work **offline** and finish in seconds.
- The Python runtime is rebuilt automatically only when `local_app\requirements.txt` changes.
- For a release with the newest yt-dlp and deno: `installer\build.bat -Refresh`
  (the installed app also updates yt-dlp by itself).
## What the script does
1. Downloads the embeddable Python and installs the packages from `local_app\requirements.txt` into it.
2. Downloads ffmpeg and deno into `bin\`.
3. Copies `server.py`, `app.py` and the `extension` folder.
4. Runs a smoke test (imports, ffmpeg, deno), then compiles `setup.iss`.
If Inno Setup is not found automatically: `installer\build.bat -InnoPath "C:\path\to\ISCC.exe"`,
or open `installer\setup.iss` in Inno Setup and press Ctrl+F9.
 
## What the installer does on the user's machine
- Installs into `%LOCALAPPDATA%\Programs\MediaCatcher` without administrator rights.
- Optionally starts with Windows and runs the app. The tray icon menu:
```
Open downloads folder
Start with Windows
Update yt-dlp now
Settings >   Change download folder... / Default quality / Notify when a download finishes
Advanced >   Install the browser extension / View log
Quit
```
- Shows a notification when a download finishes (or fails). The extension's job list has a **Show in folder** link.
- Settings are stored in `%LOCALAPPDATA%\MediaCatcher\settings.json`.
- Updates yt-dlp automatically once a day (pip inside the app folder), then restarts after downloads finish.
- Downloads go to `Downloads\MediaCatcher` unless you change the folder in the tray menu. Uninstalling never deletes them.
## Stopping the app
- Tray icon (it may be hidden under the `^` arrow) -> **Quit**, or
- Start menu -> **Media Catcher - stop**.
## Checking that you use the new files
- First line printed by `build.bat`: `Media Catcher build script - revision ...`
- The installer name: `dist\MediaCatcher-Setup-<version>.exe`
- After installing: <http://127.0.0.1:8765/health> shows `"version": "..."`
- The title of the tray menu: `Media Catcher v<version>`
## If the icon does not appear after installing
- Start menu -> **Media Catcher - debug console** shows any error in the window itself.
- Or open the log: `%LOCALAPPDATA%\MediaCatcher\app.log` (tray menu -> Advanced -> View log).
- The app never waits for the internet at startup. The yt-dlp update runs in the background and fails silently without a connection.
## After the extension is published
Set `EXTENSION_URL` at the top of `local_app/app.py` to the extension's store page. The tray item
**Advanced -> Install the browser extension** then opens the store instead of the local folder.
 
## Trying the build without installing
```
build\app\python\python.exe build\app\app.py --no-tray --no-update
```
Then open <http://127.0.0.1:8765/health>.
 