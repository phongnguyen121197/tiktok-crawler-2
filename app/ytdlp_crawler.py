"""
yt-dlp based TikTok crawler - parallel, fast, uses TikTok mobile API endpoint.

Advantages over Playwright:
- Uses TikTok's mobile API endpoint (aweme/v1/multi/aweme/detail/) directly
- ~3-5s per video instead of ~11s
- Parallel execution (4 workers by default)
- Fails fast (~2-5s) for unavailable videos instead of 53s timeout
- No browser overhead
"""

import yt_dlp
import concurrent.futures
import logging
import time
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

# Keywords to detect "data not yet propagated" vs "truly broken"
_PENDING_KEYWORDS = [
    'unable to extract', 'itemmodule', 'no video data',
    'aweme/detail', 'webpage video data', 'no initial player response',
]
_BROKEN_KEYWORDS = [
    'video unavailable', 'this video is unavailable', 'removed',
    'private video', 'does not exist', 'no video with id',
    'account suspended', 'content not available',
    'http error 404', '404', 'forbidden', '403',
]


def _fetch_single(url: str) -> Dict:
    """
    Fetch a single TikTok video's stats via yt-dlp.
    Returns a result dict compatible with the Playwright crawler format.
    """
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'skip_download': True,
        'socket_timeout': 15,
        # Retry within yt-dlp (separate from our outer retry logic)
        'retries': 1,
        'extractor_retries': 1,
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

        if not info:
            return {
                'url': url, 'success': False, 'views': None,
                'error': 'no_info', 'is_broken': False,
                'pending_propagation': True,
            }

        views = info.get('view_count')
        upload_date = info.get('upload_date')  # 'YYYYMMDD' string

        # Convert YYYYMMDD → YYYY-MM-DD
        publish_date = None
        if upload_date and len(str(upload_date)) == 8:
            d = str(upload_date)
            publish_date = f"{d[:4]}-{d[4:6]}-{d[6:8]}"

        if views is None:
            # Video was found by yt-dlp but no view count returned → likely a very
            # new video where TikTok hasn't propagated stats to the API yet.
            return {
                'url': url, 'success': False, 'views': None,
                'publish_date': publish_date,
                'error': 'no_views_yet', 'is_broken': False,
                'pending_propagation': True,
            }

        return {
            'url': url,
            'success': True,
            'views': views,
            'likes': info.get('like_count', 0) or 0,
            'comments': info.get('comment_count', 0) or 0,
            'shares': info.get('repost_count', 0) or 0,
            'publish_date': publish_date,
            'is_broken': False,
            'pending_propagation': False,
        }

    except Exception as e:
        error_msg = str(e).lower()

        is_broken = any(kw in error_msg for kw in _BROKEN_KEYWORDS)
        is_pending = (not is_broken) and any(kw in error_msg for kw in _PENDING_KEYWORDS)

        return {
            'url': url,
            'success': False,
            'views': None,
            'error': str(e)[:150],
            'is_broken': is_broken,
            # If neither broken nor pending → yt-dlp had a transient failure
            # (rate limit, network) → caller should fall back to Playwright
            'pending_propagation': is_pending,
        }


class YtDlpCrawler:
    """Parallel TikTok crawler powered by yt-dlp."""

    def __init__(self, max_workers: int = 3):
        """
        Args:
            max_workers: Parallel workers. Keep ≤ 4 to avoid IP rate-limiting.
        """
        self.max_workers = max_workers
        logger.info(f"✅ YtDlpCrawler initialized (workers={max_workers})")

    def crawl_batch(self, urls: List[str]) -> List[Dict]:
        """
        Crawl a list of TikTok video URLs in parallel.

        Returns list of result dicts with keys:
            url, success, views, likes, comments, shares,
            publish_date, is_broken, pending_propagation, error (on failure)
        """
        if not urls:
            return []

        logger.info(f"🎬 yt-dlp: crawling {len(urls)} URLs ({self.max_workers} workers)...")
        t0 = time.time()

        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            results = list(executor.map(_fetch_single, urls))

        elapsed = time.time() - t0
        success   = sum(1 for r in results if r.get('success'))
        pending   = sum(1 for r in results if r.get('pending_propagation'))
        broken    = sum(1 for r in results if r.get('is_broken'))
        failed    = len(urls) - success - pending - broken

        logger.info(
            f"✅ yt-dlp done in {elapsed:.0f}s | "
            f"✅ {success} success | "
            f"⏳ {pending} pending | "
            f"🔗 {broken} broken | "
            f"⚠️ {failed} failed (→ Playwright fallback)"
        )
        return results
