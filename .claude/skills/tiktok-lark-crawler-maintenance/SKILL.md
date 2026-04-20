---
name: tiktok-lark-crawler-maintenance
description: |
  BAT CU KHI NAO user yeu cau sua loi, debug, hoac them tinh nang cho du an TikTok crawler
  (tiktok-crawler). Su dung skill nay khi: fix bug crawler, check log Railway, debug Lark API,
  cap nhat field mapping, fix loi token, xu ly URL mismatch, check so luong record bi miss.

  Trigger phrases: "code quet thieu", "lark khong cap nhat", "record bi miss", "fix crawler",
  "debug log", "token loi", "push len github", "sua bug", "record khong ghi", "URL khong match",
  "refresh token invalid", "lark_updated thap hon processed", "fix lark", "cap nhat bitable",
  "broken link", "pending retry", "Railway log", "crawl fail", "tiktok url sai".

  Khi nao KHONG dung: tao du an moi, viet content, phan tich du lieu ngoai du an nay.
---

# TikTok Lark Crawler — Maintenance SOP

## Architecture (doc nhanh truoc khi sua)

```
Source table  tbleiRLSCGwgLCUT  →  doc  "Link air bai"  (TikTok URLs)
Target table  tblC6CHtidLuqaDu  →  ghi  view stats      (co field "Link TikTok")
```

- `app/lark_client.py`  — Lark API client: token, doc/ghi record
- `app/crawler.py`      — Logic chinh: lay record, crawl, xu ly, ghi lai
- `app/playwright_crawler.py` — Scrape TikTok bang browser

Deployment: **Railway** (check logs tai Railway dashboard)

## Quy tac bat buoc

> **Sau moi fix duoc user dong y → commit + push GitHub ngay, khong hoi.**

```bash
git add <file da sua>
git commit -m "fix: <mo ta ngan gon>"
git push origin main
```

## Giai thich cac chi so trong log

| Chi so | Y nghia |
|---|---|
| `total` | So record co "Link air bai" (lay tu source table) |
| `crawled` | So URL duoc crawl (da qua date filter) |
| `skipped_old` | Video qua cu (truoc thang truoc) — bi bo qua |
| `processed` | Da crawl thanh cong, co du lieu |
| `lark_updated` | Thuc su ghi duoc vao target table |
| `broken` | Video bi xoa / private |
| `failed` | Loi khi crawl (Playwright crash, timeout) |
| `pending_retry` | Video qua moi, chua co data, retry sau 6h |

## Debug theo trieu chung

### `total` thap hon so record thuc tren Lark

**Nguyen nhan:** `_extract_link_value()` khong doc duoc field "Link air bai"  
**Kiem tra:** Tim WARNING trong log: `'Link air bai' field non-empty but unextractable`  
**File:** `app/lark_client.py` → ham `_extract_link_value()`  
**Lark URL field (type 15) tra ve:** `{"text": "...", "link": "https://..."}` — phai dung key `link`, KHONG phai `href`

### `lark_updated` thap hon `processed`

**Nguyen nhan:** URL trong source table co query params (`?is_from_webapp=1&sender_device=pc&...`) nhung target table luu URL sach  
**Kiem tra:** Tim WARNING: `source URLs have NO matching record in write table`  
**Fix:** Da co `_normalize_tiktok_url()` trong `lark_client.py` va `_normalize_url()` trong `crawler.py` de strip query params truoc khi compare  
**Neu van loi:** Kiem tra xem `get_target_records_by_url()` co dung `_normalize_tiktok_url()` khi build dict khong

### `refresh token invalid` (code 20026)

**Nguyen nhan:** Lark rotate refresh token moi lan dung — token cu da bi consume  
**Fix nhanh:** Chay OAuth flow tai `/auth/lark` de lay token moi, cap nhat `LARK_USER_REFRESH_TOKEN` trong Railway env  
**Luu y:** Code tu dong persist token moi vao `/tmp/lark_refresh_token.txt` sau moi lan refresh thanh cong  
**Fallback:** Khi khong co user token, code tu dung tenant token (chi doc, khong ghi duoc)

### Record cu ghi dung nhung record moi khong ghi

**Nguyen nhan:** `record_id` trong source table KHAC `record_id` trong target table  
**Flow dung:** Source URL → `get_target_records_by_url()` → lay `record_id` cua target table → ghi vao target  
**KHONG** dung record_id tu source table de ghi vao target table

### Date filter loai bao nhieu record

**Logic:** Chi crawl video cua thang nay va thang truoc  
**Neu muon crawl lai video cu:** Xoa "Published Date" trong Lark hoac sua `is_recent_video()` trong `crawler.py`

## Gotchas da biet (cap nhat theo thoi gian)

1. **`link` key, khong phai `href`** — Lark URL field type 15 tra ve `{"text":"...","link":"..."}`. Cu code dung `href` nen miss. Da fix: uu tien `link` → `text` → `href`

2. **URL normalization** — source URLs co `?is_from_webapp=1&sender_device=pc&web_id=...`, target URLs sach. Phai `_normalize_tiktok_url()` ca 2 phia truoc khi compare

3. **Record ID khac nhau** — source table va target table la 2 bang rieng biet. Record ID khong lien quan. Phai build `target_record_by_url` mapping rieng

4. **Refresh token bi consume** — Lark chi cho dung refresh token 1 lan. Khi code chay va refresh, no luu token moi vao `/tmp/lark_refresh_token.txt`. Khi Railway restart file nay mat → phai OAuth lai

5. **Batch size 500** — Lark API gioi han 500 records moi page va 500 records moi batch_update. Code da xu ly pagination

6. **`record_id` vs `id`** — Lark API co the tra ve `record_id` hoac `id` tuy phien ban. Code dung `record.get('record_id') or record.get('id', '')` de xu ly ca 2

## Pattern sua code chuan

```
1. Doc log Railway → xac dinh trieu chung
2. Map trieu chung vao bang debug o tren
3. Doc file lien quan (lark_client.py / crawler.py)
4. Sua bug → test logic bang mat
5. git add + commit + push (khong hoi)
6. Bao user: "Da push, doi chay lai de verify"
```

## Reference files

- `app/lark_client.py` — ham quan trong: `_extract_link_value`, `_normalize_tiktok_url`, `get_all_active_records`, `get_target_records_by_url`, `batch_update_records`
- `app/crawler.py` — ham quan trong: `crawl_all_videos`, `_normalize_url`, `process_lark_record`, `is_recent_video`
