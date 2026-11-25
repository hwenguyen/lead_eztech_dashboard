# Project Lessons & Rules

> Living record of project conventions, architecture decisions, and hard-learned bug fixes.

## 1. Project Conventions & Stack
- **Stack & Environment**: Python backend ([backend/ai_rag.py](file:///c:/Users/Admin/OneDrive/Documents/GitHub/lead_eztech_dashboard/backend/ai_rag.py)) with Gemini API, Neon Postgres (`knowledge_chunks`), and `.venv\Scripts\python.exe`.
- **Key Commands**:
  - Unit tests: `.\.venv\Scripts\python.exe tests\test_ai_rag.py` (uses SQLite mock).
  - RAG re-ingest to Neon Postgres: chunk with `split_text_into_chunks`, embed with `embed_texts`, and batch-insert into `knowledge_chunks` via Neon HTTP SQL API (`https://<host>/sql`).

## 2. Architectural Decisions
- **AI Sale Temperature & Script Structure ([backend/ai_rag.py](file:///c:/Users/Admin/OneDrive/Documents/GitHub/lead_eztech_dashboard/backend/ai_rag.py), [RAG/TAI_LIEU_RAG_AI_SALE.md](file:///c:/Users/Admin/OneDrive/Documents/GitHub/lead_eztech_dashboard/RAG/TAI_LIEU_RAG_AI_SALE.md))**:
  - `sale` assistant uses `temperature=0.65` (others use `0.25`) so it can adapt industry-specific raw-data tasks naturally while keeping the verbatim `Kịch bản chuyên sâu` templates intact.
  - Conversation flow order: **Step 1** (ask Excel vs accounting software) -> **Step 2A** (Excel / MISA-FAST branches) -> **Industry/Field Step (`SAU STEP 1 & STEP 2A`)** (2 verbatim paragraphs: Power Query with industry-specific raw-data tasks + Excel/Power BI automated management report) -> **Step 2B** / **Step 3** / **Step 4**.
  - Always re-ingest `RAG/TAI_LIEU_RAG_AI_SALE.md` into Neon Postgres `knowledge_chunks` (`category = 'sale'`) after editing the RAG document so retrieval stays in sync with `system_prompt`.

## 3. Bugs & Gotchas (Lessons Learned)
- **Windows Application Control blocks `_psycopg` DLL locally**
  - **Cause**: Direct Postgres driver connections via `psycopg` fail on this Windows machine.
  - **Fix**: Verify code locally with `tests/test_ai_rag.py` (SQLite mock) and use Neon HTTP SQL API (`https://<host>/sql` with `Neon-Connection-String` header) with a single multi-row `INSERT` for fast RAG re-ingestion.
  - **Rule**: Do not rely on direct `psycopg` connections from local Windows scripts; use the Neon HTTP SQL API.
- **Git rebase `--continue` editor failure in PowerShell**
  - **Cause**: `git -c core.editor=true rebase --continue` failed with `there was a problem with the editor 'false'`.
  - **Fix**: Run `git commit --no-edit; git rebase --continue` after staging resolved conflict files.
- **PowerShell `python -c` quoting breaks SQL strings**
  - **Cause**: PowerShell interprets nested quotes/identifiers inside `python -c "..."`.
  - **Fix**: Pipe a single-quoted here-string (`@' ... '@ | .\.venv\Scripts\python.exe -`) instead.
- **Neon Sleep & Egress Protection for Background Workers (Bulletin & Zalo Reminders)**
  - **Cause**: Polling or exact-time workers waking up every minute will keep Neon Postgres awake 24/7, burning through the 100 CU-hours free quota rapidly.
  - **Architecture**:
    - **Fail-closed Cron & Worker**: Cron endpoint (`/api/bulletin/cron/trigger-notifications`) requires an exact bearer token / secret (`CRON_SECRET`), returning 403 on blank or mismatched tokens to avoid waking the DB via malicious bots.
    - **Exact Reminder Worker**: Only queries DB when active reminders exist, uses `INNER JOIN dim_staff` filtering exclusively for users with a mapped `zalo_conversation_id`, and stops scanning when no pending items remain. Failed sends back off by 15 minutes with a strict 2-attempt retry cap (`exact_retry_count < 2`).
    - **Group Message Sync Separation**: Bulletin sync (`pzl_g_...`) extracts messages from group chats for designated bosses (`Ann`, `TRẦN HÀ TUẤN ANH`, `Hiền Minhh`), collapsing consecutive boss messages within a 3-minute window into a single post (`merged_message_ids`), completely isolating group chat data from `dim_leads` and `fact_lead_activities`.

