"""
🚀 OPTIMIZED TikTok Playwright Crawler
======================================
- Parallel crawling: 10-12 concurrent contexts
- Resource blocking: Skip images, fonts, CSS
- Fast extraction: From embedded JSON, not DOM
- Memory management: Periodic GC

Expected performance:
- Before: 550 videos in 2 hours (~13s/video)
- After: 550 videos in 30-45 minutes (~3-5s/video)
"""

import asyncio
import json
import random
import gc
import time
import re
import logging
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
    max_concurrent: int = 10          # Number of parallel contexts (10-12 for 8GB RAM)
    delay_range: Tuple[float, float] = (0.5, 1.5)  # Random delay between requests
    timeout_ms: int = 15000           # Page load timeout (15 seconds)
    max_retries: int = 2              # Retry failed requests
    gc_interval: int = 50             # Run garbage collection every N pages
    batch_size: int = 50              # Process in batches for progress reporting


# Resources to block (dramatically speeds up page load)
BLOCKED_RESOURCE_TYPES = {
    'image', 'media', 'font', 'stylesheet', 
    'beacon', 'imageset', 'texttrack', 'websocket',
    'manifest', 'other'
}

# URL patterns to block
BLOCKED_URL_PATTERNS = [
    'analytics', 'tracking', 'doubleclick', 'googletagmanager',
    'facebook.com', 'google-analytics', 'hotjar',
    'tiktokcdn-us.com/obj/',  # Block video/image CDN
    'tiktokcdn.com/obj/',
    '.mp4', '.webp', '.jpg', '.png', '.gif', '.woff', '.woff2',
]

# User agents pool for rotation
USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0',
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
        
        # Handle milliseconds (13 digits)
        if ts > 9999999999:
            ts = ts / 1000
        
        dt = datetime.fromtimestamp(ts)
        
        # Validate reasonable year
        if dt.year < 2016 or dt.year > 2030:
            return None
            
        return dt.strftime('%Y-%m-%d')
    except:
        return None


def parse_count(count_str: str) -> int:
    """Parse TikTok count string (e.g., '1.2M', '52.3K') to integer"""
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
# ROUTE HANDLER (Block unnecessary resources)
# ============================================================================

async def route_handler(route):
    """
    Block unnecessary resources to speed up page load
    This alone can provide 2-3x speedup!
    """
    request = route.request
    
    # Block by resource type
    if request.resource_type in BLOCKED_RESOURCE_TYPES:
        await route.abort()
        return
    
    # Block by URL pattern
    url = request.url.lower()
    for pattern in BLOCKED_URL_PATTERNS:
        if pattern in url:
            await route.abort()
            return
    
    # Allow everything else
    await route.continue_()


# ============================================================================
# ANTI-DETECTION SCRIPT
# ============================================================================

STEALTH_SCRIPT = """
() => {
    // Remove webdriver flag
    Object.defineProperty(navigator, 'webdriver', {
        get: () => undefined
    });
    
    // Override plugins
    Object.defineProperty(navigator, 'plugins', {
        get: () => [1, 2, 3, 4, 5]
    });
    
    // Override languages
    Object.defineProperty(navigator, 'languages', {
        get: () => ['en-US', 'en', 'vi']
    });
    
    // Add chrome object
    window.chrome = {
        runtime: {},
        loadTimes: function() {},
        csi: function() {},
        app: {}
    };
    
    // Override permissions
    const originalQuery = window.navigator.permissions.query;
    window.navigator.permissions.query = (parameters) => (
        parameters.name === 'notifications' ?
            Promise.resolve({ state: Notification.permission }) :
            originalQuery(parameters)
    );
    
    // Mask automation
    delete window.cdc_adoQpoasnfa76pfcZLmcfl_Array;
    delete window.cdc_adoQpoasnfa76pfcZLmcfl_Promise;
    delete window.cdc_adoQpoasnfa76pfcZLmcfl_Symbol;
}
"""


# ============================================================================
# DATA EXTRACTION (Fast JSON extraction)
# ============================================================================

async def extract_video_data_fast(page: Page, url: str) -> Optional[Dict]:
    """
    Extract video data from TikTok's embedded JSON
    This is MUCH faster than parsing the DOM!
    
    TikTok embeds complete video metadata in:
    - #__UNIVERSAL_DATA_FOR_REHYDRATION__
    - #SIGI_STATE
    """
    try:
        # Method 1: UNIVERSAL_DATA (most reliable)
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
        
        # Method 2: SIGI_STATE (fallback)
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
        
        # Method 3: Regex fallback (last resort)
        html = await page.content()
        
        # Extract playCount
        views_match = re.search(r'"playCount"[:\s]*(\d+)', html)
        views = int(views_match.group(1)) if views_match else 0
        
        # Extract createTime
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
    """
    High-performance TikTok crawler with parallel processing
    
    Features:
    - 10-12 concurrent browser contexts
    - Resource blocking for faster loads
    - JSON extraction (no DOM parsing)
    - Memory management with periodic GC
    - Automatic retry with exponential backoff
    """
    
    def __init__(self, config: CrawlerConfig = None):
        self.config = config or CrawlerConfig()
        self.semaphore = asyncio.Semaphore(self.config.max_concurrent)
        self.browser = None
        self.playwright = None
        
        # Statistics
        self.stats = {
            'total': 0,
            'success': 0,
            'failed': 0,
            'start_time': None,
        }
    
    async def start(self):
        """Initialize browser"""
        self.playwright = await async_playwright().start()
        
        self.browser = await self.playwright.chromium.launch(
            headless=True,
            args=[
                '--disable-gpu',
                '--disable-dev-shm-usage',  # Critical for containers
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-extensions',
                '--disable-background-networking',
                '--disable-blink-features=AutomationControlled',
                '--disable-features=IsolateOrigins,site-per-process',
                '--memory-pressure-off',
                '--single-process',  # Reduces memory usage
            ]
        )
        
        logger.info(f"🚀 Browser started with {self.config.max_concurrent} concurrent contexts")
    
    async def stop(self):
        """Cleanup browser"""
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()
        logger.info("🛑 Browser closed")
    
    async def _create_context(self) -> BrowserContext:
        """Create a new browser context with anti-detection"""
        context = await self.browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent=random.choice(USER_AGENTS),
            locale='en-US',
            timezone_id='Asia/Ho_Chi_Minh',
            java_script_enabled=True,
            bypass_csp=True,
            ignore_https_errors=True,
        )
        
        # Add stealth script
        await context.add_init_script(STEALTH_SCRIPT)
        
        return context
    
    async def crawl_single(self, url: str, retry_count: int = 0) -> Dict:
        """
        Crawl a single video URL with semaphore control
        
        Returns:
            Dict with keys: url, success, views, publish_date, error
        """
        async with self.semaphore:
            # Random delay to avoid detection
            await asyncio.sleep(random.uniform(*self.config.delay_range))
            
            context = None
            page = None
            
            try:
                context = await self._create_context()
                page = await context.new_page()
                
                # Setup route handler to block resources
                await page.route("**/*", route_handler)
                
                # Navigate with short timeout
                # Using 'domcontentloaded' instead of 'networkidle' is KEY!
                await page.goto(
                    url, 
                    wait_until='domcontentloaded',  # ⚡ Much faster than networkidle
                    timeout=self.config.timeout_ms
                )
                
                # Small wait for JSON to be available
                await asyncio.sleep(0.3)
                
                # Extract data
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
                # Retry with exponential backoff
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
                    'error': str(e),
                }
                
            finally:
                # Always cleanup
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
    
    async def crawl_batch(self, urls: List[str], progress_callback=None) -> List[Dict]:
        """
        Crawl multiple URLs in parallel with progress reporting
        
        Args:
            urls: List of TikTok video URLs
            progress_callback: Optional callback(processed, total, success_rate)
            
        Returns:
            List of result dicts
        """
        self.stats = {
            'total': len(urls),
            'success': 0,
            'failed': 0,
            'start_time': time.time(),
        }
        
        logger.info(f"📊 Starting batch crawl: {len(urls)} URLs with {self.config.max_concurrent} concurrent contexts")
        
        results = []
        processed = 0
        
        # Process in smaller batches for progress reporting
        for i in range(0, len(urls), self.config.batch_size):
            batch = urls[i:i + self.config.batch_size]
            
            # Create tasks for this batch
            tasks = [self.crawl_single(url) for url in batch]
            
            # Run batch concurrently
            batch_results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Process results
            for result in batch_results:
                if isinstance(result, Exception):
                    results.append({
                        'url': 'unknown',
                        'success': False,
                        'error': str(result),
                    })
                else:
                    results.append(result)
            
            processed += len(batch)
            
            # Progress callback
            if progress_callback:
                success_rate = (self.stats['success'] / processed * 100) if processed > 0 else 0
                progress_callback(processed, len(urls), success_rate)
            
            # Log progress
            elapsed = time.time() - self.stats['start_time']
            rate = processed / elapsed if elapsed > 0 else 0
            eta = (len(urls) - processed) / rate if rate > 0 else 0
            
            logger.info(
                f"⏳ Progress: {processed}/{len(urls)} "
                f"({processed/len(urls)*100:.1f}%) | "
                f"Success: {self.stats['success']} | "
                f"Rate: {rate:.1f}/s | "
                f"ETA: {eta/60:.1f}min"
            )
            
            # Periodic garbage collection
            if processed % self.config.gc_interval == 0:
                gc.collect()
        
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
# SYNC WRAPPER (For FastAPI compatibility)
# ============================================================================

class TikTokPlaywrightCrawler:
    """
    Synchronous wrapper for FastAPI compatibility
    Drop-in replacement for the old crawler
    """
    
    def __init__(self):
        self.config = CrawlerConfig()
    
    def get_tiktok_views(self, video_url: str) -> Optional[Dict]:
        """
        Sync method to get single video stats
        (For backward compatibility - use crawl_batch for better performance)
        """
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                return loop.run_until_complete(self._async_get_single(video_url))
            finally:
                loop.close()
        except Exception as e:
            logger.error(f"❌ Error crawling {video_url}: {e}")
            return None
    
    async def _async_get_single(self, url: str) -> Optional[Dict]:
        """Async helper for single video"""
        crawler = OptimizedTikTokCrawler(self.config)
        await crawler.start()
        try:
            result = await crawler.crawl_single(url)
            if result.get('success'):
                return result
            return None
        finally:
            await crawler.stop()
    
    def crawl_batch_sync(self, urls: List[str]) -> List[Dict]:
        """
        Sync method to crawl multiple URLs in parallel
        THIS IS THE RECOMMENDED METHOD FOR BATCH CRAWLING!
        """
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                return loop.run_until_complete(self._async_batch(urls))
            finally:
                loop.close()
        except Exception as e:
            logger.error(f"❌ Batch crawl error: {e}")
            return []
    
    async def _async_batch(self, urls: List[str]) -> List[Dict]:
        """Async helper for batch crawling"""
        crawler = OptimizedTikTokCrawler(self.config)
        await crawler.start()
        try:
            return await crawler.crawl_batch(urls)
        finally:
            await crawler.stop()


# ============================================================================
# TEST FUNCTION
# ============================================================================

async def test_crawler():
    """Test the optimized crawler"""
    test_urls = [
        "https://www.tiktok.com/@tiktok/video/7349878645498191150",
        "https://www.tiktok.com/@tiktok/video/7350000000000000000",
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
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    asyncio.run(test_crawler())
