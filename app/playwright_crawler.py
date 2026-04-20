"""
🚀 TikTok Playwright Crawler v3.2 - PUBLISH DATE PRIORITY
======================================================
NEW v3.2:
- ✅ Preserve existing publish_date (only update if empty)
- ✅ Broken links return empty values (not preserve old data)
- ✅ Smart date handling in batch crawl
- ✅ Crash loop protection (from v3.1)

Previous fixes:
- ✅ playwright-stealth for anti-bot detection bypass
- ✅ Multiple extraction methods with comprehensive fallbacks
- ✅ URL validation before crawling
- ✅ Auto-retry failed videos at end with fresh browser
- ✅ Firefox fallback for stubborn videos
"""

import asyncio
import json
import random
import gc
import time
import re
import logging
import concurrent.futures
import traceback
from datetime import datetime
from typing import Optional, Dict, List, Tuple
from dataclasses import dataclass, field
from urllib.parse import urlparse

# Playwright imports
from playwright.async_api import async_playwright, Page, BrowserContext, TimeoutError as PlaywrightTimeout

# Try to import playwright-stealth (optional but recommended)
try:
    from playwright_stealth import stealth_async
    STEALTH_AVAILABLE = True
except ImportError:
    STEALTH_AVAILABLE = False

logger = logging.getLogger(__name__)


# ============================================================================
# CONFIGURATION
# ============================================================================

@dataclass
class CrawlerConfig:
    """Configuration for v4.1 crawler — Playwright only, optimised for low CPU/RAM"""
    delay_range: Tuple[float, float] = (0.5, 1.5)      # Shorter delays (was 2-4s)
    timeout_ms: int = 20000                             # 20s timeout (was 30s)
    max_retries: int = 1                                # 1 retry max (was 3)
    restart_browser_every: int = 50                     # Restart after N videos (was 75)
    browser_close_timeout: int = 10                     # Close timeout (was 15)
    wait_after_load: float = 1.5                        # Wait for JS render (was 2.5s)
    retry_failed_at_end: bool = False                   # Disabled — saves 2nd full pass
    use_firefox_fallback: bool = False                  # Disabled — saves RAM
    max_end_retries: int = 1                            # Max end retries

    # Crash loop protection
    max_consecutive_crashes: int = 5                    # Max crashes before skip
    crash_restart_delay: float = 2.0                    # Delay between crash restarts (was 3s)
    memory_cleanup_interval: int = 20                   # GC every N videos (was 25)

    # Publish date priority
    preserve_existing_publish_date: bool = True         # Keep existing dates
    clear_data_on_broken_link: bool = True              # Empty values for broken links


# Extended User Agents pool
USER_AGENTS = [
    # Chrome on Windows
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
    # Chrome on Mac
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    # Firefox
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:122.0) Gecko/20100101 Firefox/122.0',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:122.0) Gecko/20100101 Firefox/122.0',
    # Edge
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36 Edg/121.0.0.0',
]


# ============================================================================
# URL VALIDATION
# ============================================================================

def validate_tiktok_url(url: str) -> Tuple[bool, str]:
    """
    Validate TikTok URL before crawling
    Returns: (is_valid, cleaned_url or error_message)
    """
    if not url:
        return False, "Empty URL"
    
    url = str(url).strip()
    
    # Check for obviously invalid URLs
    if len(url) < 10:
        return False, f"URL too short: {url}"
    
    # Must contain tiktok
    if 'tiktok' not in url.lower():
        return False, f"Not a TikTok URL: {url}"
    
    # Add https if missing
    if not url.startswith('http'):
        url = 'https://' + url
    
    # Parse and validate
    try:
        parsed = urlparse(url)
        
        # Check domain
        valid_domains = ['tiktok.com', 'www.tiktok.com', 'vt.tiktok.com', 'm.tiktok.com', 'vm.tiktok.com']
        if not any(d in parsed.netloc for d in valid_domains):
            return False, f"Invalid TikTok domain: {parsed.netloc}"
        
        # Check for video path (should have /video/ or be a short link)
        if '/video/' in url:
            # Full URL - validate video ID
            match = re.search(r'/video/(\d+)', url)
            if not match:
                return False, f"Cannot extract video ID from: {url}"
        elif 'vt.tiktok' in url or 'vm.tiktok' in url:
            # Short URL - should be valid
            pass
        elif '/@' in url and '/video/' not in url:
            return False, f"Profile URL, not video: {url}"
        
        return True, url
        
    except Exception as e:
        return False, f"URL parse error: {str(e)}"


# ============================================================================
# HELPER FUNCTIONS  
# ============================================================================

def convert_timestamp_to_date(timestamp) -> Optional[str]:
    """Convert Unix timestamp to YYYY-MM-DD format"""
    try:
        if not timestamp:
            return None
        
        ts = int(timestamp) if isinstance(timestamp, str) else timestamp
        
        # Handle milliseconds
        if ts > 9999999999:
            ts = ts / 1000
        
        dt = datetime.fromtimestamp(ts)
        
        # Validate reasonable date range
        if dt.year < 2016 or dt.year > 2030:
            return None
            
        return dt.strftime('%Y-%m-%d')
    except:
        return None


def is_valid_publish_date(date_str: Optional[str]) -> bool:
    """Check if publish_date is valid and not empty"""
    if not date_str:
        return False
    
    date_str = str(date_str).strip()
    
    # Check for empty or placeholder values
    if not date_str or date_str in ['', 'None', 'null', 'N/A', '-']:
        return False
    
    # Validate date format YYYY-MM-DD
    try:
        datetime.strptime(date_str, '%Y-%m-%d')
        return True
    except:
        return False


# ============================================================================
# ENHANCED STEALTH SCRIPT
# ============================================================================

STEALTH_SCRIPT = """
() => {
    // Hide webdriver
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
    
    // Mock plugins
    Object.defineProperty(navigator, 'plugins', { 
        get: () => [
            { name: 'Chrome PDF Plugin' },
            { name: 'Chrome PDF Viewer' },
            { name: 'Native Client' }
        ] 
    });
    
    // Mock languages
    Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en', 'vi'] });
    
    // Mock chrome object
    window.chrome = { 
        runtime: {},
        loadTimes: function() {},
        csi: function() {},
        app: {}
    };
    
    // Mock permissions
    const originalQuery = window.navigator.permissions.query;
    window.navigator.permissions.query = (parameters) => (
        parameters.name === 'notifications' ?
            Promise.resolve({ state: Notification.permission }) :
            originalQuery(parameters)
    );
    
    // Hide automation indicators
    delete window.cdc_adoQpoasnfa76pfcZLmcfl_Array;
    delete window.cdc_adoQpoasnfa76pfcZLmcfl_Promise;
    delete window.cdc_adoQpoasnfa76pfcZLmcfl_Symbol;
    
    // Mock screen properties
    Object.defineProperty(screen, 'availWidth', { get: () => window.innerWidth });
    Object.defineProperty(screen, 'availHeight', { get: () => window.innerHeight });
    
    // Add fake mouse movement history
    window.mouseMovements = [];
    document.addEventListener('mousemove', (e) => {
        window.mouseMovements.push({x: e.clientX, y: e.clientY, t: Date.now()});
        if (window.mouseMovements.length > 100) window.mouseMovements.shift();
    });
}
"""


# ============================================================================
# DATA EXTRACTION - MULTIPLE METHODS
# ============================================================================

async def check_page_data_status(page: Page) -> str:
    """
    Quick check (< 0.3s) whether TikTok has data available on this page.

    Returns:
        'ok'       - data containers look populated, proceed with extraction
        'pending'  - page loaded but all data containers are empty/tiny
                     (very new video: TikTok hasn't propagated data yet)
        'broken'   - explicit 404 / "video unavailable" signal
        'unknown'  - can't tell (page didn't load properly) → proceed anyway
    """
    try:
        result = await page.evaluate("""() => {
            // Check page title for explicit failure signals
            const title = document.title || '';
            const tl = title.toLowerCase();
            if (tl.includes('page not found') || tl.includes('404')) {
                return {status: 'broken', reason: 'title_404'};
            }

            // Scan known data containers for substantial content
            const ids = [
                '__UNIVERSAL_DATA_FOR_REHYDRATION__',
                'SIGI_STATE',
                '__NEXT_DATA__',
            ];
            let maxLen = 0;
            for (const id of ids) {
                const el = document.getElementById(id);
                if (el && el.textContent) {
                    maxLen = Math.max(maxLen, el.textContent.length);
                }
            }

            // If any container has > 1000 chars there is likely real video data
            if (maxLen > 1000) {
                return {status: 'ok', reason: 'has_content_' + maxLen};
            }

            // Check UNIVERSAL_DATA status code for more specifics
            const uEl = document.getElementById('__UNIVERSAL_DATA_FOR_REHYDRATION__');
            if (uEl && uEl.textContent && uEl.textContent.length > 50) {
                try {
                    const json = JSON.parse(uEl.textContent);
                    const detail = json?.['__DEFAULT_SCOPE__']?.['webapp.video-detail'];
                    const sc = detail?.statusCode;
                    // 0 = success, but content could still be minimal (loading race)
                    // Non-zero codes mean server explicitly said no data
                    if (sc && sc !== 0) {
                        return {status: 'pending', reason: 'status_code_' + sc};
                    }
                } catch(e) {}
            }

            // All containers empty/tiny → data not ready
            if (maxLen < 100) {
                return {status: 'pending', reason: 'empty_containers'};
            }

            return {status: 'unknown', reason: 'small_content_' + maxLen};
        }""")

        return result.get('status', 'unknown') if result else 'unknown'
    except Exception:
        return 'unknown'


async def extract_video_data(page: Page, url: str) -> Optional[Dict]:
    """
    Extract video data using multiple methods with comprehensive fallbacks
    """
    data = None
    extraction_method = None
    
    try:
        # ===== METHOD 1: UNIVERSAL_DATA (Primary - Most Reliable) =====
        try:
            raw_json = await page.evaluate('''() => {
                const script = document.querySelector('#__UNIVERSAL_DATA_FOR_REHYDRATION__');
                return script ? script.textContent : null;
            }''')
            
            if raw_json:
                json_data = json.loads(raw_json)
                scope = json_data.get('__DEFAULT_SCOPE__', {})
                video_detail = scope.get('webapp.video-detail', {})
                item = video_detail.get('itemInfo', {}).get('itemStruct', {})
                
                if item:
                    stats = item.get('stats', {})
                    views = stats.get('playCount', 0)
                    if views and views > 0:
                        author = item.get('author', {})
                        data = {
                            'views': views,
                            'likes': stats.get('diggCount', 0),
                            'comments': stats.get('commentCount', 0),
                            'shares': stats.get('shareCount', 0),
                            'publish_date': convert_timestamp_to_date(item.get('createTime')),
                            'channel_id': author.get('uniqueId', '') if isinstance(author, dict) else str(author),
                        }
                        extraction_method = 'UNIVERSAL_DATA'
        except Exception as e:
            logger.debug(f"Method 1 (UNIVERSAL_DATA) failed: {e}")
        
        # ===== METHOD 2: SIGI_STATE (Legacy Format) =====
        if not data:
            try:
                raw_json = await page.evaluate('''() => {
                    const script = document.querySelector('#SIGI_STATE');
                    return script ? script.textContent : null;
                }''')
                
                if raw_json:
                    json_data = json.loads(raw_json)
                    item_module = json_data.get('ItemModule', {})
                    
                    for video_id, video_data in item_module.items():
                        stats = video_data.get('stats', {})
                        views = stats.get('playCount', 0)
                        if views and views > 0:
                            # In SIGI_STATE, 'author' is usually the uniqueId string directly
                            raw_author = video_data.get('author', '')
                            channel_id = raw_author if isinstance(raw_author, str) else raw_author.get('uniqueId', '')
                            data = {
                                'views': views,
                                'likes': stats.get('diggCount', 0),
                                'comments': stats.get('commentCount', 0),
                                'shares': stats.get('shareCount', 0),
                                'publish_date': convert_timestamp_to_date(video_data.get('createTime')),
                                'channel_id': channel_id,
                            }
                            extraction_method = 'SIGI_STATE'
                            break
            except Exception as e:
                logger.debug(f"Method 2 (SIGI_STATE) failed: {e}")
        
        # ===== METHOD 3: NEXT_DATA (New React Format) =====
        if not data:
            try:
                raw_json = await page.evaluate('''() => {
                    const script = document.querySelector('#__NEXT_DATA__');
                    return script ? script.textContent : null;
                }''')
                
                if raw_json:
                    json_data = json.loads(raw_json)
                    props = json_data.get('props', {}).get('pageProps', {})
                    item_info = props.get('itemInfo', {}).get('itemStruct', {})
                    
                    if item_info:
                        stats = item_info.get('stats', {})
                        views = stats.get('playCount', 0)
                        if views and views > 0:
                            author = item_info.get('author', {})
                            data = {
                                'views': views,
                                'likes': stats.get('diggCount', 0),
                                'comments': stats.get('commentCount', 0),
                                'shares': stats.get('shareCount', 0),
                                'publish_date': convert_timestamp_to_date(item_info.get('createTime')),
                                'channel_id': author.get('uniqueId', '') if isinstance(author, dict) else str(author),
                            }
                            extraction_method = 'NEXT_DATA'
            except Exception as e:
                logger.debug(f"Method 3 (NEXT_DATA) failed: {e}")
        
        # ===== METHOD 4: Regex from HTML (Last Resort) =====
        if not data:
            try:
                html = await page.content()
                
                # Try multiple patterns for playCount
                patterns = [
                    r'"playCount"\s*:\s*(\d+)',
                    r'"play_count"\s*:\s*(\d+)', 
                    r'"viewCount"\s*:\s*(\d+)',
                    r'playCount&quot;:(\d+)',
                    r'"stats"\s*:\s*\{[^}]*"playCount"\s*:\s*(\d+)',
                ]
                
                views = None
                for pattern in patterns:
                    match = re.search(pattern, html)
                    if match:
                        views = int(match.group(1))
                        if views > 0:
                            break
                
                if views and views > 0:
                    # Try to get createTime
                    time_match = re.search(r'"createTime"\s*:\s*"?(\d{10,13})"?', html)
                    publish_date = convert_timestamp_to_date(time_match.group(1)) if time_match else None

                    # Try to get other stats
                    likes_match = re.search(r'"diggCount"\s*:\s*(\d+)', html)
                    comments_match = re.search(r'"commentCount"\s*:\s*(\d+)', html)
                    shares_match = re.search(r'"shareCount"\s*:\s*(\d+)', html)
                    # Try to get channel username
                    username_match = re.search(r'"uniqueId"\s*:\s*"([^"]+)"', html)

                    data = {
                        'views': views,
                        'likes': int(likes_match.group(1)) if likes_match else 0,
                        'comments': int(comments_match.group(1)) if comments_match else 0,
                        'shares': int(shares_match.group(1)) if shares_match else 0,
                        'publish_date': publish_date,
                        'channel_id': username_match.group(1) if username_match else '',
                    }
                    extraction_method = 'REGEX'
            except Exception as e:
                logger.debug(f"Method 4 (REGEX) failed: {e}")
        
        # ===== METHOD 5: DOM Scraping (Visual Elements) =====
        if not data:
            try:
                # Try to get views from visible element
                views_text = await page.evaluate('''() => {
                    const selectors = [
                        '[data-e2e="video-views"]',
                        '[data-e2e="browse-video-count"]',
                        'strong[data-e2e="video-views"]',
                        '.video-count',
                        '.tiktok-1xiuanb-StrongVideoCount'
                    ];
                    for (const sel of selectors) {
                        const el = document.querySelector(sel);
                        if (el && el.textContent) return el.textContent.trim();
                    }
                    return null;
                }''')
                
                if views_text:
                    views = parse_view_count(views_text)
                    if views and views > 0:
                        data = {
                            'views': views,
                            'likes': 0,
                            'comments': 0,
                            'shares': 0,
                            'publish_date': None,
                        }
                        extraction_method = 'DOM'
            except Exception as e:
                logger.debug(f"Method 5 (DOM) failed: {e}")
        
        # Log extraction result
        if data:
            logger.debug(f"✅ Extracted via {extraction_method}: {data['views']:,} views, date: {data.get('publish_date', 'N/A')}")
        else:
            # Check for known error pages
            title = await page.title()
            if 'captcha' in title.lower() or 'verify' in title.lower():
                logger.warning(f"🚫 CAPTCHA detected for: {url}")
            elif 'not found' in title.lower() or 'unavailable' in title.lower():
                logger.warning(f"⚠️ Video not found/unavailable: {url}")
            else:
                logger.debug(f"❌ All extraction methods failed for: {url}")
        
        return data
        
    except Exception as e:
        logger.debug(f"Extraction error: {e}")
        return None


def parse_view_count(text: str) -> int:
    """Parse TikTok view count (e.g., '1.2M' -> 1200000)"""
    if not text:
        return 0
    
    text = str(text).strip().upper().replace(',', '')
    
    try:
        # Remove non-numeric except K, M, B, .
        text = re.sub(r'[^\d.KMB]', '', text)
        
        if not text:
            return 0
        
        multipliers = {'K': 1000, 'M': 1000000, 'B': 1000000000}
        
        for suffix, multiplier in multipliers.items():
            if suffix in text:
                number = float(text.replace(suffix, ''))
                return int(number * multiplier)
        
        return int(float(text))
    except:
        return 0


# ============================================================================
# SEQUENTIAL CRAWLER v3.2 - WITH PUBLISH DATE PRIORITY
# ============================================================================

class SequentialTikTokCrawler:
    """
    Sequential TikTok crawler v3.2 with publish date priority
    """
    
    def __init__(self, config: CrawlerConfig = None):
        self.config = config or CrawlerConfig()
        self.browser = None
        self.playwright = None
        self.context = None
        self.videos_since_restart = 0
        self.stats = {'total': 0, 'success': 0, 'failed': 0, 'start_time': None}
        self.failed_urls = []  # Track failed URLs for retry
        self.browser_type = 'chromium'  # Default browser
        
        # Crash tracking (v3.1)
        self.consecutive_crashes = 0
        self.total_crashes = 0
        
        # v3.2: Date stats
        self.dates_preserved = 0
        self.dates_updated = 0
    
    async def start_browser(self, browser_type: str = 'chromium'):
        """Start or restart browser with stealth settings"""
        await self.close_browser()
        
        gc.collect()
        
        try:
            self.browser_type = browser_type
            self.playwright = await async_playwright().start()
            
            # Browser launch args
            launch_args = [
                '--disable-blink-features=AutomationControlled',
                '--disable-dev-shm-usage',
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-gpu',
                '--disable-web-security',
                '--disable-features=IsolateOrigins,site-per-process',
                '--no-first-run',
                '--no-zygote',
                '--single-process',
                '--disable-infobars',
                # Disable rendering features not needed for data extraction
                '--blink-settings=imagesEnabled=false',
                '--disable-extensions',
                '--disable-background-networking',
                '--disable-sync',
                '--metrics-recording-only',
                '--mute-audio',
            ]
            
            self.browser = await self.playwright.chromium.launch(
                headless=True,
                args=launch_args
            )
            
            # Create context with realistic settings, smaller viewport saves RAM
            self.context = await self.browser.new_context(
                viewport={'width': 1280, 'height': 720},
                user_agent=random.choice(USER_AGENTS),
                locale='en-US',
                timezone_id='Asia/Ho_Chi_Minh',
                java_script_enabled=True,
                bypass_csp=True,
                ignore_https_errors=True,
                has_touch=False,
                is_mobile=False,
                device_scale_factor=1,
                color_scheme='light',
            )
            
            # Apply stealth script
            await self.context.add_init_script(STEALTH_SCRIPT)
            
            self.videos_since_restart = 0
            self.consecutive_crashes = 0
            logger.info(f"✅ {browser_type.title()} browser started successfully")
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to start {browser_type} browser: {e}")
            return False
    
    async def close_browser(self):
        """Close browser with timeout protection"""
        async def _close():
            try:
                if self.context:
                    await self.context.close()
                    self.context = None
            except:
                pass
            
            try:
                if self.browser:
                    await self.browser.close()
                    self.browser = None
            except:
                pass
            
            try:
                if self.playwright:
                    await self.playwright.stop()
                    self.playwright = None
            except:
                pass
        
        try:
            await asyncio.wait_for(_close(), timeout=self.config.browser_close_timeout)
        except asyncio.TimeoutError:
            logger.warning(f"⚠️ Browser close timed out, force killing...")
            self.context = None
            self.browser = None
            self.playwright = None
        
        gc.collect()
    
    async def crawl_single(self, url: str, existing_publish_date: Optional[str] = None, retry_count: int = 0) -> Dict:
        """
        Crawl a single URL with publish date priority
        
        Args:
            url: TikTok video URL
            existing_publish_date: Current publish_date from Lark (to preserve if valid)
            retry_count: Current retry attempt
        
        Returns:
            Dict with crawl results
        """
        
        # Validate URL first
        is_valid, result = validate_tiktok_url(url)
        if not is_valid:
            logger.warning(f"❌ Invalid URL skipped: {result}")
            self.stats['failed'] += 1
            # v3.2: Return empty values for invalid URLs (broken link)
            return {
                'url': url, 
                'success': False, 
                'views': None,
                'likes': None,
                'comments': None,
                'shares': None,
                'publish_date': None,
                'error': result,
                'is_broken': True
            }
        
        url = result  # Use cleaned URL
        
        # Check crash limit (v3.1)
        if self.consecutive_crashes >= self.config.max_consecutive_crashes:
            logger.error(f"🛑 Too many consecutive crashes ({self.consecutive_crashes}), skipping: {url[:50]}...")
            self.stats['failed'] += 1
            self.failed_urls.append(url)
            self.consecutive_crashes = 0
            return {
                'url': url, 
                'success': False, 
                'views': None,
                'likes': None,
                'comments': None,
                'shares': None,
                'publish_date': existing_publish_date if is_valid_publish_date(existing_publish_date) else None,
                'error': 'Too many consecutive crashes',
                'is_broken': False  # Not broken, just crashed - preserve date
            }
        
        # Check if browser restart needed
        if self.videos_since_restart >= self.config.restart_browser_every:
            logger.info(f"🔄 Restarting browser after {self.videos_since_restart} videos...")
            await self.start_browser(self.browser_type)
            gc.collect()
        
        # Ensure browser is running
        if not self.browser or not self.context:
            if not await self.start_browser(self.browser_type):
                return {
                    'url': url, 
                    'success': False, 
                    'views': None,
                    'likes': None,
                    'comments': None,
                    'shares': None,
                    'publish_date': existing_publish_date if is_valid_publish_date(existing_publish_date) else None,
                    'error': 'Browser failed to start',
                    'is_broken': False
                }
        
        page = None
        start_time = time.time()
        
        try:
            # Random human-like delay
            delay = random.uniform(*self.config.delay_range)
            await asyncio.sleep(delay)
            
            # Create new page
            page = await self.context.new_page()

            # ── RESOURCE BLOCKING ─────────────────────────────────────────────
            # Block heavy resources we don't need (images, media, fonts, CSS).
            # TikTok video data lives in JSON <script> tags — nothing visual needed.
            # This alone cuts page-load time ~40% and RAM usage significantly.
            async def _block_resource(route):
                if route.request.resource_type in ("image", "media", "font", "stylesheet"):
                    await route.abort()
                elif any(x in route.request.url for x in ("analytics", "tracker", "beacon", "sentry", "monitoring")):
                    await route.abort()
                else:
                    await route.continue_()
            await page.route("**/*", _block_resource)
            # ── END RESOURCE BLOCKING ─────────────────────────────────────────

            # Apply playwright-stealth if available
            if STEALTH_AVAILABLE:
                await stealth_async(page)

            # Navigate to video
            await page.goto(url, wait_until='domcontentloaded', timeout=self.config.timeout_ms)
            
            # Wait for JavaScript to render
            await asyncio.sleep(self.config.wait_after_load)
            
            # Additional wait for dynamic content
            try:
                await page.wait_for_selector('script#__UNIVERSAL_DATA_FOR_REHYDRATION__', timeout=5000)
            except:
                pass

            # ── FAST-FAIL CHECK ──────────────────────────────────────────────
            # Detect immediately if TikTok has no data on this page so we avoid
            # running all 5 extraction methods + 3 retries (~40-50s wasted).
            page_status = await check_page_data_status(page)

            if page_status == 'broken':
                elapsed = time.time() - start_time
                logger.warning(f"🔗 Fast-fail (broken) {elapsed:.1f}s: {url[:60]}...")
                self.stats['failed'] += 1
                return {
                    'url': url, 'success': False, 'views': None,
                    'likes': None, 'comments': None, 'shares': None,
                    'publish_date': None,
                    'error': 'video_unavailable', 'is_broken': True,
                    'pending_propagation': False,
                }

            if page_status == 'pending':
                elapsed = time.time() - start_time
                logger.info(f"⏳ Fast-fail (pending) {elapsed:.1f}s: {url[:60]}...")
                # Do NOT count as a failure — video will be retried later
                return {
                    'url': url, 'success': False, 'views': None,
                    'likes': None, 'comments': None, 'shares': None,
                    # Preserve existing date so date-filter works next run
                    'publish_date': existing_publish_date if is_valid_publish_date(existing_publish_date) else None,
                    'error': 'pending_propagation', 'is_broken': False,
                    'pending_propagation': True,
                }
            # ── END FAST-FAIL ────────────────────────────────────────────────

            # Extract data
            data = await extract_video_data(page, url)
            
            self.videos_since_restart += 1
            self.consecutive_crashes = 0
            elapsed = time.time() - start_time
            
            if data and data.get('views', 0) > 0:
                self.stats['success'] += 1
                
                # v3.2: Smart publish_date handling
                final_publish_date = data.get('publish_date')
                
                if self.config.preserve_existing_publish_date:
                    if is_valid_publish_date(existing_publish_date):
                        # Keep existing date
                        final_publish_date = existing_publish_date
                        self.dates_preserved += 1
                        logger.debug(f"📅 Preserved existing date: {existing_publish_date}")
                    elif is_valid_publish_date(data.get('publish_date')):
                        # Use new date from crawl
                        final_publish_date = data.get('publish_date')
                        self.dates_updated += 1
                        logger.debug(f"📅 Updated date: {final_publish_date}")
                    else:
                        final_publish_date = None
                
                channel_id = data.get('channel_id', '')
                logger.info(
                    f"✅ [{self.stats['success']}/{self.stats['total']}] "
                    f"Views: {data['views']:,} | Date: {final_publish_date or 'N/A'} | "
                    f"Channel: @{channel_id or '?'} | {elapsed:.1f}s"
                )

                return {
                    'url': url,
                    'success': True,
                    'views': data['views'],
                    'likes': data.get('likes', 0),
                    'comments': data.get('comments', 0),
                    'shares': data.get('shares', 0),
                    'publish_date': final_publish_date,
                    'channel_id': channel_id,
                    'is_broken': False
                }
            else:
                raise Exception("No data extracted")
                
        except PlaywrightTimeout:
            elapsed = time.time() - start_time
            logger.warning(f"⏱️ Timeout after {elapsed:.1f}s: {url[:60]}...")
            
            if retry_count < self.config.max_retries:
                await self.start_browser(self.browser_type)
                return await self.crawl_single(url, existing_publish_date, retry_count + 1)
            
            self.stats['failed'] += 1
            self.failed_urls.append(url)
            
            # Timeout — don't assume broken, preserve existing date
            return {
                'url': url,
                'success': False,
                'views': None,
                'likes': None,
                'comments': None,
                'shares': None,
                'publish_date': existing_publish_date if is_valid_publish_date(existing_publish_date) else None,
                'error': 'Timeout',
                'is_broken': False,
                'pending_propagation': False,
            }
            
        except Exception as e:
            error_msg = str(e)[:100]
            elapsed = time.time() - start_time
            
            # Browser crashed - restart with protection
            if any(x in error_msg.lower() for x in ['closed', 'target', 'crashed', 'disconnected']):
                self.consecutive_crashes += 1
                self.total_crashes += 1
                logger.warning(f"🔄 Browser issue ({self.consecutive_crashes}/{self.config.max_consecutive_crashes}), restarting...")
                
                await asyncio.sleep(self.config.crash_restart_delay)
                gc.collect()
                
                await self.start_browser(self.browser_type)
                
                if retry_count < self.config.max_retries:
                    return await self.crawl_single(url, existing_publish_date, retry_count + 1)
            
            # Retry for other errors
            if retry_count < self.config.max_retries:
                await asyncio.sleep(2 + retry_count)
                return await self.crawl_single(url, existing_publish_date, retry_count + 1)
            
            self.stats['failed'] += 1
            self.failed_urls.append(url)
            
            # Determine if broken link.
            # NOTE: 'no data extracted' is NOT included here — that error means
            # extraction failed but the video may still exist (e.g. TikTok changed
            # their HTML structure). Clearing data for that would be destructive.
            is_broken = any(x in error_msg.lower() for x in ['not found', 'unavailable', 'removed', '404'])
            # Also propagate the pending_propagation flag from fast-fail if it
            # somehow reaches the exception path.
            is_pending = 'pending_propagation' in error_msg.lower()
            
            if is_pending:
                return {
                    'url': url,
                    'success': False,
                    'views': None, 'likes': None, 'comments': None, 'shares': None,
                    'publish_date': existing_publish_date if is_valid_publish_date(existing_publish_date) else None,
                    'error': error_msg,
                    'is_broken': False,
                    'pending_propagation': True,
                }
            elif is_broken and self.config.clear_data_on_broken_link:
                logger.warning(f"🔗 Broken link: {error_msg}")
                return {
                    'url': url,
                    'success': False,
                    'views': None,
                    'likes': None,
                    'comments': None,
                    'shares': None,
                    'publish_date': None,  # Clear for broken
                    'error': error_msg,
                    'is_broken': True,
                    'pending_propagation': False,
                }
            else:
                # Not broken, just failed - preserve date if exists
                return {
                    'url': url,
                    'success': False,
                    'views': None,
                    'likes': None,
                    'comments': None,
                    'shares': None,
                    'publish_date': existing_publish_date if is_valid_publish_date(existing_publish_date) else None,
                    'error': error_msg,
                    'is_broken': False,
                    'pending_propagation': False,
                }
            
        finally:
            if page:
                try:
                    await page.close()
                except:
                    pass
    
    async def retry_failed_with_firefox(self, failed_urls: List[str], existing_dates: Dict[str, str] = None) -> List[Dict]:
        """Retry failed URLs using Firefox browser"""
        if not failed_urls or not self.config.use_firefox_fallback:
            return []
        
        existing_dates = existing_dates or {}
        
        logger.info(f"🦊 Retrying {len(failed_urls)} failed URLs with Firefox...")
        
        results = []
        
        # Start Firefox browser
        if not await self.start_browser('firefox'):
            logger.error("❌ Cannot start Firefox, skipping retry")
            return []
        
        for url in failed_urls:
            self.consecutive_crashes = 0
            existing_date = existing_dates.get(url, '')
            result = await self.crawl_single(url, existing_date, retry_count=self.config.max_retries - 1)
            if result.get('success'):
                results.append(result)
                logger.info(f"🦊 Firefox success: {result.get('views', 0):,} views")
        
        await self.close_browser()
        
        logger.info(f"🦊 Firefox recovered {len(results)}/{len(failed_urls)} videos")
        return results
    
    async def crawl_all(self, urls: List[str], existing_dates: Dict[str, str] = None) -> List[Dict]:
        """
        Crawl all URLs with retry for failed videos
        
        Args:
            urls: List of TikTok video URLs
            existing_dates: Dict mapping URL -> existing publish_date from Lark
        
        Returns:
            List of crawl results
        """
        existing_dates = existing_dates or {}
        
        self.stats = {
            'total': len(urls),
            'success': 0,
            'failed': 0,
            'start_time': time.time(),
        }
        self.failed_urls = []
        self.consecutive_crashes = 0
        self.total_crashes = 0
        self.dates_preserved = 0
        self.dates_updated = 0
        
        logger.info(f"📊 Starting SEQUENTIAL crawl v3.2 of {len(urls)} URLs")
        logger.info(f"⚙️ Config: Timeout={self.config.timeout_ms}ms, Restart every {self.config.restart_browser_every} videos")
        logger.info(f"🛡️ Crash protection: Max {self.config.max_consecutive_crashes} consecutive crashes")
        logger.info(f"📅 Publish date: Preserve existing={self.config.preserve_existing_publish_date}, Clear broken={self.config.clear_data_on_broken_link}")
        
        # Count existing dates
        valid_dates_count = sum(1 for d in existing_dates.values() if is_valid_publish_date(d))
        logger.info(f"📅 Existing valid dates: {valid_dates_count}/{len(urls)}")
        
        # Start browser
        if not await self.start_browser():
            logger.error("❌ Cannot start browser, aborting")
            return []
        
        results = []
        
        try:
            for idx, url in enumerate(urls, 1):
                # Progress log every 25 videos
                if idx % 25 == 1 or idx == len(urls):
                    elapsed = time.time() - self.stats['start_time']
                    rate = idx / elapsed if elapsed > 0 else 0
                    eta = (len(urls) - idx) / rate / 60 if rate > 0 else 0
                    success_rate = (self.stats['success'] / idx * 100) if idx > 0 else 0
                    
                    logger.info(
                        f"📈 Progress: {idx}/{len(urls)} ({idx/len(urls)*100:.0f}%) | "
                        f"✅ {self.stats['success']} ({success_rate:.0f}%) | "
                        f"📅 Dates: {self.dates_preserved} preserved, {self.dates_updated} updated | "
                        f"💥 Crashes: {self.total_crashes} | "
                        f"ETA: {eta:.0f}min"
                    )
                
                logger.info(f"Processing {idx}/{len(urls)}")
                
                # Get existing date for this URL
                existing_date = existing_dates.get(url, '')
                
                result = await self.crawl_single(url, existing_date)
                results.append(result)
                
                # Memory cleanup
                if idx % self.config.memory_cleanup_interval == 0:
                    gc.collect()
            
        finally:
            await self.close_browser()
        
        # ===== RETRY FAILED VIDEOS =====
        if self.config.retry_failed_at_end and self.failed_urls:
            logger.info(f"\n{'='*50}")
            logger.info(f"🔄 Retrying {len(self.failed_urls)} failed videos...")
            logger.info(f"{'='*50}\n")
            
            retry_urls = self.failed_urls.copy()
            self.failed_urls = []
            self.consecutive_crashes = 0
            
            # First retry with Chromium (fresh browser)
            if not await self.start_browser('chromium'):
                logger.error("❌ Cannot restart browser for retry")
            else:
                for url in retry_urls:
                    for i, r in enumerate(results):
                        if r['url'] == url and not r['success']:
                            existing_date = existing_dates.get(url, '')
                            new_result = await self.crawl_single(url, existing_date, retry_count=0)
                            if new_result.get('success'):
                                results[i] = new_result
                                if url in self.failed_urls:
                                    self.failed_urls.remove(url)
                            break
                
                await self.close_browser()
            
            # Firefox fallback for still-failed videos
            if self.config.use_firefox_fallback and self.failed_urls:
                firefox_results = await self.retry_failed_with_firefox(self.failed_urls.copy(), existing_dates)
                
                for fx_result in firefox_results:
                    for i, r in enumerate(results):
                        if r['url'] == fx_result['url'] and not r['success']:
                            results[i] = fx_result
                            break
        
        # Final stats
        final_success = sum(1 for r in results if r.get('success'))
        final_failed = len(results) - final_success
        final_broken = sum(1 for r in results if r.get('is_broken'))
        elapsed = time.time() - self.stats['start_time']
        success_rate = (final_success / len(urls) * 100) if urls else 0
        
        logger.info(f"""
╔════════════════════════════════════════════════════════════╗
║                  CRAWL COMPLETE v3.2                        ║
╠════════════════════════════════════════════════════════════╣
║  Total: {len(urls):>5} videos                                    ║
║  Success: {final_success:>4} ({success_rate:.1f}%)                              ║
║  Failed: {final_failed:>5} (Broken: {final_broken})                            ║
║  Crashes: {self.total_crashes:>4}                                         ║
║  📅 Dates preserved: {self.dates_preserved:>4}                              ║
║  📅 Dates updated: {self.dates_updated:>6}                              ║
║  Time: {elapsed/60:.1f} minutes                                    ║
║  Speed: {elapsed/len(urls):.1f}s per video                              ║
╚════════════════════════════════════════════════════════════╝
        """)
        
        # Log failed URLs
        if self.failed_urls:
            logger.warning(f"⚠️ Still failed after all retries: {len(self.failed_urls)} URLs")
            for url in self.failed_urls[:10]:
                logger.warning(f"   - {url}")
            if len(self.failed_urls) > 10:
                logger.warning(f"   ... and {len(self.failed_urls) - 10} more")
        
        return results


# ============================================================================
# SYNC WRAPPER FOR FASTAPI
# ============================================================================

class TikTokPlaywrightCrawler:
    """Synchronous wrapper for FastAPI compatibility"""
    
    def __init__(self):
        self.config = CrawlerConfig()
        stealth_status = "enabled" if STEALTH_AVAILABLE else "disabled (install playwright-stealth for better results)"
        logger.info(f"✅ TikTokPlaywrightCrawler v3.2 initialized | Stealth: {stealth_status}")
    
    def get_tiktok_views(self, video_url: str) -> Optional[Dict]:
        """Get single video stats"""
        try:
            return self._run_in_thread(self._async_get_single, video_url)
        except Exception as e:
            logger.error(f"❌ Error: {e}")
            return None
    
    def crawl_batch_sync(self, urls: List[str], existing_dates: Dict[str, str] = None) -> List[Dict]:
        """
        Crawl multiple URLs with retry logic
        
        Args:
            urls: List of TikTok video URLs
            existing_dates: Dict mapping URL -> existing publish_date (to preserve)
        """
        logger.info(f"📋 crawl_batch_sync v3.2 called with {len(urls)} URLs")
        
        try:
            result = self._run_in_thread(self._async_batch, urls, existing_dates or {})
            success_count = sum(1 for r in result if r.get('success'))
            logger.info(f"✅ Completed: {success_count}/{len(result)} successful ({success_count/len(result)*100:.1f}%)")
            return result
        except Exception as e:
            logger.error(f"❌ Batch error: {e}")
            logger.error(traceback.format_exc())
            return []
    
    def _run_in_thread(self, async_func, *args):
        """Run async function in separate thread"""
        def thread_target():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                return loop.run_until_complete(async_func(*args))
            finally:
                loop.close()
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(thread_target)
            return future.result(timeout=18000)  # 5 hour timeout
    
    async def _async_get_single(self, url: str) -> Optional[Dict]:
        """Async single video"""
        crawler = SequentialTikTokCrawler(self.config)
        try:
            if not await crawler.start_browser():
                return None
            result = await crawler.crawl_single(url)
            return result if result.get('success') else None
        finally:
            await crawler.close_browser()
    
    async def _async_batch(self, urls: List[str], existing_dates: Dict[str, str]) -> List[Dict]:
        """Async batch with retry"""
        crawler = SequentialTikTokCrawler(self.config)
        try:
            return await crawler.crawl_all(urls, existing_dates)
        except Exception as e:
            logger.error(f"❌ Exception: {e}")
            logger.error(traceback.format_exc())
            return []


# ============================================================================
# TEST
# ============================================================================

async def test_crawler():
    """Test crawler with sample URLs"""
    test_urls = [
        "https://www.tiktok.com/@tiktok/video/7449807305491698990",
        "https://www.tiktok.com/@tiktok/video/7447866792555382058",
    ]
    
    # Simulate existing dates from Lark
    existing_dates = {
        test_urls[0]: "2024-01-15",  # Has existing date - should preserve
        test_urls[1]: "",             # No date - should update
    }
    
    print(f"\n🧪 Testing Crawler v3.2 with {len(test_urls)} URLs\n")
    print(f"📅 Existing dates: {existing_dates}\n")
    
    crawler = SequentialTikTokCrawler()
    results = await crawler.crawl_all(test_urls, existing_dates)
    
    print("\n📊 Results:")
    for result in results:
        if result.get('success'):
            print(f"✅ Views: {result['views']:,} | Date: {result['publish_date']} | {result['url'][:50]}...")
        else:
            print(f"❌ Failed: {result.get('error', 'Unknown')} | Broken: {result.get('is_broken')} | {result['url'][:50]}...")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    asyncio.run(test_crawler())
