import gspread
from google.oauth2.service_account import Credentials
from typing import List, Dict, Optional
from datetime import datetime
import logging
import time

logger = logging.getLogger(__name__)

class GoogleSheetsClient:
    """
    Google Sheets client v3.2 with deduplication and broken link handling
    - Prevents duplicate records
    - Handles API quota limits
    - Clears data for broken links
    - Preserves publish_date intelligently
    """
    
    def __init__(self, credentials_json: dict, sheet_id: str):
        """
        Initialize Google Sheets client
        
        Args:
            credentials_json: Service account credentials dictionary
            sheet_id: Google Sheets ID
        """
        self.sheet_id = sheet_id
        
        # Setup credentials
        scopes = [
            'https://www.googleapis.com/auth/spreadsheets',
            'https://www.googleapis.com/auth/drive'
        ]
        
        try:
            creds = Credentials.from_service_account_info(
                credentials_json,
                scopes=scopes
            )
            self.client = gspread.authorize(creds)
            self.spreadsheet = self.client.open_by_key(sheet_id)
            self.worksheet = self.spreadsheet.sheet1  # Use first sheet
            
            logger.info(f"✅ Connected to Google Sheets: {self.spreadsheet.title}")
            
        except Exception as e:
            logger.error(f"❌ Failed to initialize Google Sheets client: {e}")
            raise
    
    def get_all_records_with_index(self) -> Dict[str, int]:
        """
        Get all existing records with their row indices
        Returns dict: {record_id: row_index}
        """
        try:
            all_values = self.worksheet.get_all_values()
            
            if not all_values or len(all_values) < 2:
                logger.info("📋 Sheet is empty or has only headers")
                return {}
            
            # First row is header
            headers = all_values[0]
            
            # Find Record ID column (column A, index 0)
            record_id_col = 0
            
            # Build index: {record_id: row_number}
            record_index = {}
            for i, row in enumerate(all_values[1:], start=2):
                if len(row) > record_id_col and row[record_id_col]:
                    record_id = row[record_id_col].strip()
                    if record_id:
                        record_index[record_id] = i
            
            logger.info(f"📊 Found {len(record_index)} existing records in sheet")
            return record_index
            
        except Exception as e:
            logger.error(f"❌ Error getting records index: {e}")
            return {}
    
    def get_publish_dates_by_link(self) -> Dict[str, str]:
        """
        Read existing Published Date values from Google Sheets, keyed by link URL.
        
        Columns: A=Record ID | B=Link TikTok | C=Views | D=Baseline | E=Published Date
        
        Returns:
            Dict {link_url: publish_date_str} for rows that have a valid date in column E
        """
        try:
            all_values = self.worksheet.get_all_values()
            
            if not all_values or len(all_values) < 2:
                return {}
            
            link_col = 1           # Column B - Link TikTok
            publish_date_col = 4   # Column E - Published Date
            
            dates_by_link = {}
            for row in all_values[1:]:  # Skip header
                if len(row) > publish_date_col:
                    link = row[link_col].strip() if row[link_col] else ''
                    pub_date = row[publish_date_col].strip() if row[publish_date_col] else ''
                    
                    if link and pub_date:
                        dates_by_link[link] = pub_date
            
            logger.info(f"📅 Sheets: found {len(dates_by_link)} links with Published Date")
            return dates_by_link
            
        except Exception as e:
            logger.error(f"❌ Error reading publish dates from Sheets: {e}")
            return {}
    
    def batch_update_records(self, records: List[Dict]) -> tuple:
        """
        Update or insert records with deduplication and broken link handling
        v3.2: Handles None values for broken links
        
        Args:
            records: List of record dicts with keys:
                - record_id: Unique identifier
                - link: TikTok video URL
                - views: Current view count (None for broken)
                - baseline: 24h baseline views (None for broken)
                - publish_date: Video publish date (None for broken)
                - status: 'success', 'partial', or 'broken'
                - is_broken: Boolean flag
        
        Returns:
            Tuple (updated_count, inserted_count)
        """
        try:
            if not records:
                logger.warning("⚠️ No records to update")
                return (0, 0)
            
            logger.info(f"📊 Processing {len(records)} records for batch update...")
            
            # Count broken links
            broken_count = sum(1 for r in records if r.get('is_broken'))
            if broken_count > 0:
                logger.info(f"🔗 {broken_count} broken links will have data cleared")
            
            # Get existing records
            existing_records = self.get_all_records_with_index()
            
            # Separate into updates and inserts
            records_dict = {r['record_id']: r for r in records}
            
            to_update = []  # (row_index, record)
            to_insert = []  # record
            
            for record_id, record in records_dict.items():
                if record_id in existing_records:
                    row_index = existing_records[record_id]
                    to_update.append((row_index, record))
                else:
                    to_insert.append(record)
            
            logger.info(f"📝 To update: {len(to_update)}, To insert: {len(to_insert)}")
            
            # Perform updates with rate limiting
            updated_count = self._update_records_with_rate_limit(to_update)
            
            # Perform inserts with rate limiting
            inserted_count = self._insert_records_with_rate_limit(to_insert)
            
            # Remove duplicates if any
            self._remove_duplicates()
            
            logger.info(f"✅ Batch update complete: {updated_count} updated, {inserted_count} inserted")
            return (updated_count, inserted_count)
            
        except Exception as e:
            logger.error(f"❌ Batch update failed: {e}")
            return (0, 0)
    
    def _format_value_for_sheet(self, value, is_broken: bool = False):
        """
        Format value for Google Sheets
        v3.2: Handle None values for broken links
        
        Args:
            value: The value to format
            is_broken: If True, return empty string for None
            
        Returns:
            Formatted value for Sheets
        """
        if value is None:
            return ''  # Empty cell for broken links
        
        if isinstance(value, bool):
            return str(value)
        
        return value
    
    def _update_records_with_rate_limit(self, to_update: List[tuple]) -> int:
        """
        Update existing records with rate limiting
        v3.2: Handles broken links with empty values
        """
        if not to_update:
            return 0
        
        updated_count = 0
        timestamp = datetime.now().isoformat()
        
        logger.info(f"🔄 Updating {len(to_update)} existing records...")
        
        for idx, (row_index, record) in enumerate(to_update, 1):
            try:
                is_broken = record.get('is_broken', False)
                
                # v3.2: Format values - use empty string for broken links
                views_value = self._format_value_for_sheet(record.get('views'), is_broken)
                baseline_value = self._format_value_for_sheet(record.get('baseline'), is_broken)
                publish_date_value = self._format_value_for_sheet(record.get('publish_date'), is_broken)
                
                # Status includes broken indicator
                status = record.get('status', 'unknown')
                if is_broken:
                    status = 'broken'
                
                # Prepare row data
                # Columns: Record ID | Link TikTok | Current Views | 24h Baseline | Published Date | Last Check | Status
                row_data = [
                    [
                        record['record_id'],
                        record['link'],
                        views_value,
                        baseline_value,
                        publish_date_value,
                        timestamp,
                        status
                    ]
                ]
                
                # Update the row
                range_name = f'A{row_index}:G{row_index}'
                self.worksheet.update(range_name, row_data, value_input_option='USER_ENTERED')
                
                updated_count += 1
                
                # Rate limiting
                if idx < len(to_update):
                    time.sleep(1.2)
                
                if idx % 10 == 0:
                    broken_so_far = sum(1 for _, r in to_update[:idx] if r.get('is_broken'))
                    logger.info(f"  ✅ Updated {idx}/{len(to_update)} records (broken: {broken_so_far})")
                
            except Exception as e:
                logger.error(f"❌ Error updating row {row_index}: {e}")
                
                # If rate limit error, wait longer
                if '429' in str(e) or 'quota' in str(e).lower():
                    logger.warning(f"⚠️ Rate limit hit, waiting 60 seconds...")
                    time.sleep(60)
                    
                    # Retry this record
                    try:
                        is_broken = record.get('is_broken', False)
                        views_value = self._format_value_for_sheet(record.get('views'), is_broken)
                        baseline_value = self._format_value_for_sheet(record.get('baseline'), is_broken)
                        publish_date_value = self._format_value_for_sheet(record.get('publish_date'), is_broken)
                        status = 'broken' if is_broken else record.get('status', 'unknown')
                        
                        row_data = [
                            [
                                record['record_id'],
                                record['link'],
                                views_value,
                                baseline_value,
                                publish_date_value,
                                timestamp,
                                status
                            ]
                        ]
                        range_name = f'A{row_index}:G{row_index}'
                        self.worksheet.update(range_name, row_data, value_input_option='USER_ENTERED')
                        updated_count += 1
                        logger.info(f"  ✅ Retry successful for row {row_index}")
                    except Exception as retry_error:
                        logger.error(f"❌ Retry failed for row {row_index}: {retry_error}")
        
        logger.info(f"✅ Updated {updated_count}/{len(to_update)} records successfully")
        return updated_count
    
    def _insert_records_with_rate_limit(self, to_insert: List[Dict]) -> int:
        """
        Insert new records with rate limiting
        v3.2: Handles broken links with empty values
        """
        if not to_insert:
            return 0
        
        inserted_count = 0
        timestamp = datetime.now().isoformat()
        
        logger.info(f"➕ Inserting {len(to_insert)} new records...")
        
        for idx, record in enumerate(to_insert, 1):
            try:
                is_broken = record.get('is_broken', False)
                
                # v3.2: Format values
                views_value = self._format_value_for_sheet(record.get('views'), is_broken)
                baseline_value = self._format_value_for_sheet(record.get('baseline'), is_broken)
                publish_date_value = self._format_value_for_sheet(record.get('publish_date'), is_broken)
                
                status = 'broken' if is_broken else record.get('status', 'unknown')
                
                # Prepare row data
                row_data = [
                    record['record_id'],
                    record['link'],
                    views_value,
                    baseline_value,
                    publish_date_value,
                    timestamp,
                    status
                ]
                
                # Append new row
                self.worksheet.append_row(row_data, value_input_option='USER_ENTERED')
                
                inserted_count += 1
                
                # Rate limiting
                if idx < len(to_insert):
                    time.sleep(1.2)
                
                if idx % 10 == 0:
                    logger.info(f"  ✅ Inserted {idx}/{len(to_insert)} records")
                
            except Exception as e:
                logger.error(f"❌ Error inserting record {record['record_id']}: {e}")
                
                # If rate limit error, wait longer
                if '429' in str(e) or 'quota' in str(e).lower():
                    logger.warning(f"⚠️ Rate limit hit, waiting 60 seconds...")
                    time.sleep(60)
                    
                    # Retry
                    try:
                        is_broken = record.get('is_broken', False)
                        views_value = self._format_value_for_sheet(record.get('views'), is_broken)
                        baseline_value = self._format_value_for_sheet(record.get('baseline'), is_broken)
                        publish_date_value = self._format_value_for_sheet(record.get('publish_date'), is_broken)
                        status = 'broken' if is_broken else record.get('status', 'unknown')
                        
                        row_data = [
                            record['record_id'],
                            record['link'],
                            views_value,
                            baseline_value,
                            publish_date_value,
                            timestamp,
                            status
                        ]
                        self.worksheet.append_row(row_data, value_input_option='USER_ENTERED')
                        inserted_count += 1
                        logger.info(f"  ✅ Retry successful for record {record['record_id']}")
                    except Exception as retry_error:
                        logger.error(f"❌ Retry failed for {record['record_id']}: {retry_error}")
        
        logger.info(f"✅ Inserted {inserted_count}/{len(to_insert)} records successfully")
        return inserted_count
    
    def _remove_duplicates(self):
        """Remove duplicate records based on Record ID (keep first occurrence)"""
        try:
            all_values = self.worksheet.get_all_values()
            
            if len(all_values) < 3:
                logger.info("📋 Not enough rows to check for duplicates")
                return
            
            headers = all_values[0]
            data_rows = all_values[1:]
            
            seen_ids = set()
            rows_to_delete = []
            
            for i, row in enumerate(data_rows, start=2):
                if len(row) > 0 and row[0]:
                    record_id = row[0].strip()
                    if record_id in seen_ids:
                        rows_to_delete.append(i)
                    else:
                        seen_ids.add(record_id)
            
            if rows_to_delete:
                logger.info(f"🗑️ Found {len(rows_to_delete)} duplicate rows, removing...")
                
                for row_index in sorted(rows_to_delete, reverse=True):
                    self.worksheet.delete_rows(row_index)
                    time.sleep(1.2)
                
                logger.info(f"✅ Removed {len(rows_to_delete)} duplicates")
            else:
                logger.info("✅ No duplicates found")
                
        except Exception as e:
            logger.error(f"❌ Error removing duplicates: {e}")
    
    def get_record_count(self) -> int:
        """Get total number of records (excluding header)"""
        try:
            all_values = self.worksheet.get_all_values()
            return len(all_values) - 1 if all_values else 0
        except Exception as e:
            logger.error(f"❌ Error getting record count: {e}")
            return 0
    
    def clear_all_data(self, keep_header: bool = True):
        """Clear all data from sheet"""
        try:
            if keep_header:
                all_values = self.worksheet.get_all_values()
                if len(all_values) > 1:
                    self.worksheet.delete_rows(2, len(all_values))
                    logger.info("✅ Cleared all data (kept header)")
            else:
                self.worksheet.clear()
                logger.info("✅ Cleared entire sheet")
        except Exception as e:
            logger.error(f"❌ Error clearing sheet: {e}")
