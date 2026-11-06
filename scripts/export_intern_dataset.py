import os
import sys
import time

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# Thêm thư mục gốc vào sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from database.db import engine

OUTPUT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data_for_interns"))
os.makedirs(OUTPUT_DIR, exist_ok=True)

QUERIES = {
    # 1. Bảng Lead và Lịch sử Hoạt động (Có conversation_id để JOIN sang chat & bot)
    "leads_activities.csv": r"""
        SELECT 
            l.customer_id,
            a.conversation_id,
            l.name AS customer_name,
            -- Che SĐT bảo mật: 0983665679 -> 0983***679
            CASE 
                WHEN l.phone_number IS NOT NULL AND LENGTH(l.phone_number) >= 8 
                THEN LEFT(l.phone_number, 4) || '***' || RIGHT(l.phone_number, 3)
                ELSE NULL 
            END AS phone_masked,
            CASE 
                WHEN l.phone_number IS NOT NULL AND TRIM(l.phone_number) != '' THEN 1 
                ELSE 0 
            END AS has_phone,
            l.page_id,
            l.first_created_at,
            l.phone_at,
            a.status_tag,
            a.assigned_users,
            a.message_count,
            a.is_contacted,
            a.contacted_at,
            a.contacted_dates
        FROM dim_leads l
        LEFT JOIN fact_lead_activities a ON l.id = a.lead_id
        ORDER BY l.first_created_at DESC
    """,

    # 2. Bảng Bài viết & Video Mạng xã hội (TikTok, Facebook)
    "social_posts.csv": r"""
        SELECT 
            post_id,
            platform,
            page_name,
            type,
            regexp_replace(COALESCE(message, ''), E'[\r\n\t]+', ' ', 'g') AS clean_message,
            like_count,
            comment_count,
            share_count,
            view_count,
            phone_number_count,
            inserted_at
        FROM posts
        ORDER BY inserted_at DESC
    """,

    # 3. Bảng Bình luận Mạng xã hội (Comments - có post_id để JOIN sang posts)
    "social_comments.csv": r"""
        SELECT 
            comment_id,
            post_id,
            page_name,
            customer_name,
            CASE 
                WHEN phone_number IS NOT NULL AND LENGTH(phone_number) >= 8 
                THEN LEFT(phone_number, 4) || '***' || RIGHT(phone_number, 3)
                ELSE NULL 
            END AS phone_masked,
            regexp_replace(COALESCE(message, ''), E'[\r\n\t]+', ' ', 'g') AS clean_message,
            tags,
            assigned_users,
            inserted_at
        FROM comments
        ORDER BY inserted_at DESC
    """,

    # 4. Bảng Lịch sử Bot rep tự động (có conversation_id để JOIN sang chat & leads)
    "bot_auto_replies.csv": r"""
        SELECT 
            conversation_id,
            customer_id,
            page_id,
            case_id,
            regexp_replace(COALESCE(customer_message, ''), E'[\r\n\t]+', ' ', 'g') AS customer_message,
            regexp_replace(COALESCE(reply_message, ''), E'[\r\n\t]+', ' ', 'g') AS reply_message,
            sent_at,
            status
        FROM bot_auto_replies
        ORDER BY sent_at DESC
    """,

    # 5. Tin nhắn Chat (Lọc sạch HTML và loại bỏ tin nhắn rỗng)
    "chat_messages_sample.csv": r"""
        WITH unnested_msgs AS (
            SELECT 
                r.pancake_id AS conversation_id,
                r.page_id,
                m->>'role' AS sender_role,
                m->>'inserted_at' AS sent_at,
                regexp_replace(regexp_replace(m->>'message', '<[^>]+>', '', 'g'), E'[\r\n\t]+', ' ', 'g') AS clean_text
            FROM raw_conversations r
            CROSS JOIN LATERAL json_array_elements((r.payload->'messages')::json) AS m
            WHERE r.payload->'messages' IS NOT NULL 
              AND json_typeof((r.payload->'messages')::json) = 'array'
              AND m->>'message' IS NOT NULL 
            ORDER BY r.created_at DESC
        )
        SELECT 
            conversation_id,
            page_id,
            sender_role,
            sent_at,
            clean_text AS message_text
        FROM unnested_msgs
        WHERE clean_text IS NOT NULL AND TRIM(clean_text) != ''
        LIMIT 20000
    """
}

def export_all():
    if engine.dialect.name != "postgresql":
        print("[LOI] Chua cau hinh DATABASE_URL tro toi Neon Postgres!")
        sys.exit(1)

    print("==================================================================")
    print("XUAT DU LIEU SACH CHO INTERN (DA TOI UU KHOA NGOAI & LOC EMPTY TEXT)")
    print("==================================================================")
    
    total_bytes = 0
    t0 = time.time()
    
    conn = engine.raw_connection()
    try:
        cursor = conn.cursor()
        for filename, sql in QUERIES.items():
            filepath = os.path.join(OUTPUT_DIR, filename)
            copy_sql = f"COPY ({sql.strip().rstrip(';')}) TO STDOUT WITH CSV HEADER"
            
            print(f"-> Dang xuat: {filename} ...", end=" ", flush=True)
            t_start = time.time()
            
            with open(filepath, "w", encoding="utf-8-sig") as f:
                cursor.copy_expert(copy_sql, f)
                
            f_size = os.path.getsize(filepath)
            total_bytes += f_size
            f_kb = f_size / 1024
            duration = time.time() - t_start
            
            print(f"OK! ({f_kb:.1f} KB, mat {duration:.2f}s)")
            
    finally:
        conn.close()

    total_mb = total_bytes / (1024 * 1024)
    total_time = time.time() - t0
    print("==================================================================")
    print(f"HOAN TAT! Tong Egress: {total_mb:.2f} MB trong {total_time:.2f}s")
    print("==================================================================")

if __name__ == "__main__":
    export_all()
