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

try:
    from apscheduler.schedulers.background import BackgroundScheduler
    SCHEDULER_AVAILABLE = True
except ImportError:
    SCHEDULER_AVAILABLE = False
    logging.warning("⚠️ APScheduler not installed. Auto-schedule disabled. Run: pip install apscheduler")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = FastAPI(title="TikTok View Crawler")

# Global clients
lark_client = None
sheets_client = None
crawler = None
scheduler = None

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

def _start_scheduler():
    """Start APScheduler with daily 8:00 AM Vietnam time job."""
    global scheduler
    if not SCHEDULER_AVAILABLE:
        logger.warning("⚠️ APScheduler not available — scheduled job skipped")
        return

    try:
        # Asia/Ho_Chi_Minh = UTC+7. If tzdata is not available on the server,
        # we fall back to UTC offset (01:00 UTC = 08:00 VN time).
        try:
            from zoneinfo import ZoneInfo
            tz = ZoneInfo('Asia/Ho_Chi_Minh')
            hour_utc, tz_label = 7, 'Asia/Ho_Chi_Minh'
        except Exception:
            tz = 'UTC'
            hour_utc, tz_label = 0, 'UTC (= 07:00 VN)'

        scheduler = BackgroundScheduler(timezone=tz)

        # Daily crawl at 07:00 Vietnam time
        scheduler.add_job(
            run_daily_crawl,
            'cron',
            hour=hour_utc,
            minute=0,
            id='daily_crawl',
            name='Daily TikTok View Crawl',
            replace_existing=True,
            misfire_grace_time=3600,   # Allow up to 1h late start (e.g. cold boot)
        )

        # Retry-pending at 13:00 (6 hours after daily crawl at 07:00)
        scheduler.add_job(
            _run_retry_pending,
            'cron',
            hour=(hour_utc + 6) % 24,
            minute=0,
            id='retry_pending',
            name='Retry Pending Videos',
            replace_existing=True,
            misfire_grace_time=3600,
        )

        scheduler.start()

        jobs = scheduler.get_jobs()
        for job in jobs:
            next_run = job.next_run_time.strftime('%Y-%m-%d %H:%M') if job.next_run_time else 'N/A'
            logger.info(f"⏰ Scheduled: [{job.name}] next run = {next_run} {tz_label}")

    except Exception as e:
        logger.error(f"❌ Failed to start scheduler: {e}", exc_info=True)


def _run_retry_pending():
    """Background wrapper for retry-pending job."""
    if not crawler:
        logger.warning("⚠️ Retry-pending: crawler not ready, skipping")
        return
    try:
        logger.info("🔄 Scheduled retry-pending job starting...")
        result = crawler.crawl_pending_retry()
        logger.info(f"✅ Retry-pending done: {result}")
    except Exception as e:
        logger.error(f"❌ Retry-pending job failed: {e}", exc_info=True)


@app.on_event("startup")
async def startup_event():
    """Initialize clients on startup, then start scheduler."""
    logger.info("🚀 Application starting up...")
    init_clients()
    _start_scheduler()
    logger.info("✅ Application ready")


@app.on_event("shutdown")
async def shutdown_event():
    """Gracefully shut down scheduler."""
    global scheduler
    if scheduler and scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("⏰ Scheduler stopped")

@app.get("/")
async def root():
    return {
        "message": "TikTok View Crawler API",
        "version": "4.2.0",
        "mode": "Playwright only — resource-blocking optimised",
        "features": [
            "Playwright with resource-blocking (images/media/fonts blocked → -40% CPU)",
            "Reduced delays/timeouts for faster throughput",
            "Pending propagation detection for very new videos",
            "Retry queue: /jobs/retry-pending (run 6h after daily)",
            "Lark Bitable write + Google Sheets date tracking",
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
            crawled = stats.get('crawled', 0)
            success = stats.get('success', 0)
            failed  = stats.get('failed', 0)
            broken  = stats.get('broken', 0)
            skipped = stats.get('skipped_old', 0)
            lark_updated = stats.get('lark_updated', 0)

            if crawled > 0:
                success_rate = (success / crawled) * 100
                logger.info(
                    f"📊 Crawl success: {success_rate:.1f}% ({success}/{crawled}) | "
                    f"failed={failed} broken={broken} skipped_old={skipped} | "
                    f"lark_updated={lark_updated}"
                )
                if success_rate < 70:
                    logger.warning(f"⚠️ Low crawl success rate: {success_rate:.1f}%")
        
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
@app.get("/schedule/status")
async def schedule_status():
    """Show scheduled jobs and their next run times."""
    if not scheduler or not scheduler.running:
        return {"status": "scheduler_not_running", "jobs": []}

    jobs = []
    for job in scheduler.get_jobs():
        next_run = job.next_run_time.isoformat() if job.next_run_time else None
        jobs.append({
            "id": job.id,
            "name": job.name,
            "next_run": next_run,
        })
    return {"status": "running", "jobs": jobs, "timezone": "Asia/Ho_Chi_Minh (08:00 daily)"}


@app.post("/jobs/retry-pending")
async def retry_pending_job(background_tasks: BackgroundTasks):
    """
    Retry videos that were pending data propagation during the last daily crawl.
    Run this 6+ hours after /jobs/daily to catch newly-uploaded April videos
    whose TikTok SSR data was not yet available at crawl time.
    """
    if not crawler:
        raise HTTPException(status_code=500, detail="Crawler not initialized")

    def run_retry():
        try:
            logger.info("🔄 Starting pending retry job (background)...")
            result = crawler.crawl_pending_retry()
            logger.info(f"✅ Pending retry completed: {result}")
        except Exception as e:
            logger.error(f"❌ Pending retry failed: {e}", exc_info=True)

    background_tasks.add_task(run_retry)
    logger.info("🔄 Pending retry job started in background")
    return {
        "success": True,
        "status": "started",
        "message": "Pending retry job started in background",
        "note": "Retries videos that had no data during last daily crawl (new videos)",
        "timestamp": datetime.now().isoformat(),
    }


@app.get("/debug/lark-fields")
async def debug_lark_fields():
    """
    List all field names and types from the Lark Bitable table.
    Use this to diagnose FieldNameNotFound errors — compare the exact
    field names returned here with what batch_update_records is writing.
    """
    if not lark_client:
        return {"success": False, "error": "Lark client not initialized"}
    try:
        fields = lark_client.get_table_fields()
        # Also show which names the code is currently trying to write
        write_fields_used = [
            'Lượt xem hiện tại',
            'Số view 24h trước',
            'Lần kiểm tra cuối',
            'Status',
        ]
        actual_names = [f['field_name'] for f in fields]
        mismatches = [n for n in write_fields_used if n not in actual_names]
        return {
            "success": True,
            "total_fields": len(fields),
            "fields": fields,
            "write_fields_used_by_code": write_fields_used,
            "mismatches": mismatches,
            "status": "✅ All write fields found" if not mismatches else f"❌ Mismatched: {mismatches}",
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


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
        "version": "2.3.0",
        "timestamp": datetime.now().isoformat()
    }

# ✅ OPTIONAL: Support for direct run (useful for local testing)
# This is NOT used in Railway (Railway uses Dockerfile CMD instead)
# But it's useful if you want to run: python -m app.main
if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    logger.info(f"🚀 Starting server on port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)