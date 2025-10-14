import requests
import logging
from typing import Dict, List

logger = logging.getLogger(__name__)

class LarkClient:
    def __init__(self, app_id: str, app_secret: str, bitable_app_token: str, table_id: str):
        self.app_id = app_id
        self.app_secret = app_secret
        self.bitable_app_token = bitable_app_token
        self.table_id = table_id
        self.base_url = "https://open.larksuite.com/open-apis"
        self.access_token = None
        self._get_access_token()
    
    def _get_access_token(self):
        url = f"{self.base_url}/auth/v3/tenant_access_token/internal"
        payload = {"app_id": self.app_id, "app_secret": self.app_secret}
        
        try:
            response = requests.post(url, json=payload)
            data = response.json()
            if data.get("code") == 0:
                self.access_token = data["tenant_access_token"]
                logger.info("✅ Lấy access token thành công")
            else:
                logger.error(f"Lỗi lấy token: {data}")
        except Exception as e:
            logger.error(f"Lỗi kết nối Lark: {e}")
    
    def _get_headers(self) -> Dict:
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json"
        }
    
    def get_record(self, record_id: str) -> Dict:
        url = f"{self.base_url}/bitable/v1/apps/{self.bitable_app_token}/tables/{self.table_id}/records/{record_id}"
        try:
            response = requests.get(url, headers=self._get_headers())
            data = response.json()
            if data.get("code") == 0:
                return data["data"]["record"]["fields"]
            return {}
        except Exception as e:
            logger.error(f"Lỗi get_record: {e}")
            return {}
    
    def update_record(self, record_id: str, fields: Dict):
        url = f"{self.base_url}/bitable/v1/apps/{self.bitable_app_token}/tables/{self.table_id}/records/{record_id}"
        payload = {"fields": fields}
        try:
            response = requests.put(url, headers=self._get_headers(), json=payload)
            data = response.json()
            if data.get("code") == 0:
                logger.info(f"✅ Cập nhật record {record_id} thành công")
            else:
                logger.error(f"Lỗi cập nhật: {data}")
        except Exception as e:
            logger.error(f"Lỗi update_record: {e}")
    
    def get_all_active_records(self) -> List[Dict]:
        url = f"{self.base_url}/bitable/v1/apps/{self.bitable_app_token}/tables/{self.table_id}/records"
        all_filtered_records = []
        page_token = None
        
        while True:
            params = {"page_size": 100}
            if page_token:
                params["page_token"] = page_token
            
            try:
                response = requests.get(url, headers=self._get_headers(), params=params)
                data = response.json()
                
                if data.get("code") == 0:
                    items = data["data"]["items"]
                    
                    for record in items:
                        fields = record.get("fields", {})
                        link_field = fields.get("Link air bài")
                        
                        link = None
                        if link_field:
                            if isinstance(link_field, str):
                                link = link_field
                            elif isinstance(link_field, dict):
                                link = link_field.get("text") or link_field.get("link")
                            elif isinstance(link_field, list) and len(link_field) > 0:
                                first_item = link_field[0]
                                if isinstance(first_item, dict):
                                    link = first_item.get("text") or first_item.get("link")
                                elif isinstance(first_item, str):
                                    link = first_item
                        
                        if link and isinstance(link, str) and link.strip():
                            all_filtered_records.append(record)
                    
                    if data["data"].get("has_more"):
                        page_token = data["data"]["page_token"]
                    else:
                        break
                else:
                    logger.error(f"Lỗi lấy records: {data}")
                    break
            except Exception as e:
                logger.error(f"Lỗi get_all_active_records: {e}")
                break
        
        logger.info(f"Tìm thấy {len(all_filtered_records)} records có link")
        return all_filtered_records