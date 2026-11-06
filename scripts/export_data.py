import os
import sys

# 1. Thêm dòng này để Python tìm thấy thư mục database:
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from database.db import engine

OUTPUT_FILE = "exported_b2c_leads.csv"

# r"""...""" để bảo toàn ký tự xuống dòng E'\n' của Postgres
SQL_QUERY = r"""
WITH b2c_messages AS (
    SELECT 
        l.customer_id,
        l.name AS customer_name,
        l.phone_number,
        a.status_tag,
        m->>'role' AS sender_role,
        m->>'inserted_at' AS sent_at,
        regexp_replace(m->>'message', '<[^>]+>', '', 'g') AS message_text
    FROM fact_lead_activities a
    JOIN dim_leads l ON a.lead_id = l.id
    JOIN raw_conversations r ON a.conversation_id = r.pancake_id
    CROSS JOIN LATERAL json_array_elements((r.payload->'messages')::json) AS m
    WHERE a.status_tag ILIKE '%B2C%'
      AND r.payload->'messages' IS NOT NULL
      AND json_typeof((r.payload->'messages')::json) = 'array'
      AND m->>'message' IS NOT NULL 
      AND TRIM(m->>'message') != ''
      AND LOWER(m->>'role') NOT IN ('admin')  -- Chỉ lấy tin khách nhắn
)
SELECT 
    customer_name,
    phone_number,
    customer_id,
    status_tag,
    string_agg(
        '[' || COALESCE(sender_role, 'Unknown') || ' ' || COALESCE(sent_at, '') || ']: ' || message_text,
        E'\n' ORDER BY sent_at ASC
    ) AS full_chat_history
FROM b2c_messages
GROUP BY customer_name, phone_number, customer_id, status_tag;
"""

def stream_export():
    if engine.dialect.name != "postgresql":
        print("[LOI] Chua cau hinh DATABASE_URL tro toi Neon Postgres!")
        sys.exit(1)

    copy_sql = f"COPY ({SQL_QUERY.strip().rstrip(';')}) TO STDOUT WITH CSV HEADER"
    
    print("Dang ket noi va stream du lieu tu Neon...")
    
    conn = engine.raw_connection()
    try:
        cursor = conn.cursor()
        with open(OUTPUT_FILE, "w", encoding="utf-8-sig") as f:
            cursor.copy_expert(copy_sql, f)
            
        file_size_kb = os.path.getsize(OUTPUT_FILE) / 1024
        print(f"[OK] Xuat thanh cong vao file: {OUTPUT_FILE}")
        print(f"Dung luong tai ve (Egress thuc te): ~{file_size_kb:.2f} KB")
    finally:
        conn.close()

if __name__ == "__main__":
    stream_export()