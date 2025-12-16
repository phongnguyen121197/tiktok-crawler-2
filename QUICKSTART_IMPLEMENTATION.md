# ⚡ QUICK START - IMPLEMENT PUBLISHED DATE

## 🎯 3 BƯỚC ĐƠN GIẢN

---

## BƯỚC 1: REPLACE FILES (2 phút)

**Copy 3 files mới vào project của bạn:**

```bash
# Navigate to your project
cd D:\tiktok-crawler-local\app

# Backup old files (optional)
copy playwright_crawler.py playwright_crawler.py.backup
copy crawler.py crawler.py.backup
copy sheets_client.py sheets_client.py.backup

# Replace with new files from Downloads
# Copy these 3 files from Downloads to app folder:
# - playwright_crawler.py
# - crawler.py  
# - sheets_client.py
```

**Files KHÔNG CẦN thay đổi:**
- ✅ lark_client.py (keep as is)
- ✅ main.py (keep as is)
- ✅ __init__.py (keep as is)

---

## BƯỚC 2: UPDATE GOOGLE SHEETS (1 phút)

### Option A: Manual (Recommended)

1. Open your Google Sheet
2. Right-click on column E header
3. Click "Insert 1 column left"
4. Type header: **"Published Date"**
5. Done!

### Option B: Let it auto-create

- Just run the code
- First row will be wrong
- Manually fix header to "Published Date"

**Final structure:**
```
A: Record ID
B: Link TikTok
C: Current Views
D: 24h Baseline
E: Published Date  ← NEW!
F: Last Check
G: Status
```

---

## BƯỚC 3: TEST (5 phút)

### Test locally:

```bash
# 1. Start server
python -m app.main

# 2. Trigger crawl (in new terminal)
curl -X POST http://localhost:8000/jobs/daily

# 3. Watch logs
# Should see:
#   📅 Attempting to extract publish date...
#   📅 Found publish date in...
#   ✅ Success: 150,000 views, Published: 2025-10-15
```

### Verify results:

**Check Google Sheets:**
```
✅ Column E has "Published Date" header
✅ Rows have dates like "2025-10-15"
✅ Some might be empty (that's OK if extraction failed)
```

**Check logs:**
```
✅ Logs show "Published: 2025-XX-XX" or "Published: N/A"
✅ No Python errors
✅ Crawl completes successfully
```

---

## ✅ SUCCESS CHECKLIST

```
□ Replaced 3 files (playwright_crawler.py, crawler.py, sheets_client.py)
□ Kept 3 files unchanged (lark_client.py, main.py, __init__.py)
□ Added "Published Date" column to Google Sheets (column E)
□ Restarted server successfully
□ Triggered test crawl
□ Logs show "📅 Attempting to extract publish date..."
□ Google Sheets has Published Date data
□ No errors in logs
```

**All checked? Done! 🎉**

---

## 🚨 QUICK FIXES

### Server won't start

```bash
# Check if all files in place
ls -la app/

# Check for syntax errors
python -m py_compile app/playwright_crawler.py
python -m py_compile app/crawler.py
python -m py_compile app/sheets_client.py
```

### "Column E out of range" error

```bash
# Manually add column to Google Sheets
# OR delete all data and let it recreate
```

### "Published Date always N/A"

```bash
# That's OK! Extraction might fail for some videos
# As long as some videos have dates, it's working
# TikTok HTML changes frequently
```

---

## 📊 EXPECTED RESULTS

### Logs:
```
📅 Attempting to extract publish date...
📅 Found publish date in JSON-LD: 2025-10-15
✅ Success: 150,000 views, Published: 2025-10-15
```

### Google Sheets:
```
| Record ID | Link TikTok | Views  | Baseline | Published Date | Last Check | Status  |
|-----------|-------------|--------|----------|----------------|------------|---------|
| recxxx    | tiktok.com..| 150000 | 140000   | 2025-10-15     | 2025-10-27 | success |
| recyyy    | tiktok.com..| 230000 | 220000   | 2025-10-10     | 2025-10-27 | success |
| reczzz    | tiktok.com..| 89000  | 85000    |                | 2025-10-27 | partial |
```

**Note:** Some dates might be empty - that's normal if extraction failed!

---

## 🎁 BONUS

### See which videos are recent:
```python
# Videos from last 7 days
recent = [v for v in videos if v.age_days <= 7]
```

### Calculate growth:
```python
# Views per day
growth = views / age_days if age_days > 0 else 0
```

### Find viral videos:
```python
# Recent + high views = viral
if age_days < 7 and views > 100000:
    print("🔥 VIRAL!")
```

---

## 📞 NEED HELP?

**Check:**
1. SUMMARY_CHANGES_PUBLISH_DATE.md - Full details
2. Logs in terminal - Error messages
3. Google Sheets - Data structure

**Still stuck?**
- Share error message
- Share logs
- Share screenshot

---

## ⏱️ TIME ESTIMATE

```
Replace files:   2 min
Update Sheets:   1 min
Test:            5 min
────────────────────
TOTAL:           8 min
```

**Ready? Let's go! 🚀**
