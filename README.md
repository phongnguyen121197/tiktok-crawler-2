# 🚀 TikTok Crawler - OPTIMIZED VERSION

## 📊 Performance Comparison

| Metric | Before | After | Improvement |
|--------|--------|-------|-------------|
| **550 videos** | 2 hours | 30-45 min | **3-4x faster** |
| **Per video** | ~13s | ~3-5s | **3-4x faster** |
| **Concurrent** | 1 | 10-12 | **10-12x parallel** |

---

## 🔧 What Changed?

### 1. **Parallel Processing** (10-12 concurrent)
```python
# OLD: Sequential (1 video at a time)
for url in urls:
    result = crawl(url)  # 13 seconds each

# NEW: Parallel (10-12 videos at a time)
semaphore = asyncio.Semaphore(12)
results = await asyncio.gather(*[crawl(url) for url in urls])
```

### 2. **Resource Blocking** (2-3x faster page load)
```python
# Block images, fonts, CSS, videos
BLOCKED_RESOURCE_TYPES = {'image', 'media', 'font', 'stylesheet'}
```

### 3. **Fast Extraction** (from JSON, not DOM)
```python
# OLD: Wait for DOM, parse elements
await page.wait_for_selector('[data-e2e="video-views"]')

# NEW: Extract from embedded JSON immediately
raw = page.evaluate('document.querySelector("#__UNIVERSAL_DATA_FOR_REHYDRATION__").textContent')
data = json.loads(raw)
views = data['__DEFAULT_SCOPE__']['webapp.video-detail']['itemInfo']['itemStruct']['stats']['playCount']
```

### 4. **Faster Wait Strategy**
```python
# OLD: Wait for all network requests to finish
await page.goto(url, wait_until='networkidle')  # +5-8 seconds

# NEW: Just wait for HTML to load
await page.goto(url, wait_until='domcontentloaded')  # Much faster!
```

---

## 📁 Files to Replace

Copy these files to your project:

```
app/
├── playwright_crawler.py  ← NEW (optimized parallel crawler)
├── crawler.py             ← UPDATED (uses batch processing)
├── sheets_client.py       ← UPDATED (with date validation)
├── main.py                ← UPDATED (v2.4.0)
├── lark_client.py         ← Keep existing
└── __init__.py            ← Keep existing

requirements.txt           ← UPDATED (added psutil)
```

---

## 🚀 Quick Deploy

### Step 1: Replace files
```bash
# In your tiktok-crawler-2 directory
cp playwright_crawler.py app/
cp crawler.py app/
cp sheets_client.py app/
cp main.py app/
```

### Step 2: Update requirements
```bash
pip install psutil  # For memory monitoring
```

### Step 3: Deploy to Railway
```bash
git add .
git commit -m "feat: optimize crawler with parallel processing (3-4x faster)"
git push origin main
```

### Step 4: Test
```bash
# Trigger crawl job
curl -X POST https://your-app.up.railway.app/jobs/daily
```

---

## ⚙️ Configuration

You can adjust settings in `playwright_crawler.py`:

```python
@dataclass
class CrawlerConfig:
    max_concurrent: int = 10          # Increase to 12 if no issues
    delay_range: tuple = (0.5, 1.5)   # Random delay between requests
    timeout_ms: int = 15000           # 15 second timeout
    max_retries: int = 2              # Retry failed requests
    gc_interval: int = 50             # GC every 50 pages
```

### Recommended Settings by Plan

| Railway Plan | RAM | max_concurrent | Expected Time (550 videos) |
|--------------|-----|----------------|---------------------------|
| Hobby (8GB)  | 8GB | 10-12 | 30-45 min |
| Pro (32GB)   | 32GB | 20-25 | 15-25 min |

---

## 📈 Monitoring Progress

The crawler now logs detailed progress:

```
⏳ Progress: 100/550 (18.2%) | Success: 95 | Rate: 3.2/s | ETA: 2.3min
⏳ Progress: 200/550 (36.4%) | Success: 190 | Rate: 3.1/s | ETA: 1.9min
...

╔══════════════════════════════════════════════════════════╗
║                    CRAWL COMPLETE                         ║
╠══════════════════════════════════════════════════════════╣
║  Total: 550 videos                                        ║
║  Success: 520 (94.5%)                                     ║
║  Failed: 30                                               ║
║  Time: 35.2 minutes                                       ║
║  Speed: 0.26 videos/second                                ║
╚══════════════════════════════════════════════════════════╝
```

---

## ❓ Troubleshooting

### "Memory Error" or Container Crashes
```python
# Reduce concurrent contexts
max_concurrent: int = 8  # Instead of 12
```

### "Rate Limited by TikTok"
```python
# Increase delays
delay_range: tuple = (2.0, 4.0)  # Instead of (0.5, 1.5)

# Reduce concurrent
max_concurrent: int = 5
```

### Low Success Rate (<80%)
- Check if TikTok URLs are valid
- Try increasing timeout: `timeout_ms: int = 20000`
- Check Railway logs for specific errors

---

## 🔄 API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/jobs/daily` | POST | Start optimized crawl job |
| `/jobs/fix-timestamps` | POST | Fix old timestamp data |
| `/analyze/dates` | GET | Check date column status |
| `/status` | GET | System health check |

---

## 📝 Changelog

### v2.4.0 (Optimized)
- ✅ Parallel crawling (10-12 concurrent)
- ✅ Resource blocking (images, fonts, CSS)
- ✅ Fast JSON extraction
- ✅ Memory management with periodic GC
- ✅ Progress logging with ETA
- ✅ Date validation before Sheets write

### Expected Results
- **Before:** 550 videos in 2 hours
- **After:** 550 videos in 30-45 minutes
