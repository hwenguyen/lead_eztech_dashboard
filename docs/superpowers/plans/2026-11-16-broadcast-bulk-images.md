# Broadcast Bulk Image Sending Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enable sending 1 or more images (alone or alongside personalized text) in "Bot Gửi Tin Nhắn Hàng Loạt" via Pancake Public API v1 while respecting all OpenAPI constraints.

**Architecture:** Frontend converts selected image files to base64 payloads inside `BroadcastStartRequest` (avoiding `python-multipart` dependency changes). Backend validates images, caches `upload_contents` IDs per target `api_page_id`, automatically re-uploads on `invalid_upload_fb_attachments_result`, and sends text + image calls separately because `message` and `content_ids` are mutually exclusive.

**Tech Stack:** FastAPI, Pydantic v2, Python `requests`, React + TypeScript + Tailwind CSS + Lucide Icons.

**Spec:** [`PancakeAPIDoc.yaml`](../../../PancakeAPIDoc.yaml) (`/pages/{page_id}/upload_contents` lines 2788–2850, `/pages/{page_id}/conversations/{conversation_id}/messages` lines 680–774 & `InboxMessage` lines 4340–4386).

## Global Constraints

- **No new Python dependencies**: `requirements.txt` has no `python-multipart`; transport images as base64 in JSON `BroadcastStartRequest`.
- **Mutually exclusive fields (`PancakeAPIDoc.yaml#L695`, `#L4352-L4355`)**: `InboxMessage` must NEVER send `message` and `content_ids` in the same request (causes HTTP 500). Text and images must be sent as separate API calls.
- **Platform batch size limits (`PancakeAPIDoc.yaml#L4363-L4374`)**: Max `30` `content_ids` per call for Facebook and `personal_zalo` (`pzl_...`); max `10` for Instagram/Telegram/Chat plugin; max `1` per call for all other platforms (TikTok, Zalo OA, etc.).
- **Per-Page upload & Facebook expiration (`PancakeAPIDoc.yaml#L757-L774`, `#L2788-L2850`)**: `POST /pages/{page_id}/upload_contents` uses `multipart/form-data` (`file`) and `page_access_token` query param, returning `{id, attachment_type, success}`. On `message_code == "invalid_upload_fb_attachments_result"`, clear page cache, re-upload, and retry once.
- **Image bounds**: Accept only `image/jpeg`, `image/png`, `image/gif`, `image/webp`; max `10` images per campaign; max `5 MB` decoded bytes per image (`5 * 1024 * 1024`).

## Review Focus

1. Sending both `message` and `content_ids` triggers HTTP 500 -> verify `PancakeClient.send_message()` omits `"message"` from payload whenever `content_ids` is passed for `reply_inbox`.
2. Multi-page broadcast (`all` / `all_zalo`) sharing one `content_id` across pages fails -> verify backend uploads and caches `content_id`s keyed by `api_page_id`.
3. Facebook `content_id` expiration mid-campaign (`invalid_upload_fb_attachments_result`) -> verify worker invalidates that page's cache, re-uploads, and retries once.
4. Non-Facebook/non-Zalo channels (e.g. TikTok `tt_...`) rejecting >1 `content_id` -> verify chunking splits into single-item requests for other platforms while keeping batch up to 30 for Facebook and `personal_zalo`.
5. Bad inputs (corrupt base64, unsupported MIME, >5MB file, >10 images, or empty `template` with no `images`) -> verify validation rejects upfront with HTTP 400.

---

### Task 1: Pancake Upload & Image Send Support (`PancakeClient`)

**Files:**
- Modify: `etl/pancake_client.py:952-1160`
- Test: `tests/test_pancake_upload_and_send.py`

**Interfaces:**
- Produces:
  - `PancakeClient.upload_content(self, page_id: str, file_bytes: bytes, filename: str, content_type: str = "image/jpeg", conversation_id: Optional[str] = None) -> dict` returning `{"success": bool, "id": str, "attachment_type": str, ...}`
  - `PancakeClient.send_message(self, page_id: str, conversation_id: str, message: Optional[str] = "", action: str = "reply_inbox", **kwargs) -> dict` accepting `content_ids: Optional[List[str]]` and omitting `"message"` when `content_ids` is non-empty.

- [ ] **Step 1: Write failing tests for `upload_content` and mutually exclusive `send_message` payload**

Create `tests/test_pancake_upload_and_send.py` testing:
- `test_upload_content_multipart_success`: mocks `session.post` and `_get_page_access_token` -> asserts URL `/pages/{api_pid}/upload_contents`, `params={"page_access_token": ...}`, `files={"file": (filename, file_bytes, content_type)}`, returns `{"success": True, "id": "cnt_123", "attachment_type": "PHOTO"}`.
- `test_upload_content_token_refresh_and_candidate_fallback`: mocks first response `{"success": False, "error_code": 102}` then retry success -> asserts `force_refresh=True` called.
- `test_send_message_with_content_ids_omits_message`: calls `send_message("123", "conv_1", message="ignored", content_ids=["cnt_1"])` -> asserts JSON payload sent to `session.post` is `{"action": "reply_inbox", "content_ids": ["cnt_1"]}` and `"message"` is NOT in payload.
- `test_send_message_text_only_keeps_message`: calls `send_message("123", "conv_1", message="Hello")` -> asserts `"message": "Hello"` in payload and `"content_ids"` absent.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest tests/test_pancake_upload_and_send.py -v`
Expected: FAIL (`AttributeError: 'PancakeClient' object has no attribute 'upload_content'` and `message` present with `content_ids`).

- [ ] **Step 3: Implement `upload_content()` and update `send_message()` in `etl/pancake_client.py`**

- Add `upload_content(self, page_id: str, file_bytes: bytes, filename: str, content_type: str = "image/jpeg", conversation_id: Optional[str] = None) -> dict`: reuse `_get_page_access_token`, `resolve_api_page_id`, `get_candidate_api_page_ids`, and the same retry/token-refresh loop over `candidate_page_ids` sending `files={"file": (filename, file_bytes, content_type)}` to `https://pages.fm/api/public_api/v1/pages/{cand_pid}/upload_contents` (with 60s timeout).
- Update `send_message(..., message: Optional[str] = "", ...)`: when `action != "reply_comment"` and `kwargs.get("content_ids")` is a non-empty list, construct `payload = {"action": action or "reply_inbox", "content_ids": kwargs["content_ids"]}` (omit `"message"` and don't double-insert `"message"` if `None`). Preserve `data.get("message_code")` in the returned error dict so callers can detect `"invalid_upload_fb_attachments_result"`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest tests/test_pancake_upload_and_send.py -v`
Expected: PASS (4 tests OK).

- [ ] **Step 5: Commit**

```bash
git add etl/pancake_client.py tests/test_pancake_upload_and_send.py
git commit -m "feat(pancake): add upload_content and mutually-exclusive content_ids support in send_message"
```

---

### Task 2: Broadcast Image Schema, Per-Page Upload Cache, Chunking & Worker Execution

**Files:**
- Modify: `backend/broadcast.py:283-315` (`BroadcastStartRequest` + `BroadcastImagePayload`), `backend/broadcast.py:730-945` (`_run_broadcast_worker`), `backend/broadcast.py:1293-1344` (`start_broadcast`)
- Test: `tests/test_broadcast_filters.py`

**Interfaces:**
- Consumes: `PancakeClient.upload_content`, `PancakeClient.send_message(content_ids=...)`
- Produces:
  - `BroadcastImagePayload(BaseModel)`: `filename: str`, `content_type: str`, `data_base64: str`
  - `decode_broadcast_images(images: List[BroadcastImagePayload]) -> List[Dict[str, Any]]`: validates count `<= 10`, allowed MIME (`image/jpeg`, `image/png`, `image/gif`, `image/webp`), strips `data:...;base64,` prefix, decodes base64, enforces `<= 5 * 1024 * 1024` bytes per image; raises `ValueError` on invalid input.
  - Updated `BroadcastStartRequest`: `template: str = ""`, `images: List[BroadcastImagePayload] = Field(default_factory=list)`, `send_mode: str = "text_then_images"` (valid values: `"text_then_images"`, `"images_then_text"`, `"images_only"`).
  - Helper `_get_max_content_ids_for_channel(api_page_id: str, conversation_id: str, is_zalo: bool) -> int` (returns `30` for Facebook & `personal_zalo` `pzl_`, `1` for TikTok `tt_` / other)
  - Helper `_send_images_with_auto_reupload(...) -> Dict[str, Any]` handling per-page upload caching + chunking + 1-time cache invalidation & retry when `"invalid_upload_fb_attachments_result"` occurs.

- [ ] **Step 1: Write failing tests in `tests/test_broadcast_filters.py`**

Add tests pinning:
- `test_broadcast_image_payload_validation`: valid PNG/JPEG base64 passes (including `data:image/png;base64,...` stripping) via `decode_broadcast_images`; invalid MIME (`application/pdf`), corrupt base64, >5MB decoded size, and >10 images raise `ValueError`.
- `test_start_broadcast_empty_template_requires_images`: `start_broadcast` rejects `template=""` when `images=[]` (HTTP 400), and accepts `template=""` when valid `images` are provided.
- `test_channel_content_id_batch_limits`: `_get_max_content_ids_for_channel` returns `30` for Facebook (`fb_123` / `514400205095512`) and personal Zalo (`pzl_123`), `1` for TikTok (`tt_7196...`) and unknown channels.
- `test_send_images_caches_per_page_and_reuploads_on_fb_expiry`: mocks `PancakeClient`; verifies page A uploads once for 2 consecutive recipients on page A, page B uploads separately for page B, and when recipient returns `{"success": False, "message_code": "invalid_upload_fb_attachments_result"}`, worker re-uploads to get fresh IDs and succeeds on retry.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python tests/test_broadcast_filters.py`
Expected: FAIL (`ImportError` / missing classes & helpers).

- [ ] **Step 3: Implement schemas, validation, and worker image delivery in `backend/broadcast.py`**

- Add `BroadcastImagePayload` and `decode_broadcast_images()` validating allowed MIME (`image/jpeg`, `image/png`, `image/gif`, `image/webp`), valid base64, `<= 5 MB` per file, and `<= 10` images.
- Update `BroadcastStartRequest` with `template: str = ""`, `images: List[BroadcastImagePayload] = []`, `send_mode: str = "text_then_images"` (normalize invalid `send_mode` to `"text_then_images"`).
- Update `start_broadcast()`: allow empty `template` iff `len(req.images) > 0`; fail fast with HTTP 400 if both empty, or if `req.send_mode == "images_only"` and `not req.images`, or if base64/MIME validation fails (pre-validate before spawning thread). Strip `"data:...;base64,"` safely, keep raw/base64 lightweight in `req_dict`.
- In `_run_broadcast_worker`:
  - Determine per-recipient steps from `send_mode` and whether `template.strip()` / `decoded_images` are non-empty.
  - Maintain `uploaded_cache: Dict[str, List[str]] = {}` keyed by `api_page_id`.
  - Use `_send_images_with_auto_reupload`: uploads missing pages via `client.upload_content`, chunks `content_ids` by `_get_max_content_ids_for_channel`, sends each chunk via `client.send_message(..., content_ids=chunk)`. If `res.get("message_code") == "invalid_upload_fb_attachments_result"` (or in `res.get("message", "")`), pop `uploaded_cache[api_page_id]`, re-upload once, and retry the chunk.
  - Between text and image calls for the same customer (and between chunks), wait `random.uniform(1.0, 2.0)` seconds via `_sleep_with_cancel_check`. If `is_zalo`, count Zalo sends toward `zalo_sent_count` appropriately (or keep `zalo_sent_count += 1` per customer while warning user in UI that text+image = 2 API calls).
  - Log combined `reply_message` (e.g., `f"{personalized_msg}\n[Đính kèm {len(decoded_images)} ảnh: ...]"` or `f"[Chỉ gửi {len(decoded_images)} ảnh: ...]"`), and handle `dry_run=True` without calling APIs.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python tests/test_broadcast_filters.py` and `python -m unittest tests/test_pancake_upload_and_send.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/broadcast.py tests/test_broadcast_filters.py
git commit -m "feat(broadcast): support multi-image upload cache, auto-reupload, and text/image send modes"
```

---

### Task 3: Frontend Multi-Image Picker, Send Mode UI & Live Preview

**Files:**
- Modify: `frontend-react/src/services/api.ts:440-466`
- Modify: `frontend-react/src/components/BulkMessengerDashboard.tsx:1-30, 88-105, 438-486, 515-527, 1390-1490, 2105-2185`

**Interfaces:**
- Consumes: `BroadcastStartParams` updated with `images?: BroadcastImageItem[]` and `send_mode?: 'text_then_images' | 'images_then_text' | 'images_only'`
- Produces: UI allowing users to select/remove up to 10 images (with preview thumbnails + size check <= 5MB/image), choose send mode (`text_then_images`, `images_then_text`, `images_only`), preview combined text + images in "Xem trước hiển thị thực tế", and see image summary + Zalo double-request warning in the Confirm Modal.

- [ ] **Step 1: Update TypeScript types in `frontend-react/src/services/api.ts`**

Add `BroadcastImageItem` (`filename: string; content_type: string; data_base64: string`) and optional fields `images?: BroadcastImageItem[]; send_mode?: 'text_then_images' | 'images_then_text' | 'images_only';` to `BroadcastStartParams`.

- [ ] **Step 2: Add image state, file reader, send mode selector & Live Preview in `BulkMessengerDashboard.tsx`**

- Import `Image as ImageIcon` from `lucide-react`.
- Add `attachedImages` state (`Array<{ id: string; filename: string; content_type: string; sizeBytes: number; data_base64: string; previewUrl: string }>`) and `sendMode` state (`'text_then_images' | 'images_then_text' | 'images_only'`, default `'text_then_images'`).
- File input handler (`accept="image/jpeg,image/png,image/gif,image/webp"` `multiple`): enforce max 10 images total and max 5MB/file with clear `alert(...)`; read files via `FileReader.readAsDataURL`, extract base64 payload.
- Below `<textarea>` in section 3 ("3. Soạn nội dung tin nhắn"):
  - Add compact "Đính kèm hình ảnh (tùy chọn - tối đa 10 ảnh, ≤ 5MB/ảnh)" drop/upload button, thumbnail grid with `×` remove buttons and file size badges.
  - When `attachedImages.length > 0`, show `sendMode` radio/pill selector: `Gửi chữ trước → ảnh sau`, `Gửi ảnh trước → chữ sau`, `Chỉ gửi ảnh (không kèm chữ)` (when `images_only`, disable or dim template textarea slightly with note).
  - Show inline note citing Pancake rule: *"Pancake gửi chữ và ảnh thành 2 tin nhắn riêng biệt; nếu gửi Zalo cá nhân hãy cân nhắc tăng giãn cách"*.
- Update `Live Preview` box: render image thumbnails above or below `sampleRenderedText` matching `sendMode` (hide text bubble if `images_only`).
- Update `handleStartBroadcast` & `ConfirmModal`: validate either non-empty `template` (unless `images_only`) or `attachedImages.length > 0`; pass `images` & `send_mode` to `startBroadcast()`; show attached image count and send mode in Confirm Modal; allow user to clear images easily.

- [ ] **Step 3: Verify TypeScript compilation and Vite production build**

Run: `cd frontend-react && npm run build`
Expected: `tsc && vite build` exits with code 0 and zero TypeScript errors.

- [ ] **Step 4: Commit**

```bash
git add frontend-react/src/services/api.ts frontend-react/src/components/BulkMessengerDashboard.tsx
git commit -m "feat(ui): add multi-image attachment, send mode selector, and preview to BulkMessengerDashboard"
```

---

### Task 4: Final Integration Check, Docs & Push

**Files:**
- Modify: `CLAUDE.md` (add concise session note)

- [ ] **Step 1: Run full relevant test suite and frontend build**

Run:
- `python -m unittest tests/test_pancake_upload_and_send.py -v`
- `python tests/test_broadcast_filters.py`
- `python tests/test_auto_reply_course_filter.py`
- `npm --prefix frontend-react run build`
Expected: All unit tests pass and Vite build exits 0.

- [ ] **Step 2: Update `CLAUDE.md` session log and check `git diff --stat`**

Document the new bulk image sending endpoints, mutual-exclusivity handling, and UI options in `CLAUDE.md`. Run `git status` to ensure no stray temporary files are staged.

- [ ] **Step 3: Commit & push**

```bash
git add CLAUDE.md
git commit -m "docs: document broadcast bulk image sending feature"
git push origin main
```

---

## Self-Review Checklist
- Spec coverage: `/upload_contents` (Task 1), `content_ids` mutual exclusion with `message` (Task 1), per-page upload cache & `invalid_upload_fb_attachments_result` retry (Task 2), channel batch limits 30 vs 1 (Task 2), UI image picker + send mode + preview (Task 3), tests & docs (Tasks 1–4).
- Type consistency: `BroadcastImagePayload` (`filename`, `content_type`, `data_base64`) matches `BroadcastImageItem` in `api.ts`; `send_mode` enum values (`text_then_images`, `images_then_text`, `images_only`, `text_only`) align across `BroadcastStartRequest`, `BroadcastStartParams`, and `BulkMessengerDashboard.tsx`.
- Review Focus coverage: All 5 failure modes map directly to assertions in Tasks 1 & 2.
