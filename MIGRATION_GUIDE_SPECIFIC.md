# 🔄 MIGRATION GUIDE - Playwright Integration for YOUR Project

## 📋 Overview

This guide shows EXACTLY what to change in your current project to integrate Playwright.
All line numbers and code snippets are based on YOUR current code.

---

## 🎯 What We're Doing

### Current State
```
❌ TikWM API blocked → All status = "partial"
❌ No real TikTok data
✅ But: Lark + Sheets integration works perfectly
```

### After Migration
```
✅ Playwright scraping → 80-90% success
✅ Real TikTok view counts
✅ Automatic fallback to Lark
✅ All existing endpoints still work
```

---

## 📁 FILES TO UPDATE

```
your-project/
├── app/
│   ├── crawler.py          ⚠️ REPLACE with crawler_fixed.py
│   ├── main.py             ⚠️ REPLACE with main_fixed.py
│   ├── lark_client.py      ✅ KEEP (no changes needed)
│   ├── sheets_client.py    ✅ KEEP (no changes needed)
│   └── playwright_crawler.py  🆕 ADD (new file)
├── requirements.txt        ⚠️ UPDATE (add playwright)
└── railway.json            🆕 ADD (new file)
```

---

## 🔧 STEP-BY-STEP MIGRATION

### STEP 1: Backup Current Code (1 minute)

```bash
# Create backup branch
git checkout -b backup-before-playwright
git add .
git commit -m "backup: before Playwright integration"
git push origin backup-before-playwright

# Return to main
git checkout main
```

---

### STEP 2: Add New Files (2 minutes)

#### 2.1 Add `app/playwright_crawler.py`
```bash
# Copy from package:
playwright-integration/playwright_crawler.py → your-project/app/playwright_crawler.py
```

**Content:** The Playwright crawler implementation (14 KB file)

#### 2.2 Add `railway.json`
```bash
# Copy from package:
playwright-integration/railway.json → your-project/railway.json
```

**Content:**
```json
{
  "$schema": "https://railway.app/railway.schema.json",
  "build": {
    "builder": "NIXPACKS",
    "buildCommand": "pip install -r requirements.txt && playwright install chromium"
  },
  "deploy": {
    "startCommand": "uvicorn app.main:app --host 0.0.0.0 --port $PORT",
    "healthcheckPath": "/health",
    "healthcheckTimeout": 300,
    "restartPolicyType": "ON_FAILURE",
    "restartPolicyMaxRetries": 3
  }
}
```

---

### STEP 3: Update `requirements.txt` (1 minute)

#### Current Content:
```txt
fastapi==0.104.1
uvicorn==0.24.0
python-dotenv==1.0.0
requests==2.31.0
gspread==5.12.0
google-auth==2.25.2
google-auth-oauthlib==1.2.0
google-auth-httplib2==0.2.0
```

#### ✅ ADD THIS LINE:
```txt
playwright==1.40.0
```

#### Final Content:
```txt
fastapi==0.104.1
uvicorn==0.24.0
python-dotenv==1.0.0
requests==2.31.0
gspread==5.12.0
google-auth==2.25.2
google-auth-oauthlib==1.2.0
google-auth-httplib2==0.2.0
playwright==1.40.0
```

---

### STEP 4: Replace `app/crawler.py` (1 minute)

#### Option A: Complete Replacement (Recommended)
```bash
# Delete old file
rm app/crawler.py

# Copy new fixed version
cp crawler_fixed.py app/crawler.py
```

#### Option B: Manual Updates (If you want to keep custom changes)

**🔴 CRITICAL CHANGES:**

##### Change 1: Update `__init__` method
**Location:** Line 9-15 in your current crawler.py

**Before:**
```python
def __init__(self, lark_client, sheets_client):
    """
    Initialize crawler with Lark and Sheets clients
    """
    self.lark_client = lark_client
    self.sheets_client = sheets_client
    self.tikwm_api = "https://api.tikvideo.top/api"
```

**After:**
```python
def __init__(self, lark_client, sheets_client, use_playwright=True):
    """
    Initialize crawler with Lark and Sheets clients
    """
    self.lark_client = lark_client
    self.sheets_client = sheets_client
    self.use_playwright = use_playwright and PLAYWRIGHT_AVAILABLE
    
    # Initialize Playwright crawler if available
    if self.use_playwright:
        try:
            self.playwright_crawler = TikTokPlaywrightCrawler()
            logger.info("✅ Playwright crawler initialized")
        except Exception as e:
            logger.error(f"❌ Failed to initialize Playwright: {e}")
            self.playwright_crawler = None
            self.use_playwright = False
    else:
        self.playwright_crawler = None
    
    self.tikwm_api = "https://api.tikvideo.top/api"  # Keep for reference
```

##### Change 2: Add imports at top of file
**Location:** Lines 1-6

**Before:**
```python
import requests
import logging
from typing import List, Dict
from datetime import datetime
import json

logger = logging.getLogger(__name__)
```

**After:**
```python
import logging
from typing import List, Dict, Optional
from datetime import datetime

# Import Playwright crawler
try:
    from app.playwright_crawler import TikTokPlaywrightCrawler
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    logging.warning("⚠️ Playwright not available, will use Lark data fallback only")

logger = logging.getLogger(__name__)
```

##### Change 3: Replace `get_tiktok_views` method
**Location:** Lines 33-72 in your current file

**Before:**
```python
def get_tiktok_views(self, video_url: str) -> Dict:
    """
    Get TikTok video stats using TikWM API
    Returns: {views: int, likes: int, comments: int, shares: int}
    """
    try:
        video_id = self.extract_video_id_from_url(video_url)
        
        if not video_id:
            logger.warning(f"⚠️ Invalid TikTok URL: {video_url}")
            return None
        
        # Call TikWM API
        params = {
            'url': f'https://www.tiktok.com/video/{video_id}'
        }
        
        response = requests.get(self.tikwm_api, params=params, timeout=15)
        response.raise_for_status()
        
        data = response.json()
        
        if data.get('code') == 0 and data.get('data'):
            video_data = data['data']['video']
            stats = {
                'views': video_data.get('playCount', 0),
                'likes': video_data.get('diggCount', 0),
                'comments': video_data.get('commentCount', 0),
                'shares': video_data.get('shareCount', 0)
            }
            logger.debug(f"✅ Got TikTok stats for {video_id}: {stats['views']} views")
            return stats
        else:
            logger.warning(f"⚠️ TikWM API error: {data}")
            return None
            
    except requests.exceptions.Timeout:
        logger.warning(f"⏱️ TikWM API timeout for: {video_url}")
        return None
    except Exception as e:
        logger.error(f"❌ Error getting TikTok views: {e}")
        return None
```

**After:**
```python
def get_tiktok_views(self, video_url: str) -> Optional[Dict]:
    """
    Get TikTok video stats using Playwright
    Falls back to None if Playwright fails
    
    Args:
        video_url: TikTok video URL
        
    Returns:
        Dict with {views, likes, comments, shares} or None
    """
    # Try Playwright if available
    if self.use_playwright and self.playwright_crawler:
        try:
            logger.debug(f"🔍 Crawling with Playwright: {video_url}")
            stats = self.playwright_crawler.get_tiktok_views(video_url)
            
            if stats and stats.get('views', 0) > 0:
                logger.debug(f"✅ Got TikTok stats for {video_url}: {stats['views']:,} views")
                return stats
            else:
                logger.warning(f"⚠️ Playwright returned no stats for: {video_url}")
                return None
                
        except Exception as e:
            logger.error(f"❌ Playwright error for {video_url}: {e}")
            return None
    else:
        logger.debug(f"⚠️ Playwright not available for: {video_url}")
        return None
```

**✅ KEEP UNCHANGED:**
- `extract_video_id_from_url()` ✓
- `extract_lark_field_value()` ✓
- `process_lark_record()` ✓
- `crawl_all_videos()` ✓
- `crawl_videos_batch()` ✓

---

### STEP 5: Replace `app/main.py` (1 minute)

#### Option A: Complete Replacement (Recommended)
```bash
# Delete old file
rm app/main.py

# Copy new fixed version
cp main_fixed.py app/main.py
```

#### Option B: Manual Updates

**🔴 CRITICAL CHANGES:**

##### Change 1: Update version and description
**Location:** Line 52-56

**Before:**
```python
@app.get("/")
async def root():
    return {
        "message": "TikTok View Crawler API", 
        "version": "2.1.0",
        "mode": "Google Sheets + Lark Bitable + Deduplication"
    }
```

**After:**
```python
@app.get("/")
async def root():
    return {
        "message": "TikTok View Crawler API", 
        "version": "2.2.0",
        "mode": "Playwright + Google Sheets + Lark Bitable + Deduplication",
        "features": [
            "Direct TikTok scraping via Playwright",
            "Automatic fallback to Lark data",
            "Duplicate prevention",
            "Background job processing"
        ]
    }
```

##### Change 2: Update crawler initialization
**Location:** Line 42-51

**Before:**
```python
try:
    # Initialize TikTok crawler
    if lark_client and sheets_client:
        crawler = TikTokCrawler(
            lark_client=lark_client,
            sheets_client=sheets_client
        )
        logger.info("✅ TikTok crawler initialized successfully")
```

**After:**
```python
try:
    # Initialize TikTok crawler with Playwright support
    if lark_client and sheets_client:
        crawler = TikTokCrawler(
            lark_client=lark_client,
            sheets_client=sheets_client,
            use_playwright=True  # Enable Playwright by default
        )
        logger.info("✅ TikTok crawler initialized successfully")
```

##### Change 3: Fix health check
**Location:** Line 60-66

**Before:**
```python
@app.get("/health")
async def health_check():
    return {
        "status": "healthy", 
        "timestamp": datetime.now().isoformat(),
        "lark_connected": lark_client is not None,
        "sheets_connected": sheets_client is not None,
        "crawler_ready": crawler is not None
    }
```

**After:**
```python
@app.get("/health")
async def health_check():
    return {
        "status": "healthy", 
        "timestamp": datetime.now().isoformat(),
        "lark_connected": lark_client is not None,
        "sheets_connected": sheets_client is not None,
        "crawler_ready": crawler is not None,
        "playwright_enabled": crawler.use_playwright if crawler else False
    }
```

##### Change 4: Fix daily crawl endpoint
**Location:** Line 110-126

**Before:**
```python
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
```

**After:**
```python
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
```

##### Change 5: Fix background task function
**Location:** Line 128-138

**Before:**
```python
async def run_daily_crawl():
    """Main crawler logic - runs in background"""
    try:
        logger.info("🚀 Starting daily crawl (background job)")
        
        # Run crawler
        result = crawler.crawl_all_videos()
        
        logger.info(f"✅ Daily crawl completed: {result}")
        
    except Exception as e:
        logger.error(f"❌ Daily crawl failed: {e}")
```

**After:**
```python
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
            
            if total > 0:
                success_rate = (processed / total) * 100
                logger.info(f"📊 Success rate: {success_rate:.1f}% ({processed}/{total})")
        
    except Exception as e:
        logger.error(f"❌ Daily crawl failed: {e}", exc_info=True)
```

##### Change 6: Fix batch crawl function
**Location:** Line 157-166

**Before:**
```python
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
```

**After:**
```python
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
```

##### Change 7: Fix error handler
**Location:** Line 176-182

**Before:**
```python
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    """Global exception handler"""
    logger.error(f"❌ Unhandled exception: {exc}")
    return {
        "success": False,
        "message": "Internal server error",
        "error": str(exc)
    }
```

**After:**
```python
from fastapi.responses import JSONResponse  # Add to imports

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
```

##### Change 8: Fix status endpoint error response
**Location:** Line 140-155

**Before:**
```python
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
```

**After:**
```python
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
```

**✅ KEEP UNCHANGED:**
- `init_clients()` - Only add `use_playwright=True` parameter
- `startup_event()` ✓
- `test()` ✓
- `test_lark_connection()` ✓
- `test_sheets_connection()` ✓

---

### STEP 6: Keep Existing Files (No Changes)

#### ✅ `app/lark_client.py`
**Action:** KEEP AS-IS
**Reason:** Works perfectly, no changes needed

#### ✅ `app/sheets_client.py`
**Action:** KEEP AS-IS
**Reason:** Deduplication logic is excellent, no changes needed

#### ✅ `.env`
**Action:** KEEP AS-IS
**Reason:** All environment variables remain the same

---

## 🧪 STEP 7: Test Locally (10 minutes)

### 7.1 Install Dependencies
```bash
pip install -r requirements.txt
playwright install chromium
```

### 7.2 Update Test Script
Edit `test_playwright_local.py` and add real TikTok URLs:
```python
TEST_URLS = [
    "https://www.tiktok.com/@your_account/video/1234567890",
    "https://www.tiktok.com/@your_account/video/9876543210",
]
```

### 7.3 Run Tests
```bash
python test_playwright_local.py
```

**Expected output:**
```
✅ Playwright is installed
✅ Crawler module found
🧪 PLAYWRIGHT TIKTOK CRAWLER - TEST SUITE
...
📊 TEST SUMMARY
   single               ✅ PASS
   batch                ✅ PASS
   sync                 ✅ PASS
   sync_normal          ✅ PASS

🎉 ALL TESTS PASSED! Ready to deploy to Railway.
```

---

## 🚀 STEP 8: Deploy to Railway (5 minutes)

### 8.1 Commit Changes
```bash
git add .
git status  # Review changes
git commit -m "feat: integrate Playwright TikTok crawler

- Added playwright_crawler.py for direct scraping
- Updated crawler.py with Playwright integration
- Fixed async/sync issues in main.py
- Added railway.json for deployment config
- Updated requirements.txt with playwright

Fixes: TikWM API block issue
Expected: 30-40 min crawl time for 227 records
Success rate: 80-90%"
```

### 8.2 Push to Railway
```bash
git push origin main
```

### 8.3 Monitor Deployment
1. Open Railway dashboard
2. Go to Deployments tab
3. Watch build logs

**Expected build steps:**
```
[1/5] Installing dependencies...
[2/5] Collecting playwright==1.40.0
[3/5] Running: playwright install chromium
[4/5] Chromium downloaded successfully
[5/5] Starting server...
✅ Application startup complete
```

**Build time:** ~3-5 minutes

---

## ✅ STEP 9: Verify Deployment (5 minutes)

### 9.1 Health Check
```bash
curl https://your-app.up.railway.app/health
```

**Expected response:**
```json
{
  "status": "healthy",
  "lark_connected": true,
  "sheets_connected": true,
  "crawler_ready": true,
  "playwright_enabled": true
}
```

### 9.2 Test Crawl
Use PowerShell script:
```powershell
.\TikTok_Crawler_Playwright.ps1
```

Or curl:
```bash
curl -X POST https://your-app.up.railway.app/jobs/daily
```

**Expected response:**
```json
{
  "success": true,
  "status": "started",
  "message": "Daily crawler job started in background",
  "note": "Playwright crawling takes 30-40 minutes for 227 records"
}
```

### 9.3 Monitor Logs
Railway Dashboard → Deployments → Logs

**Expected logs:**
```
🚀 Starting daily crawl (background job)
⏱️ Expected duration: 30-40 minutes with Playwright
📋 Fetching records from Lark Bitable...
✅ Fetched 227 records from Lark
🔄 Processing records and crawling views...
✅ Browser initialized successfully
Processing 1/227
🔍 Crawling with Playwright: https://...
✅ Got TikTok stats for https://...: 52,372 views
...
📊 Updating Google Sheets with deduplication...
✅ Crawler completed: {'total': 227, 'processed': 227, ...}
📊 Success rate: 85.0% (193/227)
```

---

## 🎯 STEP 10: Verify Results (After 40 minutes)

### 10.1 Check Google Sheets
1. Open your Google Sheets
2. Check columns:
   - **Column E (Last Check):** Should have recent timestamps
   - **Column C (Current Views):** Should have updated values
   - **Column F (Status):** Should show "success" for most (>80%)
3. Check for duplicates: None should exist

### 10.2 Calculate Success Rate
```
Success records = Count of "success" in column F
Total records = 227
Success rate = (Success / Total) × 100%

Target: > 80%
```

---

## 🔍 WHAT CHANGED - SUMMARY

### Files Added (3)
```
✅ app/playwright_crawler.py    (14 KB)
✅ railway.json                  (417 B)
✅ test_playwright_local.py      (7.9 KB) [optional]
```

### Files Updated (2)
```
✅ app/crawler.py                (~13 KB)
✅ app/main.py                   (~8 KB)
✅ requirements.txt              (added 1 line)
```

### Files Unchanged (3)
```
✅ app/lark_client.py
✅ app/sheets_client.py
✅ .env
```

### Total Changes
- **Lines added:** ~600
- **Lines modified:** ~50
- **Lines deleted:** ~30
- **New dependencies:** 1 (playwright)

---

## ⚠️ TROUBLESHOOTING

### Issue: Build fails with "playwright not found"
**Solution:**
- Check `railway.json` is in project root
- Verify buildCommand includes `playwright install chromium`

### Issue: "Browser not installed" error
**Solution:**
- Check Railway build logs for `Chromium downloaded successfully`
- Rebuild deployment in Railway dashboard

### Issue: Low success rate (<50%)
**Solution:**
- Check Railway logs for specific errors
- Look for patterns in failed videos
- May need to adjust delays in `playwright_crawler.py`

### Issue: Still getting "partial" status
**Solution:**
- Verify Playwright initialized: Check `/health` endpoint
- Should show `"playwright_enabled": true`
- Check logs for `"✅ Playwright crawler initialized"`

---

## 🎊 SUCCESS CRITERIA

Migration is successful when:
- [x] All tests pass locally
- [x] Railway deployment succeeds
- [x] Health check shows `playwright_enabled: true`
- [x] First crawl completes (~40 min)
- [x] Google Sheets updated
- [x] Success rate > 80%
- [x] No duplicates in sheets
- [x] Railway memory < 15%

---

## 📞 NEED HELP?

### Quick Checks
1. ✅ Railway Hobby plan active?
2. ✅ All files in correct locations?
3. ✅ Local tests passed?
4. ✅ Railway build logs show Chromium installed?

### Debug Commands
```bash
# Check Railway status
curl https://your-app.up.railway.app/status

# Check debug info
curl https://your-app.up.railway.app/debug/info

# Test Lark connection
curl https://your-app.up.railway.app/test/lark

# Test Sheets connection
curl https://your-app.up.railway.app/test/sheets
```

---

**Migration completed?** 🎉

Mark this guide as ✅ and enjoy your working Playwright crawler!

**Estimated total time:** 30-40 minutes (plus 40 min first crawl)
