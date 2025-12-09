from dotenv import load_dotenv
import os
import sys
load_dotenv()

from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import logging
from datetime import datetime
import json
from app.crawler import TikTokCrawler
from app.lark_client import LarkClient
from app.sheets_client import GoogleSheetsClient

# ✅ CRITICAL: Configure logging to output to stdout with flush
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)  # Force stdout
    ]
)
logger = logging.getLogger(__name__)

# ✅ Helper function to ensure logs are flushed
def log_print(message: str):
    """Print and flush to ensure Railway captures logs"""
    print(message, flush=True)
    logger.info(message)

app = FastAPI(title="TikTok View Crawler")

# Global clients
lark_client = None
sheets_client = None
crawler = None

def init_clients():
    """Initialize all clients at startup"""
    global lark_client, sheets_client, crawler
    
    log_print("🔧 Initializing clients...")
    
    try:
        # Initialize Lark client
        lark_client = LarkClient(
            app_id=os.getenv("LARK_APP_ID"),
            app_secret=os.getenv("LARK_APP_SECRET"),
            bitable_app_token=os.getenv("LARK_BITABLE_TOKEN"),
            table_id=os.getenv("LARK_TABLE_ID")
        )
        log_print("✅ Lark client initialized successfully")
    except Exception as e:
        log_print(f"❌ Failed to initialize Lark client: {e}")
        lark_client = None

    try:
        # Initialize Google Sheets client
        google_credentials_json_str = os.getenv("GOOGLE_APPLICATION_CREDENTIALS_JSON")
        google_sheet_id = os.getenv("GOOGLE_SHEET_ID")
        
        if google_credentials_json_str and google_sheet_id:
            google_credentials = json.loads(google_credentials_json_str)
            sheets_client = GoogleSheetsClient(
                credentials_json=google_credentials,
                sheet_id=google_sheet_id
            )
            log_print("✅ Google Sheets client initialized successfully")
        else:
            log_print("❌ Missing Google Sheets credentials or sheet ID")
            sheets_client = None
    except Exception as e:
        log_print(f"❌ Failed to initialize Google Sheets client: {e}")
        sheets_client = None
    
    try:
        # Initialize TikTok crawler with Playwright support
        if lark_client and sheets_client:
            crawler = TikTokCrawler(
                lark_client=lark_client,
                sheets_client=sheets_client,
                use_playwright=True
            )
            log_print("✅ TikTok crawler initialized successfully")
        else:
            log_print("❌ Cannot initialize crawler - missing dependencies")
            crawler = None
    except Exception as e:
        log_print(f"❌ Failed to initialize crawler: {e}")
        crawler = None

@app.on_event("startup")
async def startup_event():
    """Initialize clients on startup"""
    log_print("🚀 Application starting up...")
    init_clients()
    log_print("✅ Application ready")

@app.get("/")
async def root():
    return {
        "message": "TikTok View Crawler API", 
        "version": "2.5.0-debug",
        "mode": "Playwright + Google Sheets + Lark Bitable",
        "endpoints": {
            "/jobs/daily": "Background crawl (may not show logs)",
            "/jobs/daily-sync": "⭐ SYNC crawl - SHOWS LOGS",
            "/jobs/test-single": "Test crawl 1 video"
        }
    }

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy", 
        "timestamp": datetime.now().isoformat(),
        "lark_connected": lark_client is not None,
        "sheets_connected": sheets_client is not None,
        "crawler_ready": crawler is not None,
        "playwright_enabled": crawler.use_playwright if crawler else False
    }


# ============================================================================
# ⭐ NEW: SYNC ENDPOINT - WILL SHOW LOGS IN RAILWAY
# ============================================================================

@app.post("/jobs/daily-sync")
async def daily_crawl_sync():
    """
    ⭐ SYNCHRONOUS crawl - blocks until complete
    USE THIS TO SEE LOGS IN RAILWAY
    
    Note: Will timeout after ~10 minutes on Railway free tier
    """
    log_print("="*60)
    log_print("🚀 SYNC CRAWL STARTED")
    log_print("="*60)
    
    if not crawler:
        log_print("❌ Crawler not initialized!")
        raise HTTPException(status_code=500, detail="Crawler not initialized")
    
    try:
        log_print("📋 Calling crawler.crawl_all_videos()...")
        
        # Run synchronously - will show logs
        result = crawler.crawl_all_videos()
        
        log_print(f"✅ Crawl completed: {result}")
        log_print("="*60)
        
        return {
            "success": True,
            "message": "Sync crawl completed",
            "result": result,
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        log_print(f"❌ SYNC CRAWL FAILED: {e}")
        import traceback
        log_print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# ⭐ NEW: TEST SINGLE VIDEO
# ============================================================================

@app.post("/jobs/test-single")
async def test_single_video():
    """
    Test crawl a single video to verify Playwright works
    """
    log_print("="*60)
    log_print("🧪 TESTING SINGLE VIDEO CRAWL")
    log_print("="*60)
    
    if not crawler or not crawler.playwright_crawler:
        log_print("❌ Playwright crawler not available!")
        raise HTTPException(status_code=500, detail="Playwright not available")
    
    test_url = "https://www.tiktok.com/@tiktok/video/7449807305491698990"
    
    try:
        log_print(f"📋 Testing URL: {test_url}")
        
        result = crawler.playwright_crawler.get_tiktok_views(test_url)
        
        if result:
            log_print(f"✅ SUCCESS! Views: {result.get('views', 0):,}")
            return {
                "success": True,
                "url": test_url,
                "result": result,
                "message": "Playwright is working!"
            }
        else:
            log_print("❌ No data returned")
            return {
                "success": False,
                "url": test_url,
                "message": "Failed to extract data"
            }
            
    except Exception as e:
        log_print(f"❌ TEST FAILED: {e}")
        import traceback
        log_print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# ⭐ NEW: TEST LARK + SHEETS
# ============================================================================

@app.post("/jobs/test-pipeline")
async def test_pipeline():
    """
    Test the full pipeline without crawling:
    1. Get records from Lark
    2. Write dummy data to Sheets
    """
    log_print("="*60)
    log_print("🧪 TESTING PIPELINE (Lark → Sheets)")
    log_print("="*60)
    
    results = {
        "lark": {"success": False, "records": 0},
        "sheets": {"success": False, "message": ""}
    }
    
    # Test Lark
    try:
        log_print("📋 Step 1: Getting records from Lark...")
        records = lark_client.get_all_active_records()
        results["lark"]["success"] = True
        results["lark"]["records"] = len(records)
        log_print(f"✅ Got {len(records)} records from Lark")
        
        if records:
            # Show first record
            first = records[0]
            log_print(f"   First record ID: {first.get('id', 'N/A')}")
            
    except Exception as e:
        log_print(f"❌ Lark failed: {e}")
        results["lark"]["error"] = str(e)
    
    # Test Sheets
    try:
        log_print("📋 Step 2: Testing Google Sheets connection...")
        existing = sheets_client.get_all_records_with_index()
        results["sheets"]["success"] = True
        results["sheets"]["existing_records"] = len(existing)
        log_print(f"✅ Sheets connected, {len(existing)} existing records")
        
    except Exception as e:
        log_print(f"❌ Sheets failed: {e}")
        results["sheets"]["error"] = str(e)
    
    log_print("="*60)
    log_print(f"Results: {results}")
    
    return results


# ============================================================================
# ORIGINAL BACKGROUND ENDPOINT (may not show logs)
# ============================================================================

@app.post("/jobs/daily")
async def daily_crawl_job(background_tasks: BackgroundTasks):
    """
    Trigger daily crawler job - runs in background
    ⚠️ WARNING: Logs may not appear in Railway for background tasks
    Use /jobs/daily-sync instead to see logs
    """
    
    if not crawler:
        raise HTTPException(status_code=500, detail="Crawler not initialized")
    
    background_tasks.add_task(run_daily_crawl)
    
    log_print("🚀 Daily crawl job started in background")
    return {
        "success": True,
        "status": "started",
        "message": "Daily crawler job started in background",
        "warning": "Logs may not appear - use /jobs/daily-sync to see logs",
        "timestamp": datetime.now().isoformat()
    }

def run_daily_crawl():
    """Background crawl task"""
    try:
        log_print("🚀 [BACKGROUND] Starting daily crawl...")
        result = crawler.crawl_all_videos()
        log_print(f"✅ [BACKGROUND] Completed: {result}")
    except Exception as e:
        log_print(f"❌ [BACKGROUND] Failed: {e}")
        import traceback
        log_print(traceback.format_exc())


# ============================================================================
# OTHER ENDPOINTS
# ============================================================================

@app.get("/status")
async def get_status():
    """Get system status"""
    return {
        "status": "ok" if all([lark_client, sheets_client, crawler]) else "degraded",
        "services": {
            "lark": "healthy" if lark_client else "not_initialized",
            "sheets": "healthy" if sheets_client else "not_initialized",
            "crawler": "healthy" if crawler else "not_initialized",
            "playwright": "enabled" if (crawler and crawler.use_playwright) else "disabled"
        },
        "timestamp": datetime.now().isoformat()
    }

@app.get("/debug/info")
async def debug_info():
    """Debug information"""
    return {
        "environment": {
            "lark_configured": bool(os.getenv("LARK_APP_ID")),
            "sheets_configured": bool(os.getenv("GOOGLE_SHEET_ID")),
            "railway_env": bool(os.getenv("RAILWAY_ENVIRONMENT"))
        },
        "clients": {
            "lark_initialized": lark_client is not None,
            "sheets_initialized": sheets_client is not None,
            "crawler_initialized": crawler is not None,
            "playwright_available": crawler.use_playwright if crawler else False
        },
        "version": "2.5.0-debug",
        "timestamp": datetime.now().isoformat()
    }

@app.get("/test/lark")
async def test_lark():
    """Test Lark connection"""
    if not lark_client:
        return {"success": False, "error": "Lark not initialized"}
    
    try:
        records = lark_client.get_all_active_records()
        return {
            "success": True,
            "total_records": len(records),
            "sample": records[:2] if records else []
        }
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.get("/test/sheets")
async def test_sheets():
    """Test Sheets connection"""
    if not sheets_client:
        return {"success": False, "error": "Sheets not initialized"}
    
    try:
        records = sheets_client.get_all_records_with_index()
        return {
            "success": True,
            "total_records": len(records),
            "sample": list(records.keys())[:5]
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


# Error handler
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    log_print(f"❌ Unhandled exception: {exc}")
    return JSONResponse(
        status_code=500,
        content={"success": False, "error": str(exc)}
    )


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    log_print(f"🚀 Starting server on port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)
