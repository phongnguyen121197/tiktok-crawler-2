"""
expand_tiktok_urls.py
=====================
Standalone one-off script: scan Lark source table for TikTok SHORT URLs
(https://vt.tiktok.com/XXX/ or https://vm.tiktok.com/XXX/), resolve each
to its canonical full form (https://www.tiktok.com/@user/video/VIDEOID),
then overwrite the "Link air bài" cell.

Two-phase resolver for robustness:
  Phase 1: plain HTTP redirect via `requests` (fast, usually works)
  Phase 2: Playwright fallback for URLs TikTok blocks on HTTP

Usage:
    python expand_tiktok_urls.py                 # Dry-run (preview only, no writes)
    python expand_tiktok_urls.py --execute       # Actually write to Lark
    python expand_tiktok_urls.py --limit 20      # Process only first 20 short URLs
    python expand_tiktok_urls.py --execute --no-playwright   # Skip Playwright fallback

Env vars (reuses the main app's config — no new vars needed):
    LARK_APP_ID
    LARK_APP_SECRET
    LARK_BITABLE_TOKEN          (app_token of the Bitable)
    LARK_TABLE_ID               (source table ID — "Link air bài" lives here)
    LARK_USER_REFRESH_TOKEN     (optional — for user-scoped writes)
"""

import argparse
import asyncio
import concurrent.futures
import json
import logging
import os
import re
import sys
import time
from typing import Optional
from urllib.parse import urlparse, urlunparse

import requests
from dotenv import load_dotenv

# Reuse the main app's LarkClient — it handles token refresh, user/tenant
# token fallback, pagination quirks, and the "Link air bài" extraction edge
# cases we already fixed. Keeps this script thin.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from app.lark_client import LarkClient  # noqa: E402

# ─────────────────────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────────────────────
FIELD_NAME = "Link air bài"

SHORT_URL_PATTERN = re.compile(
    r'^https?://(vt|vm|m)\.tiktok\.com/[A-Za-z0-9]+/?',
    re.IGNORECASE,
)
# Intermediate format: may have empty username (@/video/ID) from TikTok's
# "short_fallback" redirect. We'll enrich these to full form with username.
PARTIAL_URL_PATTERN = re.compile(r'tiktok\.com/@[^/]*/video/\d+', re.IGNORECASE)
# Target format — MUST have a real username (≥1 char between @ and /video/)
FULL_URL_PATTERN = re.compile(r'tiktok\.com/@[a-zA-Z0-9_.\-]+/video/\d+', re.IGNORECASE)
# TikTok username character class (letters, digits, underscore, period, hyphen)
USERNAME_CHARS = r'[a-zA-Z0-9_.\-]+'

HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9,vi;q=0.8",
}
HTTP_TIMEOUT = 10
HTTP_SLEEP = 0.3

PW_TIMEOUT_MS = 15000       # max time for page.goto() to finish
PW_MAX_WAIT_MS = 5000       # max time to poll page.url for JS redirect (500ms interval)
PW_BATCH_SIZE = 60          # URLs per Playwright session (browser restart interval)
PW_CONCURRENCY = 3          # pages running concurrently within a session
PW_SLEEP = 0.2              # gap between spawning pages

LARK_BATCH_SIZE = 500

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# URL HELPERS
# ─────────────────────────────────────────────────────────────────────────────
def is_short_url(url: str) -> bool:
    return bool(SHORT_URL_PATTERN.match((url or '').strip()))


def is_partial_url(url: str) -> bool:
    """URL matches @*/video/ID pattern — may or may not have username."""
    return bool(PARTIAL_URL_PATTERN.search(url or ''))


def is_full_url(url: str) -> bool:
    """URL has a real @username segment."""
    return bool(FULL_URL_PATTERN.search(url or ''))


def extract_video_id(url: str) -> Optional[str]:
    m = re.search(r'/video/(\d+)', url or '')
    return m.group(1) if m else None


def normalize_full_url(url: str) -> str:
    """Strip query string/fragment from a TikTok URL."""
    try:
        p = urlparse(url)
        return urlunparse((p.scheme, p.netloc, p.path.rstrip('/'), '', '', ''))
    except Exception:
        return url.rstrip('/')


def _extract_username_from_html(html: str, video_id: str) -> Optional[str]:
    """
    Scan a TikTok video page HTML body for the author's uniqueId.
    Used to enrich @/video/ID partial URLs with the real username.

    Methods, in order of reliability:
      1. <link rel="canonical" href="...@user/video/ID">
      2. <meta property="og:url" content="...@user/video/ID">
      3. __UNIVERSAL_DATA_FOR_REHYDRATION__ JSON → author.uniqueId
      4. regex hunt for "uniqueId":"..." in page scripts
      5. regex hunt for any tiktok.com/@USER/video/VIDEO_ID match
    """
    if not html or not video_id:
        return None

    # 1. canonical link
    for m in re.finditer(
        r'<link[^>]+rel=["\']canonical["\'][^>]+href=["\']([^"\']+)["\']',
        html, re.IGNORECASE,
    ):
        um = re.match(
            rf'https?://(?:www\.)?tiktok\.com/@({USERNAME_CHARS})/video/{video_id}',
            m.group(1),
        )
        if um:
            return um.group(1)

    # 2. og:url meta
    for m in re.finditer(
        r'<meta[^>]+property=["\']og:url["\'][^>]+content=["\']([^"\']+)["\']',
        html, re.IGNORECASE,
    ):
        um = re.match(
            rf'https?://(?:www\.)?tiktok\.com/@({USERNAME_CHARS})/video/{video_id}',
            m.group(1),
        )
        if um:
            return um.group(1)

    # 3. UNIVERSAL_DATA JSON — same data source the Playwright crawler uses
    m = re.search(
        r'<script[^>]+id=["\']__UNIVERSAL_DATA_FOR_REHYDRATION__["\'][^>]*>([^<]+)</script>',
        html,
    )
    if m:
        try:
            j = json.loads(m.group(1))
            author = (
                j.get('__DEFAULT_SCOPE__', {})
                 .get('webapp.video-detail', {})
                 .get('itemInfo', {})
                 .get('itemStruct', {})
                 .get('author', {})
            )
            uid = author.get('uniqueId') if isinstance(author, dict) else None
            if uid:
                return uid
        except Exception:
            pass

    # 4. direct uniqueId regex
    m = re.search(rf'"uniqueId"\s*:\s*"({USERNAME_CHARS})"', html)
    if m:
        return m.group(1)

    # 5. full @user/video/ID pattern anywhere in HTML for this specific video
    m = re.search(
        rf'https?://(?:www\.)?tiktok\.com/@({USERNAME_CHARS})/video/{video_id}',
        html,
    )
    if m:
        return m.group(1)

    return None


def resolve_via_http(short_url: str) -> Optional[str]:
    """
    Quick HTTP check: follow the short URL and return the final URL ONLY
    if it lands directly on a full @user/video/ID form. Returns None for
    anything else (empty-user partial URL, non-video page, blocker, etc.)
    so the caller falls through to Playwright.

    Why so conservative? TikTok's short_fallback redirect returns the
    partial @/video/ID form without the username, and TikTok's video
    page blocks plain `requests` clients for HTML scraping, and oEmbed
    won't accept short URLs as input. Playwright is the only reliable
    way to recover the username.
    """
    try:
        with requests.Session() as s:
            s.headers.update(HTTP_HEADERS)
            resp = s.get(short_url, allow_redirects=True, timeout=HTTP_TIMEOUT)
            final = resp.url or ''
            if is_full_url(final):
                return normalize_full_url(final)
            # Walk redirect history — sometimes the intermediate URL is full
            # even if the final one got rewritten
            for r in resp.history:
                if is_full_url(r.url):
                    return normalize_full_url(r.url)
                loc = r.headers.get("Location", "")
                if is_full_url(loc):
                    return normalize_full_url(loc)
    except Exception as e:
        logger.debug(f"http resolve fail {short_url}: {e}")
    return None


async def _pw_resolve_one(context, url: str) -> Optional[str]:
    """
    Resolve a single short URL inside an existing Playwright context.

    Uses a simple 2-stage fixed settle (empirically reliable over
    adaptive polling which had race conditions with JS navigation).
    """
    page = None
    final = ''
    try:
        page = await context.new_page()
        try:
            await page.goto(url, wait_until="load", timeout=PW_TIMEOUT_MS)
        except Exception as e:
            # Log so we can see WHY it's failing (previous runs silently
            # returned None for all URLs when this broke)
            logger.info(f"  pw goto error for {url}: {str(e)[:100]}")
            return None

        # Fixed settle: 2.5s is enough for most JS redirects
        await asyncio.sleep(2.5)
        final = page.url

        # If still on short domain, TikTok redirect hasn't fired — wait more
        if any(x in final for x in ("vt.tiktok.com", "vm.tiktok.com")):
            await asyncio.sleep(2.5)
            final = page.url

        # ── URL-based resolution (fastest path) ──────────────────────
        if is_full_url(final):
            return normalize_full_url(final)

        # ── Partial URL (@/video/ID) — extract username from page ────
        if is_partial_url(final):
            video_id = extract_video_id(final)
            if video_id:
                # Try canonical <link> tag first
                try:
                    canonical = await page.evaluate(
                        """() => {
                            const el = document.querySelector('link[rel="canonical"]');
                            return el ? el.href : '';
                        }"""
                    )
                    if is_full_url(canonical):
                        return normalize_full_url(canonical)
                except Exception:
                    pass

                # Scan HTML for uniqueId or full URL pattern
                try:
                    html = await page.content()
                    username = _extract_username_from_html(html, video_id)
                    if username:
                        return f"https://www.tiktok.com/@{username}/video/{video_id}"
                except Exception:
                    pass

        # Last resort — scan whatever HTML loaded for any full TikTok URL
        try:
            html = await page.content()
            m = re.search(
                rf'https?://(?:www\.)?tiktok\.com/@{USERNAME_CHARS}/video/\d+',
                html,
            )
            if m:
                return normalize_full_url(m.group(0))
        except Exception:
            pass

        logger.debug(f"  pw unresolved: {url} → final={final}")
        return None
    except Exception as e:
        # Log top-level exceptions so we can see them at INFO
        logger.info(f"  pw error for {url}: {str(e)[:100]} (final={final})")
        return None
    finally:
        if page:
            try:
                await page.close()
            except Exception:
                pass


async def _pw_resolve_batch(urls: list) -> dict:
    """
    Concurrent Playwright resolver. Spawns up to PW_CONCURRENCY pages
    at a time within a single browser context, then restarts the
    browser every PW_BATCH_SIZE URLs to keep memory bounded.
    """
    from playwright.async_api import async_playwright

    LAUNCH_ARGS = ["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"]

    results = {}

    async with async_playwright() as p:

        async def _new_browser():
            browser = await p.chromium.launch(headless=True, args=LAUNCH_ARGS)
            context = await browser.new_context(
                user_agent=HTTP_HEADERS["User-Agent"],
                locale="en-US",
            )
            return browser, context

        browser, context = await _new_browser()

        try:
            for session_start in range(0, len(urls), PW_BATCH_SIZE):
                session_urls = urls[session_start:session_start + PW_BATCH_SIZE]

                # Rotate browser at session boundary (except the first)
                if session_start > 0:
                    try:
                        await browser.close()
                    except Exception:
                        pass
                    browser, context = await _new_browser()

                # Resolve session_urls with bounded concurrency
                sem = asyncio.Semaphore(PW_CONCURRENCY)

                async def _with_sem(u):
                    async with sem:
                        try:
                            res = await _pw_resolve_one(context, u)
                        except Exception as e:
                            logger.info(f"  pw wrapper-exc {u}: {str(e)[:100]}")
                            res = None
                        if res:
                            logger.info(f"  pw ✓ {u} → {res}")
                        else:
                            logger.info(f"  pw ✗ {u}")
                        return u, res

                coros = [_with_sem(u) for u in session_urls]
                pairs = await asyncio.gather(*coros, return_exceptions=True)
                for item in pairs:
                    if isinstance(item, Exception):
                        continue
                    u, res = item
                    results[u] = res
        finally:
            try:
                await browser.close()
            except Exception:
                pass
    return results


def resolve_via_playwright(urls: list) -> dict:
    """Thread wrapper around the async Playwright resolver."""
    def _run():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(_pw_resolve_batch(urls))
        finally:
            loop.close()

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        return ex.submit(_run).result(timeout=3600)


# ─────────────────────────────────────────────────────────────────────────────
# LARK SOURCE TABLE UPDATE
# ─────────────────────────────────────────────────────────────────────────────
def batch_update_source_field(lark: LarkClient, updates: list) -> tuple:
    """
    Write {FIELD_NAME: new_url} to the source table for each update.
    updates: list of {'record_id', 'new_url'}
    Returns: (updated, failed)
    """
    if not updates:
        return (0, 0)

    url = (
        f"https://open.larksuite.com/open-apis/bitable/v1/apps/"
        f"{lark.bitable_app_token}/tables/{lark.table_id}/records/batch_update"
    )
    ok, fail = 0, 0

    for i in range(0, len(updates), LARK_BATCH_SIZE):
        chunk = updates[i:i + LARK_BATCH_SIZE]
        # "Link air bài" in this workspace's source table is a URL field
        # (type 15). Lark rejects plain strings with URLFieldConvFail
        # (code 1254068); it requires the object form.
        payload = [
            {
                "record_id": u["record_id"],
                "fields": {FIELD_NAME: {"text": u["new_url"], "link": u["new_url"]}},
            }
            for u in chunk
        ]
        try:
            resp = lark._make_request("POST", url, json={"records": payload}, timeout=30)
            if not resp:
                fail += len(chunk)
                continue
            data = resp.json()
            if data.get("code") == 0:
                done = len(data.get("data", {}).get("records", chunk))
                ok += done
                logger.info(f"  ✅ Batch {i // LARK_BATCH_SIZE + 1}: {done}/{len(chunk)} updated")
            else:
                fail += len(chunk)
                code = data.get("code")
                logger.error(f"  ❌ Batch error (code={code}): {data.get('msg')}")
                if code in (1254060, 1254068):
                    logger.error(
                        f"  → Field type mismatch on '{FIELD_NAME}'. "
                        f"Sample payload: {payload[0]}"
                    )
        except Exception as e:
            fail += len(chunk)
            logger.error(f"  ❌ Exception: {e}")
        if i + LARK_BATCH_SIZE < len(updates):
            time.sleep(0.5)

    return (ok, fail)


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="Expand TikTok short URLs in Lark source table."
    )
    parser.add_argument("--execute", action="store_true",
                        help="Write to Lark (default: dry-run)")
    parser.add_argument("--limit", type=int, default=0,
                        help="Max short URLs to process (0 = all)")
    parser.add_argument("--no-playwright", action="store_true",
                        help="Skip Playwright fallback (HTTP only)")
    parser.add_argument("--verbose", action="store_true",
                        help="Verbose debug logs (show each URL resolution attempt)")
    args = parser.parse_args()

    if args.verbose:
        logger.setLevel(logging.DEBUG)
        logging.getLogger().setLevel(logging.DEBUG)

    load_dotenv()
    mode = "EXECUTE" if args.execute else "DRY-RUN"
    logger.info("=" * 60)
    logger.info(f"TikTok Short URL Expander  |  {mode}")
    logger.info("=" * 60)

    # Check required env
    required = ("LARK_APP_ID", "LARK_APP_SECRET", "LARK_BITABLE_TOKEN", "LARK_TABLE_ID")
    missing = [v for v in required if not os.getenv(v)]
    if missing:
        logger.error(f"Missing env vars: {missing}")
        sys.exit(1)

    # Build the same Lark client the main app uses (user token, refresh, etc.)
    lark = LarkClient(
        app_id=os.getenv("LARK_APP_ID"),
        app_secret=os.getenv("LARK_APP_SECRET"),
        bitable_app_token=os.getenv("LARK_BITABLE_TOKEN"),
        table_id=os.getenv("LARK_TABLE_ID"),
        user_refresh_token=os.getenv("LARK_USER_REFRESH_TOKEN"),
    )
    logger.info(f"Bitable: {lark.bitable_app_token}")
    logger.info(f"Table  : {lark.table_id}")

    # ── Scan source table ───────────────────────────────────────────────
    logger.info("\n[1/4] Scanning source table for short URLs...")
    records = lark.get_all_active_records()
    logger.info(f"Total records with link: {len(records)}")

    short_records = []
    already_full = 0
    other_format = 0
    for rec in records:
        rid = rec.get("record_id") or rec.get("id", "")
        url = lark._extract_link_value(rec.get("fields", {}).get(FIELD_NAME, ""))
        if not url or not rid:
            continue
        if is_short_url(url):
            short_records.append({"record_id": rid, "short_url": url})
        elif is_full_url(url):
            already_full += 1
        else:
            other_format += 1

    logger.info(f"  Short URLs to expand : {len(short_records)}")
    logger.info(f"  Already full URL     : {already_full}")
    logger.info(f"  Other format         : {other_format}")

    if not short_records:
        logger.info("✅ Nothing to do — no short URLs found.")
        return

    if args.limit and args.limit < len(short_records):
        short_records = short_records[:args.limit]
        logger.info(f"  → Limited to first {len(short_records)}")

    # ── Phase 1: HTTP resolve ───────────────────────────────────────────
    logger.info(f"\n[2/4] HTTP resolve ({len(short_records)} URLs)...")
    resolved = {}     # short_url → full_url
    failed = []       # list of short URLs that failed phase 1

    for idx, item in enumerate(short_records, 1):
        su = item["short_url"]
        full = resolve_via_http(su)
        if full:
            resolved[su] = full
            # Show first 3 successes so user can sanity-check format
            if len([r for r in resolved.values() if r]) <= 3:
                logger.info(f"  http ✓ {su} → {full}")
        else:
            failed.append(su)
            # Always show first 3 failures so we can diagnose
            if len(failed) <= 3:
                logger.info(f"  http ✗ {su}  (no redirect to full URL)")
        if idx % 25 == 0 or idx == len(short_records):
            logger.info(f"  progress {idx}/{len(short_records)} | ok={len(resolved)} fail={len(failed)}")
        time.sleep(HTTP_SLEEP)

    logger.info(f"  HTTP: {len(resolved)}/{len(short_records)} resolved")

    # ── Phase 2: Playwright fallback (concurrent) ───────────────────────
    if failed and not args.no_playwright:
        logger.info(f"\n[3/4] Playwright fallback ({len(failed)} URLs, "
                    f"{PW_CONCURRENCY} concurrent)...")
        try:
            pw_results = resolve_via_playwright(failed)
            for su, full in pw_results.items():
                if full:
                    resolved[su] = full
        except Exception as e:
            logger.error(f"  Playwright error: {e}")
    elif failed and args.no_playwright:
        logger.info(f"\n[3/4] Skipping Playwright fallback ({len(failed)} URLs unresolved)")

    # ── Build update list + preview ─────────────────────────────────────
    updates = []
    unresolved = []
    for item in short_records:
        su = item["short_url"]
        full = resolved.get(su)
        if full:
            updates.append({
                "record_id": item["record_id"],
                "short_url": su,
                "new_url": full,
            })
        else:
            unresolved.append(item)

    logger.info(f"\nResolution summary:")
    logger.info(f"  ✓ Resolved   : {len(updates)}")
    logger.info(f"  ✗ Unresolved : {len(unresolved)}")

    logger.info("\nSample (first 5):")
    for u in updates[:5]:
        logger.info(f"  {u['short_url']}")
        logger.info(f"  → {u['new_url']}")

    # ── Phase 3: write to Lark ──────────────────────────────────────────
    if not args.execute:
        logger.info(f"\n[4/4] DRY-RUN — no writes. Add --execute to apply {len(updates)} updates.")
        if unresolved:
            logger.warning(f"\n{len(unresolved)} URLs failed to resolve — saving to failed_expand.json")
            with open("failed_expand.json", "w", encoding="utf-8") as f:
                json.dump(unresolved, f, ensure_ascii=False, indent=2)
        return

    if not updates:
        logger.info("Nothing to write.")
        return

    logger.info(f"\n[4/4] Writing {len(updates)} updates to Lark source table...")
    ok, fail = batch_update_source_field(lark, updates)

    logger.info("\n" + "=" * 60)
    logger.info("DONE")
    logger.info(f"  HTTP resolved     : {len([r for r in resolved if r])}")
    logger.info(f"  Lark updated      : {ok}")
    logger.info(f"  Lark failed       : {fail}")
    logger.info(f"  Unresolved        : {len(unresolved)}")
    logger.info("=" * 60)

    if unresolved:
        with open("failed_expand.json", "w", encoding="utf-8") as f:
            json.dump(unresolved, f, ensure_ascii=False, indent=2)
        logger.warning("Unresolved URLs saved → failed_expand.json")


if __name__ == "__main__":
    main()
