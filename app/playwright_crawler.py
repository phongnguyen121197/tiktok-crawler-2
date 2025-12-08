"""
🚀 OPTIMIZED TikTok Playwright Crawler - FIXED VERSION
======================================================
- Fixed async/sync compatibility with FastAPI
- Better error handling and timeouts
- Progress logging that actually works
"""

import asyncio
import json
import random
import gc
import time
import re
import logging
import concurrent.futures
from datetime import datetime
from typing import Optional, Dict, List, Tuple
from dataclasses import dataclass
from playwright.async_api import async_playwright, Page, BrowserContext

logger = logging.getLogger(__name__)

# ============================================================================
# CONFIGURATION
# ============================================================================

@dataclass
class CrawlerConfig:
    """Configuration for the optimized crawler"""
    max_concurrent: int = 8           # Reduced from 10 for stability
    delay_range: Tuple[float, float] = (1.0, 2.0)  # Slightly longer delays
    timeout_ms: int = 20000           # 20 seconds timeout
    max_retries: int = 2              # Retry failed requests
    gc_interval: int = 50             # Run garbage collection every N pages
    batch_size: int = 50              # Process in batches for progress reporting


# Resources to block
BLOCKED_RESOURCE_TYPES = {
    'image', 'media', 'font', 'stylesheet', 
    'beacon', 'imageset', 'texttrack', 'websocket',
    'manifest', 'other'
}

# URL patterns to block
BLOCKED_URL_PATTERNS = [
    'analytics', 'tracking', 'doubleclick', 'googletagmanager',
    'facebook.com', 'google-analytics', 'hotjar',
    'tiktokcdn-us.com/obj/',
    'tiktokcdn.com/obj/',
    '.mp4', '.webp', '.jpg', '.png', '.gif', '.woff', '.woff2',
]

# User agents pool
USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
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


def parse_count(count_str: str) -> int:
    """Parse TikTok count string to integer"""
    if not count_str:
        return 0
    
    count_str = str(count_str).strip().upper()
    
    try:
        count_str = re.sub(r'[^\d.KMB]', '', count_str)
        if not count_str:
            return 0
        
        multipliers = {'K': 1000, 'M': 1000000, 'B': 1000000000}
        
        for suffix, multiplier in multipliers.items():
            if suffix in count_str:
                number = float(count_str.replace(suffix, ''))
                return int(number * multiplier)
        
        return int(float(count_str))
    except:
        return 0


# ============================================================================
# ROUTE HANDLER
# ============================================================================

async def route_handler(route):
    """Block unnecessary resources"""
    request = route.request
    
    if request.resource_type in BLOCKED_RESOURCE_TYPES:
        await route.abort()
        return
    
    url = request.url.lower()
    for pattern in BLOCKED_URL_PATTERNS:
        if pattern in url:
            await route.abort()
            return
    
    await route.continue_()


# ============================================================================
# STEALTH SCRIPT
# ============================================================================

STEALTH_SCRIPT = """
() => {
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
    Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
    Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en', 'vi'] });
    window.chrome = { runtime: {}, loadTimes: function() {}, csi: function() {}, app: {} };
}
"""


# ============================================================================
# DATA EXTRACTION
# ============================================================================

async def extract_video_data_fast(page: Page, url: str) -> Optional[Dict]:
    """Extract video data from TikTok's embedded JSON"""
    try:
        # Method 1: UNIVERSAL_DATA
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
                return {
                    'views': stats.get('playCount', 0),
                    'likes': stats.get('diggCount', 0),
                    'comments': stats.get('commentCount', 0),
                    'shares': stats.get('shareCount', 0),
                    'publish_date': convert_timestamp_to_date(item.get('createTime')),
                }
        
        # Method 2: SIGI_STATE
        raw_json = await page.evaluate('''() => {
            const script = document.querySelector('#SIGI_STATE');
            return script ? script.textContent : null;
        }''')
        
        if raw_json:
            data = json.loads(raw_json)
            item_module = data.get('ItemModule', {})
            
            for video_id, video_data in item_module.items():
                stats = video_data.get('stats', {})
                return {
                    'views': stats.get('playCount', 0),
                    'likes': stats.get('diggCount', 0),
                    'comments': stats.get('commentCount', 0),
                    'shares': stats.get('shareCount', 0),
                    'publish_date': convert_timestamp_to_date(video_data.get('createTime')),
                }
        
        # Method 3: Regex fallback
        html = await page.content()
        
        views_match = re.search(r'"playCount"[:\s]*(\d+)', html)
        views = int(views_match.group(1)) if views_match else 0
        
        time_match = re.search(r'"createTime"[:\s]*"?(\d{10,13})"?', html)
        publish_date = convert_timestamp_to_date(time_match.group(1)) if time_match else None
        
        if views > 0:
            return {
                'views': views,
                'likes': 0,
                'comments': 0,
                'shares': 0,
                'publish_date': publish_date,
            }
        
        return None
        
    except Exception as e:
        logger.debug(f"Extraction error for {url}: {e}")
        return None


# ============================================================================
# MAIN CRAWLER CLASS
# ============================================================================

class OptimizedTikTokCrawler:
    """High-performance TikTok crawler with parallel processing"""
    
    def __init__(self, config: CrawlerConfig = None):
        self.config = config or CrawlerConfig()
        self.semaphore = None
        self.browser = None
        self.playwright = None
        self.stats = {'total': 0, 'success': 0, 'failed': 0, 'start_time': None}
    
    async def start(self):
        """Initialize browser"""
        try:
            self.semaphore = asyncio.Semaphore(self.config.max_concurrent)
            self.playwright = await async_playwright().start()
            
            self.browser = await self.playwright.chromium.launch(
                headless=True,
                args=[
                    '--disable-gpu',
                    '--disable-dev-shm-usage',
                    '--no-sandbox',
                    '--disable-setuid-sandbox',
                    '--disable-extensions',
                    '--disable-background-networking',
                    '--disable-blink-features=AutomationControlled',
                    '--disable-features=IsolateOrigins,site-per-process',
                    '--memory-pressure-off',
                    '--single-process',
                ]
            )
            
            logger.info(f"🚀 Browser started with {self.config.max_concurrent} concurrent contexts")
            return True
        except Exception as e:
            logger.error(f"❌ Failed to start browser: {e}")
            return False
    
    async def stop(self):
        """Cleanup browser"""
        try:
            if self.browser:
                await self.browser.close()
            if self.playwright:
                await self.playwright.stop()
            logger.info("🛑 Browser closed")
        except Exception as e:
            logger.error(f"⚠️ Error closing browser: {e}")
    
    async def _create_context(self) -> BrowserContext:
        """Create a new browser context"""
        context = await self.browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent=random.choice(USER_AGENTS),
            locale='en-US',
            timezone_id='Asia/Ho_Chi_Minh',
            java_script_enabled=True,
            bypass_csp=True,
            ignore_https_errors=True,
        )
        await context.add_init_script(STEALTH_SCRIPT)
        return context
    
    async def crawl_single(self, url: str, retry_count: int = 0) -> Dict:
        """Crawl a single video URL"""
        async with self.semaphore:
            await asyncio.sleep(random.uniform(*self.config.delay_range))
            
            context = None
            page = None
            
            try:
                context = await self._create_context()
                page = await context.new_page()
                
                await page.route("**/*", route_handler)
                
                await page.goto(
                    url, 
                    wait_until='domcontentloaded',
                    timeout=self.config.timeout_ms
                )
                
                await asyncio.sleep(0.5)
                
                data = await extract_video_data_fast(page, url)
                
                if data and data.get('views', 0) > 0:
                    self.stats['success'] += 1
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
                    
            except Exception as e:
                if retry_count < self.config.max_retries:
                    delay = (2 ** retry_count) * random.uniform(0.5, 1.0)
                    await asyncio.sleep(delay)
                    return await self.crawl_single(url, retry_count + 1)
                
                self.stats['failed'] += 1
                return {
                    'url': url,
                    'success': False,
                    'views': 0,
                    'publish_date': '',
                    'error': str(e)[:100],
                }
                
            finally:
                if page:
                    try:
                        await page.close()
                    except:
                        pass
                if context:
                    try:
                        await context.close()
                    except:
                        pass
    
    async def crawl_batch(self, urls: List[str]) -> List[Dict]:
        """Crawl multiple URLs in parallel"""
        self.stats = {
            'total': len(urls),
            'success': 0,
            'failed': 0,
            'start_time': time.time(),
        }
        
        logger.info(f"📊 Starting batch crawl: {len(urls)} URLs with {self.config.max_concurrent} concurrent")
        
        results = []
        processed = 0
        
        for i in range(0, len(urls), self.config.batch_size):
            batch = urls[i:i + self.config.batch_size]
            batch_start = time.time()
            
            logger.info(f"🔄 Processing batch {i//self.config.batch_size + 1}: URLs {i+1}-{min(i+len(batch), len(urls))}")
            
            # Create tasks with timeout
            tasks = []
            for url in batch:
                task = asyncio.create_task(self.crawl_single(url))
                tasks.append(task)
            
            # Wait with overall timeout for this batch (5 min max per batch)
            try:
                batch_results = await asyncio.wait_for(
                    asyncio.gather(*tasks, return_exceptions=True),
                    timeout=300  # 5 minutes per batch of 50
                )
                
                for result in batch_results:
                    if isinstance(result, Exception):
                        results.append({
                            'url': 'unknown',
                            'success': False,
                            'error': str(result)[:100],
                        })
                        self.stats['failed'] += 1
                    else:
                        results.append(result)
                        
            except asyncio.TimeoutError:
                logger.error(f"⏱️ Batch timeout! Batch {i//self.config.batch_size + 1} took too long")
                # Cancel remaining tasks
                for task in tasks:
                    if not task.done():
                        task.cancel()
                # Add failed results for remaining URLs
                for url in batch[len([r for r in results if r.get('url') in batch]):]:
                    results.append({
                        'url': url,
                        'success': False,
                        'error': 'Batch timeout',
                    })
                    self.stats['failed'] += 1
            
            processed += len(batch)
            batch_time = time.time() - batch_start
            
            # Progress log
            elapsed = time.time() - self.stats['start_time']
            rate = processed / elapsed if elapsed > 0 else 0
            eta = (len(urls) - processed) / rate if rate > 0 else 0
            
            logger.info(
                f"⏳ Progress: {processed}/{len(urls)} ({processed/len(urls)*100:.1f}%) | "
                f"✅ {self.stats['success']} | ❌ {self.stats['failed']} | "
                f"Batch: {batch_time:.1f}s | ETA: {eta/60:.1f}min"
            )
            
            # Periodic GC
            if processed % self.config.gc_interval == 0:
                gc.collect()
                logger.info("🧹 Garbage collection done")
        
        # Final stats
        elapsed = time.time() - self.stats['start_time']
        success_rate = (self.stats['success'] / len(urls) * 100) if urls else 0
        
        logger.info(f"""
╔══════════════════════════════════════════════════════════╗
║                    CRAWL COMPLETE                         ║
╠══════════════════════════════════════════════════════════╣
║  Total: {len(urls):>6} videos                                  ║
║  Success: {self.stats['success']:>4} ({success_rate:.1f}%)                              ║
║  Failed: {self.stats['failed']:>5}                                       ║
║  Time: {elapsed/60:.1f} minutes                                    ║
║  Speed: {len(urls)/elapsed:.2f} videos/second                         ║
╚══════════════════════════════════════════════════════════╝
        """)
        
        return results


# ============================================================================
# SYNC WRAPPER - FIXED FOR FASTAPI
# ============================================================================

class TikTokPlaywrightCrawler:
    """
    Synchronous wrapper for FastAPI compatibility
    FIXED: Uses ThreadPoolExecutor to avoid event loop conflicts
    """
    
    def __init__(self):
        self.config = CrawlerConfig()
        logger.info("✅ TikTokPlaywrightCrawler initialized")
    
    def get_tiktok_views(self, video_url: str) -> Optional[Dict]:
        """Sync method to get single video stats"""
        try:
            return self._run_in_thread(self._async_get_single, video_url)
        except Exception as e:
            logger.error(f"❌ Error crawling {video_url}: {e}")
            return None
    
    def crawl_batch_sync(self, urls: List[str]) -> List[Dict]:
        """
        Sync method to crawl multiple URLs
        FIXED: Runs in separate thread to avoid FastAPI event loop conflict
        """
        logger.info(f"📋 crawl_batch_sync called with {len(urls)} URLs")
        
        try:
            result = self._run_in_thread(self._async_batch, urls)
            logger.info(f"✅ crawl_batch_sync completed with {len(result)} results")
            return result
        except Exception as e:
            logger.error(f"❌ Batch crawl error: {e}", exc_info=True)
            return []
    
    def _run_in_thread(self, async_func, *args):
        """
        Run async function in a separate thread with its own event loop
        This avoids conflicts with FastAPI's event loop
        """
        def thread_target():
            # Create new event loop for this thread
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                return loop.run_until_complete(async_func(*args))
            finally:
                loop.close()
        
        # Run in thread pool
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(thread_target)
            # Wait with timeout (60 minutes max for full crawl)
            return future.result(timeout=3600)
    
    async def _async_get_single(self, url: str) -> Optional[Dict]:
        """Async helper for single video"""
        crawler = OptimizedTikTokCrawler(self.config)
        if not await crawler.start():
            return None
        try:
            result = await crawler.crawl_single(url)
            return result if result.get('success') else None
        finally:
            await crawler.stop()
    
    async def _async_batch(self, urls: List[str]) -> List[Dict]:
        """Async helper for batch crawling"""
        logger.info(f"🔄 _async_batch starting with {len(urls)} URLs")
        
        crawler = OptimizedTikTokCrawler(self.config)
        
        if not await crawler.start():
            logger.error("❌ Failed to start crawler")
            return []
        
        try:
            results = await crawler.crawl_batch(urls)
            return results
        except Exception as e:
            logger.error(f"❌ Batch crawl exception: {e}", exc_info=True)
            return []
        finally:
            await crawler.stop()


# ============================================================================
# TEST
# ============================================================================

async def test_crawler():
    """Test the crawler"""
    test_urls = [
        "https://www.tiktok.com/@tiktok/video/7349878645498191150",
    ]
    
    print("\n🧪 Testing Optimized TikTok Crawler\n")
    
    crawler = OptimizedTikTokCrawler(CrawlerConfig(max_concurrent=2))
    await crawler.start()
    
    try:
        results = await crawler.crawl_batch(test_urls)
        
        for result in results:
            if result.get('success'):
                print(f"✅ {result['url']}")
                print(f"   Views: {result['views']:,}")
                print(f"   Published: {result.get('publish_date', 'N/A')}")
            else:
                print(f"❌ {result['url']}: {result.get('error', 'Unknown error')}")
    finally:
        await crawler.stop()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    asyncio.run(test_crawler())
