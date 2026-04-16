import logging
from typing import List, Dict, Optional
from datetime import datetime, date

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
    TikTok Crawler v4.2 — Playwright only, optimised for low CPU/RAM
    - Playwright: browser simulation, resource-blocking, fast timeouts
    - pending_propagation: new videos skipped + queued for retry after 6h
    - Broken link detection no longer clears data on transient failures
    """

    def __init__(self, lark_client, sheets_client, use_playwright=True):
        self.lark_client = lark_client
        self.sheets_client = sheets_client
        self.use_playwright = use_playwright and PLAYWRIGHT_AVAILABLE

        if self.use_playwright:
            try:
                self.playwright_crawler = TikTokPlaywrightCrawler()
                logger.info("✅ Playwright crawler initialized (v4.2 optimised)")
            except Exception as e:
                logger.error(f"❌ Failed to initialize Playwright: {e}")
                self.playwright_crawler = None
                self.use_playwright = False
        else:
            self.playwright_crawler = None

        logger.info(f"🔧 Crawler mode: {'Playwright' if self.use_playwright else 'Lark data only'}")
        
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
    
    def is_recent_video(self, publish_date_str: Optional[str]) -> bool:
        """
        Check if a video's publish date is within the crawl window.
        Returns True if:
        - publish_date is in current month or previous month
        - publish_date is None/empty (unknown → needs crawl)
        Returns False if publish_date is older than previous month.
        
        Example: If today is 2026-02-15, window = [2026-01-01, 2026-02-28]
                 Videos from 2025-12 and earlier → skip
        """
        if not publish_date_str:
            return True  # No date → treat as new, needs crawl
        
        try:
            video_date = datetime.strptime(publish_date_str, '%Y-%m-%d').date()
            today = date.today()
            
            # Calculate first day of previous month
            if today.month == 1:
                cutoff = date(today.year - 1, 12, 1)
            else:
                cutoff = date(today.year, today.month - 1, 1)
            
            return video_date >= cutoff
        except (ValueError, TypeError):
            return True  # Invalid date → treat as unknown, needs crawl
    
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
            # Lark list API may return either 'record_id' or 'id' depending on version
            record_id = lark_record.get('record_id') or lark_record.get('id', '')
            
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
                # ── pending_propagation: very new video, data not ready yet ──
                # Skip writing to sheets — caller will queue for retry.
                if tiktok_result.get('pending_propagation'):
                    logger.info(f"⏳ Pending propagation (skip write): {link_value[:50]}...")
                    return None  # Caller skips this record entirely

                # ── broken link: video deleted/private ──
                if tiktok_result.get('is_broken'):
                    logger.warning(f"🔗 Broken link detected: {link_value[:50]}...")
                    return {
                        'record_id': record_id,
                        'link': link_value,
                        'views': None,
                        'baseline': None,
                        'publish_date': None,
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
                    publish_date = tiktok_result.get('publish_date') or publish_date_from_lark
                    status = 'success'
                else:
                    # Failed but not broken - preserve Lark data
                    current_views = views_lark or 0
                    publish_date = publish_date_from_lark
                    status = 'partial'
            else:
                # No TikTok result - use Lark data only
                current_views = views_lark or 0
                publish_date = publish_date_from_lark
                status = 'partial'
            
            # "Số view 24h trước" = old "Lượt xem hiện tại" before this crawl.
            # This allows the dashboard to compute the daily view delta correctly.
            baseline = views_lark or 0
            
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
                # Lark list API may return 'record_id' or 'id' depending on version
                record_id = record.get('record_id') or record.get('id', '')

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
            
            # Log existing dates stats from Lark
            valid_dates_lark = sum(1 for d in existing_dates.values() if d)
            logger.info(f"📅 Existing valid dates from Lark: {valid_dates_lark}/{len(urls)}")

            # Step 2.1: Build URL → target record_id map from the WRITE table.
            # Source and write tables are independent; record IDs differ.
            target_record_by_url = {}
            try:
                target_record_by_url = self.lark_client.get_target_records_by_url()
                logger.info(f"✅ Target table loaded: {len(target_record_by_url)} URL→record_id mappings")
                no_target = [u for u in urls if u not in target_record_by_url]
                if no_target:
                    logger.warning(
                        f"⚠️ {len(no_target)} source URLs have NO matching record in write table "
                        f"(those won't be updated). Sample: {no_target[:3]}"
                    )
            except Exception as e:
                logger.warning(f"⚠️ Could not load target table records: {e}. Writes will be skipped.")
            
            # Step 2.5: Merge dates from Google Sheets (where crawled dates are actually stored)
            # Lark may not have Published Date, but Sheets does from previous crawl runs
            try:
                sheets_dates = self.sheets_client.get_publish_dates_by_link()
                merged_count = 0
                for url in urls:
                    if not existing_dates.get(url) and url in sheets_dates:
                        existing_dates[url] = sheets_dates[url]
                        merged_count += 1
                if merged_count > 0:
                    logger.info(f"📅 Merged {merged_count} dates from Google Sheets")
            except Exception as e:
                logger.warning(f"⚠️ Could not read dates from Sheets: {e}")
            
            valid_dates_total = sum(1 for d in existing_dates.values() if d)
            logger.info(f"📅 Total valid dates (Lark + Sheets): {valid_dates_total}/{len(urls)}")
            
            # Step 3: Filter - only crawl recent videos (current & previous month)
            all_urls = urls[:]  # Keep original list for reference
            urls_to_crawl = []
            skipped_old = 0
            
            for url in all_urls:
                existing_date = existing_dates.get(url, '')
                if self.is_recent_video(existing_date):
                    urls_to_crawl.append(url)
                else:
                    skipped_old += 1
            
            if skipped_old > 0:
                today = date.today()
                if today.month == 1:
                    cutoff_str = f"{today.year - 1}-12"
                else:
                    cutoff_str = f"{today.year}-{today.month - 1:02d}"
                logger.info(f"📅 Date filter: crawling {len(urls_to_crawl)} recent videos (>= {cutoff_str}), skipping {skipped_old} old videos")
            
            # Step 4: Playwright crawl in incremental batches
            # Batching ensures partial progress is saved if the run is interrupted.
            INCREMENTAL_BATCH_SIZE = 100
            total_to_crawl = len(urls_to_crawl)
            logger.info(
                f"🔄 Starting incremental batch crawl v4.2 "
                f"({total_to_crawl} videos, batch size {INCREMENTAL_BATCH_SIZE})..."
            )

            all_processed = []
            total_updated = 0
            total_failed = 0
            total_broken = 0
            total_pending = 0
            all_pending_urls = []  # URLs to retry later (data not propagated yet)

            for batch_start in range(0, total_to_crawl, INCREMENTAL_BATCH_SIZE):
                batch_urls = urls_to_crawl[batch_start:batch_start + INCREMENTAL_BATCH_SIZE]
                batch_num = batch_start // INCREMENTAL_BATCH_SIZE + 1
                total_batches = (total_to_crawl + INCREMENTAL_BATCH_SIZE - 1) // INCREMENTAL_BATCH_SIZE

                logger.info(
                    f"📦 Batch {batch_num}/{total_batches}: "
                    f"{len(batch_urls)} videos (progress: {batch_start}/{total_to_crawl})..."
                )

                # ── Playwright crawl ──────────────────────────────────────────
                crawl_results = {}

                if self.use_playwright and self.playwright_crawler:
                    try:
                        pw_list = self.playwright_crawler.crawl_batch_sync(
                            batch_urls,
                            existing_dates=existing_dates,
                        )
                        for r in pw_list:
                            url_r = r.get('url', '')
                            if url_r:
                                crawl_results[url_r] = r
                    except Exception as e:
                        logger.error(f"❌ Playwright batch {batch_num} error: {e}")

                # ── Process results ────────────────────────────────────────────
                batch_processed = []
                batch_pending_urls = []
                batch_failed = 0
                batch_broken = 0

                for url in batch_urls:
                    try:
                        record = record_by_url.get(url)
                        if not record:
                            continue

                        tiktok_result = crawl_results.get(url)

                        # pending_propagation → queue for retry, skip Sheets write
                        if tiktok_result and tiktok_result.get('pending_propagation'):
                            batch_pending_urls.append(url)
                            continue

                        processed = self.process_lark_record(record, tiktok_result)

                        if processed:
                            # Replace source record_id with target table's record_id
                            target_rid = target_record_by_url.get(url)
                            if not target_rid:
                                logger.debug(f"⏭️ No target record for URL, skipping write: {url[:60]}")
                                # Don't count as failure — it's a configuration gap
                            else:
                                processed['record_id'] = target_rid
                                batch_processed.append(processed)
                                if processed.get('is_broken'):
                                    batch_broken += 1
                                elif processed.get('status') != 'success':
                                    batch_failed += 1
                        else:
                            batch_failed += 1
                    except Exception as e:
                        logger.error(f"❌ Error processing record: {e}")
                        batch_failed += 1

                # ── Write batch to Lark Bitable ───────────────────────────────
                if batch_processed:
                    try:
                        updated, failed = self.lark_client.batch_update_records(batch_processed)
                        total_updated += updated
                        if failed:
                            logger.warning(f"⚠️ Batch {batch_num}: {failed} records failed Lark write")
                        logger.info(f"✅ Batch {batch_num}/{total_batches} → Lark: {updated} updated")
                    except Exception as e:
                        logger.error(f"❌ Batch {batch_num} Lark write error: {e}")

                # ── Save pending URLs to retry queue ──────────────────────────
                if batch_pending_urls:
                    try:
                        pending_records = []
                        for url in batch_pending_urls:
                            record = record_by_url.get(url)
                            if record:
                                pending_records.append({
                                    'url': url,
                                    'record_id': record.get('record_id') or record.get('id', ''),
                                })
                        self.sheets_client.save_pending_retry(pending_records)
                        logger.info(f"⏳ Queued {len(batch_pending_urls)} pending URLs for retry")
                    except Exception as e:
                        logger.warning(f"⚠️ Could not save pending queue: {e}")

                all_processed.extend(batch_processed)
                all_pending_urls.extend(batch_pending_urls)
                total_failed += batch_failed
                total_broken += batch_broken
                total_pending += len(batch_pending_urls)

                logger.info(
                    f"📊 Progress: {min(batch_start + len(batch_urls), total_to_crawl)}/{total_to_crawl} "
                    f"| processed={len(all_processed)} failed={total_failed} "
                    f"broken={total_broken} pending={total_pending}"
                )
            
            # Final summary
            success_count = sum(1 for r in all_processed if r.get('status') == 'success')
            
            result = {
                'success': True,
                'message': 'Crawler v4.1 completed successfully',
                'stats': {
                    'total': len(lark_records),
                    'crawled': total_to_crawl,
                    'skipped_old': skipped_old,
                    'processed': len(all_processed),
                    'success': success_count,
                    'lark_updated': total_updated,
                    'failed': total_failed,
                    'broken': total_broken,
                    'pending_retry': total_pending,
                }
            }

            logger.info(f"✅ Crawler v4.0 completed: {result['stats']}")
            logger.info(
                f"📅 Summary: {total_to_crawl} recent crawled, "
                f"{skipped_old} old skipped, {total_pending} queued for retry"
            )
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
            
            # Merge dates from Google Sheets (where crawled dates are actually stored)
            try:
                sheets_dates = self.sheets_client.get_publish_dates_by_link()
                for url in urls:
                    if not existing_dates.get(url) and url in sheets_dates:
                        existing_dates[url] = sheets_dates[url]
            except Exception as e:
                logger.warning(f"⚠️ Could not read dates from Sheets: {e}")
            
            # Filter: only crawl recent videos (current & previous month)
            urls_to_crawl = []
            skipped_old = 0
            
            for url in urls:
                existing_date = existing_dates.get(url, '')
                if self.is_recent_video(existing_date):
                    urls_to_crawl.append(url)
                else:
                    skipped_old += 1
            
            if skipped_old > 0:
                logger.info(f"📅 Date filter: crawling {len(urls_to_crawl)} recent, skipping {skipped_old} old videos")
            
            # Batch crawl (only recent videos)
            crawl_results = {}
            if self.use_playwright and self.playwright_crawler:
                results_list = self.playwright_crawler.crawl_batch_sync(urls_to_crawl, existing_dates=existing_dates)
                for result in results_list:
                    url = result.get('url', '')
                    if url:
                        crawl_results[url] = result
            
            # Process results (only recent videos)
            processed_records = []
            for url in urls_to_crawl:
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
                    'crawled': len(urls_to_crawl),
                    'skipped_old': skipped_old,
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
    
    def crawl_pending_retry(self) -> Dict:
        """
        Retry videos that were marked as pending_propagation in previous runs.
        Should be called 6+ hours after the main daily crawl.

        Flow:
            1. Read pending URLs from Sheets "Pending Retry" tab
            2. Try yt-dlp first (parallel), then Playwright for misses
            3. On success: write to main sheet + remove from pending
            4. On failure: increment attempt count; drop after 3 attempts
        """
        try:
            logger.info("🔄 Starting pending retry crawl...")

            pending_items = self.sheets_client.get_pending_retry()
            if not pending_items:
                logger.info("✅ No pending URLs to retry")
                return {'success': True, 'message': 'No pending URLs', 'stats': {'retried': 0, 'resolved': 0}}

            logger.info(f"⏳ Found {len(pending_items)} pending URLs to retry")

            urls = [item['url'] for item in pending_items]
            url_to_item = {item['url']: item for item in pending_items}

            # Load target table URL→record_id mapping
            target_record_by_url = {}
            try:
                target_record_by_url = self.lark_client.get_target_records_by_url()
                logger.info(f"✅ Retry: target table {len(target_record_by_url)} URL mappings loaded")
            except Exception as e:
                logger.warning(f"⚠️ Retry: could not load target table records: {e}")

            # Build existing_dates from Sheets for date preservation
            try:
                existing_dates = self.sheets_client.get_publish_dates_by_link()
            except Exception:
                existing_dates = {}

            # ── Playwright crawl ───────────────────────────────────────────────
            crawl_results = {}

            if self.use_playwright and self.playwright_crawler:
                try:
                    pw_list = self.playwright_crawler.crawl_batch_sync(
                        urls, existing_dates=existing_dates
                    )
                    for r in pw_list:
                        url_r = r.get('url', '')
                        if url_r:
                            crawl_results[url_r] = r
                except Exception as e:
                    logger.error(f"❌ Playwright retry error: {e}")

            # ── Process results ────────────────────────────────────────────────
            resolved_urls = []
            still_pending = []
            to_write = []

            for item in pending_items:
                url = item['url']
                record_id = item.get('record_id', '')
                attempts = item.get('attempts', 1)

                result = crawl_results.get(url)
                if not result:
                    still_pending.append({**item, 'attempts': attempts + 1})
                    continue

                if result.get('success') and result.get('views', 0) > 0:
                    # Got data! Use target table record_id for writing
                    publish_date = result.get('publish_date') or existing_dates.get(url)
                    target_rid = target_record_by_url.get(url) or record_id
                    to_write.append({
                        'record_id': target_rid,
                        'link': url,
                        'views': result['views'],
                        'baseline': result.get('views', 0),  # first-time write, use as baseline
                        'publish_date': publish_date,
                        'status': 'success',
                        'is_broken': False,
                    })
                    resolved_urls.append(url)
                elif result.get('is_broken'):
                    resolved_urls.append(url)  # Remove from pending (it's gone)
                    logger.info(f"🔗 Pending URL confirmed broken, removing: {url[:50]}...")
                elif attempts >= 3:
                    # Give up after 3 total attempts
                    resolved_urls.append(url)
                    logger.warning(f"⚠️ Giving up on pending URL after 3 attempts: {url[:50]}...")
                else:
                    still_pending.append({**item, 'attempts': attempts + 1})

            # Write resolved records to Lark Bitable
            if to_write:
                self.lark_client.batch_update_records(to_write)
                logger.info(f"✅ Wrote {len(to_write)} resolved pending records to Lark")

            # Update pending queue: remove resolved, keep still-pending
            if resolved_urls or still_pending:
                self.sheets_client.update_pending_retry(
                    remove_urls=resolved_urls,
                    update_items=still_pending,
                )

            stats = {
                'retried': len(pending_items),
                'resolved': len(resolved_urls),
                'still_pending': len(still_pending),
                'written_to_sheets': len(to_write),
            }
            logger.info(f"✅ Pending retry done: {stats}")
            return {'success': True, 'message': 'Pending retry completed', 'stats': stats}

        except Exception as e:
            logger.error(f"❌ Pending retry failed: {e}")
            return {'success': False, 'message': str(e), 'stats': {}}

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
