"""
🚀 OPTIMIZED TikTok Crawler
===========================
Uses BATCH processing instead of sequential crawling
Expected: 550 videos in 30-45 minutes (was 2 hours)
"""

import logging
from typing import List, Dict, Optional
from datetime import datetime

# Import optimized Playwright crawler
try:
    from app.playwright_crawler import TikTokPlaywrightCrawler, OptimizedTikTokCrawler, CrawlerConfig
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    logging.warning("⚠️ Playwright not available")

import asyncio

logger = logging.getLogger(__name__)


class TikTokCrawler:
    """
    TikTok Crawler with OPTIMIZED batch processing
    
    Key changes from original:
    1. Uses batch crawling (10-12 concurrent) instead of sequential
    2. Collects all URLs first, then crawls in parallel
    3. Single batch update to Sheets instead of one-by-one
    """
    
    def __init__(self, lark_client, sheets_client, use_playwright=True):
        self.lark_client = lark_client
        self.sheets_client = sheets_client
        self.use_playwright = use_playwright and PLAYWRIGHT_AVAILABLE
        
        if self.use_playwright:
            self.playwright_crawler = TikTokPlaywrightCrawler()
            logger.info("✅ Optimized Playwright crawler initialized")
        else:
            self.playwright_crawler = None
        
        logger.info(f"🔧 Crawler mode: {'Optimized Parallel' if self.use_playwright else 'Fallback only'}")
    
    def extract_lark_field_value(self, field_data, field_type: str = 'text'):
        """Extract value from Lark field (handles different formats)"""
        try:
            if not field_data:
                return None
            
            if isinstance(field_data, list):
                if len(field_data) == 0:
                    return None
                first_item = field_data[0]
                if isinstance(first_item, dict):
                    if field_type == 'text':
                        return str(first_item.get('text', '')).strip()
                    elif field_type == 'number':
                        try:
                            return int(first_item.get('text', 0))
                        except:
                            return 0
                    return first_item
                else:
                    if field_type == 'number':
                        try:
                            return int(first_item)
                        except:
                            return 0
                    return str(first_item)
            
            if isinstance(field_data, dict):
                if field_type == 'link':
                    return (field_data.get('text') or field_data.get('link') or '').strip()
                elif field_type == 'text':
                    return str(field_data.get('text', '')).strip()
                return field_data
            
            if field_type == 'number':
                try:
                    return int(field_data) if field_data else 0
                except:
                    return 0
            return str(field_data).strip() if field_data else None
            
        except Exception as e:
            logger.warning(f"⚠️ Error extracting field: {e}")
            return None
    
    def crawl_all_videos(self) -> Dict:
        """
        🚀 OPTIMIZED Main crawler function
        
        New approach:
        1. Get all records from Lark
        2. Extract all URLs
        3. Batch crawl ALL URLs in parallel (10-12 concurrent)
        4. Match results back to records
        5. Batch update to Sheets
        """
        try:
            start_time = datetime.now()
            logger.info("🚀 Starting OPTIMIZED TikTok crawler...")
            
            # Step 1: Get records from Lark
            logger.info("📋 Fetching records from Lark Bitable...")
            lark_records = self.lark_client.get_all_active_records()
            
            if not lark_records:
                logger.error("❌ No records found in Lark")
                return self._error_result("No records found in Lark")
            
            logger.info(f"✅ Fetched {len(lark_records)} records from Lark")
            
            # Step 2: Extract URLs and build lookup
            logger.info("🔗 Extracting URLs from records...")
            url_to_record = {}  # {url: lark_record}
            urls_to_crawl = []
            
            for lark_record in lark_records:
                fields = lark_record.get('fields', {})
                record_id = lark_record.get('id', '')
                
                link_field = fields.get('Link air bài', {})
                link_value = self.extract_lark_field_value(link_field, 'link')
                
                if link_value:
                    urls_to_crawl.append(link_value)
                    url_to_record[link_value] = lark_record
            
            logger.info(f"🔗 Found {len(urls_to_crawl)} URLs to crawl")
            
            if not urls_to_crawl:
                return self._error_result("No valid URLs found")
            
            # Step 3: BATCH CRAWL all URLs in parallel! 🚀
            logger.info(f"⚡ Starting parallel crawl of {len(urls_to_crawl)} URLs...")
            
            if self.use_playwright and self.playwright_crawler:
                crawl_results = self.playwright_crawler.crawl_batch_sync(urls_to_crawl)
            else:
                # Fallback: no crawling, use Lark data only
                crawl_results = [{'url': url, 'success': False} for url in urls_to_crawl]
            
            # Build results lookup
            results_by_url = {r['url']: r for r in crawl_results if r}
            
            # Step 4: Process results and prepare Sheets data
            logger.info("📊 Processing results...")
            processed_records = []
            success_count = 0
            partial_count = 0
            failed_count = 0
            
            for url, lark_record in url_to_record.items():
                crawl_result = results_by_url.get(url, {})
                fields = lark_record.get('fields', {})
                record_id = lark_record.get('id', '')
                
                # Get Lark fallback data
                views_lark = self.extract_lark_field_value(
                    fields.get('Lượt xem hiện tại', []), 'number'
                )
                baseline_lark = self.extract_lark_field_value(
                    fields.get('Số view 24h trước', []), 'number'
                )
                
                # Determine final values
                if crawl_result.get('success'):
                    current_views = crawl_result.get('views', views_lark or 0)
                    publish_date = crawl_result.get('publish_date', '')
                    status = 'success'
                    success_count += 1
                else:
                    current_views = views_lark or 0
                    publish_date = ''
                    status = 'partial' if views_lark else 'failed'
                    if views_lark:
                        partial_count += 1
                    else:
                        failed_count += 1
                
                baseline = baseline_lark or views_lark or 0
                
                processed_records.append({
                    'record_id': record_id,
                    'link': url,
                    'views': current_views,
                    'baseline': baseline,
                    'publish_date': publish_date,
                    'status': status,
                })
            
            logger.info(f"✅ Processed: {success_count} success, {partial_count} partial, {failed_count} failed")
            
            # Step 5: Batch update to Sheets
            logger.info("📊 Updating Google Sheets...")
            updated, inserted = self.sheets_client.batch_update_records(processed_records)
            
            # Calculate duration
            duration = (datetime.now() - start_time).total_seconds()
            
            result = {
                'success': True,
                'message': 'Optimized crawler completed successfully',
                'duration_seconds': duration,
                'duration_minutes': duration / 60,
                'stats': {
                    'total': len(lark_records),
                    'urls_crawled': len(urls_to_crawl),
                    'success': success_count,
                    'partial': partial_count,
                    'failed': failed_count,
                    'updated': updated,
                    'inserted': inserted,
                    'speed_per_video': duration / len(urls_to_crawl) if urls_to_crawl else 0,
                }
            }
            
            logger.info(f"""
╔══════════════════════════════════════════════════════════════════╗
║                    🎉 CRAWLER COMPLETE                            ║
╠══════════════════════════════════════════════════════════════════╣
║  Total records: {len(lark_records):>5}                                         ║
║  Crawled: {success_count:>5} success | {partial_count:>4} partial | {failed_count:>4} failed         ║
║  Sheets: {updated:>5} updated | {inserted:>4} inserted                        ║
║  Duration: {duration/60:.1f} minutes ({duration:.0f} seconds)                    ║
║  Speed: {duration/len(urls_to_crawl):.2f}s per video                                  ║
╚══════════════════════════════════════════════════════════════════╝
            """)
            
            return result
            
        except Exception as e:
            logger.error(f"❌ Crawler failed: {e}", exc_info=True)
            return self._error_result(str(e))
    
    def crawl_videos_batch(self, record_ids: List[str] = None) -> Dict:
        """
        Crawl specific videos by Record IDs (or all if None)
        Uses the same optimized batch approach
        """
        try:
            logger.info("🚀 Starting batch crawler...")
            
            all_records = self.lark_client.get_all_active_records()
            
            if record_ids:
                lark_records = [r for r in all_records if r.get('id') in record_ids]
                logger.info(f"🔍 Filtered to {len(lark_records)} records")
            else:
                lark_records = all_records
            
            # Extract URLs
            urls_to_crawl = []
            url_to_record = {}
            
            for record in lark_records:
                fields = record.get('fields', {})
                link = self.extract_lark_field_value(fields.get('Link air bài', {}), 'link')
                if link:
                    urls_to_crawl.append(link)
                    url_to_record[link] = record
            
            # Batch crawl
            if self.use_playwright and self.playwright_crawler:
                crawl_results = self.playwright_crawler.crawl_batch_sync(urls_to_crawl)
            else:
                crawl_results = []
            
            results_by_url = {r['url']: r for r in crawl_results if r}
            
            # Process
            processed_records = []
            for url, record in url_to_record.items():
                result = results_by_url.get(url, {})
                fields = record.get('fields', {})
                
                views_lark = self.extract_lark_field_value(
                    fields.get('Lượt xem hiện tại', []), 'number'
                )
                baseline_lark = self.extract_lark_field_value(
                    fields.get('Số view 24h trước', []), 'number'
                )
                
                processed_records.append({
                    'record_id': record.get('id', ''),
                    'link': url,
                    'views': result.get('views', views_lark or 0),
                    'baseline': baseline_lark or views_lark or 0,
                    'publish_date': result.get('publish_date', ''),
                    'status': 'success' if result.get('success') else 'partial',
                })
            
            updated, inserted = self.sheets_client.batch_update_records(processed_records)
            
            return {
                'success': True,
                'message': 'Batch crawl completed',
                'stats': {
                    'total': len(lark_records),
                    'processed': len(processed_records),
                    'updated': updated,
                    'inserted': inserted,
                }
            }
            
        except Exception as e:
            logger.error(f"❌ Batch crawl failed: {e}")
            return self._error_result(str(e))
    
    def _error_result(self, message: str) -> Dict:
        """Return error result dict"""
        return {
            'success': False,
            'message': message,
            'stats': {
                'total': 0,
                'processed': 0,
                'updated': 0,
                'inserted': 0,
                'failed': 0,
            }
        }
    
    # Legacy method for backward compatibility
    def get_tiktok_views(self, video_url: str) -> Optional[Dict]:
        """Get single video stats (for backward compatibility)"""
        if self.use_playwright and self.playwright_crawler:
            return self.playwright_crawler.get_tiktok_views(video_url)
        return None
