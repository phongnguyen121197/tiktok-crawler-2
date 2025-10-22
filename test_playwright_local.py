"""
Test script for Playwright TikTok Crawler
Run this locally BEFORE deploying to Railway to verify everything works

Usage:
    python test_playwright_local.py
"""

import asyncio
import logging
import sys
from datetime import datetime

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Test URLs - Replace with real TikTok video URLs
TEST_URLS = [
    "https://www.tiktok.com/@username/video/1234567890123456789",  # Replace with real URL
    "https://www.tiktok.com/@username/video/9876543210987654321",  # Replace with real URL
]


async def test_single_video():
    """Test crawling a single video"""
    from app.playwright_crawler import PlaywrightTikTokCrawler
    
    print("\n" + "="*60)
    print("TEST 1: Single Video Crawl")
    print("="*60 + "\n")
    
    test_url = TEST_URLS[0]
    
    try:
        async with PlaywrightTikTokCrawler() as crawler:
            print(f"🔍 Testing with: {test_url}")
            print(f"⏳ This may take 15-20 seconds...\n")
            
            stats = await crawler.get_video_stats(test_url)
            
            if stats:
                print(f"✅ SUCCESS!")
                print(f"   📊 Views:    {stats['views']:,}")
                print(f"   ❤️  Likes:    {stats['likes']:,}")
                print(f"   💬 Comments: {stats['comments']:,}")
                print(f"   🔄 Shares:   {stats['shares']:,}")
                return True
            else:
                print(f"❌ FAILED - No stats returned")
                print(f"⚠️  Check if URL is valid and publicly accessible")
                return False
                
    except Exception as e:
        print(f"❌ ERROR: {e}")
        return False


async def test_multiple_videos():
    """Test crawling multiple videos in batch"""
    from app.playwright_crawler import PlaywrightTikTokCrawler
    
    print("\n" + "="*60)
    print("TEST 2: Multiple Videos Batch Crawl")
    print("="*60 + "\n")
    
    try:
        async with PlaywrightTikTokCrawler() as crawler:
            print(f"🔍 Testing with {len(TEST_URLS)} videos")
            print(f"⏳ This may take 30-60 seconds...\n")
            
            results = await crawler.crawl_batch(TEST_URLS)
            
            success_count = sum(1 for v in results.values() if v is not None)
            
            print(f"\n📊 BATCH RESULTS:")
            print(f"   Total:     {len(TEST_URLS)}")
            print(f"   Success:   {success_count}")
            print(f"   Failed:    {len(TEST_URLS) - success_count}")
            print(f"   Success %: {success_count/len(TEST_URLS)*100:.1f}%")
            
            # Show details for each video
            print(f"\n📋 DETAILS:")
            for i, (url, stats) in enumerate(results.items(), 1):
                if stats:
                    print(f"   {i}. ✅ {stats['views']:,} views - {url[:50]}...")
                else:
                    print(f"   {i}. ❌ Failed - {url[:50]}...")
            
            return success_count > 0
            
    except Exception as e:
        print(f"❌ ERROR: {e}")
        return False


async def test_sync_wrapper():
    """Test the synchronous wrapper (used by FastAPI)"""
    from app.playwright_crawler import TikTokPlaywrightCrawler
    
    print("\n" + "="*60)
    print("TEST 3: Sync Wrapper (FastAPI Compatible)")
    print("="*60 + "\n")
    
    try:
        crawler = TikTokPlaywrightCrawler()
        
        test_url = TEST_URLS[0]
        print(f"🔍 Testing sync wrapper with: {test_url}")
        print(f"⏳ This may take 15-20 seconds...\n")
        
        stats = crawler.get_tiktok_views(test_url)
        
        if stats:
            print(f"✅ SUCCESS!")
            print(f"   📊 Views: {stats['views']:,}")
            return True
        else:
            print(f"❌ FAILED - No stats returned")
            return False
            
    except Exception as e:
        print(f"❌ ERROR: {e}")
        return False


def test_sync_wrapper_normal():
    """Test sync wrapper without async context"""
    from app.playwright_crawler import TikTokPlaywrightCrawler
    
    print("\n" + "="*60)
    print("TEST 4: Sync Wrapper (Normal Python)")
    print("="*60 + "\n")
    
    try:
        crawler = TikTokPlaywrightCrawler()
        
        test_url = TEST_URLS[0]
        print(f"🔍 Testing: {test_url}")
        print(f"⏳ Please wait...\n")
        
        stats = crawler.get_tiktok_views(test_url)
        
        if stats:
            print(f"✅ SUCCESS!")
            print(f"   📊 Views: {stats['views']:,}")
            return True
        else:
            print(f"❌ FAILED")
            return False
            
    except Exception as e:
        print(f"❌ ERROR: {e}")
        return False


async def run_all_tests():
    """Run all tests"""
    print("\n" + "="*60)
    print("🧪 PLAYWRIGHT TIKTOK CRAWLER - TEST SUITE")
    print("="*60)
    print(f"⏰ Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Check if test URLs are updated
    if "username" in TEST_URLS[0]:
        print("\n" + "!"*60)
        print("⚠️  WARNING: Please update TEST_URLS with real TikTok video URLs")
        print("   Edit this file and replace the placeholder URLs")
        print("!"*60 + "\n")
        return False
    
    results = {}
    
    # Test 1: Single video
    results['single'] = await test_single_video()
    await asyncio.sleep(2)
    
    # Test 2: Multiple videos
    results['batch'] = await test_multiple_videos()
    await asyncio.sleep(2)
    
    # Test 3: Sync wrapper (async context)
    results['sync'] = await test_sync_wrapper()
    
    # Test 4: Sync wrapper (normal)
    print("\n⏳ Running sync test (may take a moment)...")
    results['sync_normal'] = test_sync_wrapper_normal()
    
    # Summary
    print("\n" + "="*60)
    print("📊 TEST SUMMARY")
    print("="*60 + "\n")
    
    passed = sum(results.values())
    total = len(results)
    
    for test_name, result in results.items():
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"   {test_name:20s} {status}")
    
    print(f"\n   Total: {passed}/{total} tests passed ({passed/total*100:.0f}%)")
    
    if passed == total:
        print("\n🎉 ALL TESTS PASSED! Ready to deploy to Railway.")
    else:
        print("\n⚠️  SOME TESTS FAILED. Please fix issues before deploying.")
        print("\nCommon issues:")
        print("   - Test URLs are not valid/public TikTok videos")
        print("   - TikTok is blocking your IP (try different network)")
        print("   - Chromium not installed (run: playwright install chromium)")
    
    print("\n" + "="*60)
    print(f"⏰ Finished at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*60 + "\n")
    
    return passed == total


def main():
    """Main entry point"""
    print("\n🚀 Starting Playwright TikTok Crawler Tests...\n")
    
    # Check if playwright is installed
    try:
        from playwright.async_api import async_playwright
        print("✅ Playwright is installed")
    except ImportError:
        print("❌ ERROR: Playwright is not installed")
        print("\nPlease run:")
        print("   pip install playwright")
        print("   playwright install chromium")
        sys.exit(1)
    
    # Check if app.playwright_crawler exists
    try:
        from app.playwright_crawler import PlaywrightTikTokCrawler
        print("✅ Crawler module found")
    except ImportError:
        print("❌ ERROR: app.playwright_crawler module not found")
        print("\nPlease ensure:")
        print("   1. You're running from project root directory")
        print("   2. app/playwright_crawler.py exists")
        sys.exit(1)
    
    # Run tests
    success = asyncio.run(run_all_tests())
    
    # Exit with appropriate code
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
