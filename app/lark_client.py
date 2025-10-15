import requests
import time
import logging

logger = logging.getLogger(__name__)

class LarkClient:
    def __init__(self, app_id, app_secret, bitable_app_token, table_id):
        self.app_id = app_id
        self.app_secret = app_secret
        self.bitable_app_token = bitable_app_token
        self.table_id = table_id
        
        # Token cache
        self.tenant_access_token = None
        self.token_expire_time = 0
        
        # Get initial token
        self._refresh_token()
    
    def _refresh_token(self):
        """Refresh tenant access token"""
        url = "https://open.larksuite.com/open-apis/auth/v3/tenant_access_token/internal"
        
        payload = {
            "app_id": self.app_id,
            "app_secret": self.app_secret
        }
        
        try:
            response = requests.post(url, json=payload, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            if data.get("code") == 0:
                self.tenant_access_token = data.get("tenant_access_token")
                # Token valid for 2 hours, refresh after 1.5 hours to be safe
                self.token_expire_time = time.time() + 5400  # 1.5 hours = 5400 seconds
                logger.info("✅ Lark token refreshed successfully")
                return True
            else:
                logger.error(f"❌ Failed to refresh token: {data}")
                return False
                
        except Exception as e:
            logger.error(f"❌ Error refreshing token: {e}")
            return False
    
    def _get_valid_token(self):
        """Get valid token, refresh if expired"""
        current_time = time.time()
        
        # If token expired or will expire in 5 minutes, refresh
        if not self.tenant_access_token or current_time >= (self.token_expire_time - 300):
            logger.info("🔄 Token expired or expiring soon, refreshing...")
            self._refresh_token()
        
        return self.tenant_access_token
    
    def _make_request(self, method, url, **kwargs):
        """Make HTTP request with auto token refresh"""
        max_retries = 2
        
        for attempt in range(max_retries):
            token = self._get_valid_token()
            
            if not token:
                logger.error("❌ Failed to get valid token")
                return None
            
            headers = kwargs.get('headers', {})
            headers['Authorization'] = f'Bearer {token}'
            kwargs['headers'] = headers
            
            try:
                response = requests.request(method, url, **kwargs)
                data = response.json()
                
                # If token invalid (99991663), refresh and retry
                if data.get('code') == 99991663:
                    logger.warning(f"⚠️ Token invalid (attempt {attempt + 1}/{max_retries}), refreshing...")
                    self._refresh_token()
                    if attempt < max_retries - 1:
                        continue
                    else:
                        return response
                
                return response
                
            except Exception as e:
                logger.error(f"❌ Request error on attempt {attempt + 1}: {e}")
                if attempt == max_retries - 1:
                    raise
        
        return None
    
    def _extract_link_value(self, link_field):
        """
        Extract link value from Lark field
        Handles both string and dict formats
        """
        if not link_field:
            return ""
        
        # If it's a dictionary (Lark link field format)
        if isinstance(link_field, dict):
            # Try 'text' first, then 'href'
            link_value = link_field.get("text", "") or link_field.get("href", "")
            return str(link_value).strip()
        
        # If it's a list (multiple values)
        if isinstance(link_field, list):
            if len(link_field) > 0:
                first_item = link_field[0]
                if isinstance(first_item, dict):
                    link_value = first_item.get("text", "") or first_item.get("href", "")
                else:
                    link_value = str(first_item)
                return link_value.strip()
            return ""
        
        # If it's a string
        if isinstance(link_field, str):
            return link_field.strip()
        
        # Default
        return ""
    
    def get_all_active_records(self):
        """
        Get all records with non-empty "Link air bài" field from Lark Bitable
        Filters out records where link is empty
        """
        url = f"https://open.larksuite.com/open-apis/bitable/v1/apps/{self.bitable_app_token}/tables/{self.table_id}/records"
        
        all_records = []
        page_token = None
        total_processed = 0
        skipped_count = 0
        
        try:
            while True:
                params = {
                    'page_size': 500
                }
                
                if page_token:
                    params['page_token'] = page_token
                
                response = self._make_request('GET', url, params=params, timeout=30)
                
                if not response:
                    break
                
                data = response.json()
                
                if data.get('code') != 0:
                    logger.error(f"❌ Lark API error: {data}")
                    break
                
                items = data.get('data', {}).get('items', [])
                
                # Filter: Only keep records with non-empty "Link air bài"
                for item in items:
                    total_processed += 1
                    fields = item.get('fields', {})
                    
                    # 🔑 FILTER: Check "Link air bài" field and extract value properly
                    link_field = fields.get("Link air bài", "")
                    link_value = self._extract_link_value(link_field)
                    
                    if not link_value:
                        skipped_count += 1
                        logger.debug(f"⏭️  Skipping record {item.get('id')} - empty 'Link air bài'")
                        continue
                    
                    all_records.append(item)
                
                # Check for next page
                page_token = data.get('data', {}).get('page_token')
                if not page_token:
                    break
            
            logger.info(f"✅ Lark Bitable Scan Complete:")
            logger.info(f"   • Total records processed: {total_processed}")
            logger.info(f"   • Records with link: {len(all_records)}")
            logger.info(f"   • Skipped (empty link): {skipped_count}")
            
            return all_records
            
        except Exception as e:
            logger.error(f"❌ Error getting records: {e}")
            return []
    
    def get_record(self, record_id):
        """Get single record by ID"""
        url = f"https://open.larksuite.com/open-apis/bitable/v1/apps/{self.bitable_app_token}/tables/{self.table_id}/records/{record_id}"
        
        try:
            response = self._make_request('GET', url, timeout=10)
            
            if not response:
                return {}
            
            data = response.json()
            
            if data.get('code') == 0:
                return data.get('data', {}).get('record', {})
            else:
                logger.error(f"❌ Error getting record {record_id}: {data}")
                return {}
                
        except Exception as e:
            logger.error(f"❌ Exception getting record {record_id}: {e}")
            return {}