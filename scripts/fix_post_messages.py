import sys
import os
import io
import time
import logging

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("fix_post_messages")

from database.db import get_db
from database.models import Post
from etl.pancake_client import PancakeClient

def run_fix():
    db = next(get_db())
    client = PancakeClient()
    page_id = '514400205095512'

    logger.info(f"Đang lấy danh sách bài viết chuẩn từ Pancake API cho Page {page_id}...")
    api_posts = client.get_posts(page_id, days_back=180, limit=300)
    logger.info(f"Đã lấy {len(api_posts)} bài viết từ Pancake API.")

    api_post_map = {}
    for p in api_posts:
        pid = p.get('post_id')
        msg = (p.get('message') or '').strip()
        if pid and msg:
            api_post_map[pid] = msg

    logger.info(f"Có {len(api_post_map)} bài viết có nội dung caption thật từ Pancake API.")

    db_posts = db.query(Post).filter(Post.platform == 'facebook').all()
    logger.info(f"Có {len(db_posts)} bài viết trong database.")

    updated_count = 0
    cleared_count = 0

    known_comment_snippets = {
        '.', '..', '...', 'ib', 'Ib', 'IB', 'inbox', 'Inbox',
        'e xin giá khó học với ah', 'Cho xin file', 'Cho e xin promt vs ạ',
        'Mình nhé', 'Có support mua tk ko b', 'Em xin khóa hoc', 'Em xin file ạ',
        'Mình xin file ạ.', 'Quan tâm', 'Đăng ký lớp học ở đâu?'
    }

    for p in db_posts:
        real_msg = api_post_map.get(p.post_id)
        if real_msg:
            if p.message != real_msg:
                p.message = real_msg
                updated_count += 1
        else:
            # Nếu không tìm thấy trong API mà nội dung lại là comment rác của khách
            current_msg = (p.message or '').strip()
            is_from_comment = isinstance(p.payload, dict) and p.payload.get('from_comments')
            if current_msg in known_comment_snippets or (is_from_comment and len(current_msg) < 30 and ('xin' in current_msg.lower() or 'ib' in current_msg.lower() or current_msg == '.')):
                p.message = None
                cleared_count += 1

    db.commit()
    logger.info(f"HOÀN TẤT: Đã cập nhật {updated_count} bài viết với caption thật từ Pancake API. Đã xóa {cleared_count} bình luận rác.")

    # Xóa cache backend
    try:
        from backend.facebook_metrics import _FB_CACHE, _FB_CACHE_LOCK
        with _FB_CACHE_LOCK:
            _FB_CACHE.clear()
        logger.info("Đã xóa cache _FB_CACHE thành công!")
    except Exception as e:
        logger.warning(f"Không thể xóa cache memory: {e}")

if __name__ == '__main__':
    run_fix()
