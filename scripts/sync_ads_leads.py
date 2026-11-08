"""Script quét và đồng bộ thông tin Facebook Ads (ad_id, post_id) từ Pancake API vào database."""
import os
import sys
import time
import io
import logging
from typing import List, Dict, Any, Optional
from dotenv import load_dotenv

load_dotenv(".env.local")
load_dotenv(".env")

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from database.db import SessionLocal
from database.models import RawConversation, FactLeadActivity, DimLead, Post
from database.schema import ensure_schema
from etl.pancake_client import PancakeClient
from etl.utils import resolve_canonical_page_name, build_post_url

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

FB_PAGE_IDS = [
    "514400205095512",      # Anh Kế toán làm Data (Facebook)
    "629476615535063343",   # Eztech Phân Tích Dữ Liệu
]

def sync_ads_for_page(client: PancakeClient, page_id: str, max_convs: int = 2000):
    ptoken, pid, pname = client._get_page_access_token(page_id)
    if not ptoken:
        logger.warning(f"Không có token cho page {page_id}")
        return

    logger.info(f"=== Bắt đầu quét Ads cho Page: {pname} (ID: {pid}) ===")
    
    url = f"https://pages.fm/api/public_api/v2/pages/{pid}/conversations"
    all_ads_convs = []
    last_id = None
    scanned = 0
    
    while scanned < max_convs:
        params = {
            "page_access_token": ptoken,
            "page_size": 100,
        }
        if last_id:
            params["last_conversation_id"] = last_id
            
        try:
            resp = client.session.get(url, params=params, timeout=20)
            if resp.status_code != 200:
                logger.error(f"HTTP {resp.status_code}: {resp.text[:200]}")
                break
            data = resp.json()
            convs = data.get("conversations", [])
            if not convs:
                break
            
            scanned += len(convs)
            for c in convs:
                c_ads = c.get("ads") or []
                c_ad_ids = c.get("ad_ids") or []
                if c_ads or c_ad_ids:
                    # Lấy ad_id và post_id
                    ad_id = None
                    ad_post_id = None
                    for ad in c_ads:
                        if isinstance(ad, dict):
                            if ad.get("ad_id"):
                                ad_id = str(ad["ad_id"]).strip()
                            if ad.get("post_id"):
                                ad_post_id = str(ad["post_id"]).strip()
                            if ad_id:
                                break
                    if not ad_id and c_ad_ids:
                        ad_id = str(c_ad_ids[0]).strip()
                    
                    all_ads_convs.append({
                        "id": str(c.get("id")),
                        "customer_id": str(c.get("customer_id") or ""),
                        "ad_id": ad_id,
                        "post_id": ad_post_id or c.get("post_id"),
                        "raw_ads": c_ads,
                        "raw_ad_ids": c_ad_ids
                    })
                    
            new_last = convs[-1].get("id")
            if new_last == last_id:
                break
            last_id = new_last
            time.sleep(0.15)
        except Exception as e:
            logger.error(f"Lỗi khi cào page {page_id}: {e}")
            break

    logger.info(f"Đã duyệt {scanned} hội thoại, phát hiện {len(all_ads_convs)} hội thoại từ Ads ({len(all_ads_convs)/max(1, scanned)*100:.1f}%)")

    if not all_ads_convs:
        return

    # Cập nhật database
    db = SessionLocal()
    try:
        updated_acts = 0
        updated_leads = 0
        updated_raws = 0

        # Map conversation_id -> ad info
        ad_map = {item["id"]: item for item in all_ads_convs}
        conv_ids = list(ad_map.keys())
        
        # Batch query 300 IDs
        for i in range(0, len(conv_ids), 300):
            batch_ids = conv_ids[i:i+300]
            
            # 1. FactLeadActivity
            acts = db.query(FactLeadActivity).filter(FactLeadActivity.conversation_id.in_(batch_ids)).all()
            for act in acts:
                info = ad_map.get(act.conversation_id)
                if info:
                    if info["ad_id"] and act.ad_id != info["ad_id"]:
                        act.ad_id = info["ad_id"]
                        updated_acts += 1
                    if info["post_id"] and not act.post_id:
                        act.post_id = info["post_id"]
                        act.post_url = build_post_url(info["post_id"], page_id=pid)
                        
            # 2. RawConversation
            raws = db.query(RawConversation).filter(RawConversation.pancake_id.in_(batch_ids)).all()
            for raw in raws:
                info = ad_map.get(raw.pancake_id)
                if info and raw.payload:
                    payload = dict(raw.payload)
                    payload["ads"] = info["raw_ads"]
                    payload["ad_ids"] = info["raw_ad_ids"]
                    if info["post_id"]:
                        payload["post_id"] = info["post_id"]
                    raw.payload = payload
                    updated_raws += 1

            # 3. DimLead
            batch_cust_ids = [ad_map[cid]["customer_id"] for cid in batch_ids if ad_map[cid].get("customer_id")]
            leads = db.query(DimLead).filter(DimLead.customer_id.in_(batch_cust_ids)).all()
            for lead in leads:
                # Find matching ad info
                for item in all_ads_convs:
                    if item["customer_id"] == lead.customer_id:
                        if item["ad_id"] and not lead.ad_id:
                            lead.ad_id = item["ad_id"]
                            updated_leads += 1
                        if item["post_id"] and not lead.post_id:
                            lead.post_id = item["post_id"]
                            lead.post_url = build_post_url(item["post_id"], page_id=pid)
                        break

            db.commit()

        logger.info(f"Hoàn thành lưu DB: {updated_acts} activities, {updated_leads} leads, {updated_raws} raw conversations đã được gắn Ad ID!")
    except Exception as e:
        db.rollback()
        logger.error(f"Lỗi khi lưu DB: {e}")
    finally:
        db.close()


def main():
    ensure_schema()
    client = PancakeClient()
    for pid in FB_PAGE_IDS:
        sync_ads_for_page(client, pid, max_convs=2000)

if __name__ == "__main__":
    main()
