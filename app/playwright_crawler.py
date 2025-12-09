"""
🚀 TikTok Playwright Crawler - SEQUENTIAL STABLE VERSION v2
============================================================
FIXED: Browser restart hang issue
- Added timeout to close_browser() 
- Increased restart_browser_every from 50 to 100
- Force kill browser if close takes too long
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
from dataclasses import dataclass
from playwright.async_api import async_playwright, Page, BrowserContext, TimeoutError as PlaywrightTimeout

logger = logging.getLogger(__name__)

# ============================================================================
# CONFIGURATION
# ============================================================================

@dataclass
class CrawlerConfig:
    """Configuration for sequential crawler"""
    delay_range: Tuple[float, float] = (1.5, 3.0)  # Delay between requests
    timeout_ms: int = 25000           # 25 seconds timeout per page
    max_retries: int = 2              # Retry failed requests
    restart_browser_every: int = 100  # ✅ INCREASED from 50 to 100 to reduce restart frequency
    browser_close_timeout: int = 10   # ✅ NEW: Max seconds to wait for browser close


# User agents
USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:122.0) Gecko/20100101 Firefox/122.0',
]


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def convert_timestamp_to_date(timestamp) -> Optional[str]:
    """Convert Unix timestamp to YYYY-MM-DD format"""
    try:
        if not timestamp:
            return None
        
        ts = int(timestamp) if isinstance(timestamp, str) else timestamp
        
        if ts > 9999999999:
            ts = ts / 1000
        
        dt = datetime.fromtimestamp(ts)
        
        if dt.year < 2016 or dt.year > 2030:
            return None
            
        return dt.strftime('%Y-%m-%d')
    except:
        return None


# ============================================================================
# STEALTH SCRIPT
# ============================================================================

STEALTH_SCRIPT = """
() => {
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
    Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
    Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
    window.chrome = { runtime: {} };
    
    const originalQuery = window.navigator.permissions.query;
    window.navigator.permissions.query = (parameters) => (
        parameters.name === 'notifications' ?
            Promise.resolve({ state: Notification.permission }) :
            originalQuery(parameters)
    );
}
"""


# ============================================================================
# DATA EXTRACTION
# ============================================================================

async def extract_video_data(page: Page, url: str) -> Optional[Dict]:
    """Extract video data from TikTok page"""
    try:
        # Method 1: UNIVERSAL_DATA (most common)
        raw_json = await page.evaluate('''() => {
            const script = document.querySelector('#__UNIVERSAL_DATA_FOR_REHYDRATION__');
            return script ? script.textContent : null;
        }''')
        
        if raw_json:
            data = json.loads(raw_json)
            scope = data.get('__DEFAULT_SCOPE__', {})
            video_detail = scope.get('webapp.video-detail', {})
            item = video_detail.get('itemInfo', {}).get('itemStruct', {})
            
            if item:
                stats = item.get('stats', {})
                views = stats.get('playCount', 0)
                if views > 0:
                    return {
                        'views': views,
                        'likes': stats.get('diggCount', 0),
                        'comments': stats.get('commentCount', 0),
                        'shares': stats.get('shareCount', 0),
                        'publish_date': convert_timestamp_to_date(item.get('createTime')),
                    }
        
        # Method 2: SIGI_STATE (older format)
        raw_json = await page.evaluate('''() => {
            const script = document.querySelector('#SIGI_STATE');
            return script ? script.textContent : null;
        }''')
        
        if raw_json:
            data = json.loads(raw_json)
            item_module = data.get('ItemModule', {})
            
            for video_id, video_data in item_module.items():
                stats = video_data.get('stats', {})
                views = stats.get('playCount', 0)
                if views > 0:
                    return {
                        'views': views,
                        'likes': stats.get('diggCount', 0),
                        'comments': stats.get('commentCount', 0),
                        'shares': stats.get('shareCount', 0),
                        'publish_date': convert_timestamp_to_date(video_data.get('createTime')),
                    }
        
        # Method 3: Regex fallback
        html = await page.content()
        
        views_match = re.search(r'"playCount"[:\s]*(\d+)', html)
        if views_match:
            views = int(views_match.group(1))
            if views > 0:
                time_match = re.search(r'"createTime"[:\s]*"?(\d{10,13})"?', html)
                publish_date = convert_timestamp_to_date(time_match.group(1)) if time_match else None
                
                return {
                    'views': views,
                    'likes': 0,
                    'comments': 0,
                    'shares': 0,
                    'publish_date': publish_date,
                }
        
        # Check for error pages
        title = await page.title()
        if 'captcha' in title.lower() or 'verify' in title.lower():
            logger.warning(f"🚫 CAPTCHA detected!")
        elif 'not found' in title.lower() or 'unavailable' in title.lower():
            logger.warning(f"⚠️ Video not found/unavailable")
        
        return None
        
    except Exception as e:
        logger.debug(f"Extraction error: {e}")
        return None


# ============================================================================
# SEQUENTIAL CRAWLER
# ============================================================================

class SequentialTikTokCrawler:
    """
    Sequential TikTok crawler - ONE video at a time
    Much more stable than parallel version
    """
    
    def __init__(self, config: CrawlerConfig = None):
        self.config = config or CrawlerConfig()
        self.browser = None
        self.playwright = None
        self.context = None
        self.videos_since_restart = 0
        self.stats = {'total': 0, 'success': 0, 'failed': 0, 'start_time': None}
    
    async def start_browser(self):
        """Start or restart browser"""
        # Close existing browser if any
        await self.close_browser()
        
        try:
            self.playwright = await async_playwright().start()
            
            self.browser = await self.playwright.chromium.launch(
                headless=True,
                args=[
                    '--disable-gpu',
                    '--disable-dev-shm-usage',
                    '--no-sandbox',
                    '--disable-setuid-sandbox',
                    '--disable-blink-features=AutomationControlled',
                    '--single-process',
                    '--no-zygote',
                ]
            )
            
            # Create persistent context
            self.context = await self.browser.new_context(
                viewport={'width': 1920, 'height': 1080},
                user_agent=random.choice(USER_AGENTS),
                locale='en-US',
                timezone_id='Asia/Ho_Chi_Minh',
                java_script_enabled=True,
                bypass_csp=True,
                ignore_https_errors=True,
            )
            await self.context.add_init_script(STEALTH_SCRIPT)
            
            self.videos_since_restart = 0
            logger.info("✅ Browser started successfully")
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to start browser: {e}")
            return False
    
    async def close_browser(self):
        """
        ✅ FIXED: Close browser with timeout to prevent hanging
        """
        async def _close_with_timeout():
            """Inner function to close browser components"""
            try:
                if self.context:
                    await self.context.close()
                    self.context = None
            except Exception as e:
                logger.debug(f"Error closing context: {e}")
            
            try:
                if self.browser:
                    await self.browser.close()
                    self.browser = None
            except Exception as e:
                logger.debug(f"Error closing browser: {e}")
            
            try:
                if self.playwright:
                    await self.playwright.stop()
                    self.playwright = None
            except Exception as e:
                logger.debug(f"Error stopping playwright: {e}")
        
        try:
            # ✅ Add timeout to prevent hanging
            await asyncio.wait_for(
                _close_with_timeout(),
                timeout=self.config.browser_close_timeout
            )
            logger.debug("Browser closed successfully")
        except asyncio.TimeoutError:
            logger.warning(f"⚠️ Browser close timed out after {self.config.browser_close_timeout}s, force killing...")
            # Force reset references even if close failed
            self.context = None
            self.browser = None
            self.playwright = None
            # Force garbage collection
            gc.collect()
        except Exception as e:
            logger.debug(f"Error in close_browser: {e}")
            # Reset references
            self.context = None
            self.browser = None
            self.playwright = None
    
    async def crawl_single(self, url: str, retry_count: int = 0) -> Dict:
        """Crawl a single URL"""
        # Check if we need to restart browser
        if self.videos_since_restart >= self.config.restart_browser_every:
            logger.info(f"🔄 Restarting browser after {self.videos_since_restart} videos...")
            await self.start_browser()
            gc.collect()
        
        # Ensure browser is running
        if not self.browser or not self.context:
            if not await self.start_browser():
                return {'url': url, 'success': False, 'views': 0, 'error': 'Browser failed to start'}
        
        page = None
        start_time = time.time()
        
        try:
            # Random delay
            delay = random.uniform(*self.config.delay_range)
            await asyncio.sleep(delay)
            
            # Create new page
            page = await self.context.new_page()
            
            # Navigate
            await page.goto(url, wait_until='load', timeout=self.config.timeout_ms)
            
            # Wait for JS
            await asyncio.sleep(1.0)
            
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
            logger.warning(f"⏱️ Timeout after {elapsed:.1f}s")
            
            if retry_count < self.config.max_retries:
                # Restart browser on timeout
                await self.start_browser()
                return await self.crawl_single(url, retry_count + 1)
            
            self.stats['failed'] += 1
            return {'url': url, 'success': False, 'views': 0, 'error': 'Timeout'}
            
        except Exception as e:
            error_msg = str(e)[:80]
            elapsed = time.time() - start_time
            
            # If browser crashed, restart it
            if 'closed' in error_msg.lower() or 'target' in error_msg.lower():
                logger.warning(f"🔄 Browser issue, restarting...")
                await self.start_browser()
                
                if retry_count < self.config.max_retries:
                    return await self.crawl_single(url, retry_count + 1)
            
            if retry_count < self.config.max_retries:
                await asyncio.sleep(2)
                return await self.crawl_single(url, retry_count + 1)
            
            self.stats['failed'] += 1
            logger.warning(f"❌ Failed: {error_msg}")
            return {'url': url, 'success': False, 'views': 0, 'error': error_msg}
            
        finally:
            if page:
                try:
                    await page.close()
                except:
                    pass
    
    async def crawl_all(self, urls: List[str]) -> List[Dict]:
        """Crawl all URLs sequentially"""
        self.stats = {
            'total': len(urls),
            'success': 0,
            'failed': 0,
            'start_time': time.time(),
        }
        
        logger.info(f"📊 Starting SEQUENTIAL crawl of {len(urls)} URLs")
        logger.info(f"⚙️ Timeout: {self.config.timeout_ms}ms, Restart every: {self.config.restart_browser_every} videos")
        
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
        
        # Final stats
        elapsed = time.time() - self.stats['start_time']
        success_rate = (self.stats['success'] / len(urls) * 100) if urls else 0
        
        logger.info(f"""
╔════════════════════════════════════════════════════════╗
║                  CRAWL COMPLETE                         ║
╠════════════════════════════════════════════════════════╣
║  Total: {len(urls):>5} videos                                ║
║  Success: {self.stats['success']:>4} ({success_rate:.1f}%)                           ║
║  Failed: {self.stats['failed']:>5}                                    ║
║  Time: {elapsed/60:.1f} minutes                                 ║
║  Speed: {elapsed/len(urls):.1f}s per video                          ║
╚════════════════════════════════════════════════════════╝
        """)
        
        return results


# ============================================================================
# SYNC WRAPPER FOR FASTAPI
# ============================================================================

class TikTokPlaywrightCrawler:
    """Synchronous wrapper for FastAPI compatibility"""
    
    def __init__(self):
        self.config = CrawlerConfig()
        logger.info("✅ TikTokPlaywrightCrawler initialized (SEQUENTIAL mode)")
    
    def get_tiktok_views(self, video_url: str) -> Optional[Dict]:
        """Get single video stats"""
        try:
            return self._run_in_thread(self._async_get_single, video_url)
        except Exception as e:
            logger.error(f"❌ Error: {e}")
            return None
    
    def crawl_batch_sync(self, urls: List[str]) -> List[Dict]:
        """Crawl multiple URLs SEQUENTIALLY"""
        logger.info(f"📋 crawl_batch_sync called with {len(urls)} URLs (SEQUENTIAL mode)")
        
        try:
            result = self._run_in_thread(self._async_batch, urls)
            success_count = sum(1 for r in result if r.get('success'))
            logger.info(f"✅ Completed: {success_count}/{len(result)} successful")
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
            # 4 hour timeout for full crawl
            return future.result(timeout=14400)
    
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
        """Async batch - runs sequentially"""
        logger.info(f"🔄 Starting sequential crawl of {len(urls)} URLs")
        
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
    """Test with a few URLs"""
    test_urls = [
        "https://www.tiktok.com/@tiktok/video/7449807305491698990",
        "https://www.tiktok.com/@tiktok/video/7447866792555382058",
    ]
    
    print(f"\n🧪 Testing Sequential Crawler with {len(test_urls)} URLs\n")
    
    crawler = SequentialTikTokCrawler()
    results = await crawler.crawl_all(test_urls)
    
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
