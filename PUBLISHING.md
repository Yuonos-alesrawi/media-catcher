# Publishing the extension (free stores)
 
| Store | Cost | Zip to upload |
|---|---|---|
| **Microsoft Edge Add-ons** | free developer registration | `media-catcher-chromium-<version>.zip` |
| **Firefox Add-ons (AMO)** | free | `media-catcher-firefox-<version>.zip` |
| Opera Add-ons (optional) | free | the chromium zip |
| Chrome Web Store | one-time registration fee | not covered here |
 
Brave and Vivaldi are Chromium browsers: users can install your Chromium zip manually (Load unpacked).
Fees and policies change, so check each store's current page before you start.
 
## 1. Before you submit
1. Publish the installer and put its link in `extension/config.js` (see `RELEASE.md`).
2. Put `PRIVACY.md` in your GitHub repository (fill in the date and contact). The store listing needs its URL.
3. Take 2-3 screenshots (1280x800 is accepted everywhere): the popup with a detected video, and the welcome page.
4. Raise `version` in `extension/manifest.json` for every upload.
5. Build both zips (the script refuses to build while placeholders are still in the files):
```
python tools/package_extension.py --gecko-id media-catcher@your-name
```
   `--gecko-id` is your permanent Firefox add-on id. Choose it once, never change it.
 
## 2. Microsoft Edge Add-ons
1. Register at <https://partner.microsoft.com/dashboard/microsoftedge> with a Microsoft account (individual developer).
2. **Create new extension** and upload the chromium zip.
3. Fill in: category (Productivity), description, screenshots, the privacy policy URL, and the support link.
4. Submit. Review usually takes a few days. Updates: upload a new zip with a higher version.
## 3. Firefox Add-ons (AMO)
1. Sign in at <https://addons.mozilla.org/developers/> with a Firefox account.
2. **Submit a New Add-on** and choose:
   - **On this site** to be listed in the store (public listing), or
   - **On your own** to get a signed `.xpi` you host yourself (for example on your GitHub release). Also free.
3. Upload the firefox zip. The add-on declares that it collects no data (`data_collection_permissions: none`).
4. Add reviewer notes (see below), then submit.
5. After install, Firefox may ask the user to allow access to all sites. The extension needs it to see media requests.
## 3b. Opera Add-ons (optional)
Opera runs on Chromium, so the same chromium zip is used. Register at <https://addons.opera.com/developer/>, upload the zip
and fill in the listing as for Edge. Read Opera's own pages before you submit, because their rules differ from the other stores:
- Publishing guidelines: <https://help.opera.com/en/extensions/publishing-guidelines/>
- Acceptance criteria: <https://help.opera.com/en/extensions/acceptance-criteria/>
## 4. Listing text (starting point)
**Summary** (keep under 132 characters):
> Detects videos and audio on the page and downloads them with a small helper app on your computer.
 
**Description:**
> Media Catcher finds the video and audio files that a page loads, shows them with their quality, and sends
> the one you choose to a small helper app that runs on your own computer. The download uses your own
> logged-in session, so course platforms and member areas work too.
>
> - Pick the quality, or download audio only (MP3)
> - Progress bar with speed and time left
> - Works with HLS, DASH and direct files, and with every site that yt-dlp supports
>
> **Requires a free helper app for Windows** (installer link inside the extension). The source code is public
> at <your GitHub URL>. Nothing is collected or sent to any server. DRM-protected videos are not supported.
> You are responsible for having the right to download the content.
 
**Single purpose:** "Detect video and audio files on the current page and send them to the user's local download app."
 
**Permission justifications:**
- `webRequest` + all sites: to detect media requests on the pages the user visits. Nothing is modified or blocked.
- `tabs`: to read the URL and title of the active tab.
- `storage`: to keep the list of downloads and the chosen quality.
**Notes for reviewers:**
> The extension contains no remote code. It sends the detected media URL and request headers only to a helper
> application on the user's own computer (127.0.0.1:8765). The helper app is separate software published as open
> source at <your GitHub URL>; the extension links to its installer on the welcome page. Test: install the helper
> app, open any page with a video, play it, and open the popup.
 
## 5. Things that can slow a review
- A listing that promotes downloading copyrighted content or specific streaming services. Keep the text neutral.
- A missing privacy policy URL, or permissions that are not explained. Use the text above.
- If a store rejects an extension that needs a helper app, distribute it yourself: attach the chromium zip to your
  GitHub release (Load unpacked) and use AMO's "On your own" option for Firefox.
## 6. Updating
Change the version, rebuild with `tools/package_extension.py`, and upload the new zip to each store.
The installer link and `minAppVersion` in `config.js` only need changing when the helper app changes.
 
## 7. After the stores give you the extension id (optional hardening)
Edge, Chrome and Opera assign your published extension a permanent id (a 32-letter string, visible in the
store URL and in `edge://extensions`). Put these ids in `CHROMIUM_EXTENSION_IDS` in `local_app/server.py`:
```python
CHROMIUM_EXTENSION_IDS = ["abcdefghijklmnopabcdefghijklmnop"]  # the ids of your published extension
```
Then the app refuses every other Chromium extension. Leave the list empty while you test with Load unpacked
(an unpacked extension gets a different, random id). **Firefox cannot be pinned**: it gives each install a random
`moz-extension://` id, so Firefox requests are always accepted (they are still checked for the extension scheme,
the `Host` header and the `Origin` header). Changing the list means releasing a new installer.
 
Order of releases when the helper app changes: publish the new installer first, then raise `minAppVersion`
in `config.js` and update the extension in the stores.
 