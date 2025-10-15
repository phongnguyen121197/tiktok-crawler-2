import gspread
from google.oauth2.service_account import Credentials
import os
import json
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

class GoogleSheetsClient:
    def __init__(self):
        """Initialize Google Sheets client"""
        try:
            # Define the scope
            scope = [
                'https://www.googleapis.com/auth/spreadsheets',
                'https://www.googleapis.com/auth/drive'
            ]
            
            # Try to read credentials from environment variable (for Railway)
            credentials_json = os.getenv('GOOGLE_APPLICATION_CREDENTIALS_JSON')
            
            if credentials_json:
                # On Railway - read from env variable
                logger.info("📦 Loading credentials from environment variable")
                creds_dict = json.loads(credentials_json)
                creds = Credentials.from_service_account_info(
                    creds_dict,
                    scopes=scope
                )
            else:
                # Local - read from file
                logger.info("📁 Loading credentials from file")
                creds = Credentials.from_service_account_file(
                    'credentials.json',
                    scopes=scope
                )
            
            # Authorize the client
            self.client = gspread.authorize(creds)
            
            # Open the spreadsheet
            self.sheet_id = os.getenv('GOOGLE_SHEET_ID')
            if not self.sheet_id:
                raise ValueError("GOOGLE_SHEET_ID environment variable is not set")
            
            self.spreadsheet = self.client.open_by_key(self.sheet_id)
            self.worksheet = self.spreadsheet.sheet1  # First sheet
            
            logger.info("✅ Google Sheets client initialized successfully")
            
        except Exception as e:
            logger.error(f"❌ Failed to initialize Google Sheets: {str(e)}")
            raise

    def find_row_by_record_id(self, record_id: str) -> int:
        """Find row number by record_id (column A)"""
        try:
            # Get all values in column A (Record ID)
            record_ids = self.worksheet.col_values(1)
            
            # Find the row (index + 1 because sheets are 1-indexed)
            if record_id in record_ids:
                return record_ids.index(record_id) + 1
            return None
            
        except Exception as e:
            logger.error(f"Error finding record {record_id}: {str(e)}")
            return None

    def get_record_by_id(self, record_id: str):
        """Get a single record by record_id"""
        try:
            row_num = self.find_row_by_record_id(record_id)
            
            if not row_num:
                return None
            
            # Get the row data
            row_data = self.worksheet.row_values(row_num)
            
            if len(row_data) >= 6:
                return {
                    'record_id': row_data[0],
                    'link': row_data[1],
                    'current_views': int(row_data[2]) if row_data[2] and str(row_data[2]).isdigit() else 0,
                    'baseline_views': int(row_data[3]) if row_data[3] and str(row_data[3]).isdigit() else 0,
                    'last_check': row_data[4] if len(row_data) > 4 else '',
                    'status': row_data[5] if len(row_data) > 5 else 'Active'
                }
            return None
            
        except Exception as e:
            logger.error(f"Error getting record {record_id}: {str(e)}")
            return None

    def update_or_append_record(self, record_id: str, link: str, 
                                current_views: int, baseline_views: int, 
                                last_check: str, status: str = "Active"):
        """Update existing record or append new one"""
        try:
            row_num = self.find_row_by_record_id(record_id)
            
            row_data = [
                record_id,           # A: Record ID
                link,                # B: Link TikTok
                current_views,       # C: Lượt xem hiện tại
                baseline_views,      # D: Số view 24h trước
                last_check,          # E: Lần kiểm tra cuối
                status               # F: Status
            ]
            
            if row_num:
                # Update existing row
                self.worksheet.update(f'A{row_num}:F{row_num}', [row_data])
                logger.info(f"✅ Updated row {row_num} for {record_id}")
            else:
                # Append new row
                self.worksheet.append_row(row_data)
                logger.info(f"✅ Appended new row for {record_id}")
                
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to update {record_id}: {str(e)}")
            return False

    def get_all_records(self):
        """Get all records from sheet (excluding header)"""
        try:
            all_records = self.worksheet.get_all_records()
            logger.info(f"📊 Found {len(all_records)} records in Google Sheets")
            return all_records
        except Exception as e:
            logger.error(f"Error getting records: {str(e)}")
            return []