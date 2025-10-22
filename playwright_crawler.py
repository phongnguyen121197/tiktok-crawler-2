import asyncio
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout
import re
from typing import Optional, Dict
import logging

logger = logging.getLogger(__name__)

class PlaywrightTikTokCrawler:
    """
    TikTok crawler using Playwright for direct scraping
    Designed for Railway deployment with 1x/day execution
    """
    
    def __init__(self):
        self.browser = None
        self.context = None
        self.playwright = None
        self.max_retries = 3
        self.timeout = 20000  # 20 seconds per video
        
    async def __aenter__(self):
        """Context manager entry - initialize browser"""
        await self.init_browser()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - cleanup browser"""
        await self.close_browser()
    
    async def init_browser(self):
        """Initialize Playwright browser with anti-detection settings"""
        try:
            self.playwright = await async_playwright().start()
            
            # Launch browser with realistic settings
            self.browser = await self.playwright.chromium.launch(
                headless=True,
                args=[
                    '--disable-blink-features=AutomationControlled',
                    '--no-sandbox',
                    '--disable-dev-shm-usage',
                    '--disable-gpu',
                    '--disable-software-rasterizer',
                    '--disable-setuid-sandbox',
                ]
            )
            
            # Create context with realistic user agent and viewport
            self.context = await self.browser.new_context(
                viewport={'width': 1920, 'height': 1080},
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                locale='en-US',
                timezone_id='Asia/Ho_Chi_Minh',
                java_script_enabled=True,
            )
            
            # Anti-detection: Remove webdriver flag
            await self.context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                });
                
                // Override plugins length
                Object.defineProperty(navigator, 'plugins', {
                    get: () => [1, 2, 3, 4, 5]
                });
                
                // Override languages
                Object.defineProperty(navigator, 'languages', {
                    get: () => ['en-US', 'en']
                });
            """)
            
            logger.info("✅ Browser initialized successfully")
            
        except Exception as e:
            logger.error(f"❌ Failed to initialize browser: {e}")
            raise
    
    async def close_browser(self):
        """Cleanup browser resources"""
        try:
            if self.context:
                await self.context.close()
            if self.browser:
                await self.browser.close()
            if self.playwright:
                await self.playwright.stop()
            logger.info("✅ Browser closed successfully")
        except Exception as e:
            logger.error(f"⚠️ Error closing browser: {e}")
    
    async def get_video_stats(self, video_url: str) -> Optional[Dict]:
        """
        Crawl a single TikTok video and extract stats
        
        Args:
            video_url: TikTok video URL
            
        Returns:
            Dict with views, likes, comments, shares or None if failed
        """
        for attempt in range(self.max_retries):
            page = None
            try:
                page = await self.context.new_page()
                
                logger.info(f"🔍 Crawling {video_url} (attempt {attempt + 1}/{self.max_retries})")
                
                # Navigate to video
                await page.goto(video_url, wait_until='domcontentloaded', timeout=self.timeout)
                
                # Wait a bit for dynamic content to load
                await asyncio.sleep(3)
                
                # Extract stats using multiple strategies
                stats = await self._extract_stats_from_page(page)
                
                await page.close()
                
                if stats and stats.get('views', 0) > 0:
                    logger.info(f"✅ Successfully crawled {video_url}: {stats['views']:,} views")
                    return stats
                else:
                    logger.warning(f"⚠️ No stats found for {video_url}, attempt {attempt + 1}")
                    
            except PlaywrightTimeout:
                logger.warning(f"⏱️ Timeout for {video_url}, attempt {attempt + 1}/{self.max_retries}")
                if page:
                    await page.close()
                await asyncio.sleep(3)  # Wait before retry
                
            except Exception as e:
                logger.error(f"❌ Error crawling {video_url}: {e}, attempt {attempt + 1}")
                if page:
                    await page.close()
                await asyncio.sleep(3)
        
        logger.error(f"❌ Failed to crawl {video_url} after {self.max_retries} attempts")
        return None
    
    async def _extract_stats_from_page(self, page) -> Optional[Dict]:
        """
        Extract view count and engagement stats from TikTok page
        Uses multiple selector strategies as backup
        """
        try:
            # Wait for video container
            try:
                await page.wait_for_selector('[data-e2e="browse-video"]', timeout=10000)
            except:
                logger.warning("Video container not found, trying alternative selectors")
            
            # Strategy 1: Try data-e2e attributes (most reliable)
            views = await self._try_selector(page, '[data-e2e="video-views"]')
            likes = await self._try_selector(page, '[data-e2e="like-count"]')
            comments = await self._try_selector(page, '[data-e2e="comment-count"]')
            shares = await self._try_selector(page, '[data-e2e="share-count"]')
            
            # Strategy 2: Try alternative selectors
            if not views:
                views = await self._try_selector(page, 'strong[data-e2e="video-views"]')
            
            if not views:
                views = await self._try_selector(page, '[data-e2e="browse-video-desc"] strong')
            
            # Strategy 3: Extract from page content using regex
            if not views:
                content = await page.content()
                views = self._extract_views_from_html(content)
            
            # Strategy 4: Try JSON-LD structured data
            if not views:
                views = await self._extract_from_json_ld(page)
            
            if views:
                parsed_views = self._parse_count(views)
                if parsed_views > 0:
                    return {
                        'views': parsed_views,
                        'likes': self._parse_count(likes) if likes else 0,
                        'comments': self._parse_count(comments) if comments else 0,
                        'shares': self._parse_count(shares) if shares else 0,
                    }
            
            logger.warning("Could not extract views from any strategy")
            return None
            
        except Exception as e:
            logger.error(f"Error extracting stats: {e}")
            return None
    
    async def _try_selector(self, page, selector: str) -> Optional[str]:
        """Try to get text from a selector, return None if not found"""
        try:
            element = await page.query_selector(selector)
            if element:
                text = await element.inner_text()
                return text.strip() if text else None
        except Exception as e:
            logger.debug(f"Selector {selector} failed: {e}")
        return None
    
    async def _extract_from_json_ld(self, page) -> Optional[str]:
        """Extract view count from JSON-LD structured data"""
        try:
            json_ld = await page.query_selector('script[type="application/ld+json"]')
            if json_ld:
                content = await json_ld.inner_text()
                import json
                data = json.loads(content)
                
                # Try different possible paths in JSON-LD
                if 'interactionStatistic' in data:
                    for stat in data['interactionStatistic']:
                        if stat.get('@type') == 'InteractionCounter':
                            if 'WatchAction' in stat.get('interactionType', ''):
                                return str(stat.get('userInteractionCount'))
        except Exception as e:
            logger.debug(f"JSON-LD extraction failed: {e}")
        return None
    
    def _extract_views_from_html(self, html: str) -> Optional[str]:
        """Extract view count from HTML using regex as fallback"""
        patterns = [
            r'"playCount":(\d+)',
            r'"viewCount":(\d+)',
            r'viewCount&quot;:(\d+)',
            r'"videoMeta":\{[^}]*"playCount":(\d+)',
            r'video:views.*?content="(\d+)"',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, html)
            if match:
                logger.info(f"Found views via regex pattern: {pattern}")
                return match.group(1)
        return None
    
    def _parse_count(self, count_str: str) -> int:
        """
        Parse TikTok count string to integer
        Examples: '1.2M' -> 1200000, '52.3K' -> 52300, '1234' -> 1234
        """
        if not count_str:
            return 0
        
        count_str = count_str.strip().upper()
        
        try:
            # Remove any non-numeric chars except K, M, B, .
            count_str = re.sub(r'[^\d.KMB]', '', count_str)
            
            if not count_str:
                return 0
            
            multipliers = {'K': 1000, 'M': 1000000, 'B': 1000000000}
            
            for suffix, multiplier in multipliers.items():
                if suffix in count_str:
                    number = float(count_str.replace(suffix, ''))
                    return int(number * multiplier)
            
            return int(float(count_str))
        except Exception as e:
            logger.debug(f"Failed to parse count '{count_str}': {e}")
            return 0
    
    async def crawl_batch(self, video_urls: list) -> Dict[str, Optional[Dict]]:
        """
        Crawl multiple videos sequentially (to avoid rate limiting)
        
        Args:
            video_urls: List of TikTok video URLs
            
        Returns:
            Dict mapping URL to stats dict
        """
        results = {}
        total = len(video_urls)
        
        for i, url in enumerate(video_urls):
            logger.info(f"📊 Progress: {i+1}/{total} ({(i+1)/total*100:.1f}%)")
            
            stats = await self.get_video_stats(url)
            results[url] = stats
            
            # Add delay between requests to avoid rate limiting
            if i < total - 1:
                await asyncio.sleep(2)  # 2 second delay between videos
        
        # Summary
        success_count = sum(1 for v in results.values() if v is not None)
        logger.info(f"🎯 Batch complete: {success_count}/{total} successful ({success_count/total*100:.1f}%)")
        
        return results


# Sync wrapper for use in existing FastAPI code
class TikTokPlaywrightCrawler:
    """Synchronous wrapper for async Playwright crawler"""
    
    def __init__(self):
        self.async_crawler = None
    
    def get_tiktok_views(self, video_url: str) -> Optional[Dict]:
        """
        Synchronous method to get video stats
        Compatible with existing crawler.py interface
        
        Returns same format as old API: {views, likes, comments, shares}
        """
        try:
            # Create new event loop for this call
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            async def _crawl():
                async with PlaywrightTikTokCrawler() as crawler:
                    return await crawler.get_video_stats(video_url)
            
            result = loop.run_until_complete(_crawl())
            loop.close()
            
            return result
            
        except Exception as e:
            logger.error(f"❌ Sync wrapper error for {video_url}: {e}")
            return None
    
    def crawl_batch_sync(self, video_urls: list) -> Dict[str, Optional[Dict]]:
        """
        Synchronous batch crawl
        More efficient than calling get_tiktok_views multiple times
        """
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            async def _crawl():
                async with PlaywrightTikTokCrawler() as crawler:
                    return await crawler.crawl_batch(video_urls)
            
            results = loop.run_until_complete(_crawl())
            loop.close()
            
            return results
            
        except Exception as e:
            logger.error(f"❌ Batch sync wrapper error: {e}")
            return {}


# Test function
async def test_crawler():
    """Test the crawler with a sample video"""
    test_url = "https://www.tiktok.com/@username/video/7123456789012345678"
    
    async with PlaywrightTikTokCrawler() as crawler:
        print(f"\n🧪 Testing crawler with: {test_url}\n")
        stats = await crawler.get_video_stats(test_url)
        
        if stats:
            print(f"✅ Success!")
            print(f"   Views: {stats['views']:,}")
            print(f"   Likes: {stats['likes']:,}")
            print(f"   Comments: {stats['comments']:,}")
            print(f"   Shares: {stats['shares']:,}")
        else:
            print(f"❌ Failed to crawl video")


if __name__ == "__main__":
    # Run test
    logging.basicConfig(level=logging.INFO)
    asyncio.run(test_crawler())
