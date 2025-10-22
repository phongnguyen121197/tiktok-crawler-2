import logging
from typing import Dict, List, Optional
from datetime import datetime

# Import Playwright crawler
try:
    from app.playwright_crawler import TikTokPlaywrightCrawler
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    logging.warning("⚠️ Playwright not available, will use Lark data only")

logger = logging.getLogger(__name__)

class TikTokCrawler:
    """
    Main TikTok crawler class that processes Lark records and updates Google Sheets
    Now uses Playwright for scraping instead of API
    """
    
    def __init__(self, lark_client, sheets_client, use_playwright=True):
        self.lark_client = lark_client
        self.sheets_client = sheets_client
        self.use_playwright = use_playwright and PLAYWRIGHT_AVAILABLE
        
        if self.use_playwright:
            self.playwright_crawler = TikTokPlaywrightCrawler()
            logger.info("✅ Initialized with Playwright crawler")
        else:
            self.playwright_crawler = None
            logger.info("ℹ️ Initialized without Playwright (will use Lark data only)")
    
    def extract_video_id_from_url(self, url: str) -> Optional[str]:
        """Extract video ID from TikTok URL"""
        try:
            if '/video/' in url:
                video_id = url.split('/video/')[-1].split('?')[0]
                return video_id
        except Exception as e:
            logger.error(f"Error extracting video ID from {url}: {e}")
        return None
    
    def get_tiktok_views(self, video_url: str) -> Optional[Dict]:
        """
        Get TikTok video stats using Playwright
        Returns: {views, likes, comments, shares} or None
        """
        if not self.use_playwright or not self.playwright_crawler:
            logger.warning(f"Playwright not available for {video_url}")
            return None
        
        try:
            logger.info(f"🔍 Crawling with Playwright: {video_url}")
            stats = self.playwright_crawler.get_tiktok_views(video_url)
            
            if stats and stats.get('views', 0) > 0:
                logger.info(f"✅ Got {stats['views']:,} views for {video_url}")
                return stats
            else:
                logger.warning(f"⚠️ No stats returned from Playwright for {video_url}")
                return None
                
        except Exception as e:
            logger.error(f"❌ Error getting TikTok views for {video_url}: {e}")
            return None
    
    def extract_lark_field_value(self, field_data, field_type='text'):
        """
        Extract value from Lark field data (handles various formats)
        
        Args:
            field_data: The field data from Lark (can be dict, list, string, etc.)
            field_type: Type of field ('text', 'number', 'link')
            
        Returns:
            Extracted value as string or None
        """
        try:
            # Handle None/empty
            if field_data is None:
                return None
            
            # Handle string
            if isinstance(field_data, str):
                return field_data.strip() if field_data.strip() else None
            
            # Handle dict (e.g., {"text": "...", "link": "..."})
            if isinstance(field_data, dict):
                # Try 'text' first, then 'link'
                value = field_data.get('text') or field_data.get('link')
                if value:
                    return str(value).strip() if str(value).strip() else None
                return None
            
            # Handle list (e.g., [{"text": "123", "type": "text"}])
            if isinstance(field_data, list):
                if len(field_data) == 0:
                    return None
                
                first_item = field_data[0]
                
                if isinstance(first_item, dict):
                    value = first_item.get('text') or first_item.get('link')
                    if value:
                        return str(value).strip() if str(value).strip() else None
                elif isinstance(first_item, str):
                    return first_item.strip() if first_item.strip() else None
                else:
                    return str(first_item).strip() if str(first_item).strip() else None
            
            # Handle other primitives (int, float, etc.)
            if isinstance(field_data, (int, float)):
                return str(field_data)
            
            # Last resort: convert to string
            value = str(field_data).strip()
            return value if value else None
            
        except Exception as e:
            logger.error(f"Error extracting field value: {e}")
            return None
    
    def process_lark_record(self, lark_record: Dict) -> Optional[Dict]:
        """
        Process a single Lark record: extract data and crawl TikTok
        
        Args:
            lark_record: Record from Lark Bitable
            
        Returns:
            Processed record dict ready for Google Sheets or None if failed
        """
        try:
            record_id = lark_record.get('record_id') or lark_record.get('id')
            fields = lark_record.get('fields', {})
            
            # Extract TikTok link
            link_field = fields.get('Link air bài')
            link = self.extract_lark_field_value(link_field, 'link')
            
            if not link:
                logger.warning(f"No TikTok link found for record {record_id}")
                return None
            
            # Extract baseline (24h ago views)
            baseline_field = fields.get('Số view 24h trước')
            baseline = self.extract_lark_field_value(baseline_field, 'number')
            baseline_int = int(baseline) if baseline and baseline.isdigit() else 0
            
            # Extract current views from Lark (as fallback)
            current_field = fields.get('Lượt xem hiện tại')
            lark_views = self.extract_lark_field_value(current_field, 'number')
            lark_views_int = int(lark_views) if lark_views and lark_views.isdigit() else 0
            
            # Try to crawl fresh data from TikTok
            crawled_stats = self.get_tiktok_views(link)
            
            # Determine which views to use
            if crawled_stats and crawled_stats.get('views', 0) > 0:
                # Use freshly crawled data
                views = crawled_stats['views']
                status = 'success'
                logger.info(f"✅ Using crawled views: {views:,} for {link}")
            else:
                # Fallback to Lark data
                views = lark_views_int
                status = 'partial'
                logger.warning(f"⚠️ Using Lark fallback views: {views:,} for {link}")
            
            # Build record for Google Sheets
            processed_record = {
                'record_id': record_id,
                'link': link,
                'views': views,
                'baseline': baseline_int,
                'timestamp': datetime.now().isoformat(),
                'status': status
            }
            
            return processed_record
            
        except Exception as e:
            logger.error(f"Error processing record {lark_record.get('id')}: {e}")
            return None
    
    def crawl_all_videos(self) -> Dict:
        """
        Main function: Crawl all videos from Lark and update Google Sheets
        
        Returns:
            Stats dict with results
        """
        try:
            logger.info("🚀 Starting full crawl job...")
            
            # Step 1: Fetch all records from Lark
            logger.info("📥 Fetching records from Lark Bitable...")
            lark_records = self.lark_client.get_all_active_records()
            total_records = len(lark_records)
            logger.info(f"📊 Found {total_records} records in Lark")
            
            if total_records == 0:
                logger.warning("⚠️ No records found in Lark")
                return {
                    'total': 0,
                    'processed': 0,
                    'updated': 0,
                    'inserted': 0,
                    'failed': 0
                }
            
            # Step 2: Process each record
            logger.info("⚙️ Processing records...")
            processed_records = []
            failed_count = 0
            
            for i, lark_record in enumerate(lark_records):
                logger.info(f"📝 Processing record {i+1}/{total_records}")
                
                processed_record = self.process_lark_record(lark_record)
                
                if processed_record:
                    processed_records.append(processed_record)
                else:
                    failed_count += 1
            
            logger.info(f"✅ Processed {len(processed_records)} records, {failed_count} failed")
            
            # Step 3: Update Google Sheets with deduplication
            if len(processed_records) > 0:
                logger.info("📤 Updating Google Sheets with deduplication...")
                sheets_result = self.sheets_client.batch_update_records(processed_records)
                
                updated_count = sheets_result.get('updated', 0)
                inserted_count = sheets_result.get('inserted', 0)
                duplicates_removed = sheets_result.get('duplicates_removed', 0)
                
                logger.info(f"✅ Sheets update complete: {updated_count} updated, {inserted_count} inserted, {duplicates_removed} duplicates removed")
            else:
                logger.warning("⚠️ No records to update in Google Sheets")
                updated_count = 0
                inserted_count = 0
            
            # Return summary
            result = {
                'total': total_records,
                'processed': len(processed_records),
                'updated': updated_count,
                'inserted': inserted_count,
                'failed': failed_count
            }
            
            logger.info(f"🎉 Crawl job complete: {result}")
            return result
            
        except Exception as e:
            logger.error(f"❌ Error in crawl_all_videos: {e}", exc_info=True)
            return {
                'total': 0,
                'processed': 0,
                'updated': 0,
                'inserted': 0,
                'failed': 0,
                'error': str(e)
            }
    
    def crawl_videos_batch(self, record_ids: List[str]) -> Dict:
        """
        Crawl specific records by their IDs
        
        Args:
            record_ids: List of Lark record IDs to crawl
            
        Returns:
            Stats dict with results
        """
        try:
            logger.info(f"🎯 Starting batch crawl for {len(record_ids)} records...")
            
            processed_records = []
            failed_count = 0
            
            for record_id in record_ids:
                try:
                    # Get record from Lark
                    lark_record = self.lark_client.get_record(record_id)
                    
                    if lark_record:
                        processed_record = self.process_lark_record(lark_record)
                        if processed_record:
                            processed_records.append(processed_record)
                        else:
                            failed_count += 1
                    else:
                        logger.warning(f"Record {record_id} not found in Lark")
                        failed_count += 1
                        
                except Exception as e:
                    logger.error(f"Error processing record {record_id}: {e}")
                    failed_count += 1
            
            # Update Google Sheets
            if len(processed_records) > 0:
                sheets_result = self.sheets_client.batch_update_records(processed_records)
                updated_count = sheets_result.get('updated', 0)
                inserted_count = sheets_result.get('inserted', 0)
            else:
                updated_count = 0
                inserted_count = 0
            
            result = {
                'total': len(record_ids),
                'processed': len(processed_records),
                'updated': updated_count,
                'inserted': inserted_count,
                'failed': failed_count
            }
            
            logger.info(f"✅ Batch crawl complete: {result}")
            return result
            
        except Exception as e:
            logger.error(f"❌ Error in crawl_videos_batch: {e}")
            return {
                'total': len(record_ids),
                'processed': 0,
                'updated': 0,
                'inserted': 0,
                'failed': len(record_ids),
                'error': str(e)
            }
