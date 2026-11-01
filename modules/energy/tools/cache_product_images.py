import json
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]  # the project folder
PRODUCT_DIR = BASE / "static" / "products"
SOURCE_FILE = PRODUCT_DIR / "sources.json"

BROWSER_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) " "AppleWebKit/537.36 (KHTML, like Gecko) " "Chrome/152.0.0.0 Safari/537.36"),
    "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,nl;q=0.8",
    "Referer": "https://www.mastervolt.com/",
    "Sec-Fetch-Dest": "image",
    "Sec-Fetch-Mode": "no-cors",
    "Sec-Fetch-Site": "cross-site",
}


def _valid_image(path: Path) -> bool:
    if not path.exists() or path.stat().st_size < 1024:
        return False
    head = path.read_bytes()[:16]
    return head.startswith(b"\xff\xd8\xff") or head.startswith(b"\x89PNG\r\n\x1a\n") or head[:4] in (b"RIFF", b"GIF8")  # JPEG  # PNG


def _download_urllib(url: str, target: Path):
    req = urllib.request.Request(url, headers=BROWSER_HEADERS)
    with urllib.request.urlopen(req, timeout=20) as r, open(target, "wb") as f:
        f.write(r.read())


def _download_curl(url: str, target: Path):
    # Windows has curl.exe by default.  This fallback is useful when the CDN
    # treats Python's urllib client differently from a browser-like curl request.
    cmd = [
        "curl.exe",
        "--fail",
        "--location",
        "--silent",
        "--show-error",
        "--retry",
        "2",
        "--connect-timeout",
        "10",
        "--max-time",
        "30",
        "-A",
        BROWSER_HEADERS["User-Agent"],
        "-H",
        f"Accept: {BROWSER_HEADERS['Accept']}",
        "-H",
        f"Accept-Language: {BROWSER_HEADERS['Accept-Language']}",
        "-e",
        BROWSER_HEADERS["Referer"],
        "-o",
        str(target),
        url,
    ]
    subprocess.run(cmd, check=True)


def cache_product_images(force=False, quiet=False):
    PRODUCT_DIR.mkdir(parents=True, exist_ok=True)
    sources = json.loads(SOURCE_FILE.read_text(encoding="utf-8"))
    results = {}

    for filename, url in sources.items():
        target = PRODUCT_DIR / filename

        if _valid_image(target) and not force:
            results[filename] = "cached"
            if not quiet:
                print(f"[cached] {filename}")
            continue

        tmp = target.with_suffix(target.suffix + ".tmp")
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass

        errors = []

        # First try urllib with browser/CDN headers.
        try:
            _download_urllib(url, tmp)
            if not _valid_image(tmp):
                raise RuntimeError("downloaded response is not a valid image")
        except Exception as exc:
            errors.append(f"urllib: {exc}")
            try:
                tmp.unlink(missing_ok=True)
            except Exception:
                pass

            # Then try Windows curl.exe with the same browser headers.
            try:
                _download_curl(url, tmp)
                if not _valid_image(tmp):
                    raise RuntimeError("curl response is not a valid image")
            except Exception as curl_exc:
                errors.append(f"curl: {curl_exc}")
                try:
                    tmp.unlink(missing_ok=True)
                except Exception:
                    pass

        if _valid_image(tmp):
            tmp.replace(target)
            results[filename] = "downloaded"
            if not quiet:
                print(f"[downloaded] {filename}")
        else:
            results[filename] = "error: " + " | ".join(errors)
            if not quiet:
                print(f"[warning] {filename}: {' | '.join(errors)}")

    return results


if __name__ == "__main__":
    force = "--force" in sys.argv
    result = cache_product_images(force=force, quiet=False)
    failed = [k for k, v in result.items() if v.startswith("error:")]

    if failed:
        print()
        print("Mastervolt's image CDN rejected the automated download.")
        print("The dashboard itself is unaffected and will fall back to the old icons.")
        print()
        print("You can test one URL manually in PowerShell with:")
        print(
            'curl.exe -L --fail -A "Mozilla/5.0" '
            '-e "https://www.mastervolt.com/" '
            "-o static\\products\\solar.jpg "
            '"https://images.mastervolt.nl/images/products/full/6904_scm60mpptmbrv.jpg"'
        )
        print()
        print("Then rerun: py cache_product_images.py")
        raise SystemExit(1)
