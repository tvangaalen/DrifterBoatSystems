# v0.18.1 — Mastervolt image CDN 403 workaround

The Mastervolt image CDN returned HTTP 403 to Python's original urllib downloader.

The cache utility now:
1. Sends a full browser-style request header set, including Mastervolt Referer.
2. Falls back to Windows `curl.exe` with the same browser headers.
3. Validates that the downloaded file is really an image before installing it.
4. Leaves the existing dashboard icon fallback intact when the CDN still rejects
   automated retrieval.

The server starter no longer runs the cache command visibly on every launch.
The application itself performs a quiet best-effort cache attempt at startup.

Manual retry:
`py cache_product_images.py --force`
