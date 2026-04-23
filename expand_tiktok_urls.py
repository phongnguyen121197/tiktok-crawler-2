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
FULL_URL_PATTERN = re.compile(r'tiktok\.com/@[^/]+/video/\d+', re.IGNORECASE)

HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9,vi;q=0.8",
}
HTTP_TIMEOUT = 10
HTTP_SLEEP = 0.3

PW_TIMEOUT_MS = 15000
PW_BATCH_SIZE = 20
PW_SLEEP = 0.5

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


def is_full_url(url: str) -> bool:
    return bool(FULL_URL_PATTERN.search(url or ''))


def normalize_full_url(url: str) -> str:
    """Strip query string/fragment from a full TikTok URL."""
    try:
        p = urlparse(url)
        return urlunparse((p.scheme, p.netloc, p.path.rstrip('/'), '', '', ''))
    except Exception:
        return url.rstrip('/')


def resolve_via_http(short_url: str) -> Optional[str]:
    """
    Follow HTTP redirects, scan redirect chain + response HTML for full URL.
    TikTok short URLs sometimes use a JS redirect, meaning the final
    `resp.url` is still the short form but the HTML body references the
    full @user/video/ID URL (canonical meta tag or embedded JSON).
    """
    try:
        with requests.Session() as s:
            s.headers.update(HTTP_HEADERS)
            resp = s.get(short_url, allow_redirects=True, timeout=HTTP_TIMEOUT)
            final = resp.url or ''

            # Happy path — redirect chain ended at full URL
            if is_full_url(final):
                return normalize_full_url(final)

            # Walk the redirect history looking for a full URL
            for r in resp.history:
                if is_full_url(r.url):
                    return normalize_full_url(r.url)
                loc = r.headers.get("Location", "")
                if is_full_url(loc):
                    return normalize_full_url(loc)

            # Last resort — scan the HTML body. Works when the short URL
            # returns a page containing a canonical <link> or JSON payload.
            html = resp.text or ''
            m = re.search(
                r'https?://(?:www\.)?tiktok\.com/@[^/\s"\'<>]+/video/\d+',
                html,
            )
            if m:
                return normalize_full_url(m.group(0))

            logger.debug(f"  http no-resolve: {short_url} → final={final} (history={len(resp.history)})")
    except Exception as e:
        logger.debug(f"http resolve fail {short_url}: {e}")
    return None


async def _pw_resolve_batch(urls: list) -> dict:
    """
    Playwright fallback. Loads each short URL, waits for JS redirects to
    settle, then reads the final URL. If the URL stays short (redirect
    happened client-side and we read page.url too early), falls back to
    the <link rel="canonical"> tag and an HTML regex scan.
    """
    from playwright.async_api import async_playwright

    results = {}
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu", "--single-process"],
        )
        context = await browser.new_context(
            user_agent=HTTP_HEADERS["User-Agent"],
            locale="en-US",
        )
        for url in urls:
            resolved = None
            try:
                page = await context.new_page()
                await page.goto(url, wait_until="load", timeout=PW_TIMEOUT_MS)
                # Let any JS redirect settle
                await asyncio.sleep(2)
                final = page.url

                # If we're still on the short domain, wait a bit more —
                # sometimes the JS redirect fires after initial load.
                if any(x in final for x in ("vt.tiktok.com", "vm.tiktok.com")):
                    await asyncio.sleep(3)
                    final = page.url

                if is_full_url(final):
                    resolved = normalize_full_url(final)
                else:
                    # Canonical link — most reliable alternate source
                    try:
                        canonical = await page.evaluate(
                            """() => {
                                const el = document.querySelector('link[rel="canonical"]');
                                return el ? el.href : '';
                            }"""
                        )
                        if is_full_url(canonical):
                            resolved = normalize_full_url(canonical)
                    except Exception:
                        pass

                    # Last resort — regex the rendered HTML
                    if not resolved:
                        try:
                            html = await page.content()
                            m = re.search(
                                r'https?://(?:www\.)?tiktok\.com/@[^/\s"\'<>]+/video/\d+',
                                html,
                            )
                            if m:
                                resolved = normalize_full_url(m.group(0))
                        except Exception:
                            pass

                logger.info(f"  pw: {url} → {resolved or f'(failed, final={final})'}")
                await page.close()
            except Exception as e:
                logger.debug(f"pw resolve fail {url}: {e}")
                logger.info(f"  pw: {url} → (exception: {str(e)[:60]})")
            results[url] = resolved
            await asyncio.sleep(PW_SLEEP)
        await context.close()
        await browser.close()
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
        payload = [
            {"record_id": u["record_id"], "fields": {FIELD_NAME: u["new_url"]}}
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
                if code == 1254060:
                    logger.error(
                        f"  → 'Link air bài' rejected plain string. Field may require "
                        f"URL object format. Sample: {payload[0]}"
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

    # ── Phase 2: Playwright fallback ────────────────────────────────────
    if failed and not args.no_playwright:
        logger.info(f"\n[3/4] Playwright fallback ({len(failed)} URLs)...")
        for i in range(0, len(failed), PW_BATCH_SIZE):
            batch = failed[i:i + PW_BATCH_SIZE]
            bnum = i // PW_BATCH_SIZE + 1
            total_b = (len(failed) + PW_BATCH_SIZE - 1) // PW_BATCH_SIZE
            logger.info(f"  batch {bnum}/{total_b} ({len(batch)} URLs)...")
            try:
                pw_results = resolve_via_playwright(batch)
                for su, full in pw_results.items():
                    if full:
                        resolved[su] = full
            except Exception as e:
                logger.error(f"  Playwright batch {bnum} error: {e}")
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
