import gspread
from google.oauth2.service_account import Credentials
from typing import List, Dict, Optional
from datetime import datetime
import logging
import time
import re

logger = logging.getLogger(__name__)

class GoogleSheetsClient:
    """
    Google Sheets client with deduplication and rate limit handling
    Prevents duplicate records and handles API quota limits
    
    ✅ v2.5.0 - OPTIMIZED: Only update Published Date when needed
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
    
    def _is_valid_date_format(self, value: str) -> bool:
        """
        ✅ NEW: Check if value is a valid date in YYYY-MM-DD format
        
        Args:
            value: String to check
            
        Returns:
            bool: True if valid YYYY-MM-DD format
        """
        if not value or not isinstance(value, str):
            return False
        
        # Check format YYYY-MM-DD
        if not re.match(r'^\d{4}-\d{2}-\d{2}$', value.strip()):
            return False
        
        # Validate actual date
        try:
            datetime.strptime(value.strip(), '%Y-%m-%d')
            return True
        except ValueError:
            return False
    
    def _validate_and_format_publish_date(self, publish_date) -> str:
        """
        Validate and format publish_date before writing to Sheets
        
        Args:
            publish_date: The publish_date value (could be string, int, None)
            
        Returns:
            str: Formatted date string (YYYY-MM-DD) or empty string
        """
        if not publish_date:
            return ''
        
        # If it's already a valid date string (YYYY-MM-DD)
        if isinstance(publish_date, str):
            if re.match(r'^\d{4}-\d{2}-\d{2}$', publish_date):
                return publish_date
            
            # Try to parse other date formats
            try:
                if 'T' in publish_date:
                    dt = datetime.fromisoformat(publish_date.replace('Z', '+00:00'))
                    return dt.strftime('%Y-%m-%d')
            except:
                pass
            
            # If it's a numeric string (timestamp), convert it
            if publish_date.isdigit():
                return self._convert_timestamp_to_date(int(publish_date))
            
            return ''
        
        # If it's a number (timestamp), convert it
        if isinstance(publish_date, (int, float)):
            return self._convert_timestamp_to_date(publish_date)
        
        return ''
    
    def _convert_timestamp_to_date(self, timestamp) -> str:
        """
        Convert Unix timestamp to YYYY-MM-DD format
        Handles both 10-digit (seconds) and 13-digit (milliseconds)
        """
        try:
            if not timestamp:
                return ''
            
            if isinstance(timestamp, str):
                timestamp = float(timestamp)
            
            if timestamp > 9999999999:
                timestamp = timestamp / 1000
            
            dt = datetime.fromtimestamp(timestamp)
            
            if dt.year < 2016 or dt.year > 2030:
                return ''
            
            return dt.strftime('%Y-%m-%d')
            
        except Exception as e:
            logger.error(f"❌ Error converting timestamp {timestamp}: {e}")
            return ''
    
    def get_all_records_with_index(self) -> Dict[str, dict]:
        """
        ✅ UPDATED: Get all existing records with their row indices AND existing data
        Returns dict: {record_id: {'row': row_index, 'publish_date': existing_date}}
        
        This is used for:
        - Deduplication
        - Checking existing publish_date values
        """
        try:
            all_values = self.worksheet.get_all_values()
            
            if not all_values or len(all_values) < 2:
                logger.info("📋 Sheet is empty or has only headers")
                return {}
            
            # Column indices (0-based):
            # A=0: Record ID | B=1: Link | C=2: Views | D=3: Baseline | E=4: Published Date | F=5: Last Check | G=6: Status
            record_id_col = 0
            publish_date_col = 4
            
            record_index = {}
            for i, row in enumerate(all_values[1:], start=2):  # Start from row 2 (skip header)
                if len(row) > record_id_col and row[record_id_col]:
                    record_id = row[record_id_col].strip()
                    if record_id:
                        # Get existing publish_date if available
                        existing_date = ''
                        if len(row) > publish_date_col:
                            existing_date = row[publish_date_col].strip() if row[publish_date_col] else ''
                        
                        record_index[record_id] = {
                            'row': i,
                            'publish_date': existing_date
                        }
            
            logger.info(f"📊 Found {len(record_index)} existing records in sheet")
            return record_index
            
        except Exception as e:
            logger.error(f"❌ Error getting records index: {e}")
            return {}
    
    def batch_update_records(self, records: List[Dict]) -> tuple:
        """
        Update or insert records with deduplication and rate limit handling
        
        ✅ OPTIMIZED: Only update Published Date if:
        - Cell is empty, OR
        - Cell has invalid format (not YYYY-MM-DD)
        
        Args:
            records: List of record dicts
        
        Returns:
            Tuple (updated_count, inserted_count)
        """
        try:
            if not records:
                logger.warning("⚠️ No records to update")
                return (0, 0)
            
            logger.info(f"📊 Processing {len(records)} records for batch update...")
            
            # Get existing records WITH their publish_date values
            existing_records = self.get_all_records_with_index()
            
            # Separate into updates and inserts
            records_dict = {r['record_id']: r for r in records}
            
            to_update = []  # (row_index, record, existing_publish_date)
            to_insert = []  # record
            
            for record_id, record in records_dict.items():
                if record_id in existing_records:
                    row_info = existing_records[record_id]
                    row_index = row_info['row']
                    existing_publish_date = row_info.get('publish_date', '')
                    to_update.append((row_index, record, existing_publish_date))
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
    
    def _update_records_with_rate_limit(self, to_update: List[tuple]) -> int:
        """
        Update existing records with rate limiting
        
        ✅ OPTIMIZED: Preserve existing valid publish_date
        
        Args:
            to_update: List of (row_index, record, existing_publish_date) tuples
            
        Returns:
            Number of successfully updated records
        """
        if not to_update:
            return 0
        
        updated_count = 0
        timestamp = datetime.now().isoformat()
        dates_preserved = 0
        dates_updated = 0
        
        logger.info(f"🔄 Updating {len(to_update)} existing records...")
        
        for idx, (row_index, record, existing_publish_date) in enumerate(to_update, 1):
            try:
                # ✅ SMART PUBLISH DATE LOGIC
                new_publish_date = record.get('publish_date', '')
                validated_new_date = self._validate_and_format_publish_date(new_publish_date)
                
                # Decide which date to use
                if self._is_valid_date_format(existing_publish_date):
                    # ✅ KEEP existing valid date
                    final_publish_date = existing_publish_date
                    dates_preserved += 1
                elif validated_new_date:
                    # Use new date from crawler
                    final_publish_date = validated_new_date
                    dates_updated += 1
                else:
                    # Both empty or invalid
                    final_publish_date = ''
                
                # Prepare row data
                # Columns: Record ID | Link TikTok | Current Views | 24h Baseline | Published Date | Last Check | Status
                row_data = [
                    [
                        str(record['record_id']),
                        str(record['link']),
                        record['views'],
                        record['baseline'],
                        final_publish_date,  # ✅ Smart publish_date
                        timestamp,
                        str(record['status'])
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
                    logger.info(f"  ✅ Updated {idx}/{len(to_update)} records")
                
            except Exception as e:
                logger.error(f"❌ Error updating row {row_index}: {e}")
                
                # If rate limit error, wait longer
                if '429' in str(e) or 'quota' in str(e).lower():
                    logger.warning(f"⚠️ Rate limit hit, waiting 60 seconds...")
                    time.sleep(60)
                    
                    # Retry
                    try:
                        new_publish_date = record.get('publish_date', '')
                        validated_new_date = self._validate_and_format_publish_date(new_publish_date)
                        
                        if self._is_valid_date_format(existing_publish_date):
                            final_publish_date = existing_publish_date
                        elif validated_new_date:
                            final_publish_date = validated_new_date
                        else:
                            final_publish_date = ''
                        
                        row_data = [
                            [
                                str(record['record_id']),
                                str(record['link']),
                                record['views'],
                                record['baseline'],
                                final_publish_date,
                                timestamp,
                                str(record['status'])
                            ]
                        ]
                        range_name = f'A{row_index}:G{row_index}'
                        self.worksheet.update(range_name, row_data, value_input_option='USER_ENTERED')
                        updated_count += 1
                    except Exception as retry_error:
                        logger.error(f"❌ Retry failed for row {row_index}: {retry_error}")
        
        logger.info(f"✅ Updated {updated_count}/{len(to_update)} records")
        logger.info(f"📅 Dates: {dates_preserved} preserved, {dates_updated} updated")
        return updated_count
    
    def _insert_records_with_rate_limit(self, to_insert: List[Dict]) -> int:
        """
        Insert new records with rate limiting
        
        Args:
            to_insert: List of record dicts
            
        Returns:
            Number of successfully inserted records
        """
        if not to_insert:
            return 0
        
        inserted_count = 0
        timestamp = datetime.now().isoformat()
        
        logger.info(f"➕ Inserting {len(to_insert)} new records...")
        
        for idx, record in enumerate(to_insert, 1):
            try:
                # Validate publish_date for new records
                raw_publish_date = record.get('publish_date')
                validated_publish_date = self._validate_and_format_publish_date(raw_publish_date)
                
                # Prepare row data
                row_data = [
                    str(record['record_id']),
                    str(record['link']),
                    record['views'],
                    record['baseline'],
                    validated_publish_date,
                    timestamp,
                    str(record['status'])
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
                        raw_publish_date = record.get('publish_date')
                        validated_publish_date = self._validate_and_format_publish_date(raw_publish_date)
                        
                        row_data = [
                            str(record['record_id']),
                            str(record['link']),
                            record['views'],
                            record['baseline'],
                            validated_publish_date,
                            timestamp,
                            str(record['status'])
                        ]
                        self.worksheet.append_row(row_data, value_input_option='USER_ENTERED')
                        inserted_count += 1
                    except Exception as retry_error:
                        logger.error(f"❌ Retry failed for {record['record_id']}: {retry_error}")
        
        logger.info(f"✅ Inserted {inserted_count}/{len(to_insert)} records successfully")
        return inserted_count
    
    def _remove_duplicates(self):
        """
        Remove duplicate records based on Record ID (keep first occurrence)
        """
        try:
            all_values = self.worksheet.get_all_values()
            
            if len(all_values) < 3:
                return
            
            seen_ids = set()
            rows_to_delete = []
            
            for i, row in enumerate(all_values[1:], start=2):
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
                
        except Exception as e:
            logger.error(f"❌ Error removing duplicates: {e}")
    
    def fix_timestamp_dates(self) -> int:
        """
        🔧 MIGRATION: Convert all timestamp values in column E to date strings
        """
        try:
            logger.info("🔧 Starting timestamp migration for column E (Published Date)...")
            
            all_values = self.worksheet.get_all_values()
            
            if len(all_values) < 2:
                return 0
            
            fixed_count = 0
            publish_date_col = 4
            
            for row_idx, row in enumerate(all_values[1:], start=2):
                if len(row) > publish_date_col:
                    cell_value = row[publish_date_col]
                    
                    # Check if it's a timestamp (10-13 digits)
                    if cell_value and cell_value.isdigit() and len(cell_value) >= 10:
                        timestamp = int(cell_value)
                        converted_date = self._convert_timestamp_to_date(timestamp)
                        
                        if converted_date:
                            logger.info(f"  📅 Row {row_idx}: {cell_value} -> {converted_date}")
                            self.worksheet.update_cell(row_idx, publish_date_col + 1, converted_date)
                            fixed_count += 1
                            time.sleep(1.2)
            
            logger.info(f"✅ Migration complete: Fixed {fixed_count} timestamps")
            return fixed_count
            
        except Exception as e:
            logger.error(f"❌ Migration failed: {e}")
            return 0
    
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
