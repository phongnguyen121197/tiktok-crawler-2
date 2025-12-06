from dotenv import load_dotenv
import os
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

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = FastAPI(title="TikTok View Crawler")

# Global clients
lark_client = None
sheets_client = None
crawler = None

def init_clients():
    """Initialize all clients at startup"""
    global lark_client, sheets_client, crawler
    
    try:
        # Initialize Lark client
        lark_client = LarkClient(
            app_id=os.getenv("LARK_APP_ID"),
            app_secret=os.getenv("LARK_APP_SECRET"),
            bitable_app_token=os.getenv("LARK_BITABLE_TOKEN"),
            table_id=os.getenv("LARK_TABLE_ID")
        )
        logger.info("✅ Lark client initialized successfully")
    except Exception as e:
        logger.error(f"❌ Failed to initialize Lark client: {e}")
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
            logger.info("✅ Google Sheets client initialized successfully")
        else:
            logger.error("❌ Missing Google Sheets credentials or sheet ID")
            sheets_client = None
    except Exception as e:
        logger.error(f"❌ Failed to initialize Google Sheets client: {e}")
        sheets_client = None
    
    try:
        # Initialize TikTok crawler with Playwright support
        if lark_client and sheets_client:
            crawler = TikTokCrawler(
                lark_client=lark_client,
                sheets_client=sheets_client,
                use_playwright=True  # Enable Playwright by default
            )
            logger.info("✅ TikTok crawler initialized successfully")
        else:
            logger.error("❌ Cannot initialize crawler - missing dependencies")
            crawler = None
    except Exception as e:
        logger.error(f"❌ Failed to initialize crawler: {e}")
        crawler = None

@app.on_event("startup")
async def startup_event():
    """Initialize clients on startup"""
    logger.info("🚀 Application starting up...")
    init_clients()
    logger.info("✅ Application ready")

@app.get("/")
async def root():
    return {
        "message": "TikTok View Crawler API", 
        "version": "2.4.0",
        "mode": "Playwright + Google Sheets + Lark Bitable + Deduplication",
        "features": [
            "Direct TikTok scraping via Playwright",
            "Published date extraction",
            "Automatic fallback to Lark data",
            "Duplicate prevention",
            "Background job processing",
            "Timestamp migration support"
        ]
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

@app.get("/test")
async def test():
    """Simple test endpoint"""
    return {
        "message": "Test endpoint works", 
        "timestamp": datetime.now().isoformat()
    }

@app.get("/test/lark")
async def test_lark_connection():
    """Test Lark Bitable connection"""
    if not lark_client:
        logger.error("Lark client not initialized")
        return {"success": False, "error": "Lark client not configured"}
    
    try:
        records = lark_client.get_all_active_records()
        return {
            "success": True,
            "total_records": len(records),
            "message": f"Retrieved {len(records)} active records from Lark",
            "sample_records": records[:2] if len(records) > 0 else []
        }
    except Exception as e:
        logger.error(f"Error testing Lark: {e}")
        return {"success": False, "error": str(e)}

@app.get("/test/sheets")
async def test_sheets_connection():
    """Test Google Sheets connection"""
    if not sheets_client:
        logger.error("Sheets client not initialized")
        return {"success": False, "error": "Sheets client not configured"}
    
    try:
        record_index = sheets_client.get_all_records_with_index()
        return {
            "success": True,
            "total_records": len(record_index),
            "message": f"Retrieved {len(record_index)} records from Google Sheets",
            "sample_records": list(record_index.keys())[:5]
        }
    except Exception as e:
        logger.error(f"Error testing Sheets: {e}")
        return {"success": False, "error": str(e)}

@app.post("/jobs/daily")
async def daily_crawl_job(background_tasks: BackgroundTasks):
    """
    Trigger daily crawler job - runs in background
    Expected duration: 30-40 minutes for 227 records with Playwright
    """
    
    if not lark_client:
        raise HTTPException(status_code=500, detail="Lark client not initialized")
    if not sheets_client:
        raise HTTPException(status_code=500, detail="Sheets client not initialized")
    if not crawler:
        raise HTTPException(status_code=500, detail="Crawler not initialized")
    
    # ✅ FIXED: Use sync function for background task (not async)
    background_tasks.add_task(run_daily_crawl)
    
    logger.info("🚀 Daily crawl job started in background")
    return {
        "success": True,
        "status": "started",
        "message": "Daily crawler job started in background",
        "note": "Playwright crawling takes 30-40 minutes for 227 records",
        "estimated_completion": "Check Google Sheets in 40-45 minutes",
        "timestamp": datetime.now().isoformat()
    }

def run_daily_crawl():
    """
    Main crawler logic - runs in background
    ✅ FIXED: Changed from async to sync function
    """
    try:
        logger.info("🚀 Starting daily crawl (background job)")
        logger.info("⏱️ Expected duration: 30-40 minutes with Playwright")
        
        # Run crawler (this is a sync function)
        result = crawler.crawl_all_videos()
        
        logger.info(f"✅ Daily crawl completed: {result}")
        
        # Log success rate
        if result.get('success') and result.get('stats'):
            stats = result['stats']
            total = stats.get('total', 0)
            processed = stats.get('processed', 0)
            failed = stats.get('failed', 0)
            
            if total > 0:
                success_rate = (processed / total) * 100
                logger.info(f"📊 Success rate: {success_rate:.1f}% ({processed}/{total})")
                
                if success_rate < 80:
                    logger.warning(f"⚠️ Low success rate: {success_rate:.1f}%")
        
    except Exception as e:
        logger.error(f"❌ Daily crawl failed: {e}", exc_info=True)

@app.get("/status")
async def get_status():
    """Get system status"""
    try:
        lark_ok = lark_client is not None
        sheets_ok = sheets_client is not None
        crawler_ok = crawler is not None
        playwright_ok = crawler.use_playwright if crawler else False
        
        return {
            "status": "ok" if all([lark_ok, sheets_ok, crawler_ok]) else "degraded",
            "services": {
                "lark": "healthy" if lark_ok else "not_initialized",
                "sheets": "healthy" if sheets_ok else "not_initialized",
                "crawler": "healthy" if crawler_ok else "not_initialized",
                "playwright": "enabled" if playwright_ok else "disabled"
            },
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"Error getting status: {e}")
        # ✅ FIXED: Proper error response format
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": str(e)}
        )

class CrawlRequest(BaseModel):
    """Manual crawl request model"""
    record_ids: list = None

@app.post("/jobs/crawl-batch")
async def crawl_batch(request: CrawlRequest, background_tasks: BackgroundTasks):
    """
    Crawl specific records by IDs
    Useful for re-crawling failed videos or testing
    """
    
    if not crawler:
        raise HTTPException(status_code=500, detail="Crawler not initialized")
    
    # ✅ FIXED: Changed to sync function (not async)
    def batch_task():
        try:
            logger.info(f"📋 Starting batch crawl for {len(request.record_ids) if request.record_ids else 'all'} records")
            result = crawler.crawl_videos_batch(record_ids=request.record_ids)
            logger.info(f"✅ Batch crawl completed: {result}")
        except Exception as e:
            logger.error(f"❌ Batch crawl failed: {e}", exc_info=True)
    
    background_tasks.add_task(batch_task)
    
    record_count = len(request.record_ids) if request.record_ids else "all"
    logger.info(f"📋 Batch crawl job started for {record_count} records")
    
    return {
        "success": True,
        "message": "Batch crawl job started",
        "record_count": record_count,
        "timestamp": datetime.now().isoformat()
    }

# ✅ NEW: Migration endpoint to fix old timestamps
@app.post("/jobs/fix-timestamps")
async def fix_timestamps(background_tasks: BackgroundTasks):
    """
    🔧 MIGRATION: Convert timestamps in column E to date strings
    
    This will find all cells in column E (Published Date) that contain
    10 or 13 digit numbers and convert them to YYYY-MM-DD format.
    
    Example:
        1758128400000 -> 2025-09-18
    """
    
    if not sheets_client:
        raise HTTPException(status_code=500, detail="Sheets client not initialized")
    
    def migration_task():
        try:
            logger.info("🔧 Starting timestamp migration...")
            fixed_count = sheets_client.fix_timestamp_dates()
            logger.info(f"✅ Migration completed: Fixed {fixed_count} timestamps")
        except Exception as e:
            logger.error(f"❌ Migration failed: {e}", exc_info=True)
    
    background_tasks.add_task(migration_task)
    
    logger.info("🔧 Timestamp migration job started in background")
    return {
        "success": True,
        "status": "started",
        "message": "Timestamp migration started in background",
        "description": "Converting timestamps in column E to YYYY-MM-DD format",
        "timestamp": datetime.now().isoformat()
    }

# ✅ NEW: Analyze dates endpoint (check before migration)
@app.get("/analyze/dates")
async def analyze_dates():
    """
    📊 Analyze the Published Date column (E) to see what needs fixing
    
    Returns counts of:
    - Valid dates (YYYY-MM-DD format)
    - Timestamps (need conversion)
    - Empty cells
    """
    
    if not sheets_client:
        raise HTTPException(status_code=500, detail="Sheets client not initialized")
    
    try:
        logger.info("📊 Analyzing Published Date column...")
        
        all_values = sheets_client.worksheet.get_all_values()
        
        if len(all_values) < 2:
            return {
                "success": True,
                "message": "Sheet is empty or has only headers",
                "analysis": {
                    "total_rows": 0,
                    "valid_dates": 0,
                    "timestamps": 0,
                    "empty_cells": 0
                }
            }
        
        publish_date_col = 4  # Column E (0-indexed)
        timestamps = []
        valid_dates = []
        empty_cells = []
        other = []
        
        for row_idx, row in enumerate(all_values[1:], start=2):  # Skip header
            if len(row) > publish_date_col:
                cell_value = str(row[publish_date_col]).strip()
                
                if not cell_value:
                    empty_cells.append(row_idx)
                elif cell_value.isdigit() and len(cell_value) >= 10:
                    timestamps.append({
                        "row": row_idx,
                        "value": cell_value,
                        "converted": sheets_client._convert_timestamp_to_date(int(cell_value))
                    })
                elif len(cell_value) == 10 and '-' in cell_value:  # YYYY-MM-DD
                    valid_dates.append(row_idx)
                else:
                    other.append({"row": row_idx, "value": cell_value})
        
        return {
            "success": True,
            "message": "Analysis complete",
            "analysis": {
                "total_rows": len(all_values) - 1,
                "valid_dates": len(valid_dates),
                "timestamps_to_fix": len(timestamps),
                "empty_cells": len(empty_cells),
                "other_format": len(other)
            },
            "sample_timestamps": timestamps[:5],
            "sample_other": other[:5],
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"❌ Analysis failed: {e}")
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": str(e)}
        )

# ✅ IMPROVED: Better global exception handler
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    """Global exception handler"""
    logger.error(f"❌ Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "success": False,
            "message": "Internal server error",
            "error": str(exc),
            "timestamp": datetime.now().isoformat()
        }
    )

# Additional helper endpoint for debugging
@app.get("/debug/info")
async def debug_info():
    """
    Debug information endpoint
    Shows current configuration and status
    """
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
        "version": "2.4.0",
        "timestamp": datetime.now().isoformat()
    }

# ✅ OPTIONAL: Support for direct run (useful for local testing)
if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    logger.info(f"🚀 Starting server on port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)
