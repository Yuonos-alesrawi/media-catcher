# Publishing the installer so the extension can download it

The extension opens the installer link from its welcome page, and from the popup when the app is not running.
The link is set once in `extension/config.js`.

## Steps (GitHub Releases, free)
1. Create an account on github.com and a new **public** repository named `media-catcher`.
2. Build the installer: `installer\build.bat`. It creates two files in `dist\`:
   - `MediaCatcher-Setup-0.4.2.exe` (the name contains the version)
   - `MediaCatcher-Setup.exe` (the same file with a fixed name)
3. In the repository: **Releases -> Create a new release**. Create a tag such as `v0.4.2`,
   upload **`MediaCatcher-Setup.exe`** (the fixed name), leave the label on **None**, and click **Publish release**.
4. Open `extension/config.js` and set the link:
   ```js
   installerUrl: "https://github.com/YOUR-ACCOUNT/media-catcher/releases/latest/download/MediaCatcher-Setup.exe",
   ```
5. Reload the extension. Test it: quit the app, open the extension popup and press **Install the app**.

For every new app version: build, create a new release and upload `MediaCatcher-Setup.exe`.
The link inside the extension never changes, because it always points to the latest release.

## Notes
- If GitHub is not reachable for your users, put any **direct** link to the exe in `installerUrl`
  (your own server or any file host). Large Google Drive files usually go through a confirmation page,
  so they do not work as direct downloads.
- The installer is not code-signed, so Windows shows a SmartScreen warning. The welcome page explains
  "More info -> Run anyway" to the user.
- When you submit the extension to the Chrome Web Store, it is safer to link to a description page
  (for example the release page) instead of directly to an exe, and to state clearly in the listing that
  the extension needs a helper app. Check the current store policies before publishing.
- `minAppVersion` in `config.js`: raise it only when the extension needs a new feature of the app.
  Users with an older app are then asked to update.
