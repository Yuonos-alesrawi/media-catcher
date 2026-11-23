# Privacy Policy - Media Catcher

_Last updated: 11/23/2026

Media Catcher does not collect, store on a server, sell or share any personal data.

## What the extension does
- It watches the network requests of the pages you open, only to find video and audio files
  (HLS, DASH, MP4 and similar).
- For each file it finds it keeps, in your browser's temporary storage, the file's address and the request
  headers needed to download it (such as Referer and Cookie), so the download works with your own session.
- When you press **Download**, this information is sent **only to the helper app running on your own computer**
  (`http://127.0.0.1:8765`). It is never sent to the developer or to any other server.
- Your download list and the last quality you chose are stored locally in the browser.

## The helper app
The helper app runs on your computer and downloads the file directly from the website you were visiting.
Once a day it checks the Python package index (pypi.org) for a newer version of yt-dlp; this request
contains no personal data. Log files stay on your computer (`%LOCALAPPDATA%\MediaCatcher`).

## What is not collected
No analytics, no tracking, no advertising, no accounts, no browsing history leaves your computer.

## Permissions
- `webRequest` and access to all sites: to detect media requests on the pages you visit.
- `tabs`: to read the address and title of the current tab.
- `storage`: to remember your download list and settings.

## Contact
younosalesrawi@gmail.com
