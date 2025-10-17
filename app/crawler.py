import requests
import logging
from typing import List, Dict
from datetime import datetime
import re
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

class TikTokCrawler:
    def __init__(self, lark_client, sheets_client):
        """
        Initialize crawler with Lark and Sheets clients
        """
        self.lark_client = lark_client
        self.sheets_client = sheets_client
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        
    def extract_video_id_from_url(self, url: str) -> str:
        """Extract TikTok video ID from URL"""
        try:
            if '/video/' in url:
                video_id = url.split('/video/')[1]
                if '?' in video_id:
                    video_id = video_id.split('?')[0]
                return video_id.strip()
            
            logger.warning(f"Could not extract video ID from: {url}")
            return None
            
        except Exception as e:
            logger.error(f"Error extracting video ID: {e}")
            return None
    
    def get_tiktok_views_from_og_tags(self, video_url: str) -> Dict:
        """
        Get TikTok video stats from Open Graph meta tags
        Returns: {views: int, status: 'success'/'partial'/'failed'}
        """
        try:
            # Normalize URL
            if not video_url.startswith('http'):
                video_url = 'https://' + video_url
            
            logger.debug(f"Fetching OG tags from: {video_url}")
            
            # Fetch page with timeout
            response = self.session.get(
                video_url,
                timeout=10,
                allow_redirects=True,
                verify=False  # Ignore SSL cert issues
            )
            response.raise_for_status()
            
            # Parse HTML
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Try to find view count in various meta tags
            views = None
            
            # Method 1: Look for og:description which often contains view count
            og_description = soup.find('meta', property='og:description')
            if og_description and og_description.get('content'):
                desc = og_description['content']
                # Pattern: "123.4K Likes, 456 Comments, 789.1K Shares"
                # Or: "123K views"
                views_match = re.search(r'(\d+[.,]?\d*)\s*[KMB]?\s*(?:views?|plays?)', desc, re.IGNORECASE)
                if views_match:
                    views_str = views_match.group(1).replace(',', '.')
                    views = self._convert_to_int(views_str)
                    logger.debug(f"Found views in og:description: {views}")
            
            # Method 2: Look for structured data (JSON-LD)
            if not views:
                scripts = soup.find_all('script', type='application/ld+json')
                for script in scripts:
                    try:
                        import json
                        data = json.loads(script.string)
                        if isinstance(data, dict):
                            # Look for VideoObject
                            if data.get('@type') == 'VideoObject' and 'interactionCount' in data:
                                interaction = data['interactionCount']
                                if isinstance(interaction, dict):
                                    views = int(interaction.get('UserPlayss', 0))
                                    logger.debug(f"Found views in JSON-LD: {views}")
                                    break
                    except:
                        pass
            
            # Method 3: Look for specific meta tags
            if not views:
                for tag_name in ['twitter:text:views', 'tiktok:views']:
                    tag = soup.find('meta', property=tag_name)
                    if tag and tag.get('content'):
                        views = self._convert_to_int(tag['content'])
                        if views:
                            logger.debug(f"Found views in {tag_name}: {views}")
                            break
            
            # Method 4: Regex search in page title or other text
            if not views:
                title = soup.find('title')
                if title:
                    title_text = title.get_text()
                    # Try to find view count in title
                    match = re.search(r'(\d+[.,]?\d*[KMB]?)\s*views?', title_text, re.IGNORECASE)
                    if match:
                        views = self._convert_to_int(match.group(1))
                        logger.debug(f"Found views in title: {views}")
            
            if views and views > 0:
                return {
                    'views': views,
                    'status': 'success',
                    'source': 'og_tags'
                }
            else:
                # Could not extract views, but URL is valid
                logger.warning(f"Could not extract view count from {video_url}")
                return {
                    'views': 0,
                    'status': 'partial',
                    'source': 'og_tags'
                }
                
        except requests.exceptions.Timeout:
            logger.warning(f"Timeout fetching {video_url}")
            return {'views': 0, 'status': 'timeout', 'source': 'og_tags'}
        except requests.exceptions.ConnectionError:
            logger.warning(f"Connection error for {video_url}")
            return {'views': 0, 'status': 'connection_error', 'source': 'og_tags'}
        except Exception as e:
            logger.error(f"Error getting TikTok views: {e}")
            return {'views': 0, 'status': 'error', 'source': 'og_tags'}
    
    def _convert_to_int(self, value_str: str) -> int:
        """Convert string like '1.2M' or '500K' to integer"""
        try:
            if not value_str:
                return 0
            
            value_str = str(value_str).strip().upper()
            
            # Remove commas
            value_str = value_str.replace(',', '')
            
            # Check for multipliers
            if 'M' in value_str:
                return int(float(value_str.replace('M', '')) * 1_000_000)
            elif 'K' in value_str:
                return int(float(value_str.replace('K', '')) * 1_000)
            elif 'B' in value_str:
                return int(float(value_str.replace('B', '')) * 1_000_000_000)
            else:
                return int(float(value_str))
        except:
            return 0
    
    def extract_lark_field_value(self, field_data, field_type: str = 'text'):
        """Extract value from Lark field (handles different formats)"""
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
        """Process Lark record and extract relevant data for Google Sheets"""
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
            
            # Get current views from TikTok OG tags
            tiktok_data = self.get_tiktok_views_from_og_tags(link_value)
            
            if tiktok_data['status'] == 'success' and tiktok_data['views'] > 0:
                current_views = tiktok_data['views']
                status = 'success'
            else:
                # Fallback to Lark data
                current_views = views_lark or 0
                status = 'partial'  # Using Lark data, not crawled from TikTok
            
            # Use Lark baseline, or current views if no baseline
            if baseline_value:
                baseline = baseline_value
            else:
                baseline = views_lark or current_views or 0
            
            processed_record = {
                'record_id': record_id,
                'link': link_value,
                'views': current_views,
                'baseline': baseline,
                'status': status,
                'source_data': {
                    'lark_views': views_lark,
                    'lark_baseline': baseline_value,
                    'crawled_views': tiktok_data['views'] if tiktok_data['status'] == 'success' else None
                }
            }
            
            logger.debug(f"Processed record {record_id}: {current_views} views (status: {status})")
            return processed_record
            
        except Exception as e:
            logger.error(f"Error processing Lark record: {e}")
            return None
    
    def crawl_all_videos(self) -> Dict:
        """Main crawler function"""
        try:
            logger.info("Starting TikTok crawler...")
            
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
        """Crawl specific videos by Record IDs"""
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