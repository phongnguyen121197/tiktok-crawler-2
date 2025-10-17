import gspread
from google.oauth2.service_account import Credentials
import logging
from datetime import datetime
from typing import Dict, List, Tuple

logger = logging.getLogger(__name__)

class GoogleSheetsClient:
    def __init__(self, credentials_json, sheet_id):
        """Initialize Google Sheets client"""
        try:
            # Load credentials
            creds = Credentials.from_service_account_info(
                credentials_json,
                scopes=['https://www.googleapis.com/auth/spreadsheets']
            )
            
            self.client = gspread.authorize(creds)
            self.sheet_id = sheet_id
            self.sheet = self.client.open_by_key(sheet_id)
            self.worksheet = self.sheet.sheet1  # First sheet
            
            logger.info("✅ Google Sheets client initialized successfully")
        except Exception as e:
            logger.error(f"❌ Error initializing Google Sheets: {e}")
            raise
    
    def get_all_records_with_index(self) -> Dict[str, int]:
        """
        Get all records from Google Sheets
        Returns: {record_id: row_number}
        """
        try:
            all_values = self.worksheet.get_all_values()
            
            record_index = {}
            # Skip header row (row 1)
            for idx, row in enumerate(all_values[1:], start=2):
                if len(row) > 0 and row[0].strip():  # Column A = Record ID
                    record_id = row[0].strip()
                    record_index[record_id] = idx
            
            logger.info(f"✅ Loaded {len(record_index)} existing records from Google Sheets")
            return record_index
            
        except Exception as e:
            logger.error(f"❌ Error reading Google Sheets: {e}")
            return {}
    
    def remove_duplicates(self):
        """
        Remove duplicate records by Record ID
        Keep the latest record (highest row number), delete older ones
        """
        try:
            all_values = self.worksheet.get_all_values()
            
            # Build dict: record_id -> list of row numbers
            record_occurrences = {}
            for idx, row in enumerate(all_values[1:], start=2):
                if len(row) > 0 and row[0].strip():
                    record_id = row[0].strip()
                    if record_id not in record_occurrences:
                        record_occurrences[record_id] = []
                    record_occurrences[record_id].append(idx)
            
            # Find duplicates
            rows_to_delete = []
            duplicates_found = 0
            
            for record_id, row_numbers in record_occurrences.items():
                if len(row_numbers) > 1:
                    # Keep the latest (highest row number), mark others for deletion
                    duplicates_found += len(row_numbers) - 1
                    rows_to_delete.extend(sorted(row_numbers[:-1], reverse=True))
            
            # Delete duplicate rows (from bottom to top to avoid index shifting)
            if rows_to_delete:
                logger.info(f"🔄 Found {duplicates_found} duplicate records, removing...")
                for row_num in sorted(set(rows_to_delete), reverse=True):
                    self.worksheet.delete_rows(row_num)
                    logger.info(f"   Deleted row {row_num}")
                
                logger.info(f"✅ Removed {duplicates_found} duplicate records")
                return duplicates_found
            else:
                logger.info("✅ No duplicates found")
                return 0
            
        except Exception as e:
            logger.error(f"❌ Error removing duplicates: {e}")
            return 0
    
    def update_or_insert_records(self, records: List[Dict]) -> Tuple[int, int]:
        """
        Update existing records or insert new ones
        Args: List of record dicts with keys: record_id, link, views, baseline, status
        Returns: (updated_count, inserted_count)
        """
        try:
            # Get current record index
            record_index = self.get_all_records_with_index()
            
            updated_count = 0
            inserted_count = 0
            timestamp = datetime.now().isoformat()
            
            for record in records:
                record_id = record.get('record_id', '')
                
                if not record_id:
                    logger.warning("⚠️ Skipping record without record_id")
                    continue
                
                # Prepare row data: [Record ID, Link, Current Views, 24h Baseline, Last Check, Status]
                row_data = [
                    record_id,
                    record.get('link', ''),
                    record.get('views', ''),
                    record.get('baseline', ''),
                    timestamp,
                    record.get('status', 'success')
                ]
                
                if record_id in record_index:
                    # UPDATE existing record
                    row_num = record_index[record_id]
                    try:
                        self.worksheet.update(f'A{row_num}:F{row_num}', [row_data])
                        updated_count += 1
                        logger.debug(f"✏️ Updated record {record_id} at row {row_num}")
                    except Exception as e:
                        logger.error(f"❌ Error updating row {row_num}: {e}")
                else:
                    # INSERT new record
                    try:
                        self.worksheet.append_row(row_data)
                        inserted_count += 1
                        logger.debug(f"✚ Inserted new record {record_id}")
                    except Exception as e:
                        logger.error(f"❌ Error inserting record {record_id}: {e}")
            
            logger.info(f"✅ Records updated: {updated_count}, inserted: {inserted_count}")
            return updated_count, inserted_count
            
        except Exception as e:
            logger.error(f"❌ Error in update_or_insert_records: {e}")
            return 0, 0
    
    def batch_update_records(self, records: List[Dict]) -> Tuple[int, int]:
        """
        Batch update/insert records efficiently
        First removes duplicates, then updates/inserts
        """
        try:
            logger.info("🔄 Starting batch update process...")
            
            # Step 1: Remove any existing duplicates first
            duplicates_removed = self.remove_duplicates()
            
            # Step 2: Update or insert records
            updated, inserted = self.update_or_insert_records(records)
            
            # Step 3: Final cleanup - remove any new duplicates that might have been created
            final_duplicates = self.remove_duplicates()
            
            logger.info(f"✅ Batch update complete:")
            logger.info(f"   • Duplicates removed (initial): {duplicates_removed}")
            logger.info(f"   • Records updated: {updated}")
            logger.info(f"   • Records inserted: {inserted}")
            logger.info(f"   • Duplicates removed (final): {final_duplicates}")
            
            return updated, inserted
            
        except Exception as e:
            logger.error(f"❌ Error in batch_update_records: {e}")
            return 0, 0