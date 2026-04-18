import requests
import time
import logging

logger = logging.getLogger(__name__)

class LarkClient:
    def __init__(self, app_id, app_secret, bitable_app_token, table_id,
                 user_refresh_token: str = None, write_table_id: str = None):
        self.app_id = app_id
        self.app_secret = app_secret
        self.bitable_app_token = bitable_app_token
        self.table_id = table_id          # Source table — read "Link air bài"
        # Target table — write view data. Falls back to table_id if not set.
        self.write_table_id = write_table_id or table_id

        # ── Tenant token (read-only for Bitable in some workspaces) ──────────
        self.tenant_access_token = None
        self.tenant_expire_time = 0

        # ── User token (has edit access if the user owns the Bitable) ────────
        self.user_access_token = None
        self.user_expire_time = 0
        self.user_refresh_token = user_refresh_token  # long-lived, stored in env

        # Bootstrap tokens
        self._refresh_tenant_token()
        # Prefer file-persisted token (newer after rotation) over env var
        self._load_persisted_token()
        if self.user_refresh_token:
            self._refresh_user_token()
            logger.info("✅ User token mode enabled — Bitable writes will use user identity")
        else:
            logger.warning(
                "⚠️  No LARK_USER_REFRESH_TOKEN set. "
                "Bitable writes use tenant token (may be read-only). "
                "Run GET /auth/lark to obtain a user token."
            )

    # ── Tenant token ──────────────────────────────────────────────────────────

    def _refresh_tenant_token(self):
        """Refresh app-level tenant access token."""
        url = "https://open.larksuite.com/open-apis/auth/v3/tenant_access_token/internal"
        try:
            resp = requests.post(url, json={"app_id": self.app_id, "app_secret": self.app_secret}, timeout=10)
            data = resp.json()
            if data.get("code") == 0:
                self.tenant_access_token = data["tenant_access_token"]
                self.tenant_expire_time = time.time() + 5400
                logger.info("✅ Tenant token refreshed")
                return True
            logger.error(f"❌ Tenant token refresh failed: {data}")
        except Exception as e:
            logger.error(f"❌ Tenant token refresh error: {e}")
        return False

    def _get_tenant_token(self):
        if not self.tenant_access_token or time.time() >= self.tenant_expire_time - 300:
            self._refresh_tenant_token()
        return self.tenant_access_token

    # ── User token ────────────────────────────────────────────────────────────

    # Path where rotated refresh token is persisted across restarts
    _TOKEN_FILE = "/tmp/lark_refresh_token.txt"

    def _load_persisted_token(self):
        """On startup, prefer the persisted token file over the env var (it's newer)."""
        try:
            import os as _os
            if _os.path.exists(self._TOKEN_FILE):
                with open(self._TOKEN_FILE, 'r') as f:
                    tok = f.read().strip()
                if tok:
                    logger.info("🔑 Loaded persisted refresh token from file (overrides env var)")
                    self.user_refresh_token = tok
        except Exception as e:
            logger.warning(f"⚠️ Could not load persisted token: {e}")

    def _persist_token(self, refresh_token: str):
        """Save the latest refresh token to disk so restarts don't lose it."""
        try:
            with open(self._TOKEN_FILE, 'w') as f:
                f.write(refresh_token)
            logger.info("💾 Rotated refresh token persisted to file")
        except Exception as e:
            logger.warning(f"⚠️ Could not persist refresh token: {e}")

    def _refresh_user_token(self):
        """Use stored refresh_token to get a new user access_token."""
        if not self.user_refresh_token:
            return False
        url = "https://open.larksuite.com/open-apis/authen/v1/refresh_access_token"
        app_token = self._get_tenant_token()
        try:
            resp = requests.post(
                url,
                json={"grant_type": "refresh_token", "refresh_token": self.user_refresh_token},
                headers={"Authorization": f"Bearer {app_token}"},
                timeout=10,
            )
            data = resp.json()
            if data.get("code") == 0:
                d = data.get("data", {})
                self.user_access_token = d.get("access_token")
                expires_in = int(d.get("expires_in", 7200))
                self.user_expire_time = time.time() + expires_in - 300
                # Lark rotates the refresh token on every use — save the new one
                new_rt = d.get("refresh_token")
                if new_rt and new_rt != self.user_refresh_token:
                    self.user_refresh_token = new_rt
                    self._persist_token(new_rt)
                logger.info("✅ User access token refreshed")
                return True
            logger.error(f"❌ User token refresh failed: {data}")
        except Exception as e:
            logger.error(f"❌ User token refresh error: {e}")
        return False

    def set_user_tokens(self, access_token: str, refresh_token: str, expires_in: int = 7200):
        """Called after OAuth callback to store the freshly-obtained tokens."""
        self.user_access_token = access_token
        self.user_refresh_token = refresh_token
        self.user_expire_time = time.time() + expires_in - 300
        # Persist so the token survives Railway restarts
        if refresh_token:
            self._persist_token(refresh_token)
        logger.info("✅ User tokens set via OAuth callback")

    def _get_user_token(self):
        if not self.user_access_token or time.time() >= self.user_expire_time:
            self._refresh_user_token()
        return self.user_access_token

    def _basic_auth(self) -> str:
        """Base64-encoded app_id:app_secret for Basic auth header."""
        import base64
        creds = f"{self.app_id}:{self.app_secret}"
        return base64.b64encode(creds.encode()).decode()

    def get_oauth_url(self, redirect_uri: str, state: str = "lark_oauth") -> str:
        """Build the Lark OAuth authorization URL."""
        import urllib.parse
        params = {
            "app_id": self.app_id,
            "redirect_uri": redirect_uri,
            "scope": "bitable:app",
            "state": state,
        }
        return "https://open.larksuite.com/open-apis/authen/v1/authorize?" + urllib.parse.urlencode(params)

    def exchange_code_for_tokens(self, code: str) -> dict:
        """Exchange OAuth authorization code for access + refresh tokens."""
        url = "https://open.larksuite.com/open-apis/authen/v1/access_token"
        app_token = self._get_tenant_token()
        try:
            resp = requests.post(
                url,
                json={"grant_type": "authorization_code", "code": code},
                headers={"Authorization": f"Bearer {app_token}"},
                timeout=10,
            )
            data = resp.json()
            if data.get("code") == 0:
                d = data.get("data", {})
                self.set_user_tokens(
                    access_token=d.get("access_token", ""),
                    refresh_token=d.get("refresh_token", ""),
                    expires_in=int(d.get("expires_in", 7200)),
                )
                return {"success": True, "data": d}
            return {"success": False, "error": data}
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ── Unified request helper ─────────────────────────────────────────────────

    def _get_write_token(self):
        """Return user token for writes if available, else tenant token."""
        if self.user_refresh_token or self.user_access_token:
            tok = self._get_user_token()
            if tok:
                return tok
            logger.warning("⚠️ User token unavailable, falling back to tenant token for write")
        return self._get_tenant_token()

    def _refresh_token(self):
        """Legacy alias kept for compatibility."""
        return self._refresh_tenant_token()

    def _get_valid_token(self):
        """Legacy alias — returns tenant token (used for reads)."""
        return self._get_tenant_token()

    def _make_request(self, method, url, **kwargs):
        """Make HTTP request. Reads use tenant token; writes use user token."""
        # Determine which token to use based on HTTP method
        is_write = method.upper() in ('POST', 'PUT', 'PATCH', 'DELETE')
        get_token = self._get_write_token if is_write else self._get_tenant_token

        max_retries = 2
        for attempt in range(max_retries):
            token = get_token()
            if not token:
                logger.error("❌ Failed to get valid token")
                return None

            headers = dict(kwargs.get('headers', {}))
            headers['Authorization'] = f'Bearer {token}'
            kwargs['headers'] = headers

            try:
                response = requests.request(method, url, **kwargs)
                data = response.json()

                if data.get('code') == 99991663:
                    logger.warning(f"⚠️ Token invalid (attempt {attempt+1}), refreshing...")
                    if is_write:
                        self._refresh_user_token()
                    else:
                        self._refresh_tenant_token()
                    if attempt < max_retries - 1:
                        continue
                return response

            except Exception as e:
                logger.error(f"❌ Request error attempt {attempt+1}: {e}")
                if attempt == max_retries - 1:
                    raise
        return None
    
    def _extract_link_value(self, link_field):
        """
        Extract link value from Lark field.
        Handles all formats the Lark API returns for URL/text fields:
          - dict with 'text' key  (rich text)
          - dict with 'link' key  (Lark URL field type 15 — most common)
          - dict with 'href' key  (legacy / some SDK versions)
          - list of dicts          (multi-segment rich text)
          - plain string
        """
        if not link_field:
            return ""

        # ── dict (Lark URL field returns {"text": "...", "link": "..."}) ─────
        if isinstance(link_field, dict):
            # Prioritise 'link' (URL field type 15), then 'text', then 'href'
            link_value = (
                link_field.get("link", "")
                or link_field.get("text", "")
                or link_field.get("href", "")
            )
            return str(link_value).strip()

        # ── list (rich-text array or multiple URL segments) ────────────────
        if isinstance(link_field, list):
            if not link_field:
                return ""
            # Walk all segments and return the first non-empty URL/text found
            for item in link_field:
                if isinstance(item, dict):
                    val = (
                        item.get("link", "")
                        or item.get("text", "")
                        or item.get("href", "")
                    )
                    val = str(val).strip()
                    if val:
                        return val
                else:
                    val = str(item).strip()
                    if val:
                        return val
            return ""

        # ── plain string ───────────────────────────────────────────────────
        if isinstance(link_field, str):
            return link_field.strip()

        return ""

    @staticmethod
    def _normalize_tiktok_url(url: str) -> str:
        """
        Strip query string and fragment from a TikTok URL to get the canonical
        base URL, so source-table URLs (with tracking params) match target-table
        URLs (usually clean).

        Examples:
            https://www.tiktok.com/@user/video/123?is_from_webapp=1&sender_device=pc
            → https://www.tiktok.com/@user/video/123

            https://www.tiktok.com/@user/video/123   (already clean)
            → https://www.tiktok.com/@user/video/123
        """
        if not url:
            return ""
        try:
            from urllib.parse import urlparse, urlunparse
            p = urlparse(url.strip())
            # Keep scheme + netloc + path; drop query (?...) and fragment (#...)
            return urlunparse((p.scheme, p.netloc, p.path.rstrip('/'), '', '', ''))
        except Exception:
            return url.strip()

    def get_target_records_by_url(self) -> dict:
        """
        Read all records from write_table_id (target table) and return
        a {url: record_id} mapping so crawler can find the right record to update.
        The target table has a "Link TikTok" field (fldnv3knkY) that stores the URL.
        """
        api_url = (
            f"https://open.larksuite.com/open-apis/bitable/v1/apps/"
            f"{self.bitable_app_token}/tables/{self.write_table_id}/records"
        )
        result = {}
        page_token = None
        try:
            while True:
                params = {'page_size': 500}
                if page_token:
                    params['page_token'] = page_token
                response = self._make_request('GET', api_url, params=params, timeout=30)
                if not response:
                    break
                data = response.json()
                if data.get('code') != 0:
                    logger.error(f"❌ get_target_records_by_url error: {data}")
                    break
                items = data.get('data', {}).get('items', [])
                for item in items:
                    record_id = item.get('record_id') or item.get('id', '')
                    fields = item.get('fields', {})
                    link_field = fields.get('Link TikTok', '')
                    link_value = self._extract_link_value(link_field)
                    if link_value and record_id:
                        # Store normalized URL as key so source URLs with query
                        # params (?is_from_webapp=1&...) can still match.
                        normalized = self._normalize_tiktok_url(link_value)
                        result[normalized] = record_id
                        # Also keep original in case target table has query params
                        if normalized != link_value:
                            result[link_value] = record_id
                page_token = data.get('data', {}).get('page_token')
                if not page_token:
                    break
            logger.info(f"✅ Target table ({self.write_table_id}): {len(result)} URL→record_id mappings loaded")
            return result
        except Exception as e:
            logger.error(f"❌ get_target_records_by_url exception: {e}")
            return {}

    def get_all_active_records(self):
        """
        Get all records with non-empty "Link air bài" field from Lark Bitable
        Filters out records where link is empty
        """
        url = f"https://open.larksuite.com/open-apis/bitable/v1/apps/{self.bitable_app_token}/tables/{self.table_id}/records"
        
        all_records = []
        page_token = None
        total_processed = 0
        skipped_count = 0
        
        try:
            while True:
                params = {
                    'page_size': 500
                }
                
                if page_token:
                    params['page_token'] = page_token
                
                response = self._make_request('GET', url, params=params, timeout=30)
                
                if not response:
                    break
                
                data = response.json()
                
                if data.get('code') != 0:
                    logger.error(f"❌ Lark API error: {data}")
                    break
                
                items = data.get('data', {}).get('items', [])

                # Filter: Only keep records with non-empty "Link air bài"
                for item in items:
                    total_processed += 1
                    fields = item.get('fields', {})

                    # 🔑 FILTER: Check "Link air bài" field and extract value properly
                    link_field = fields.get("Link air bài", "")
                    link_value = self._extract_link_value(link_field)

                    if not link_value:
                        skipped_count += 1
                        rid = item.get('record_id') or item.get('id', '?')
                        # Log raw field value at WARNING so it appears in Railway logs
                        # (helps diagnose format issues — expected to be empty for truly blank rows)
                        if link_field:
                            logger.warning(
                                f"⚠️ Record {rid}: 'Link air bài' field non-empty but unextractable "
                                f"(type={type(link_field).__name__}, raw={str(link_field)[:120]})"
                            )
                        else:
                            logger.debug(f"⏭️  Skipping record {rid} - 'Link air bài' is blank")
                        continue

                    all_records.append(item)

                # Check for next page
                page_token = data.get('data', {}).get('page_token')
                if not page_token:
                    break

            logger.info(
                f"✅ Lark Bitable Scan: total={total_processed} "
                f"with_link={len(all_records)} skipped_empty={skipped_count}"
            )
            if skipped_count > 0:
                logger.warning(
                    f"⚠️ {skipped_count} records skipped — 'Link air bài' blank or unextractable. "
                    f"Check WARNING lines above for non-empty-but-unextractable cases."
                )
            
            return all_records
            
        except Exception as e:
            logger.error(f"❌ Error getting records: {e}")
            return []
    
    # ─────────────────────────────────────────────────────────────────────────
    # WRITE BACK TO BITABLE
    # ─────────────────────────────────────────────────────────────────────────

    def _date_str_to_ms(self, date_str: str):
        """Convert 'YYYY-MM-DD' to Unix timestamp in milliseconds (UTC midnight)."""
        try:
            from datetime import datetime
            dt = datetime.strptime(str(date_str).strip(), '%Y-%m-%d')
            return int(dt.timestamp() * 1000)
        except Exception:
            return None

    def batch_update_records(self, records: list) -> tuple:
        """
        Batch update records in Lark Bitable with crawled view stats.

        Updates these fields (matching the Bitable column names in the screenshot):
            Lượt xem hiện tại  - new crawled view count
            Số view 24h trước  - previous view count (for delta tracking)
            Published Date     - video publish date (only when newly discovered)
            Lần kiểm tra cuối  - timestamp of this crawl run
            Status             - success / partial / broken

        Args:
            records: list of processed record dicts (from process_lark_record)
        Returns:
            (updated_count, failed_count)
        """
        if not records:
            return (0, 0)

        LARK_BATCH_SIZE = 500   # Lark API hard limit per request
        updated_total = 0
        failed_total = 0
        now_ms = int(time.time() * 1000)

        url = (
            f"https://open.larksuite.com/open-apis/bitable/v1/apps/"
            f"{self.bitable_app_token}/tables/{self.write_table_id}/records/batch_update"
        )

        for i in range(0, len(records), LARK_BATCH_SIZE):
            batch = records[i:i + LARK_BATCH_SIZE]
            update_records = []

            for record in batch:
                record_id = record.get('record_id', '')
                if not record_id:
                    continue

                is_broken = record.get('is_broken', False)
                fields = {
                    'Lần kiểm tra cuối': now_ms,
                    'Status': 'broken' if is_broken else record.get('status', 'partial'),
                }

                if not is_broken:
                    views = record.get('views')
                    baseline = record.get('baseline')

                    if views is not None:
                        fields['Lượt xem hiện tại'] = int(views)
                    if baseline is not None:
                        fields['Số view 24h trước'] = int(baseline)
                    # Write publish date to target table (fldWRnSR35, DateTime type 5)
                    pub_date = record.get('publish_date')
                    if pub_date:
                        pub_ms = self._date_str_to_ms(pub_date)
                        if pub_ms:
                            fields['Published Date'] = pub_ms

                update_records.append({'record_id': record_id, 'fields': fields})

            if not update_records:
                continue

            # Debug: log a sample record_id so we can confirm IDs are non-empty
            sample_id = update_records[0].get('record_id', '')
            if not sample_id:
                logger.warning("⚠️ First record has empty record_id — writes will be skipped by Lark!")
            else:
                logger.debug(f"🔑 Sample record_id for this batch: {sample_id}")

            try:
                response = self._make_request(
                    'POST', url,
                    json={'records': update_records},
                    timeout=30,
                )

                if not response:
                    failed_total += len(update_records)
                    continue

                data = response.json()
                if data.get('code') == 0:
                    updated_records = data.get('data', {}).get('records', [])
                    updated_total += len(updated_records)
                    logger.info(
                        f"✅ Lark: updated {len(updated_records)}/{len(update_records)} records"
                    )
                else:
                    error_code = data.get('code')
                    error_msg = data.get('msg', '')
                    logger.error(
                        f"❌ Lark batch_update error "
                        f"(code={error_code}): {error_msg}"
                    )
                    # Log full response and sample fields for debugging FieldNameNotFound
                    if error_code == 1254045 and update_records:
                        sample_fields = list(update_records[0].get('fields', {}).keys())
                        logger.error(f"   Fields being written: {sample_fields}")
                        logger.error(f"   Full response: {data}")
                    failed_total += len(update_records)

            except Exception as e:
                logger.error(f"❌ Lark batch_update exception: {e}")
                failed_total += len(update_records)

            # Brief pause between large batches to respect rate limits
            if i + LARK_BATCH_SIZE < len(records):
                time.sleep(0.5)

        logger.info(f"📊 Lark write done: {updated_total} updated, {failed_total} failed")
        return (updated_total, failed_total)

    def get_table_fields(self, table_id: str = None) -> list:
        """
        Get all field definitions from the Lark Bitable table.
        Returns list of {field_id, field_name, field_type} dicts.
        Useful for debugging FieldNameNotFound errors.

        Args:
            table_id: override which table to query (default: self.table_id / source table)
        """
        tbl = table_id or self.table_id
        url = (
            f"https://open.larksuite.com/open-apis/bitable/v1/apps/"
            f"{self.bitable_app_token}/tables/{tbl}/fields"
        )
        try:
            response = self._make_request('GET', url, params={'page_size': 100}, timeout=10)
            if not response:
                return []
            data = response.json()
            if data.get('code') == 0:
                items = data.get('data', {}).get('items', [])
                return [
                    {
                        'field_id':   f.get('field_id'),
                        'field_name': f.get('field_name'),
                        'field_type': f.get('type'),
                        # Include full property blob so we can spot formula/lookup indicators
                        'ui_type':    f.get('ui_type'),
                        'property':   f.get('property'),
                        'is_primary': f.get('is_primary'),
                    }
                    for f in items
                ]
            else:
                logger.error(f"❌ get_table_fields error: {data}")
                return []
        except Exception as e:
            logger.error(f"❌ get_table_fields exception: {e}")
            return []

    def get_record(self, record_id, table_id: str = None):
        """Get single record by ID (defaults to write_table_id / target table)"""
        tbl = table_id or self.write_table_id
        url = f"https://open.larksuite.com/open-apis/bitable/v1/apps/{self.bitable_app_token}/tables/{tbl}/records/{record_id}"

        try:
            response = self._make_request('GET', url, timeout=10)

            if not response:
                return {}

            data = response.json()

            if data.get('code') == 0:
                return data.get('data', {}).get('record', {})
            else:
                logger.error(f"❌ Error getting record {record_id}: {data}")
                return {}

        except Exception as e:
            logger.error(f"❌ Exception getting record {record_id}: {e}")
            return {}

    def test_write_record(self, record_id: str, fields: dict) -> dict:
        """
        Write fields using BATCH_UPDATE (same endpoint as production code),
        then read back to verify actual change in Bitable.

        Returns detailed diagnostic including raw API response body.
        """
        # Step 1: Read current values
        before_record = self.get_record(record_id)
        before_fields = before_record.get('fields', {}) if before_record else {}

        # Step 2: Write via batch_update (identical to production path)
        batch_url = (
            f"https://open.larksuite.com/open-apis/bitable/v1/apps/"
            f"{self.bitable_app_token}/tables/{self.write_table_id}/records/batch_update"
        )
        write_payload = {
            'records': [{'record_id': record_id, 'fields': fields}]
        }
        try:
            response = self._make_request('POST', batch_url, json=write_payload, timeout=15)
            if not response:
                return {'success': False, 'error': 'No response from Lark API'}
            api_data = response.json()
        except Exception as e:
            return {'success': False, 'error': str(e)}

        # Extract what Lark says the record looks like after write
        returned_records = api_data.get('data', {}).get('records', [])
        returned_fields = returned_records[0].get('fields', {}) if returned_records else {}

        # Step 3: Read back after a pause to check for caching issues
        time.sleep(3)
        after_record = self.get_record(record_id)
        after_fields = after_record.get('fields', {}) if after_record else {}

        # Step 4: Compare before vs after
        changed = {}
        not_changed = {}
        for field_name, new_val in fields.items():
            before_val = before_fields.get(field_name)
            after_val  = after_fields.get(field_name)
            if str(after_val) != str(before_val):
                changed[field_name] = {'before': before_val, 'after': after_val, 'expected': new_val}
            else:
                not_changed[field_name] = {
                    'before': before_val,
                    'after': after_val,
                    'expected': new_val,
                    # What Lark PUT response says the value is NOW
                    'in_write_response': returned_fields.get(field_name),
                }

        return {
            'success': api_data.get('code') == 0,
            'api_code': api_data.get('code'),
            'api_msg': api_data.get('msg', ''),
            'written_fields': fields,
            # Raw response from Lark (full data section) — key diagnostic
            'lark_raw_response': api_data.get('data', {}),
            'lark_write_response_fields': returned_fields,
            'fields_changed_in_bitable': changed,
            'fields_NOT_changed_in_bitable': not_changed,
            'verdict': (
                '✅ Fields ARE writable' if changed and not not_changed
                else ('⚠️ SOME fields writable' if changed else '❌ Fields are READ-ONLY or write REJECTED')
            ),
        }