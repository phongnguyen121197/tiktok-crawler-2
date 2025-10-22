# ✅ DEPLOYMENT CHECKLIST - PLAYWRIGHT CRAWLER

Print this page and check off items as you complete them!

---

## 📋 PRE-DEPLOYMENT CHECKLIST

### Environment Verification
- [ ] Railway Hobby Plan is active ($5/month)
- [ ] Git repository is connected to Railway
- [ ] All environment variables are set in Railway:
  - [ ] `LARK_APP_ID`
  - [ ] `LARK_APP_SECRET`
  - [ ] `LARK_BITABLE_TOKEN`
  - [ ] `LARK_TABLE_ID`
  - [ ] `GOOGLE_APPLICATION_CREDENTIALS_JSON`
  - [ ] `GOOGLE_SHEET_ID`

### Documentation Review
- [ ] Read `QUICK_START.md` (5 min)
- [ ] Skim `DEPLOY_GUIDE.md` (know where to find help)
- [ ] Understand expected timing: 30-40 min per crawl

---

## 🧪 LOCAL TESTING (REQUIRED)

### Setup Local Environment
- [ ] Python 3.9+ installed
- [ ] Install dependencies:
  ```bash
  pip install -r requirements.txt
  ```
- [ ] Install Playwright browsers:
  ```bash
  playwright install chromium
  ```
- [ ] Verify installation:
  ```bash
  playwright --version
  ```

### Prepare Test URLs
- [ ] Open `test_playwright_local.py`
- [ ] Replace `TEST_URLS` with 2-3 real TikTok video URLs
- [ ] Ensure URLs are public videos (not private)
- [ ] Save file

### Run Tests
- [ ] Run test script:
  ```bash
  python test_playwright_local.py
  ```
- [ ] All 4 tests pass ✅
- [ ] Single video crawl works
- [ ] Batch crawl works
- [ ] Sync wrapper works
- [ ] No errors in output

**If tests fail:**
- [ ] Check internet connection
- [ ] Verify TikTok URLs are valid
- [ ] Try different network (mobile hotspot?)
- [ ] Check if Chromium installed correctly

---

## 📦 FILE PREPARATION

### Copy Files to Project
- [ ] `app/playwright_crawler.py` → Copy to project `app/` folder
- [ ] `app/crawler.py` → Replace existing file in project
- [ ] `requirements.txt` → Replace existing file in root
- [ ] `railway.json` → Copy to project root (new file)
- [ ] `TikTok_Crawler_Playwright.ps1` → Copy to project root

### Verify File Structure
```
your-project/
├── app/
│   ├── __init__.py
│   ├── main.py
│   ├── lark_client.py
│   ├── sheets_client.py
│   ├── crawler.py              ← UPDATED
│   └── playwright_crawler.py    ← NEW
├── requirements.txt             ← UPDATED
├── railway.json                 ← NEW
├── .env
└── TikTok_Crawler_Playwright.ps1 ← NEW
```

- [ ] All files are in correct locations
- [ ] No missing files
- [ ] File names are correct (case-sensitive!)

---

## 🚀 DEPLOYMENT TO RAILWAY

### Git Commit & Push
- [ ] Stage all changes:
  ```bash
  git add .
  ```
- [ ] Commit with clear message:
  ```bash
  git commit -m "feat: integrate Playwright TikTok crawler"
  ```
- [ ] Push to main branch:
  ```bash
  git push origin main
  ```
- [ ] Git push successful (no errors)

### Monitor Railway Build
- [ ] Open Railway dashboard
- [ ] Click on your service
- [ ] Go to "Deployments" tab
- [ ] Click on latest deployment
- [ ] Watch build logs

**Build should show:**
- [ ] `Installing dependencies...`
- [ ] `Collecting playwright==1.40.0`
- [ ] `playwright install chromium`
- [ ] `Chromium... downloaded`
- [ ] `Starting server...`
- [ ] `Application startup complete`

**Expected build time:** 3-5 minutes

**If build fails:**
- [ ] Check Railway logs for error message
- [ ] Verify `railway.json` is in root folder
- [ ] Verify `requirements.txt` includes `playwright==1.40.0`
- [ ] Check Railway Hobby plan is active

---

## ✅ POST-DEPLOYMENT VERIFICATION

### Health Check
- [ ] Wait for deployment to complete
- [ ] Note down Railway URL: `https://________.up.railway.app`
- [ ] Test health endpoint:
  ```bash
  curl https://your-app.up.railway.app/health
  ```
- [ ] Response shows:
  - [ ] `"status": "healthy"`
  - [ ] `"lark_connected": true`
  - [ ] `"sheets_connected": true`
  - [ ] `"crawler_ready": true`

**If health check fails:**
- [ ] Check Railway logs
- [ ] Verify environment variables are set
- [ ] Wait 1 minute and retry (service may be starting)

### Test Status Endpoint
- [ ] Test status endpoint:
  ```bash
  curl https://your-app.up.railway.app/status
  ```
- [ ] Response shows all services healthy

---

## 🎯 FIRST CRAWL TEST

### Trigger Test Crawl
- [ ] Choose trigger method:
  
  **Option A - PowerShell (Recommended):**
  - [ ] Double-click `TikTok_Crawler_Playwright.ps1`
  - [ ] Script shows "Service is HEALTHY"
  - [ ] Script shows "Crawl job STARTED successfully"
  
  **Option B - Curl:**
  ```bash
  curl -X POST https://your-app.up.railway.app/jobs/daily
  ```
  - [ ] Response: `"success": true`
  - [ ] Response: `"status": "started"`

### Monitor Progress
- [ ] Start time noted: _______ (current time)
- [ ] Expected completion: _______ (add 40 minutes)
- [ ] Railway logs are streaming
- [ ] See log messages like:
  - [ ] "Starting full crawl job..."
  - [ ] "Found 227 records in Lark"
  - [ ] "Browser initialized successfully"
  - [ ] "Crawling with Playwright: https://..."
  - [ ] "Progress: X/227"

**During 40-minute wait:**
- [ ] ☕ Take a coffee break
- [ ] 📊 Check Railway resource usage (should be < 10% memory)
- [ ] 📝 Periodically check logs for errors

---

## 📊 VERIFY RESULTS

### Check Google Sheets (After ~40 minutes)
- [ ] Open your Google Sheets
- [ ] Check "Last Check Timestamp" column:
  - [ ] All timestamps are recent (within last hour)
  - [ ] Timestamps are consistent
- [ ] Check "Current Views" column:
  - [ ] Values look reasonable
  - [ ] Values are numeric (not blank)
- [ ] Check "Status" column:
  - [ ] Most show "success" (target: >80%)
  - [ ] Some "partial" is OK (<20%)
- [ ] Check for duplicates:
  - [ ] No duplicate Record IDs
  - [ ] Each record appears only once
- [ ] Total row count:
  - [ ] Should be 227 rows (or your record count)

### Check Railway Logs
- [ ] Final log message shows:
  - [ ] "Crawl job complete"
  - [ ] "processed: 227"
  - [ ] "updated: 227"
  - [ ] "failed: X" (should be low, < 20%)
- [ ] No critical errors in logs
- [ ] Success rate is acceptable (>80%)

### Calculate Metrics
```
Success Rate = (227 - failed) / 227 * 100%
Your Success Rate: _______%
```

- [ ] Success rate > 80% ✓
- [ ] Total time was 30-45 minutes ✓
- [ ] No server crashes ✓

---

## 🎉 SUCCESS CRITERIA

All boxes below should be checked for successful deployment:

- [ ] ✅ Local tests passed
- [ ] ✅ Railway build successful
- [ ] ✅ Health check returns healthy
- [ ] ✅ First crawl completed without crashes
- [ ] ✅ Google Sheets updated with new data
- [ ] ✅ Success rate > 80%
- [ ] ✅ No duplicate records in sheets
- [ ] ✅ Time was 30-45 minutes
- [ ] ✅ Railway memory usage < 15%

**If all checked: DEPLOYMENT SUCCESSFUL! 🎉**

---

## 🔧 TROUBLESHOOTING CHECKLIST

### If Build Fails
- [ ] Verify `railway.json` exists in root
- [ ] Check Railway plan is Hobby ($5/month)
- [ ] Review build logs for specific error
- [ ] Ensure `requirements.txt` includes `playwright==1.40.0`
- [ ] Try manual rebuild in Railway

### If Health Check Fails
- [ ] Wait 2 minutes for service to fully start
- [ ] Check Railway logs for startup errors
- [ ] Verify all environment variables are set
- [ ] Test each service individually:
  - [ ] Test Lark: `/test/lark`
  - [ ] Test Sheets: `/test/sheets`

### If Crawl Fails or Low Success Rate
- [ ] Check Railway logs for specific errors
- [ ] Look for patterns in failed videos
- [ ] Verify TikTok URLs are public and valid
- [ ] Check if Railway IP is being rate-limited
- [ ] Consider increasing delays between requests

### If Google Sheets Not Updated
- [ ] Verify Google credentials are correct
- [ ] Check Sheet ID in environment variables
- [ ] Check service account has edit permissions
- [ ] Look for errors in Railway logs mentioning "sheets"

---

## 📝 POST-DEPLOYMENT TASKS

### Documentation
- [ ] Update project README with new Playwright info
- [ ] Document any custom configuration changes
- [ ] Note down any issues encountered and solutions

### Monitoring Setup
- [ ] Set up daily cron job (Railway Cron or external)
- [ ] Configure alerts for failed crawls
- [ ] Set up log monitoring (optional)

### Team Communication
- [ ] Notify team of new deployment
- [ ] Share updated PowerShell script
- [ ] Document new crawl timing (40 min vs 3 min)

---

## 🔄 ONGOING MAINTENANCE

### Daily Checks
- [ ] Verify crawl completed successfully
- [ ] Check success rate in logs
- [ ] Verify Google Sheets updated
- [ ] Check Railway resource usage

### Weekly Checks
- [ ] Review failed videos for patterns
- [ ] Check Railway costs
- [ ] Monitor for TikTok HTML changes
- [ ] Review logs for any new errors

### Monthly Tasks
- [ ] Review overall success rate trends
- [ ] Update Playwright if new version available
- [ ] Optimize delays if needed
- [ ] Consider parallel crawling if approved

---

## 🆘 ROLLBACK PLAN

### If Critical Issues Arise
- [ ] Stop current crawl job (if running)
- [ ] Revert to previous version:
  ```bash
  git revert HEAD
  git push origin main
  ```
- [ ] Wait for Railway to redeploy (~2 min)
- [ ] Verify old version works
- [ ] Investigate issue before re-attempting

---

## 📞 SUPPORT RESOURCES

- [ ] `QUICK_START.md` - Quick reference
- [ ] `DEPLOY_GUIDE.md` - Detailed guide
- [ ] `ARCHITECTURE.md` - System architecture
- [ ] Railway logs - Real-time debugging
- [ ] Railway docs - https://docs.railway.app

---

**Deployment Date:** ___________________
**Deployed By:** ___________________
**Railway URL:** ___________________
**Notes:** 
_________________________________________________
_________________________________________________
_________________________________________________

---

**Status:** ⬜ In Progress | ⬜ Complete | ⬜ Issues Found

**Final Sign-off:** ___________________  Date: ___________

---

🎊 Good luck with your deployment! 🚀
