# ⚡ QUICK START - PLAYWRIGHT CRAWLER

## 🎯 3 Bước Deploy Nhanh

### 1️⃣ Test Local (5 phút)

```bash
# Install
pip install -r requirements.txt
playwright install chromium

# Update TEST_URLS trong test_playwright_local.py với TikTok URLs thật

# Run test
python test_playwright_local.py
```

✅ **Kết quả mong đợi:** All tests PASS

---

### 2️⃣ Deploy to Railway (5 phút)

```bash
# Copy files vào project:
# - app/playwright_crawler.py (NEW)
# - app/crawler.py (UPDATED)
# - requirements.txt (UPDATED)
# - railway.json (NEW)

git add .
git commit -m "feat: add Playwright crawler"
git push origin main
```

⏳ Railway sẽ auto-build (~3-5 phút)

---

### 3️⃣ Trigger Crawl (1 phút)

**Option A - PowerShell:**
```powershell
.\TikTok_Crawler_Fixed.ps1
```

**Option B - Curl:**
```bash
curl -X POST https://your-app.up.railway.app/jobs/daily
```

⏳ **Crawl time:** 30-40 phút cho 227 videos

---

## 🔍 Check Results

1. **Logs:** Railway Dashboard → Deployments → View Logs
2. **Data:** Mở Google Sheets
3. **Health:** `curl https://your-app.up.railway.app/health`

---

## ⚠️ Common Issues

| Issue | Solution |
|-------|----------|
| Build fails | Check `railway.json` có buildCommand đúng |
| "Browser not installed" | Verify build logs có `playwright install chromium` |
| Timeout | Hobby plan có 60min timeout, OK cho 227 videos |
| Low success rate | TikTok rate limiting, tăng delay trong code |

---

## 📊 Success Metrics

- ✅ Success rate: > 80%
- ✅ Time: 30-40 minutes
- ✅ No duplicates in Google Sheets
- ✅ Status column shows "success" (not "partial")

---

## 🎯 What's Different from API Version?

| Feature | API Version | Playwright Version |
|---------|-------------|-------------------|
| Cost | $10-50/month | $5/month (Railway only) |
| Speed per video | ~0.5s | ~7-10s |
| Total time (227) | 2-3 min | 30-40 min |
| Reliability | Depends on API | Direct scraping |
| Rate limiting | API limits | TikTok rate limits |
| Maintenance | Easy | Medium |

---

## 💡 Tips

1. **Chạy vào lúc ít traffic:** 2-4 AM để tránh rate limit
2. **Monitor logs:** Để catch issues sớm
3. **Keep retry logic:** 3 retries per video is good
4. **Check Google Sheets:** Sau mỗi crawl để verify

---

## 🚨 Emergency Rollback

Nếu có vấn đề, rollback ngay:

```bash
git revert HEAD
git push origin main
```

Railway sẽ deploy version cũ (~2 phút)

---

Xem `DEPLOY_GUIDE.md` để biết chi tiết đầy đủ.
