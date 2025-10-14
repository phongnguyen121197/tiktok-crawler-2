import requests
import re
import logging

logger = logging.getLogger(__name__)

async def crawl_tiktok_views(video_url: str, max_retries: int = 3) -> dict:
    """
    Crawl TikTok views using TikWM API (no watermark)
    API docs: https://www.tikwm.com/api
    """
    logger.info(f"Bắt đầu crawl qua API: {video_url}")
    
    tiktok_id = extract_tiktok_id(video_url)
    
    # API endpoint
    api_url = "https://www.tikwm.com/api/"
    
    for attempt in range(max_retries):
        try:
            logger.info(f"Attempt {attempt + 1}/{max_retries}")
            
            response = requests.post(
                api_url,
                data={
                    "url": video_url,
                    "count": 12,
                    "cursor": 0,
                    "web": 1,
                    "hd": 1
                },
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                },
                timeout=30
            )
            
            response.raise_for_status()
            data = response.json()
            
            logger.info(f"API Response: {data.get('code')}, msg: {data.get('msg')}")
            
            if data.get("code") == 0 and data.get("data"):
                video_data = data["data"]
                views = video_data.get("play_count", 0)
                
                if views > 0:
                    logger.info(f"✅ Crawl thành công: {views} views")
                    return {
                        "success": True,
                        "views": views,
                        "tiktok_id": tiktok_id,
                        "extra_data": {
                            "likes": video_data.get("digg_count", 0),
                            "comments": video_data.get("comment_count", 0),
                            "shares": video_data.get("share_count", 0),
                            "title": video_data.get("title", "")
                        }
                    }
            
            logger.warning(f"API trả về code: {data.get('code')}, msg: {data.get('msg')}")
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Request error attempt {attempt+1}: {e}")
        except Exception as e:
            logger.error(f"Lỗi attempt {attempt+1}: {e}")
    
    return {
        "success": False, 
        "error": "Không crawl được sau nhiều lần thử"
    }

def extract_tiktok_id(url: str) -> str:
    match = re.search(r'/video/(\d+)', url)
    return match.group(1) if match else ""