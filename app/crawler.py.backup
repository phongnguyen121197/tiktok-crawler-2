import requests
import logging
from typing import List, Dict
from datetime import datetime
import json

logger = logging.getLogger(__name__)

class TikTokCrawler:
    def __init__(self, lark_client, sheets_client):
        """
        Initialize crawler with Lark and Sheets clients
        """
        self.lark_client = lark_client
        self.sheets_client = sheets_client
        self.tikwm_api = "https://api.tikvideo.top/api"
        
    def extract_video_id_from_url(self, url: str) -> str:
        """Extract TikTok video ID from URL"""
        try:
            if '/video/' in url:
                video_id = url.split('/video/')[1]
                # Remove query parameters if any
                if '?' in video_id:
                    video_id = video_id.split('?')[0]
                return video_id.strip()
            
            logger.warning(f"Could not extract video ID from: {url}")
            return None
            
        except Exception as e:
            logger.error(f"Error extracting video ID: {e}")
            return None
    
    def get_tiktok_views(self, video_url: str) -> Dict:
        """
        Get TikTok video stats using TikWM API
        Returns: {views: int, likes: int, comments: int, shares: int}
        """
        try:
            video_id = self.extract_video_id_from_url(video_url)
            
            if not video_id:
                logger.warning(f"Invalid TikTok URL: {video_url}")
                return None
            
            # Call TikWM API
            params = {
                'url': f'https://www.tiktok.com/video/{video_id}'
            }
            
            response = requests.get(self.tikwm_api, params=params, timeout=15)
            response.raise_for_status()
            
            data = response.json()
            
            if data.get('code') == 0 and data.get('data'):
                video_data = data['data']['video']
                stats = {
                    'views': video_data.get('playCount', 0),
                    'likes': video_data.get('diggCount', 0),
                    'comments': video_data.get('commentCount', 0),
                    'shares': video_data.get('shareCount', 0)
                }
                logger.info(f"✅ Got TikTok stats for {video_id}: {stats['views']} views")
                return stats
            else:
                logger.warning(f"TikWM API error: {data}")
                return None
                
        except requests.exceptions.Timeout:
            logger.warning(f"TikWM API timeout for: {video_url}")
            return None
        except Exception as e:
            logger.error(f"Error getting TikTok views: {e}")
            return None
    
    def extract_lark_field_value(self, field_data, field_type: str = 'text'):
        """
        Extract value from Lark field (handles different formats)
        Formats: text, number, link, array
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
                        return int(first_item.get('text', 0))
                    else:
                        return first_item
                # List of primitives
                else:
                    if field_type == 'number':
                        return int(first_item)
                    else:
                        return str(first_item)
            
            # If it's a dictionary (like link field)
            if isinstance(field_data, dict):
                if field_type == 'link':
                    return field_data.get('text') or field_data.get('link')
                elif field_type == 'text':
                    return str(field_data.get('text', '')).strip()
                else:
                    return field_data
            
            # If it's a primitive
            if field_type == 'number':
                return int(field_data) if field_data else 0
            else:
                return str(field_data).strip() if field_data else None
                
        except Exception as e:
            logger.warning(f"Error extracting field value: {e}")
            return None
    
    def process_lark_record(self, lark_record: Dict) -> Dict:
        """
        Process Lark record and extract relevant data for Google Sheets
        Returns: {record_id, link, views, baseline, status, source_data}
        """
        try:
            fields = lark_record.get('fields', {})
            record_id = lark_record.get('id', '')
            
            # Extract Link
            link_field = fields.get('Link air bài', {})
            link_value = self.extract_lark_field_value(link_field, 'link')
            
            if not link_value:
                logger.warning(f"Record {record_id} has no link, skipping")
                return None
            
            # Extract Current Views from Lark
            current_views_lark = fields.get('Lượt xem hiện tại', [])
            views_lark = self.extract_lark_field_value(current_views_lark, 'number')
            
            # Extract 24h Baseline from Lark
            baseline_lark = fields.get('Số view 24h trước', [])
            baseline_value = self.extract_lark_field_value(baseline_lark, 'number')
            
            # Get current views from TikWM API
            tiktok_stats = self.get_tiktok_views(link_value)
            
            if tiktok_stats:
                current_views = tiktok_stats.get('views', views_lark or 0)
                status = 'success'
            else:
                current_views = views_lark or 0
                status = 'partial'
            
            # Use Lark baseline, or calculate from Lark data
            if baseline_value:
                baseline = baseline_value
            else:
                baseline = views_lark or 0
            
            processed_record = {
                'record_id': record_id,
                'link': link_value,
                'views': current_views,
                'baseline': baseline,
                'status': status,
                'source_data': {
                    'lark_views': views_lark,
                    'lark_baseline': baseline_value,
                    'tiktok_stats': tiktok_stats
                }
            }
            
            logger.info(f"Processed record {record_id}: {current_views} views (status: {status})")
            return processed_record
            
        except Exception as e:
            logger.error(f"Error processing Lark record: {e}")
            return None
    
    def crawl_all_videos(self) -> Dict:
        """
        Main crawler function
        1. Get all active records from Lark
        2. Process each record (crawl views)
        3. Update/Insert into Google Sheets with deduplication
        """
        try:
            logger.info("🚀 Starting TikTok crawler...")
            
            # Step 1: Get records from Lark
            logger.info("Fetching records from Lark Bitable...")
            lark_records = self.lark_client.get_all_active_records()
            
            if not lark_records:
                logger.error("No records found in Lark")
                return {
                    'success': False,
                    'message': 'No records found in Lark',
                    'stats': {
                        'total': 0,
                        'processed': 0,
                        'updated': 0,
                        'inserted': 0,
                        'failed': 0
                    }
                }
            
            logger.info(f"Fetched {len(lark_records)} records from Lark")
            
            # Step 2: Process each record
            logger.info("Processing records and crawling views...")
            processed_records = []
            failed_count = 0
            
            for idx, lark_record in enumerate(lark_records, 1):
                logger.info(f"Processing {idx}/{len(lark_records)}")
                
                try:
                    processed = self.process_lark_record(lark_record)
                    if processed:
                        processed_records.append(processed)
                    else:
                        failed_count += 1
                except Exception as e:
                    logger.error(f"Error processing record {idx}: {e}")
                    failed_count += 1
            
            logger.info(f"Processed {len(processed_records)} records, {failed_count} failed")
            
            # Step 3: Update/Insert into Google Sheets with deduplication
            logger.info("Updating Google Sheets with deduplication...")
            updated, inserted = self.sheets_client.batch_update_records(processed_records)
            
            result = {
                'success': True,
                'message': 'Crawler completed successfully',
                'stats': {
                    'total': len(lark_records),
                    'processed': len(processed_records),
                    'updated': updated,
                    'inserted': inserted,
                    'failed': failed_count
                }
            }
            
            logger.info(f"Crawler completed: {result['stats']}")
            return result
            
        except Exception as e:
            logger.error(f"Crawler failed: {e}")
            return {
                'success': False,
                'message': str(e),
                'stats': {
                    'total': 0,
                    'processed': 0,
                    'updated': 0,
                    'inserted': 0,
                    'failed': 0
                }
            }
    
    def crawl_videos_batch(self, record_ids: List[str] = None) -> Dict:
        """
        Crawl specific videos by Record IDs (optional)
        If record_ids is None, crawl all
        """
        try:
            logger.info("Starting batch crawler...")
            
            # Get all records
            all_records = self.lark_client.get_all_active_records()
            
            # Filter if specific IDs provided
            if record_ids:
                lark_records = [r for r in all_records if r.get('id') in record_ids]
                logger.info(f"Filtered to {len(lark_records)} records")
            else:
                lark_records = all_records
            
            # Process
            processed_records = []
            for record in lark_records:
                processed = self.process_lark_record(record)
                if processed:
                    processed_records.append(processed)
            
            # Update sheets
            updated, inserted = self.sheets_client.batch_update_records(processed_records)
            
            return {
                'success': True,
                'message': 'Batch crawl completed',
                'stats': {
                    'total': len(lark_records),
                    'processed': len(processed_records),
                    'updated': updated,
                    'inserted': inserted
                }
            }
            
        except Exception as e:
            logger.error(f"Batch crawl failed: {e}")
            return {'success': False, 'message': str(e)}