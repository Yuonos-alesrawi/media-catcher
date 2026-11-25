// Extension settings. Edit this file only when publishing.
const CONFIG = {
  // Direct link to the installer. With GitHub Releases the link never changes, because it always
  // points at the latest release - as long as the uploaded file has no version in its name:
  // MediaCatcher-Setup.exe  (build.bat creates a copy with this name inside dist).
  installerUrl: "https://github.com/Yuonos-alesrawi/media-catcher/releases/latest/download/MediaCatcher-Setup.exe",

  // Oldest app version this extension works with. If the user's app is older, they are asked to update it.
  minAppVersion: "0.5.0",

  // Address of the local app
  api: "http://127.0.0.1:8765",
};
