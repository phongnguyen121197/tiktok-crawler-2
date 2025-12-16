"""
🚀 TikTok Playwright Crawler v3.0 - PRODUCTION STABLE
======================================================
FIXES:
- ✅ playwright-stealth for anti-bot detection bypass
- ✅ Multiple extraction methods with comprehensive fallbacks
- ✅ URL validation before crawling
- ✅ Auto-retry failed videos at end with fresh browser
- ✅ Firefox fallback for stubborn videos
- ✅ Human-like random delays
- ✅ Better error logging with URL tracking
- ✅ Preserves existing Lark data on failure
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
    """Configuration for v3 crawler with better defaults"""
    delay_range: Tuple[float, float] = (2.0, 4.0)      # Increased human-like delays
    timeout_ms: int = 30000                             # 30 seconds timeout
    max_retries: int = 3                                # More retries
    restart_browser_every: int = 75                     # Restart more frequently
    browser_close_timeout: int = 15                     # Longer close timeout
    wait_after_load: float = 2.5                        # Wait for JS to render
    retry_failed_at_end: bool = True                    # Re-crawl failed videos
    use_firefox_fallback: bool = True                   # Try Firefox for failed videos
    max_end_retries: int = 2                            # Max retries at end


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
                        data = {
                            'views': views,
                            'likes': stats.get('diggCount', 0),
                            'comments': stats.get('commentCount', 0),
                            'shares': stats.get('shareCount', 0),
                            'publish_date': convert_timestamp_to_date(item.get('createTime')),
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
                            data = {
                                'views': views,
                                'likes': stats.get('diggCount', 0),
                                'comments': stats.get('commentCount', 0),
                                'shares': stats.get('shareCount', 0),
                                'publish_date': convert_timestamp_to_date(video_data.get('createTime')),
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
                            data = {
                                'views': views,
                                'likes': stats.get('diggCount', 0),
                                'comments': stats.get('commentCount', 0),
                                'shares': stats.get('shareCount', 0),
                                'publish_date': convert_timestamp_to_date(item_info.get('createTime')),
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
                    
                    data = {
                        'views': views,
                        'likes': int(likes_match.group(1)) if likes_match else 0,
                        'comments': int(comments_match.group(1)) if comments_match else 0,
                        'shares': int(shares_match.group(1)) if shares_match else 0,
                        'publish_date': publish_date,
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
            logger.debug(f"✅ Extracted via {extraction_method}: {data['views']:,} views")
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
# SEQUENTIAL CRAWLER v3
# ============================================================================

class SequentialTikTokCrawler:
    """
    Sequential TikTok crawler v3 with improved reliability
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
    
    async def start_browser(self, browser_type: str = 'chromium'):
        """Start or restart browser with stealth settings"""
        await self.close_browser()
        
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
                '--window-size=1920,1080',
                '--start-maximized',
            ]
            
            if browser_type == 'firefox':
                self.browser = await self.playwright.firefox.launch(
                    headless=True,
                    args=['--width=1920', '--height=1080']
                )
            else:
                self.browser = await self.playwright.chromium.launch(
                    headless=True,
                    args=launch_args
                )
            
            # Create context with realistic settings
            self.context = await self.browser.new_context(
                viewport={'width': 1920, 'height': 1080},
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
    
    async def crawl_single(self, url: str, retry_count: int = 0) -> Dict:
        """Crawl a single URL with comprehensive error handling"""
        
        # Validate URL first
        is_valid, result = validate_tiktok_url(url)
        if not is_valid:
            logger.warning(f"❌ Invalid URL skipped: {result}")
            self.stats['failed'] += 1
            return {'url': url, 'success': False, 'views': 0, 'error': result}
        
        url = result  # Use cleaned URL
        
        # Check if browser restart needed
        if self.videos_since_restart >= self.config.restart_browser_every:
            logger.info(f"🔄 Restarting browser after {self.videos_since_restart} videos...")
            await self.start_browser(self.browser_type)
            gc.collect()
        
        # Ensure browser is running
        if not self.browser or not self.context:
            if not await self.start_browser(self.browser_type):
                return {'url': url, 'success': False, 'views': 0, 'error': 'Browser failed to start'}
        
        page = None
        start_time = time.time()
        
        try:
            # Random human-like delay
            delay = random.uniform(*self.config.delay_range)
            await asyncio.sleep(delay)
            
            # Create new page
            page = await self.context.new_page()
            
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
                pass  # Script might not exist, continue anyway
            
            # Extract data
            data = await extract_video_data(page, url)
            
            self.videos_since_restart += 1
            elapsed = time.time() - start_time
            
            if data and data.get('views', 0) > 0:
                self.stats['success'] += 1
                logger.info(f"✅ [{self.stats['success']}/{self.stats['total']}] Views: {data['views']:,} | {elapsed:.1f}s")
                return {
                    'url': url,
                    'success': True,
                    'views': data['views'],
                    'likes': data.get('likes', 0),
                    'comments': data.get('comments', 0),
                    'shares': data.get('shares', 0),
                    'publish_date': data.get('publish_date', ''),
                }
            else:
                raise Exception("No data extracted")
                
        except PlaywrightTimeout:
            elapsed = time.time() - start_time
            logger.warning(f"⏱️ Timeout after {elapsed:.1f}s: {url[:60]}...")
            
            if retry_count < self.config.max_retries:
                await self.start_browser(self.browser_type)
                return await self.crawl_single(url, retry_count + 1)
            
            self.stats['failed'] += 1
            self.failed_urls.append(url)
            return {'url': url, 'success': False, 'views': 0, 'error': 'Timeout'}
            
        except Exception as e:
            error_msg = str(e)[:100]
            elapsed = time.time() - start_time
            
            # Browser crashed - restart
            if any(x in error_msg.lower() for x in ['closed', 'target', 'crashed', 'disconnected']):
                logger.warning(f"🔄 Browser issue, restarting...")
                await self.start_browser(self.browser_type)
                
                if retry_count < self.config.max_retries:
                    return await self.crawl_single(url, retry_count + 1)
            
            # Retry for other errors
            if retry_count < self.config.max_retries:
                await asyncio.sleep(2 + retry_count)
                return await self.crawl_single(url, retry_count + 1)
            
            self.stats['failed'] += 1
            self.failed_urls.append(url)
            logger.warning(f"❌ Failed after {retry_count} retries: {error_msg}")
            return {'url': url, 'success': False, 'views': 0, 'error': error_msg}
            
        finally:
            if page:
                try:
                    await page.close()
                except:
                    pass
    
    async def retry_failed_with_firefox(self, failed_urls: List[str]) -> List[Dict]:
        """Retry failed URLs using Firefox browser"""
        if not failed_urls or not self.config.use_firefox_fallback:
            return []
        
        logger.info(f"🦊 Retrying {len(failed_urls)} failed URLs with Firefox...")
        
        results = []
        
        # Start Firefox browser
        if not await self.start_browser('firefox'):
            logger.error("❌ Cannot start Firefox, skipping retry")
            return []
        
        for url in failed_urls:
            # Reset retry count for Firefox attempt
            result = await self.crawl_single(url, retry_count=self.config.max_retries - 1)
            if result.get('success'):
                results.append(result)
                logger.info(f"🦊 Firefox success: {result.get('views', 0):,} views")
        
        await self.close_browser()
        
        logger.info(f"🦊 Firefox recovered {len(results)}/{len(failed_urls)} videos")
        return results
    
    async def crawl_all(self, urls: List[str]) -> List[Dict]:
        """Crawl all URLs with retry for failed videos"""
        self.stats = {
            'total': len(urls),
            'success': 0,
            'failed': 0,
            'start_time': time.time(),
        }
        self.failed_urls = []
        
        logger.info(f"📊 Starting SEQUENTIAL crawl v3.0 of {len(urls)} URLs")
        logger.info(f"⚙️ Config: Timeout={self.config.timeout_ms}ms, Restart every {self.config.restart_browser_every} videos")
        
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
                        f"ETA: {eta:.0f}min"
                    )
                
                result = await self.crawl_single(url)
                results.append(result)
                
                # Garbage collection every 50 videos
                if idx % 50 == 0:
                    gc.collect()
            
        finally:
            await self.close_browser()
        
        # ===== RETRY FAILED VIDEOS =====
        if self.config.retry_failed_at_end and self.failed_urls:
            logger.info(f"\n{'='*50}")
            logger.info(f"🔄 Retrying {len(self.failed_urls)} failed videos...")
            logger.info(f"{'='*50}\n")
            
            # Track which URLs we're retrying
            retry_urls = self.failed_urls.copy()
            self.failed_urls = []
            
            # First retry with Chromium (fresh browser)
            if not await self.start_browser('chromium'):
                logger.error("❌ Cannot restart browser for retry")
            else:
                for url in retry_urls:
                    # Find and update result
                    for i, r in enumerate(results):
                        if r['url'] == url and not r['success']:
                            new_result = await self.crawl_single(url, retry_count=0)
                            if new_result.get('success'):
                                results[i] = new_result
                                # Remove from failed list if it was re-added
                                if url in self.failed_urls:
                                    self.failed_urls.remove(url)
                            break
                
                await self.close_browser()
            
            # Firefox fallback for still-failed videos
            if self.config.use_firefox_fallback and self.failed_urls:
                firefox_results = await self.retry_failed_with_firefox(self.failed_urls.copy())
                
                for fx_result in firefox_results:
                    for i, r in enumerate(results):
                        if r['url'] == fx_result['url'] and not r['success']:
                            results[i] = fx_result
                            break
        
        # Final stats
        final_success = sum(1 for r in results if r.get('success'))
        final_failed = len(results) - final_success
        elapsed = time.time() - self.stats['start_time']
        success_rate = (final_success / len(urls) * 100) if urls else 0
        
        logger.info(f"""
╔════════════════════════════════════════════════════════════╗
║                  CRAWL COMPLETE v3.0                        ║
╠════════════════════════════════════════════════════════════╣
║  Total: {len(urls):>5} videos                                    ║
║  Success: {final_success:>4} ({success_rate:.1f}%)                              ║
║  Failed: {final_failed:>5}                                         ║
║  Time: {elapsed/60:.1f} minutes                                    ║
║  Speed: {elapsed/len(urls):.1f}s per video                              ║
╚════════════════════════════════════════════════════════════╝
        """)
        
        # Log failed URLs for manual review
        if self.failed_urls:
            logger.warning(f"⚠️ Still failed after all retries: {len(self.failed_urls)} URLs")
            for url in self.failed_urls[:10]:  # Log first 10
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
        logger.info(f"✅ TikTokPlaywrightCrawler v3.0 initialized | Stealth: {stealth_status}")
    
    def get_tiktok_views(self, video_url: str) -> Optional[Dict]:
        """Get single video stats"""
        try:
            return self._run_in_thread(self._async_get_single, video_url)
        except Exception as e:
            logger.error(f"❌ Error: {e}")
            return None
    
    def crawl_batch_sync(self, urls: List[str]) -> List[Dict]:
        """Crawl multiple URLs with retry logic"""
        logger.info(f"📋 crawl_batch_sync v3.0 called with {len(urls)} URLs")
        
        try:
            result = self._run_in_thread(self._async_batch, urls)
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
    
    async def _async_batch(self, urls: List[str]) -> List[Dict]:
        """Async batch with retry"""
        crawler = SequentialTikTokCrawler(self.config)
        try:
            return await crawler.crawl_all(urls)
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
        "invalid-url",  # Test URL validation
        "",  # Test empty URL
    ]
    
    print(f"\n🧪 Testing Crawler v3.0 with {len(test_urls)} URLs\n")
    
    crawler = SequentialTikTokCrawler()
    results = await crawler.crawl_all(test_urls)
    
    print("\n📊 Results:")
    for result in results:
        if result.get('success'):
            print(f"✅ Views: {result['views']:,} | {result['url'][:50]}...")
        else:
            print(f"❌ Failed: {result.get('error', 'Unknown')} | {result['url'][:50]}...")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    asyncio.run(test_crawler())
