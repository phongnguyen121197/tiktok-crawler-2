"""
🚀 TikTok Playwright Crawler - DEBUG VERSION
=============================================
- Detailed logging for troubleshooting
- Reduced concurrency for stability
- No resource blocking (to test if that's the issue)
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
# CONFIGURATION - CONSERVATIVE SETTINGS FOR DEBUGGING
# ============================================================================

@dataclass
class CrawlerConfig:
    """Configuration - conservative for debugging"""
    max_concurrent: int = 4           # Reduced for stability
    delay_range: Tuple[float, float] = (2.0, 4.0)  # Longer delays
    timeout_ms: int = 30000           # 30 seconds timeout
    max_retries: int = 1              # Less retries for faster feedback
    gc_interval: int = 25             # More frequent GC
    batch_size: int = 25              # Smaller batches


# User agents
USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
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
    
    // Hide automation
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
    """Extract video data with detailed logging"""
    try:
        # Method 1: UNIVERSAL_DATA
        logger.debug(f"🔍 Trying UNIVERSAL_DATA extraction for {url[:50]}...")
        
        raw_json = await page.evaluate('''() => {
            const script = document.querySelector('#__UNIVERSAL_DATA_FOR_REHYDRATION__');
            return script ? script.textContent : null;
        }''')
        
        if raw_json:
            logger.debug(f"📄 Found UNIVERSAL_DATA, length: {len(raw_json)}")
            data = json.loads(raw_json)
            scope = data.get('__DEFAULT_SCOPE__', {})
            video_detail = scope.get('webapp.video-detail', {})
            item = video_detail.get('itemInfo', {}).get('itemStruct', {})
            
            if item:
                stats = item.get('stats', {})
                views = stats.get('playCount', 0)
                logger.info(f"✅ Extracted views={views} from UNIVERSAL_DATA")
                return {
                    'views': views,
                    'likes': stats.get('diggCount', 0),
                    'comments': stats.get('commentCount', 0),
                    'shares': stats.get('shareCount', 0),
                    'publish_date': convert_timestamp_to_date(item.get('createTime')),
                }
        
        # Method 2: SIGI_STATE
        logger.debug(f"🔍 Trying SIGI_STATE extraction...")
        
        raw_json = await page.evaluate('''() => {
            const script = document.querySelector('#SIGI_STATE');
            return script ? script.textContent : null;
        }''')
        
        if raw_json:
            logger.debug(f"📄 Found SIGI_STATE, length: {len(raw_json)}")
            data = json.loads(raw_json)
            item_module = data.get('ItemModule', {})
            
            for video_id, video_data in item_module.items():
                stats = video_data.get('stats', {})
                views = stats.get('playCount', 0)
                logger.info(f"✅ Extracted views={views} from SIGI_STATE")
                return {
                    'views': views,
                    'likes': stats.get('diggCount', 0),
                    'comments': stats.get('commentCount', 0),
                    'shares': stats.get('shareCount', 0),
                    'publish_date': convert_timestamp_to_date(video_data.get('createTime')),
                }
        
        # Method 3: Regex fallback
        logger.debug(f"🔍 Trying regex extraction...")
        html = await page.content()
        html_preview = html[:500] if len(html) > 500 else html
        logger.debug(f"📄 Page HTML preview: {html_preview[:200]}...")
        
        views_match = re.search(r'"playCount"[:\s]*(\d+)', html)
        if views_match:
            views = int(views_match.group(1))
            logger.info(f"✅ Extracted views={views} from regex")
            
            time_match = re.search(r'"createTime"[:\s]*"?(\d{10,13})"?', html)
            publish_date = convert_timestamp_to_date(time_match.group(1)) if time_match else None
            
            return {
                'views': views,
                'likes': 0,
                'comments': 0,
                'shares': 0,
                'publish_date': publish_date,
            }
        
        # Check if we got a CAPTCHA or error page
        title = await page.title()
        logger.warning(f"⚠️ No data found. Page title: {title}")
        
        if 'captcha' in html.lower() or 'verify' in html.lower():
            logger.error(f"🚫 CAPTCHA detected!")
        
        return None
        
    except Exception as e:
        logger.error(f"❌ Extraction error: {e}")
        return None


# ============================================================================
# MAIN CRAWLER CLASS
# ============================================================================

class OptimizedTikTokCrawler:
    """TikTok crawler with detailed debugging"""
    
    def __init__(self, config: CrawlerConfig = None):
        self.config = config or CrawlerConfig()
        self.semaphore = None
        self.browser = None
        self.playwright = None
        self.stats = {'total': 0, 'success': 0, 'failed': 0, 'start_time': None}
    
    async def start(self):
        """Initialize browser with debug logging"""
        try:
            logger.info("🚀 Starting Playwright browser...")
            self.semaphore = asyncio.Semaphore(self.config.max_concurrent)
            self.playwright = await async_playwright().start()
            
            self.browser = await self.playwright.chromium.launch(
                headless=True,
                args=[
                    '--disable-gpu',
                    '--disable-dev-shm-usage',
                    '--no-sandbox',
                    '--disable-setuid-sandbox',
                    '--disable-blink-features=AutomationControlled',
                    '--disable-features=IsolateOrigins,site-per-process',
                    '--single-process',
                ]
            )
            
            logger.info(f"✅ Browser started successfully")
            logger.info(f"📊 Config: concurrent={self.config.max_concurrent}, timeout={self.config.timeout_ms}ms")
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to start browser: {e}")
            logger.error(traceback.format_exc())
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
        """Create browser context"""
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
        """Crawl single URL with detailed logging"""
        async with self.semaphore:
            delay = random.uniform(*self.config.delay_range)
            logger.debug(f"⏳ Waiting {delay:.1f}s before crawling...")
            await asyncio.sleep(delay)
            
            context = None
            page = None
            start_time = time.time()
            
            try:
                logger.info(f"🌐 Crawling: {url[:60]}...")
                
                context = await self._create_context()
                page = await context.new_page()
                
                # NO resource blocking - let everything through for debugging
                # Just navigate directly
                
                logger.debug(f"📡 Navigating to URL...")
                
                await page.goto(
                    url, 
                    wait_until='load',  # Wait for full page load
                    timeout=self.config.timeout_ms
                )
                
                elapsed = time.time() - start_time
                logger.debug(f"📄 Page loaded in {elapsed:.1f}s")
                
                # Wait a bit for JS to execute
                await asyncio.sleep(1.5)
                
                # Extract data
                data = await extract_video_data(page, url)
                
                if data and data.get('views', 0) > 0:
                    self.stats['success'] += 1
                    elapsed = time.time() - start_time
                    logger.info(f"✅ SUCCESS: {url[:50]}... | Views: {data['views']:,} | Time: {elapsed:.1f}s")
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
                    raise Exception("No views data extracted")
                    
            except PlaywrightTimeout as e:
                elapsed = time.time() - start_time
                logger.warning(f"⏱️ TIMEOUT after {elapsed:.1f}s: {url[:50]}...")
                
                if retry_count < self.config.max_retries:
                    logger.info(f"🔄 Retrying... (attempt {retry_count + 2})")
                    await asyncio.sleep(random.uniform(2, 4))
                    return await self.crawl_single(url, retry_count + 1)
                
                self.stats['failed'] += 1
                return {'url': url, 'success': False, 'views': 0, 'publish_date': '', 'error': 'Timeout'}
                
            except Exception as e:
                elapsed = time.time() - start_time
                error_msg = str(e)[:100]
                logger.error(f"❌ FAILED after {elapsed:.1f}s: {url[:50]}... | Error: {error_msg}")
                
                if retry_count < self.config.max_retries:
                    logger.info(f"🔄 Retrying... (attempt {retry_count + 2})")
                    await asyncio.sleep(random.uniform(2, 4))
                    return await self.crawl_single(url, retry_count + 1)
                
                self.stats['failed'] += 1
                return {'url': url, 'success': False, 'views': 0, 'publish_date': '', 'error': error_msg}
                
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
        """Crawl URLs in batches"""
        self.stats = {
            'total': len(urls),
            'success': 0,
            'failed': 0,
            'start_time': time.time(),
        }
        
        logger.info(f"📊 Starting batch crawl: {len(urls)} URLs")
        logger.info(f"⚙️ Settings: {self.config.max_concurrent} concurrent, {self.config.timeout_ms}ms timeout")
        
        results = []
        processed = 0
        
        for i in range(0, len(urls), self.config.batch_size):
            batch = urls[i:i + self.config.batch_size]
            batch_num = i // self.config.batch_size + 1
            total_batches = (len(urls) + self.config.batch_size - 1) // self.config.batch_size
            
            logger.info(f"🔄 Batch {batch_num}/{total_batches}: URLs {i+1}-{min(i+len(batch), len(urls))}")
            
            # Create and run tasks
            tasks = [asyncio.create_task(self.crawl_single(url)) for url in batch]
            
            # Wait with timeout (10 min per batch of 25)
            try:
                batch_results = await asyncio.wait_for(
                    asyncio.gather(*tasks, return_exceptions=True),
                    timeout=600  # 10 minutes
                )
                
                for idx, result in enumerate(batch_results):
                    if isinstance(result, Exception):
                        logger.error(f"❌ Task exception: {result}")
                        results.append({
                            'url': batch[idx] if idx < len(batch) else 'unknown',
                            'success': False,
                            'error': str(result)[:100],
                        })
                        self.stats['failed'] += 1
                    else:
                        results.append(result)
                        
            except asyncio.TimeoutError:
                logger.error(f"⏱️ BATCH TIMEOUT! Batch {batch_num} exceeded 10 minutes")
                for task in tasks:
                    if not task.done():
                        task.cancel()
                for url in batch:
                    if not any(r.get('url') == url for r in results):
                        results.append({'url': url, 'success': False, 'error': 'Batch timeout'})
                        self.stats['failed'] += 1
            
            processed += len(batch)
            
            # Progress log
            elapsed = time.time() - self.stats['start_time']
            success_rate = (self.stats['success'] / processed * 100) if processed > 0 else 0
            
            logger.info(
                f"📈 Progress: {processed}/{len(urls)} ({processed/len(urls)*100:.1f}%) | "
                f"✅ {self.stats['success']} ({success_rate:.0f}%) | ❌ {self.stats['failed']}"
            )
            
            # Garbage collection
            if processed % self.config.gc_interval == 0:
                gc.collect()
        
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
╚════════════════════════════════════════════════════════╝
        """)
        
        return results


# ============================================================================
# SYNC WRAPPER
# ============================================================================

class TikTokPlaywrightCrawler:
    """Synchronous wrapper for FastAPI"""
    
    def __init__(self):
        self.config = CrawlerConfig()
        logger.info("✅ TikTokPlaywrightCrawler initialized")
    
    def get_tiktok_views(self, video_url: str) -> Optional[Dict]:
        """Get single video stats"""
        try:
            return self._run_in_thread(self._async_get_single, video_url)
        except Exception as e:
            logger.error(f"❌ Error: {e}")
            return None
    
    def crawl_batch_sync(self, urls: List[str]) -> List[Dict]:
        """Crawl multiple URLs"""
        logger.info(f"📋 crawl_batch_sync called with {len(urls)} URLs")
        
        try:
            result = self._run_in_thread(self._async_batch, urls)
            logger.info(f"✅ Completed with {len(result)} results")
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
            return future.result(timeout=3600)
    
    async def _async_get_single(self, url: str) -> Optional[Dict]:
        """Async single video"""
        crawler = OptimizedTikTokCrawler(self.config)
        if not await crawler.start():
            return None
        try:
            result = await crawler.crawl_single(url)
            return result if result.get('success') else None
        finally:
            await crawler.stop()
    
    async def _async_batch(self, urls: List[str]) -> List[Dict]:
        """Async batch"""
        logger.info(f"🔄 _async_batch starting with {len(urls)} URLs")
        
        crawler = OptimizedTikTokCrawler(self.config)
        
        if not await crawler.start():
            logger.error("❌ Failed to start crawler")
            return []
        
        try:
            return await crawler.crawl_batch(urls)
        except Exception as e:
            logger.error(f"❌ Exception: {e}")
            logger.error(traceback.format_exc())
            return []
        finally:
            await crawler.stop()


# ============================================================================
# TEST - Run directly to test
# ============================================================================

async def test_single_url():
    """Test with single URL"""
    test_url = "https://www.tiktok.com/@tiktok/video/7449807305491698990"
    
    print(f"\n🧪 Testing single URL: {test_url}\n")
    
    crawler = OptimizedTikTokCrawler(CrawlerConfig(max_concurrent=1))
    
    if not await crawler.start():
        print("❌ Failed to start browser")
        return
    
    try:
        result = await crawler.crawl_single(test_url)
        
        if result.get('success'):
            print(f"✅ SUCCESS!")
            print(f"   Views: {result['views']:,}")
            print(f"   Published: {result.get('publish_date', 'N/A')}")
        else:
            print(f"❌ FAILED: {result.get('error', 'Unknown')}")
    finally:
        await crawler.stop()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    asyncio.run(test_single_url())
