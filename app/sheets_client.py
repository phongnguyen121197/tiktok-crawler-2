import gspread
from google.oauth2.service_account import Credentials
from typing import List, Dict, Optional
from datetime import datetime
import logging
import time

logger = logging.getLogger(__name__)

class GoogleSheetsClient:
    """
    Google Sheets client with deduplication and rate limit handling
    Prevents duplicate records and handles API quota limits
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
        
        This is used for deduplication - checking which records already exist
        """
        try:
            # Get all values from sheet
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
            for i, row in enumerate(all_values[1:], start=2):  # Start from row 2 (skip header)
                if len(row) > record_id_col and row[record_id_col]:
                    record_id = row[record_id_col].strip()
                    if record_id:
                        record_index[record_id] = i
            
            logger.info(f"📊 Found {len(record_index)} existing records in sheet")
            return record_index
            
        except Exception as e:
            logger.error(f"❌ Error getting records index: {e}")
            return {}
    
    def batch_update_records(self, records: List[Dict]) -> tuple:
        """
        Update or insert records with deduplication and rate limit handling
        
        Args:
            records: List of record dicts with keys:
                - record_id: Unique identifier
                - link: TikTok video URL
                - views: Current view count
                - baseline: 24h baseline views
                - status: 'success' or 'partial'
        
        Returns:
            Tuple (updated_count, inserted_count)
        """
        try:
            if not records:
                logger.warning("⚠️ No records to update")
                return (0, 0)
            
            logger.info(f"📊 Processing {len(records)} records for batch update...")
            
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
    
    def _update_records_with_rate_limit(self, to_update: List[tuple]) -> int:
        """
        Update existing records with rate limiting
        
        Args:
            to_update: List of (row_index, record) tuples
            
        Returns:
            Number of successfully updated records
        """
        if not to_update:
            return 0
        
        updated_count = 0
        timestamp = datetime.now().isoformat()
        
        logger.info(f"🔄 Updating {len(to_update)} existing records...")
        
        for idx, (row_index, record) in enumerate(to_update, 1):
            try:
                # Prepare row data
                # Columns: Record ID | Link TikTok | Current Views | 24h Baseline | Last Check | Status
                row_data = [
                    [
                        record['record_id'],
                        record['link'],
                        record['views'],
                        record['baseline'],
                        timestamp,
                        record['status']
                    ]
                ]
                
                # Update the row
                range_name = f'A{row_index}:F{row_index}'
                self.worksheet.update(range_name, row_data, value_input_option='USER_ENTERED')
                
                updated_count += 1
                
                # ✅ CRITICAL: Rate limiting to avoid Google API quota (60 writes/min)
                # Sleep 1.2 seconds = 50 writes/minute (safely under 60 limit)
                if idx < len(to_update):  # Don't sleep after last update
                    time.sleep(1.2)
                
                if idx % 10 == 0:
                    logger.info(f"  ✅ Updated {idx}/{len(to_update)} records")
                
            except Exception as e:
                logger.error(f"❌ Error updating row {row_index}: {e}")
                
                # If rate limit error, wait longer
                if '429' in str(e) or 'quota' in str(e).lower():
                    logger.warning(f"⚠️ Rate limit hit, waiting 60 seconds...")
                    time.sleep(60)
                    
                    # Retry this record
                    try:
                        row_data = [
                            [
                                record['record_id'],
                                record['link'],
                                record['views'],
                                record['baseline'],
                                timestamp,
                                record['status']
                            ]
                        ]
                        range_name = f'A{row_index}:F{row_index}'
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
                # Prepare row data
                row_data = [
                    record['record_id'],
                    record['link'],
                    record['views'],
                    record['baseline'],
                    timestamp,
                    record['status']
                ]
                
                # Append new row
                self.worksheet.append_row(row_data, value_input_option='USER_ENTERED')
                
                inserted_count += 1
                
                # ✅ CRITICAL: Rate limiting
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
                        row_data = [
                            record['record_id'],
                            record['link'],
                            record['views'],
                            record['baseline'],
                            timestamp,
                            record['status']
                        ]
                        self.worksheet.append_row(row_data, value_input_option='USER_ENTERED')
                        inserted_count += 1
                        logger.info(f"  ✅ Retry successful for record {record['record_id']}")
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
            
            if len(all_values) < 3:  # Header + at least 2 rows
                logger.info("📋 Not enough rows to check for duplicates")
                return
            
            headers = all_values[0]
            data_rows = all_values[1:]
            
            # Track seen record IDs
            seen_ids = set()
            rows_to_delete = []
            
            # Find duplicates (keep first, mark rest for deletion)
            for i, row in enumerate(data_rows, start=2):  # Start from row 2
                if len(row) > 0 and row[0]:  # Check if Record ID exists
                    record_id = row[0].strip()
                    if record_id in seen_ids:
                        rows_to_delete.append(i)
                    else:
                        seen_ids.add(record_id)
            
            if rows_to_delete:
                logger.info(f"🗑️ Found {len(rows_to_delete)} duplicate rows, removing...")
                
                # Delete from bottom to top (to maintain row indices)
                for row_index in sorted(rows_to_delete, reverse=True):
                    self.worksheet.delete_rows(row_index)
                    time.sleep(1.2)  # Rate limiting
                
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
        """
        Clear all data from sheet
        
        Args:
            keep_header: If True, keep first row (header)
        """
        try:
            if keep_header:
                # Delete all rows except header
                all_values = self.worksheet.get_all_values()
                if len(all_values) > 1:
                    self.worksheet.delete_rows(2, len(all_values))
                    logger.info("✅ Cleared all data (kept header)")
            else:
                # Clear everything
                self.worksheet.clear()
                logger.info("✅ Cleared entire sheet")
        except Exception as e:
            logger.error(f"❌ Error clearing sheet: {e}")