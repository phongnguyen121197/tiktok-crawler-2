import logging
from typing import List, Dict, Optional
from datetime import datetime

# Import Playwright crawler
try:
    from app.playwright_crawler import TikTokPlaywrightCrawler
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    logging.warning("⚠️ Playwright not available, will use Lark data fallback only")

logger = logging.getLogger(__name__)

class TikTokCrawler:
    """
    TikTok Crawler v3.2 with Playwright integration
    NOW WITH PUBLISH DATE PRIORITY! 📅
    - Preserves existing publish_date if already set
    - Clears data for broken/unavailable links
    """
    
    def __init__(self, lark_client, sheets_client, use_playwright=True):
        """
        Initialize crawler with Lark and Sheets clients
        
        Args:
            lark_client: LarkClient instance
            sheets_client: GoogleSheetsClient instance
            use_playwright: Use Playwright for scraping (default: True)
        """
        self.lark_client = lark_client
        self.sheets_client = sheets_client
        self.use_playwright = use_playwright and PLAYWRIGHT_AVAILABLE
        
        # Initialize Playwright crawler if available
        if self.use_playwright:
            try:
                self.playwright_crawler = TikTokPlaywrightCrawler()
                logger.info("✅ Playwright crawler v3.2 initialized")
            except Exception as e:
                logger.error(f"❌ Failed to initialize Playwright: {e}")
                self.playwright_crawler = None
                self.use_playwright = False
        else:
            self.playwright_crawler = None
        
        logger.info(f"🔧 Crawler mode: {'Playwright v3.2' if self.use_playwright else 'Lark fallback only'}")
        
    def extract_video_id_from_url(self, url: str) -> Optional[str]:
        """Extract TikTok video ID from URL"""
        try:
            if '/video/' in url:
                video_id = url.split('/video/')[1]
                if '?' in video_id:
                    video_id = video_id.split('?')[0]
                return video_id.strip()
            
            logger.warning(f"⚠️ Could not extract video ID from: {url}")
            return None
            
        except Exception as e:
            logger.error(f"❌ Error extracting video ID: {e}")
            return None
    
    def extract_lark_field_value(self, field_data, field_type: str = 'text'):
        """
        Extract value from Lark field (handles different formats)
        Formats: text, number, link, array, date
        """
        try:
            if not field_data:
                return None
            
            # If it's a list
            if isinstance(field_data, list):
                if len(field_data) == 0:
                    return None
                
                first_item = field_data[0]
                
                # List of objects
                if isinstance(first_item, dict):
                    if field_type == 'text':
                        return str(first_item.get('text', '')).strip()
                    elif field_type == 'number':
                        text_value = first_item.get('text', '0')
                        try:
                            return int(text_value)
                        except (ValueError, TypeError):
                            return 0
                    else:
                        return first_item
                # List of primitives
                else:
                    if field_type == 'number':
                        try:
                            return int(first_item)
                        except (ValueError, TypeError):
                            return 0
                    else:
                        return str(first_item)
            
            # If it's a dictionary (like link field)
            if isinstance(field_data, dict):
                if field_type == 'link':
                    link_value = field_data.get('text') or field_data.get('link')
                    return str(link_value).strip() if link_value else None
                elif field_type == 'text':
                    return str(field_data.get('text', '')).strip()
                else:
                    return field_data
            
            # If it's a primitive
            if field_type == 'number':
                try:
                    return int(field_data) if field_data else 0
                except (ValueError, TypeError):
                    return 0
            else:
                return str(field_data).strip() if field_data else None
                
        except Exception as e:
            logger.warning(f"⚠️ Error extracting field value: {e}")
            return None
    
    def extract_publish_date_from_lark(self, field_data) -> Optional[str]:
        """
        Extract publish date from Lark field
        Handles: timestamp (int), date string, text
        Returns: YYYY-MM-DD format or None
        """
        try:
            if not field_data:
                return None
            
            # If it's a number (timestamp)
            if isinstance(field_data, (int, float)):
                if field_data > 0:
                    ts = field_data / 1000 if field_data > 9999999999 else field_data
                    dt = datetime.fromtimestamp(ts)
                    if 2016 <= dt.year <= 2030:
                        return dt.strftime('%Y-%m-%d')
                return None
            
            # If it's a string
            if isinstance(field_data, str):
                field_data = field_data.strip()
                if not field_data or field_data in ['', 'None', 'null', 'N/A', '-']:
                    return None
                
                # Try parsing as date
                for fmt in ['%Y-%m-%d', '%d/%m/%Y', '%m/%d/%Y', '%Y/%m/%d']:
                    try:
                        dt = datetime.strptime(field_data, fmt)
                        return dt.strftime('%Y-%m-%d')
                    except:
                        continue
                
                # Try as timestamp string
                try:
                    ts = int(field_data)
                    ts = ts / 1000 if ts > 9999999999 else ts
                    dt = datetime.fromtimestamp(ts)
                    if 2016 <= dt.year <= 2030:
                        return dt.strftime('%Y-%m-%d')
                except:
                    pass
                
                return None
            
            # If it's a dict (Lark field format)
            if isinstance(field_data, dict):
                text_value = field_data.get('text', '')
                return self.extract_publish_date_from_lark(text_value)
            
            # If it's a list
            if isinstance(field_data, list) and len(field_data) > 0:
                return self.extract_publish_date_from_lark(field_data[0])
            
            return None
            
        except Exception as e:
            logger.debug(f"Error extracting publish date: {e}")
            return None
    
    def process_lark_record(self, lark_record: Dict, tiktok_result: Dict = None) -> Optional[Dict]:
        """
        Process Lark record with TikTok crawl result
        v3.2: Handles publish_date priority and broken links
        
        Args:
            lark_record: Record from Lark Bitable
            tiktok_result: Result from crawler (optional, if batch crawled)
            
        Returns:
            Dict with processed data or None
        """
        try:
            fields = lark_record.get('fields', {})
            record_id = lark_record.get('id', '')
            
            # Extract Link
            link_field = fields.get('Link air bài', {})
            link_value = self.extract_lark_field_value(link_field, 'link')
            
            if not link_value:
                logger.warning(f"⚠️ Record {record_id} has no link, skipping")
                return None
            
            # Extract Current Views from Lark (fallback data)
            current_views_lark = fields.get('Lượt xem hiện tại', [])
            views_lark = self.extract_lark_field_value(current_views_lark, 'number')
            
            # Extract 24h Baseline from Lark
            baseline_lark = fields.get('Số view 24h trước', [])
            baseline_value = self.extract_lark_field_value(baseline_lark, 'number')
            
            # 📅 Extract existing Published Date from Lark
            publish_date_lark_field = fields.get('Published Date', '')
            publish_date_from_lark = self.extract_publish_date_from_lark(publish_date_lark_field)
            
            # Use provided TikTok result or fallback to Lark data
            if tiktok_result:
                # v3.2: Check if broken link
                if tiktok_result.get('is_broken'):
                    # Broken link - clear all data
                    logger.warning(f"🔗 Broken link detected: {link_value[:50]}...")
                    return {
                        'record_id': record_id,
                        'link': link_value,
                        'views': None,  # Will be handled by sheets_client
                        'baseline': None,
                        'publish_date': None,  # Clear date for broken link
                        'status': 'broken',
                        'is_broken': True,
                        'source_data': {
                            'lark_views': views_lark,
                            'lark_baseline': baseline_value,
                            'lark_publish_date': publish_date_from_lark,
                            'tiktok_stats': tiktok_result,
                            'error': tiktok_result.get('error', '')
                        }
                    }
                
                if tiktok_result.get('success') and tiktok_result.get('views', 0) > 0:
                    # Success - use crawled data
                    current_views = tiktok_result.get('views', views_lark or 0)
                    
                    # v3.2: Publish date from crawler already handles priority
                    publish_date = tiktok_result.get('publish_date') or publish_date_from_lark
                    
                    status = 'success'
                else:
                    # Failed but not broken - use Lark fallback, preserve date
                    current_views = views_lark or 0
                    publish_date = publish_date_from_lark
                    status = 'partial'
            else:
                # No TikTok result - use Lark data only
                current_views = views_lark or 0
                publish_date = publish_date_from_lark
                status = 'partial'
            
            # Use Lark baseline
            baseline = baseline_value if baseline_value else (views_lark or 0)
            
            processed_record = {
                'record_id': record_id,
                'link': link_value,
                'views': current_views,
                'baseline': baseline,
                'publish_date': publish_date,
                'status': status,
                'is_broken': False,
                'source_data': {
                    'lark_views': views_lark,
                    'lark_baseline': baseline_value,
                    'lark_publish_date': publish_date_from_lark,
                    'tiktok_stats': tiktok_result
                }
            }
            
            logger.debug(f"✅ Processed record {record_id}: {current_views:,} views, Published: {publish_date or 'N/A'} (status: {status})")
            return processed_record
            
        except Exception as e:
            logger.error(f"❌ Error processing Lark record: {e}")
            return None
    
    def crawl_all_videos(self) -> Dict:
        """
        Main crawler function v3.2
        1. Get all active records from Lark
        2. Extract existing publish_dates for priority handling
        3. Batch crawl with Playwright
        4. Process results with broken link detection
        5. Update/Insert into Google Sheets
        
        Returns:
            Dict with success status and statistics
        """
        try:
            logger.info("🚀 Starting TikTok crawler v3.2...")
            
            # Step 1: Get records from Lark
            logger.info("📋 Fetching records from Lark Bitable...")
            lark_records = self.lark_client.get_all_active_records()
            
            if not lark_records:
                logger.error("❌ No records found in Lark")
                return {
                    'success': False,
                    'message': 'No records found in Lark',
                    'stats': {
                        'total': 0, 'processed': 0, 'updated': 0,
                        'inserted': 0, 'failed': 0, 'broken': 0
                    }
                }
            
            logger.info(f"✅ Fetched {len(lark_records)} records from Lark")
            
            # Step 2: Build URL list and existing_dates map
            urls = []
            existing_dates = {}
            record_by_url = {}
            
            for record in lark_records:
                fields = record.get('fields', {})
                record_id = record.get('id', '')
                
                # Extract link
                link_field = fields.get('Link air bài', {})
                link_value = self.extract_lark_field_value(link_field, 'link')
                
                if not link_value:
                    continue
                
                # Extract existing publish_date
                publish_date_field = fields.get('Published Date', '')
                existing_date = self.extract_publish_date_from_lark(publish_date_field)
                
                urls.append(link_value)
                existing_dates[link_value] = existing_date or ''
                record_by_url[link_value] = record
            
            # Log existing dates stats
            valid_dates_count = sum(1 for d in existing_dates.values() if d)
            logger.info(f"📅 Existing valid dates: {valid_dates_count}/{len(urls)}")
            
            # Step 3: Batch crawl with Playwright
            logger.info("🔄 Starting batch crawl with Playwright v3.2...")
            crawl_results = {}
            
            if self.use_playwright and self.playwright_crawler:
                try:
                    # 📅 Pass existing_dates to crawler for priority handling
                    results_list = self.playwright_crawler.crawl_batch_sync(urls, existing_dates=existing_dates)
                    
                    # Map results by URL
                    for result in results_list:
                        url = result.get('url', '')
                        if url:
                            crawl_results[url] = result
                            
                except Exception as e:
                    logger.error(f"❌ Batch crawl error: {e}")
            
            # Step 4: Process each record with crawl results
            logger.info("🔄 Processing records with crawl results...")
            processed_records = []
            failed_count = 0
            broken_count = 0
            
            for idx, url in enumerate(urls, 1):
                if idx % 50 == 0:
                    logger.info(f"Processing records: {idx}/{len(urls)}")
                
                try:
                    record = record_by_url.get(url)
                    if not record:
                        continue
                    
                    tiktok_result = crawl_results.get(url)
                    processed = self.process_lark_record(record, tiktok_result)
                    
                    if processed:
                        processed_records.append(processed)
                        if processed.get('is_broken'):
                            broken_count += 1
                        elif processed.get('status') != 'success':
                            failed_count += 1
                    else:
                        failed_count += 1
                        
                except Exception as e:
                    logger.error(f"❌ Error processing record {idx}: {e}")
                    failed_count += 1
            
            logger.info(f"✅ Processed {len(processed_records)} records, {failed_count} failed, {broken_count} broken")
            
            # Step 5: Update/Insert into Google Sheets
            logger.info("📊 Updating Google Sheets...")
            updated, inserted = self.sheets_client.batch_update_records(processed_records)
            
            # Calculate success stats
            success_count = sum(1 for r in processed_records if r.get('status') == 'success')
            
            result = {
                'success': True,
                'message': 'Crawler v3.2 completed successfully',
                'stats': {
                    'total': len(lark_records),
                    'processed': len(processed_records),
                    'success': success_count,
                    'updated': updated,
                    'inserted': inserted,
                    'failed': failed_count,
                    'broken': broken_count
                }
            }
            
            logger.info(f"✅ Crawler v3.2 completed: {result['stats']}")
            return result
            
        except Exception as e:
            logger.error(f"❌ Crawler failed: {e}")
            return {
                'success': False,
                'message': str(e),
                'stats': {
                    'total': 0, 'processed': 0, 'updated': 0,
                    'inserted': 0, 'failed': 0, 'broken': 0
                }
            }
    
    def crawl_videos_batch(self, record_ids: List[str] = None) -> Dict:
        """
        Crawl specific videos by Record IDs (optional)
        If record_ids is None, crawl all
        """
        try:
            logger.info("🚀 Starting batch crawler v3.2...")
            
            # Get all records
            all_records = self.lark_client.get_all_active_records()
            
            # Filter if specific IDs provided
            if record_ids:
                lark_records = [r for r in all_records if r.get('id') in record_ids]
                logger.info(f"🔍 Filtered to {len(lark_records)} records")
            else:
                lark_records = all_records
            
            # Build URL list and existing_dates
            urls = []
            existing_dates = {}
            record_by_url = {}
            
            for record in lark_records:
                fields = record.get('fields', {})
                link_field = fields.get('Link air bài', {})
                link_value = self.extract_lark_field_value(link_field, 'link')
                
                if not link_value:
                    continue
                
                publish_date_field = fields.get('Published Date', '')
                existing_date = self.extract_publish_date_from_lark(publish_date_field)
                
                urls.append(link_value)
                existing_dates[link_value] = existing_date or ''
                record_by_url[link_value] = record
            
            # Batch crawl
            crawl_results = {}
            if self.use_playwright and self.playwright_crawler:
                results_list = self.playwright_crawler.crawl_batch_sync(urls, existing_dates=existing_dates)
                for result in results_list:
                    url = result.get('url', '')
                    if url:
                        crawl_results[url] = result
            
            # Process results
            processed_records = []
            for url in urls:
                record = record_by_url.get(url)
                if not record:
                    continue
                
                tiktok_result = crawl_results.get(url)
                processed = self.process_lark_record(record, tiktok_result)
                if processed:
                    processed_records.append(processed)
            
            # Update sheets
            updated, inserted = self.sheets_client.batch_update_records(processed_records)
            
            return {
                'success': True,
                'message': 'Batch crawl v3.2 completed',
                'stats': {
                    'total': len(lark_records),
                    'processed': len(processed_records),
                    'updated': updated,
                    'inserted': inserted
                }
            }
            
        except Exception as e:
            logger.error(f"❌ Batch crawl failed: {e}")
            return {
                'success': False, 
                'message': str(e),
                'stats': {
                    'total': 0, 'processed': 0, 'updated': 0, 'inserted': 0
                }
            }
    
    # Legacy method for single video (kept for compatibility)
    def get_tiktok_views(self, video_url: str) -> Optional[Dict]:
        """Get TikTok video stats using Playwright"""
        if self.use_playwright and self.playwright_crawler:
            try:
                logger.debug(f"🔍 Crawling with Playwright: {video_url}")
                stats = self.playwright_crawler.get_tiktok_views(video_url)
                
                if stats and stats.get('views', 0) > 0:
                    logger.debug(f"✅ Got TikTok stats: {stats['views']:,} views")
                    return stats
                else:
                    logger.warning(f"⚠️ Playwright returned no stats")
                    return None
                    
            except Exception as e:
                logger.error(f"❌ Playwright error: {e}")
                return None
        else:
            logger.debug(f"⚠️ Playwright not available")
            return None
