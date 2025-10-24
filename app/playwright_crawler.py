import asyncio
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout
import re
import random
from typing import Optional, Dict
import logging

logger = logging.getLogger(__name__)

class PlaywrightTikTokCrawler:
    """
    Simplified TikTok crawler with better stability
    Each video gets a fresh browser instance to avoid context issues
    """
    
    def __init__(self):
        self.max_retries = 3
        self.timeout = 30000  # 30 seconds
        
    async def __aenter__(self):
        """Context manager entry"""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit"""
        pass
    
    async def get_video_stats(self, video_url: str) -> Optional[Dict]:
        """
        Crawl single video with isolated browser instance per attempt
        ✅ KEY FIX: Create fresh browser for each attempt to avoid context issues
        """
        for attempt in range(self.max_retries):
            playwright = None
            browser = None
            context = None
            page = None
            
            try:
                logger.info(f"🔍 Crawling {video_url} (attempt {attempt + 1}/{self.max_retries})")
                
                # Random delay
                await asyncio.sleep(random.uniform(1, 2))
                
                # ✅ FIX: Create fresh browser instance for each attempt
                playwright = await async_playwright().start()
                
                browser = await playwright.chromium.launch(
                    headless=True,
                    args=[
                        '--no-sandbox',
                        '--disable-setuid-sandbox',
                        '--disable-dev-shm-usage',
                        '--disable-gpu',
                    ]
                )
                
                context = await browser.new_context(
                    viewport={'width': 1920, 'height': 1080},
                    user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
                )
                
                # Anti-detection
                await context.add_init_script("""
                    Object.defineProperty(navigator, 'webdriver', {
                        get: () => undefined
                    });
                """)
                
                page = await context.new_page()
                
                # Navigate
                await page.goto(video_url, wait_until='domcontentloaded', timeout=self.timeout)
                
                # Wait for content
                await asyncio.sleep(random.uniform(3, 5))
                
                # Extract stats
                stats = await self._extract_stats(page)
                
                # Cleanup
                await page.close()
                await context.close()
                await browser.close()
                await playwright.stop()
                
                # Check results
                if stats and stats.get('views', 0) > 0:
                    logger.info(f"✅ Success: {stats['views']:,} views")
                    return stats
                else:
                    logger.warning(f"⚠️ No stats found, attempt {attempt + 1}")
                    if attempt < self.max_retries - 1:
                        await asyncio.sleep(random.uniform(2, 3))
                    
            except Exception as e:
                logger.error(f"❌ Error: {e}")
                
            finally:
                # Ensure cleanup
                try:
                    if page:
                        await page.close()
                except:
                    pass
                try:
                    if context:
                        await context.close()
                except:
                    pass
                try:
                    if browser:
                        await browser.close()
                except:
                    pass
                try:
                    if playwright:
                        await playwright.stop()
                except:
                    pass
        
        logger.error(f"❌ Failed after {self.max_retries} attempts")
        return None
    
    async def _extract_stats(self, page) -> Optional[Dict]:
        """Extract stats with multiple strategies"""
        views = None
        
        try:
            if page.is_closed():
                return None
            
            # STRATEGY 1: CSS selectors
            selectors = [
                '[data-e2e="video-views"]',
                'strong[data-e2e="video-views"]',
                '[data-e2e="browse-video-desc"] strong',
            ]
            
            for selector in selectors:
                try:
                    element = await page.query_selector(selector)
                    if element:
                        text = await element.inner_text()
                        if text:
                            views = text.strip()
                            break
                except:
                    pass
            
            # STRATEGY 2: Regex from HTML
            if not views:
                try:
                    html = await page.content()
                    patterns = [
                        r'"playCount":(\d+)',
                        r'"viewCount":(\d+)',
                        r'playCount&quot;:(\d+)',
                    ]
                    
                    for pattern in patterns:
                        match = re.search(pattern, html)
                        if match:
                            views = match.group(1)
                            logger.info(f"Found via regex: {pattern}")
                            break
                except:
                    pass
            
            # Parse and return
            if views:
                parsed_views = self._parse_count(views)
                if parsed_views > 0:
                    return {
                        'views': parsed_views,
                        'likes': 0,
                        'comments': 0,
                        'shares': 0,
                    }
            
            return None
            
        except Exception as e:
            logger.error(f"Extract error: {e}")
            return None
    
    def _parse_count(self, count_str: str) -> int:
        """Parse count string to integer"""
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
    
    async def crawl_batch(self, video_urls: list) -> Dict[str, Optional[Dict]]:
        """Crawl multiple videos"""
        results = {}
        total = len(video_urls)
        
        for i, url in enumerate(video_urls):
            logger.info(f"📊 Progress: {i+1}/{total} ({(i+1)/total*100:.1f}%)")
            
            stats = await self.get_video_stats(url)
            results[url] = stats
            
            if i < total - 1:
                await asyncio.sleep(random.uniform(2, 4))
        
        success_count = sum(1 for v in results.values() if v is not None)
        logger.info(f"🎯 Complete: {success_count}/{total} ({success_count/total*100:.1f}%)")
        
        return results


class TikTokPlaywrightCrawler:
    """Synchronous wrapper for FastAPI compatibility"""
    
    def __init__(self):
        pass
    
    def get_tiktok_views(self, video_url: str) -> Optional[Dict]:
        """Sync method to get video stats"""
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                async def _crawl():
                    async with PlaywrightTikTokCrawler() as crawler:
                        return await crawler.get_video_stats(video_url)
                
                return loop.run_until_complete(_crawl())
            finally:
                loop.close()
        except Exception as e:
            logger.error(f"❌ Sync wrapper error: {e}")
            return None
    
    def crawl_batch_sync(self, video_urls: list) -> Dict[str, Optional[Dict]]:
        """Sync batch crawl"""
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                async def _crawl():
                    async with PlaywrightTikTokCrawler() as crawler:
                        return await crawler.crawl_batch(video_urls)
                
                return loop.run_until_complete(_crawl())
            finally:
                loop.close()
        except Exception as e:
            logger.error(f"❌ Batch error: {e}")
            return {}


# Test function
async def test_crawler():
    """Test with sample videos"""
    test_urls = [
        "https://vt.tiktok.com/ZSUPWkfRN/",
        "https://www.tiktok.com/@thanhtg98/video/7559145944147610888",
    ]
    
    async with PlaywrightTikTokCrawler() as crawler:
        print(f"\n🧪 Testing {len(test_urls)} videos\n")
        
        for url in test_urls:
            print(f"Testing: {url}")
            stats = await crawler.get_video_stats(url)
            
            if stats:
                print(f"✅ Success: {stats['views']:,} views\n")
            else:
                print(f"❌ Failed\n")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    asyncio.run(test_crawler())