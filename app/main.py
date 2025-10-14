from dotenv import load_dotenv
import os
load_dotenv()

from fastapi import FastAPI, BackgroundTasks, HTTPException
from pydantic import BaseModel
import logging
from datetime import datetime, timedelta
import requests
from app.crawler import crawl_tiktok_views
from app.lark_client import LarkClient
from app.sheets_client import GoogleSheetsClient

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = FastAPI(title="TikTok View Crawler")

# Initialize Lark client
try:
    lark = LarkClient(
        app_id=os.getenv("LARK_APP_ID"),
        app_secret=os.getenv("LARK_APP_SECRET"),
        bitable_app_token=os.getenv("LARK_BITABLE_TOKEN"),
        table_id=os.getenv("LARK_TABLE_ID")
    )
    logger.info("✅ Lark client khởi tạo thành công")
except Exception as e:
    logger.error(f"❌ Không thể khởi tạo Lark client: {e}")
    lark = None

# Initialize Google Sheets client
try:
    sheets = GoogleSheetsClient()
    logger.info("✅ Google Sheets client khởi tạo thành công")
except Exception as e:
    logger.error(f"❌ Không thể khởi tạo Google Sheets client: {e}")
    sheets = None

class LarkWebhookPayload(BaseModel):
    record_id: str
    video_url: str

@app.get("/")
async def root():
    return {
        "message": "TikTok View Crawler API", 
        "version": "2.0.0",
        "mode": "Google Sheets + Lark Anycross"
    }

@app.get("/health")
async def health_check():
    return {
        "status": "healthy", 
        "timestamp": datetime.now().isoformat(),
        "lark_connected": lark is not None,
        "sheets_connected": sheets is not None
    }

@app.get("/test")
async def test():
    return {"message": "Test endpoint works"}

@app.get("/test/crawl")
async def test_crawl_endpoint(url: str):
    logger.info(f"Testing crawl: {url}")
    result = await crawl_tiktok_views(url)
    return result

@app.get("/test/lark")
async def test_lark_connection():
    if not lark:
        return {"error": "Lark client chưa được cấu hình"}
    
    try:
        records = lark.get_all_active_records()
        return {
            "success": True,
            "total_records": len(records),
            "sample_records": records[:3] if len(records) > 0 else []
        }
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.get("/test/sheets")
async def test_sheets_connection():
    """Test Google Sheets connection"""
    if not sheets:
        return {"error": "Google Sheets client chưa được cấu hình"}
    
    try:
        records = sheets.get_all_records()
        return {
            "success": True,
            "total_records": len(records),
            "sample_records": records[:3] if records else []
        }
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/webhooks/lark")
async def handle_lark_webhook(payload: LarkWebhookPayload, background_tasks: BackgroundTasks):
    if not lark or not sheets:
        return {"error": "Clients chưa được cấu hình"}
    logger.info(f"Nhận webhook: {payload.record_id}")
    background_tasks.add_task(process_single_video, payload.record_id, payload.video_url)
    return {"message": "Đã tiếp nhận"}

@app.post("/jobs/daily")
async def daily_crawl_job():
    """Crawl all videos from Lark and write to Google Sheets"""
    if not lark:
        raise HTTPException(status_code=500, detail="Lark client chưa được cấu hình")
    if not sheets:
        raise HTTPException(status_code=500, detail="Google Sheets client chưa được cấu hình")
    
    try:
        logger.info("🚀 Bắt đầu daily crawl job")
        
        # Read records from Lark
        records = lark.get_all_active_records()
        logger.info(f"📊 Tìm thấy {len(records)} records từ Lark Bitable")
        
        success_count = 0
        error_count = 0
        
        for record in records:
            try:
                record_id = record.get('record_id')
                fields = record.get('fields', {})
                
                # Get TikTok link
                link_field = fields.get('Link air bài')
                
                # Extract URL
                video_url = None
                if isinstance(link_field, str):
                    video_url = link_field
                elif isinstance(link_field, dict):
                    video_url = link_field.get("link") or link_field.get("text")
                elif isinstance(link_field, list) and len(link_field) > 0:
                    first = link_field[0]
                    if isinstance(first, dict):
                        video_url = first.get("text") or first.get("link")
                    elif isinstance(first, str):
                        video_url = first
                
                if not video_url or 'tiktok.com' not in video_url:
                    logger.warning(f"⚠️ Bỏ qua record {record_id}: không có link TikTok hợp lệ")
                    continue
                
                logger.info(f"🎬 Bắt đầu crawl qua API: {video_url}")
                
                # Crawl views
                result = await crawl_tiktok_views(video_url)
                
                if not result.get("success"):
                    logger.warning(f"⚠️ Không crawl được: {video_url}")
                    error_count += 1
                    continue
                
                current_views = int(result["views"])
                logger.info(f"✅ Crawl thành công: {current_views} views")
                
                # Get baseline views
                baseline_views = fields.get('Số view 24h trước', 0)
                if isinstance(baseline_views, str):
                    baseline_views = int(baseline_views) if baseline_views.isdigit() else 0
                elif baseline_views is None:
                    baseline_views = 0
                
                # Check if need to update baseline (after 24h)
                last_checked = fields.get("Lần kiểm tra cuối", "")
                now = datetime.now()
                update_baseline = False
                
                if last_checked:
                    try:
                        last_checked_clean = str(last_checked).replace("Z", "").replace("+00:00", "")
                        if "T" in last_checked_clean:
                            last_check_time = datetime.fromisoformat(last_checked_clean)
                        else:
                            last_check_time = datetime.strptime(last_checked_clean, "%Y-%m-%d %H:%M:%S")
                        
                        if (now - last_check_time) >= timedelta(hours=24):
                            update_baseline = True
                    except Exception as e:
                        logger.warning(f"Parse datetime error: {e}")
                        update_baseline = True
                else:
                    # First time check
                    baseline_views = current_views
                
                # Update baseline if 24h passed
                if update_baseline:
                    old_views = fields.get("Lượt xem hiện tại", current_views)
                    baseline_views = int(old_views) if old_views else current_views
                
                # Write to Google Sheets
                last_check_str = now.strftime("%Y-%m-%d %H:%M:%S")
                
                sheets_success = sheets.update_or_append_record(
                    record_id=record_id,
                    link=video_url,
                    current_views=current_views,
                    baseline_views=baseline_views,
                    last_check=last_check_str,
                    status="Active"
                )
                
                if sheets_success:
                    success_count += 1
                    logger.info(f"✅ Updated {record_id}: {current_views} views (baseline: {baseline_views})")
                else:
                    error_count += 1
                    logger.error(f"❌ Failed to write to Sheets: {record_id}")
                    
            except Exception as e:
                logger.error(f"❌ Lỗi xử lý record {record_id}: {str(e)}")
                error_count += 1
                continue
        
        logger.info(f"🎉 Hoàn thành crawl: {success_count} thành công, {error_count} lỗi")
        
        return {
            "status": "completed",
            "total_records": len(records),
            "success": success_count,
            "errors": error_count,
            "note": "Dữ liệu đã ghi vào Google Sheets. Dùng Lark Anycross để sync sang Bitable."
        }
        
    except Exception as e:
        logger.error(f"❌ Job failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

async def process_single_video(record_id: str, video_url: str):
    """Process single video (for webhook)"""
    try:
        result = await crawl_tiktok_views(video_url)
        
        if result["success"]:
            current_views = int(result["views"])
            
            # Get old record from Lark
            old_record = lark.get_record(record_id)
            fields = old_record.get("fields", {})
            
            last_checked = fields.get("Lần kiểm tra cuối", "")
            baseline_views = int(fields.get("Số view 24h trước") or 0)
            
            # Check if 24h passed
            now = datetime.now()
            update_baseline = False
            
            if last_checked:
                try:
                    last_checked_clean = str(last_checked).replace("Z", "").replace("+00:00", "")
                    if "T" in last_checked_clean:
                        last_check_time = datetime.fromisoformat(last_checked_clean)
                    else:
                        last_check_time = datetime.strptime(last_checked_clean, "%Y-%m-%d %H:%M:%S")
                    
                    if (now - last_check_time) >= timedelta(hours=24):
                        update_baseline = True
                except Exception as e:
                    logger.warning(f"Parse datetime error: {e}")
                    update_baseline = True
            else:
                baseline_views = current_views
            
            if update_baseline:
                baseline_views = int(fields.get("Lượt xem hiện tại") or current_views)
            
            # Write to Google Sheets
            last_check_str = now.strftime("%Y-%m-%d %H:%M:%S")
            
            sheets.update_or_append_record(
                record_id=record_id,
                link=video_url,
                current_views=current_views,
                baseline_views=baseline_views,
                last_check=last_check_str,
                status="Active"
            )
            
            logger.info(f"✅ Updated {record_id}: {current_views} views (baseline: {baseline_views})")
        else:
            logger.warning(f"⚠️ Failed to crawl {record_id}")
    except Exception as e:
        logger.error(f"❌ Lỗi process_single_video: {e}")