# 🚀 HƯỚNG DẪN DEPLOY PLAYWRIGHT CRAWLER LÊN RAILWAY

## 📋 CHECKLIST TRƯỚC KHI DEPLOY

- [ ] Railway Hobby Plan đã active ($5/month)
- [ ] Git repository đã setup
- [ ] Đã test local thành công
- [ ] Environment variables đã config trong Railway

---

## 🧪 STEP 1: TEST LOCAL (BẮT BUỘC)

### 1.1 Cài đặt dependencies

```bash
# Cài đặt Python packages
pip install -r requirements.txt

# Cài đặt Playwright browsers
playwright install chromium
```

### 1.2 Update test URLs

Mở file `test_playwright_local.py` và sửa TEST_URLS:

```python
TEST_URLS = [
    "https://www.tiktok.com/@your_account/video/1234567890",  # URL thật
    "https://www.tiktok.com/@your_account/video/9876543210",  # URL thật
]
```

### 1.3 Chạy test

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

**Nếu test FAIL:**
- Check internet connection
- Verify TikTok URLs are public and valid
- Try with different TikTok videos
- Check if TikTok is blocking your IP

---

## 📤 STEP 2: DEPLOY LÊN RAILWAY

### 2.1 Update code trong project

Copy các file sau vào project của bạn:

```
project_root/
├── app/
│   ├── playwright_crawler.py     ← FILE MỚI
│   ├── crawler.py                ← ĐÃ UPDATE
│   ├── main.py                   (giữ nguyên)
│   ├── lark_client.py            (giữ nguyên)
│   └── sheets_client.py          (giữ nguyên)
├── requirements.txt              ← ĐÃ UPDATE
├── railway.json                  ← FILE MỚI
└── test_playwright_local.py      ← FILE MỚI (optional)
```

### 2.2 Commit và push

```bash
git add .
git commit -m "feat: integrate Playwright crawler for TikTok scraping"
git push origin main
```

### 2.3 Railway sẽ tự động deploy

Railway sẽ:
1. Detect changes
2. Run build command: `pip install -r requirements.txt && playwright install chromium`
3. Start server: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`

**Build time:** ~3-5 phút (vì phải install Chromium browser)

### 2.4 Check deployment logs

Trong Railway dashboard:
1. Click vào service
2. Mở tab "Deployments"
3. Click vào deployment mới nhất
4. Xem logs

**Expected logs:**
```
✅ Playwright installed successfully
✅ Chromium browser installed
✅ Starting uvicorn server...
✅ Application startup complete
```

---

## 🧪 STEP 3: TEST PRODUCTION

### 3.1 Health check

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
  "timestamp": "2025-10-17T10:30:00"
}
```

### 3.2 Test với sample crawl

Option A: Dùng PowerShell script
```powershell
.\TikTok_Crawler_Fixed.ps1
```

Option B: Dùng curl
```bash
curl -X POST https://your-app.up.railway.app/jobs/daily
```

**Expected response:**
```json
{
  "success": true,
  "status": "started",
  "message": "Daily crawler job started in background",
  "timestamp": "2025-10-17T10:30:00"
}
```

### 3.3 Monitor logs trong Railway

Mở Railway dashboard → Deployments → View Logs

**Expected logs:**
```
🚀 Starting full crawl job...
📥 Fetching records from Lark Bitable...
📊 Found 227 records in Lark
⚙️ Processing records...
✅ Browser initialized successfully
🔍 Crawling with Playwright: https://tiktok.com/...
✅ Got 52,372 views for https://tiktok.com/...
📤 Updating Google Sheets with deduplication...
✅ Sheets update complete: 227 updated, 0 inserted, 0 duplicates removed
🎉 Crawl job complete
```

**Time estimate:** 30-40 phút cho 227 videos

---

## ⚠️ TROUBLESHOOTING

### Issue 1: Build fails với "playwright not found"

**Solution:** Check `railway.json` có đúng buildCommand:
```json
"buildCommand": "pip install -r requirements.txt && playwright install chromium"
```

### Issue 2: "Browser not installed" error

**Solution:** Railway đã install Chromium chưa? Check build logs:
```
playwright install chromium
```

### Issue 3: Memory limit exceeded

**Check:** Railway plan
- Free tier: 512MB (KHÔNG ĐỦ)
- Hobby tier: 8GB (CẦN)

**Solution:** Upgrade to Hobby plan trong Railway dashboard

### Issue 4: Job timeout sau 30 phút

**Current status:** Railway Hobby có timeout ~60 phút cho background jobs, nên 30-40 phút crawl là OK.

Nếu vẫn timeout:
- Tăng timeout trong `railway.json`:
```json
"healthcheckTimeout": 600
```

### Issue 5: Crawl chậm hoặc fail nhiều

**Possible causes:**
- TikTok rate limiting
- Network issues
- Videos không public

**Solution:**
- Tăng delay giữa requests trong `playwright_crawler.py`:
```python
await asyncio.sleep(3)  # Từ 2s lên 3s
```

- Tăng max_retries:
```python
self.max_retries = 5  # Từ 3 lên 5
```

### Issue 6: "Failed to extract views" cho nhiều videos

**Check:**
1. Videos có public không?
2. TikTok có đổi HTML structure không?
3. IP của Railway có bị block không?

**Debug:**
- Xem logs để biết selector nào fail
- Test với different TikTok accounts
- Add more selector strategies trong `_extract_stats_from_page()`

---

## 📊 MONITORING & MAINTENANCE

### Daily checks

```bash
# Check health
curl https://your-app.up.railway.app/health

# Check system status
curl https://your-app.up.railway.app/status
```

### View crawl results

1. Mở Google Sheets
2. Check timestamp column
3. Verify views được update
4. Check status column (success vs partial)

### Success metrics

Monitor trong Railway logs:
- **Success rate:** Nên > 80% videos crawl thành công
- **Time:** 227 videos trong 30-40 phút
- **Errors:** < 20% fail rate

---

## 🔄 ROLLBACK PLAN

Nếu Playwright có vấn đề, rollback về API crawler:

### Option 1: Quick fix trong code

Trong `app/crawler.py`, đổi:
```python
self.use_playwright = False  # Disable Playwright
```

### Option 2: Revert commit

```bash
git revert HEAD
git push origin main
```

Railway sẽ tự động deploy version cũ.

---

## 📈 OPTIMIZATION TIPS

### 1. Parallel crawling (nếu cần nhanh hơn)

Hiện tại: Sequential (1 video at a time)
Future: Parallel (5-10 videos cùng lúc)

**Trade-off:**
- ✅ Nhanh hơn 5-10x
- ❌ Tốn RAM nhiều hơn
- ❌ Dễ bị rate limit

### 2. Caching

Cache view count trong Redis hoặc SQLite:
- Nếu crawl trong 1 giờ: dùng cached data
- Giảm load lên TikTok
- Tăng tốc độ

### 3. Smart retry

Thay vì retry ngay:
- Exponential backoff: 2s → 4s → 8s
- Skip video nếu fail 3 lần
- Retry list vào cuối job

---

## ✅ DEPLOYMENT COMPLETE CHECKLIST

- [ ] Local tests passed
- [ ] Code pushed to Git
- [ ] Railway deployed successfully
- [ ] Health check returns 200 OK
- [ ] Test crawl completed
- [ ] Google Sheets updated correctly
- [ ] No duplicates in sheets
- [ ] Logs show expected behavior
- [ ] Success rate > 80%
- [ ] Time < 45 minutes for 227 videos

---

## 🎯 NEXT STEPS (OPTIONAL)

1. **Setup scheduled job:**
   - Railway Cron: Chạy daily vào 2:00 AM
   - Hoặc dùng external cron (cron-job.org)

2. **Add monitoring:**
   - Sentry for error tracking
   - Logging service (Papertrail, Logtail)
   - Success/fail rate dashboard

3. **Implement push to Lark:**
   - Update Lark fields từ Google Sheets
   - Bidirectional sync

---

## 📞 SUPPORT

Nếu gặp vấn đề:
1. Check Railway logs
2. Check Google Sheets
3. Test local lại
4. Review this guide
5. Check TikTok status (có bị down không)

Good luck! 🚀
