from dotenv import load_dotenv
import os
load_dotenv()

from fastapi import FastAPI, BackgroundTasks, HTTPException
from pydantic import BaseModel
import logging
from datetime import datetime, timedelta
import json
from app.crawler import TikTokCrawler
from app.lark_client import LarkClient
from app.sheets_client import GoogleSheetsClient
import asyncio

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
        # Initialize TikTok crawler
        if lark_client and sheets_client:
            crawler = TikTokCrawler(
                lark_client=lark_client,
                sheets_client=sheets_client
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
        "version": "2.1.0",
        "mode": "Google Sheets + Lark Bitable + Deduplication"
    }

@app.get("/health")
async def health_check():
    return {
        "status": "healthy", 
        "timestamp": datetime.now().isoformat(),
        "lark_connected": lark_client is not None,
        "sheets_connected": sheets_client is not None,
        "crawler_ready": crawler is not None
    }

@app.get("/test")
async def test():
    return {"message": "Test endpoint works", "timestamp": datetime.now().isoformat()}

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
    """Trigger daily crawler job - runs in background"""
    
    if not lark_client:
        raise HTTPException(status_code=500, detail="Lark client not initialized")
    if not sheets_client:
        raise HTTPException(status_code=500, detail="Sheets client not initialized")
    if not crawler:
        raise HTTPException(status_code=500, detail="Crawler not initialized")
    
    # Start background task
    background_tasks.add_task(run_daily_crawl)
    
    logger.info("🚀 Daily crawl job started in background")
    return {
        "success": True,
        "status": "started",
        "message": "Daily crawler job started in background",
        "note": "Check Google Sheets in 5-10 minutes for results",
        "timestamp": datetime.now().isoformat()
    }

async def run_daily_crawl():
    """Main crawler logic - runs in background"""
    try:
        logger.info("🚀 Starting daily crawl (background job)")
        
        # Run crawler
        result = crawler.crawl_all_videos()
        
        logger.info(f"✅ Daily crawl completed: {result}")
        
    except Exception as e:
        logger.error(f"❌ Daily crawl failed: {e}")

@app.get("/status")
async def get_status():
    """Get system status"""
    try:
        lark_ok = lark_client is not None
        sheets_ok = sheets_client is not None
        crawler_ok = crawler is not None
        
        return {
            "status": "ok" if all([lark_ok, sheets_ok, crawler_ok]) else "degraded",
            "services": {
                "lark": "✅ ready" if lark_ok else "❌ not initialized",
                "sheets": "✅ ready" if sheets_ok else "❌ not initialized",
                "crawler": "✅ ready" if crawler_ok else "❌ not initialized"
            },
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"Error getting status: {e}")
        return {"status": "error", "message": str(e)}, 500

class CrawlRequest(BaseModel):
    """Manual crawl request model"""
    record_ids: list = None

@app.post("/jobs/crawl-batch")
async def crawl_batch(request: CrawlRequest, background_tasks: BackgroundTasks):
    """Crawl specific records by IDs"""
    
    if not crawler:
        raise HTTPException(status_code=500, detail="Crawler not initialized")
    
    async def batch_task():
        try:
            result = crawler.crawl_videos_batch(record_ids=request.record_ids)
            logger.info(f"✅ Batch crawl completed: {result}")
        except Exception as e:
            logger.error(f"❌ Batch crawl failed: {e}")
    
    background_tasks.add_task(batch_task)
    
    logger.info(f"📋 Batch crawl job started for {len(request.record_ids) if request.record_ids else 'all'} records")
    return {
        "success": True,
        "message": "Batch crawl job started",
        "record_count": len(request.record_ids) if request.record_ids else "all",
        "timestamp": datetime.now().isoformat()
    }

# Error handler
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    """Global exception handler"""
    logger.error(f"❌ Unhandled exception: {exc}")
    return {
        "success": False,
        "message": "Internal server error",
        "error": str(exc)
    }