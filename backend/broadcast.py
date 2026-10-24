"""
================================================================================
ROUTER QUẢN LÝ GỬI TIN NHẮN HÀNG LOẠT (BROADCAST / AUTO-MESSENGER)
Hỗ trợ đầy đủ bộ lọc chi tiết (Nội dung, Tên kênh, Tên khách, Nhân viên, Giới tính, Tags)
và Lịch sử chi tiết từng lần chạy Bot.
================================================================================
"""

import os
import time
import random
import logging
import threading
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional, Tuple

from fastapi import APIRouter, Depends, Query, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import or_, desc, func

from database.db import get_db, SessionLocal
from database.models import DimLead, FactLeadActivity, BotAutoReplyLog
from etl.pancake_client import PancakeClient
from etl.utils import (
    VN_TZ,
    is_page_id,
    resolve_canonical_page_name,
    KNOWN_PAGE_NAMES,
    ZALO_PAGE_NAMES,
    build_pancake_url
)

logger = logging.getLogger("BroadcastAPI")

router = APIRouter()

def get_vn_now():
    return datetime.now(VN_TZ).replace(tzinfo=None)

# ==============================================================================
# 1. BỘ SUY LUẬN GIỚI TÍNH TỰ ĐỘNG THEO TÊN TIẾNG VIỆT
# ==============================================================================
FEMALE_KEYWORDS = {
    "thị", "thi", "hương", "huong", "mai", "ngọc", "ngoc", "lan", "hằng", "hang",
    "hà", "ha", "trang", "thảo", "thao", "quỳnh", "quynh", "nhi", "phương", "phuong",
    "linh", "nhung", "yến", "yen", "dung", "hạnh", "hanh", "loan", "trâm", "tram",
    "hiền", "hien", "nga", "tuyết", "tuyet", "hoa", "liên", "lien", "diệu", "dieu",
    "huyền", "huyen", "châu", "chau", "vi", "thủy", "thuy", "nhài", "nhai", "bích",
    "bich", "thoa", "thu", "vân", "van", "uyên", "uyen", "oanh", "mơ", "ly", "vy",
    "hồng", "hong", "thắm", "tham", "mỹ", "my", "khánh", "giang"
}

MALE_KEYWORDS = {
    "văn", "van", "đức", "duc", "minh", "hùng", "hung", "dũng", "dung", "tuấn", "tuan",
    "hoàng", "hoang", "trọng", "trong", "hải", "hai", "long", "quân", "quan", "bảo",
    "bao", "thành", "thanh", "cường", "cuong", "nam", "thắng", "thang", "sơn", "son",
    "tùng", "tung", "phúc", "phuc", "tiến", "tien", "nguyên", "nguyen",
    "trung", "kiên", "kien", "việt", "viet", "quang", "khoa", "trường", "truong", "đăng",
    "dang", "huy", "đạt", "dat", "khôi", "khoi", "bách", "bach", "bình", "binh", "bắc",
    "bac", "chí", "chi", "hiếu", "hieu", "trí", "tri", "lâm", "lam", "thịnh", "thinh"
}

def infer_vietnamese_gender(name: Optional[str]) -> str:
    """
    Suy luận giới tính từ họ và tên tiếng Việt:
    - 'female': Nữ
    - 'male': Nam
    - 'unknown': Chưa rõ
    """
    if not name or not name.strip():
        return "unknown"

    words = [w.lower().strip() for w in name.strip().split() if w.strip()]
    if not words:
        return "unknown"

    # Ưu tiên từ đệm (thường là từ áp chót)
    if len(words) >= 2:
        middle = words[-2]
        if middle in ("thị", "thi"):
            return "female"
        if middle in ("văn", "van"):
            return "male"

    # Kiểm tra tên chính (từ cuối cùng) và các từ còn lại
    last_word = words[-1]
    if last_word in ("hương", "ngọc", "lan", "hằng", "thảo", "quỳnh", "nhi", "linh", "yến", "loan", "trâm", "nga", "tuyết", "hoa"):
        return "female"
    if last_word in ("hùng", "dũng", "tuấn", "cường", "thắng", "sơn", "tùng", "kiên", "đăng", "huy", "đạt", "khôi", "bách"):
        return "male"

    for w in words:
        if w in FEMALE_KEYWORDS and w not in MALE_KEYWORDS:
            return "female"
    for w in words:
        if w in MALE_KEYWORDS and w not in FEMALE_KEYWORDS:
            return "male"

    return "unknown"

def get_gender_title(gender: str) -> Tuple[str, str]:
    """Trả về (Title viết hoa, Title viết thường)."""
    if gender == "male":
        return "Anh", "anh"
    elif gender == "female":
        return "Chị", "chị"
    return "Anh/Chị", "anh/chị"

def render_personalized_template(template: str, recipient: Dict[str, Any]) -> str:
    """Thay thế các biến động vào mẫu tin nhắn."""
    gender = recipient.get("gender") or infer_vietnamese_gender(recipient.get("name"))
    title_cap, title_lower = get_gender_title(gender)

    raw_name = (recipient.get("name") or "").strip()
    cust_name = raw_name if raw_name else title_lower

    msg = template.replace("{name}", cust_name)
    msg = msg.replace("{gender_title}", title_cap)
    msg = msg.replace("{gender_title_lower}", title_lower)
    msg = msg.replace("{phone}", recipient.get("phone_number") or "")
    msg = msg.replace("{customer_id}", str(recipient.get("customer_id") or ""))
    msg = msg.replace("{page_id}", str(recipient.get("page_id") or ""))
    msg = msg.replace("{staff}", str(recipient.get("assigned_users") or "chăm sóc khách hàng"))
    return msg.strip()


# ==============================================================================
# 2. PYDANTIC SCHEMAS CHO SETTINGS VÀ LỊCH SỬ
# ==============================================================================
class BroadcastOptionsResponse(BaseModel):
    pages: List[str]
    zalo_pages: List[str]
    employees: List[str]
    tags: List[str]
    gender_options: List[Dict[str, str]]

class BroadcastPreviewRequest(BaseModel):
    page_id: Optional[str] = None
    name_filter: Optional[str] = None
    employee: Optional[str] = None
    gender: Optional[str] = "all"  # 'all', 'male', 'female', 'unknown'
    tag: Optional[str] = None
    days_ago: Optional[int] = None
    limit: int = 20
    template: str = "Chào {gender_title} {name}, bên em gửi {gender_title_lower} thông tin ưu đãi mới nhất ạ!"
    exclude_already_sent: bool = True
    campaign_name: Optional[str] = None

class BroadcastRecipientItem(BaseModel):
    lead_id: int
    customer_id: str
    conversation_id: str
    name: str
    gender: str
    gender_title: str
    phone_number: Optional[str] = None
    page_id: str
    status_tag: Optional[str] = None
    assigned_users: Optional[str] = None
    rendered_message: str
    first_created_at: Optional[str] = None
    pancake_url: Optional[str] = None

class BroadcastPreviewResponse(BaseModel):
    total_matching: int
    limit: int
    recipients: List[BroadcastRecipientItem]

class BroadcastStartRequest(BaseModel):
    campaign_name: str
    template: str
    page_id: Optional[str] = None
    name_filter: Optional[str] = None
    employee: Optional[str] = None
    gender: Optional[str] = "all"
    tag: Optional[str] = None
    days_ago: Optional[int] = None
    limit: int = 50
    delay: float = 1.2
    dry_run: bool = True
    exclude_already_sent: bool = True
    target_conversation_ids: Optional[List[str]] = None

class BroadcastStatusResponse(BaseModel):
    task_id: str
    campaign_name: str
    is_running: bool
    total: int
    processed: int
    success: int
    failed: int
    dry_run: bool
    current_recipient: Optional[str] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    logs: List[Dict[str, Any]] = []

class BroadcastHistoryItem(BaseModel):
    id: int
    campaign_name: str
    conversation_id: str
    customer_id: Optional[str] = None
    customer_name: Optional[str] = None
    phone_number: Optional[str] = None
    page_id: str
    message: str
    status: str
    error_message: Optional[str] = None
    sent_at: str
    pancake_url: Optional[str] = None

class BroadcastCampaignSummary(BaseModel):
    campaign_name: str
    page_id: Optional[str] = None
    total_messages: int
    success_count: int
    failed_count: int
    dry_run_count: int
    first_sent_at: Optional[str] = None
    last_sent_at: Optional[str] = None
    status: str


# ==============================================================================
# 3. QUẢN LÝ TÁC VỤ BACKGROUND BROADCAST
# ==============================================================================
_BROADCAST_TASKS: Dict[str, Dict[str, Any]] = {}
_BROADCAST_LOCK = threading.Lock()


def _run_broadcast_worker(task_id: str, req_data: Dict[str, Any]):
    """Luồng worker thực thi gửi tin hàng loạt trong nền an toàn."""
    db = SessionLocal()
    client = PancakeClient()

    try:
        campaign_name = req_data["campaign_name"]
        template = req_data["template"]
        page_id = req_data.get("page_id")
        name_filter = req_data.get("name_filter")
        employee = req_data.get("employee")
        gender_filter = req_data.get("gender") or "all"
        tag_filter = req_data.get("tag")
        days_ago = req_data.get("days_ago")
        limit = req_data.get("limit", 50)
        delay = max(0.5, float(req_data.get("delay", 1.2)))
        dry_run = bool(req_data.get("dry_run", True))
        exclude_already_sent = bool(req_data.get("exclude_already_sent", True))

        target_conv_ids = req_data.get("target_conversation_ids")
        if target_conv_ids and isinstance(target_conv_ids, list):
            target_conv_ids = [str(cid).strip() for cid in target_conv_ids if cid and str(cid).strip()]
        else:
            target_conv_ids = None

        # 1. Truy vấn danh sách khách hàng
        query = db.query(
            DimLead.id.label("lead_id"),
            DimLead.customer_id,
            DimLead.name,
            DimLead.phone_number,
            DimLead.page_id,
            DimLead.first_created_at,
            FactLeadActivity.conversation_id,
            FactLeadActivity.status_tag,
            FactLeadActivity.assigned_users
        ).join(FactLeadActivity, DimLead.id == FactLeadActivity.lead_id)

        recipients = []

        if target_conv_ids:
            # Chế độ gửi theo danh sách tùy chỉnh (Custom recipient list do user chọn/áp dụng)
            query = query.filter(FactLeadActivity.conversation_id.in_(target_conv_ids))
            raw_rows = query.all()

            row_by_conv = {}
            for r in raw_rows:
                cid = str(r.conversation_id) if r.conversation_id else None
                if cid and cid not in row_by_conv:
                    row_by_conv[cid] = r

            for cid in target_conv_ids:
                r = row_by_conv.get(cid)
                if not r:
                    continue
                inferred_gen = infer_vietnamese_gender(r.name)
                recipients.append({
                    "lead_id": r.lead_id,
                    "customer_id": r.customer_id,
                    "conversation_id": cid,
                    "name": r.name or "",
                    "gender": inferred_gen,
                    "phone_number": r.phone_number or "",
                    "page_id": str(r.page_id),
                    "status_tag": r.status_tag or "",
                    "assigned_users": r.assigned_users or ""
                })
        else:
            # Chế độ tự động lọc theo bộ lọc thông thường
            if page_id and page_id.strip() and page_id != "all":
                clean_pid = page_id.strip()
                canonical = resolve_canonical_page_name(clean_pid, fallback=clean_pid)
                query = query.filter(or_(DimLead.page_id == clean_pid, DimLead.page_id == canonical))

            if employee and employee.strip() and employee != "all":
                query = query.filter(FactLeadActivity.assigned_users.ilike(f"%{employee.strip()}%"))

            if tag_filter and tag_filter.strip() and tag_filter != "all":
                query = query.filter(FactLeadActivity.status_tag.ilike(f"%{tag_filter.strip()}%"))

            if name_filter and name_filter.strip():
                query = query.filter(DimLead.name.ilike(f"%{name_filter.strip()}%"))

            if days_ago and days_ago > 0:
                cutoff = get_vn_now() - timedelta(days=days_ago)
                query = query.filter(DimLead.first_created_at >= cutoff)

            query = query.order_by(DimLead.first_created_at.desc())
            raw_rows = query.limit(limit * 3).all()

            # Loại trừ khách đã gửi
            already_sent_convs = set()
            if exclude_already_sent and campaign_name:
                sent_logs = db.query(BotAutoReplyLog.conversation_id).filter(
                    BotAutoReplyLog.case_id == campaign_name,
                    BotAutoReplyLog.status == "SENT"
                ).all()
                already_sent_convs = {str(r[0]) for r in sent_logs if r[0]}

            for r in raw_rows:
                conv_id = str(r.conversation_id) if r.conversation_id else None
                if not conv_id or (exclude_already_sent and conv_id in already_sent_convs):
                    continue

                inferred_gen = infer_vietnamese_gender(r.name)
                if gender_filter and gender_filter != "all" and inferred_gen != gender_filter:
                    continue

                recipients.append({
                    "lead_id": r.lead_id,
                    "customer_id": r.customer_id,
                    "conversation_id": conv_id,
                    "name": r.name or "",
                    "gender": inferred_gen,
                    "phone_number": r.phone_number or "",
                    "page_id": str(r.page_id),
                    "status_tag": r.status_tag or "",
                    "assigned_users": r.assigned_users or ""
                })

                if len(recipients) >= limit:
                    break

        with _BROADCAST_LOCK:
            if task_id in _BROADCAST_TASKS:
                _BROADCAST_TASKS[task_id]["total"] = len(recipients)

        # 2. Duyệt gửi từng tin
        for index, rec in enumerate(recipients, 1):
            with _BROADCAST_LOCK:
                task = _BROADCAST_TASKS.get(task_id)
                if not task or not task.get("is_running"):
                    logger.info(f"Broadcast task {task_id} bị hủy bởi người dùng.")
                    break
                task["current_recipient"] = f"{rec.get('name') or 'Khách hàng'} ({rec['conversation_id']})"

            personalized_msg = render_personalized_template(template, rec)
            conv_id = rec["conversation_id"]
            p_id = rec["page_id"]

            log_status = "SENT"
            err_msg = None

            if dry_run:
                # Mô phỏng
                log_status = "DRY_RUN"
                res = {"success": True, "message": "[DRY-RUN] Giả lập gửi thành công"}
            else:
                # Gửi live qua Pancake API (POST /pages/{page_id}/conversations/{conversation_id}/messages)
                res = client.send_message(
                    page_id=p_id,
                    conversation_id=conv_id,
                    message=personalized_msg,
                    action="reply_inbox"
                )
                if not res.get("success"):
                    log_status = "FAILED"
                    err_msg = res.get("message") or res.get("message_code") or "Lỗi gửi tin Pancake"

            # Lưu vào Database bot_auto_replies
            try:
                log_entry = BotAutoReplyLog(
                    conversation_id=conv_id,
                    customer_id=rec.get("customer_id"),
                    page_id=p_id,
                    case_id=campaign_name,
                    customer_message=f"[BROADCAST] {rec.get('status_tag') or ''}",
                    reply_message=personalized_msg,
                    sent_at=get_vn_now(),
                    status=log_status,
                    error_message=err_msg
                )
                db.add(log_entry)
                db.commit()
            except Exception as dbe:
                db.rollback()
                logger.warning(f"Lỗi khi lưu log broadcast vào DB: {dbe}")

            # Cập nhật tiến trình task
            with _BROADCAST_LOCK:
                if task_id in _BROADCAST_TASKS:
                    t = _BROADCAST_TASKS[task_id]
                    t["processed"] += 1
                    if log_status in ("SENT", "DRY_RUN"):
                        t["success"] += 1
                    else:
                        t["failed"] += 1

                    t["logs"].append({
                        "index": index,
                        "customer_name": rec.get("name") or "N/A",
                        "phone_number": rec.get("phone_number") or "N/A",
                        "conversation_id": conv_id,
                        "page_id": p_id,
                        "status": log_status,
                        "error_message": err_msg,
                        "time": get_vn_now().strftime("%H:%M:%S")
                    })
                    # Giữ tối đa 100 log gần nhất trong RAM
                    if len(t["logs"]) > 100:
                        t["logs"] = t["logs"][-100:]

            # Nghỉ an toàn để tuân thủ Rate Limit <= 5 req/s của Pancake API
            if index < len(recipients):
                time.sleep(delay + random.uniform(0.1, 0.4))

    except Exception as e:
        logger.error(f"Lỗi ngoại lệ trong broadcast worker: {e}", exc_info=True)
    finally:
        with _BROADCAST_LOCK:
            if task_id in _BROADCAST_TASKS:
                t = _BROADCAST_TASKS[task_id]
                t["is_running"] = False
                t["current_recipient"] = None
                t["finished_at"] = get_vn_now().strftime("%Y-%m-%d %H:%M:%S")
        db.close()


# ==============================================================================
# 4. CÁC API ENDPOINTS
# ==============================================================================

@router.get("/options", response_model=BroadcastOptionsResponse)
def get_broadcast_options(db: Session = Depends(get_db)):
    """Lấy danh sách các options (Kênh, Nhân viên, Tags, Giới tính) phục vụ bộ lọc."""
    # 1. Danh sách Pages
    page_results = db.query(DimLead.page_id).distinct().all()
    pages_set = set()
    for (pg,) in page_results:
        if pg:
            p_name = resolve_canonical_page_name(pg.strip(), fallback=None)
            if p_name and not is_page_id(p_name):
                pages_set.add(p_name)
    for known in set(KNOWN_PAGE_NAMES.values()):
        pages_set.add(known)
    sorted_pages = sorted(list(pages_set))

    # 2. Danh sách Nhân viên
    emp_results = db.query(FactLeadActivity.assigned_users).distinct().all()
    emp_set = set()
    for (users,) in emp_results:
        if users:
            for u in users.split(","):
                u_clean = u.strip()
                if u_clean:
                    emp_set.add(u_clean)
    sorted_employees = sorted(list(emp_set))

    # 3. Danh sách Tags
    tag_results = db.query(FactLeadActivity.status_tag).distinct().all()
    tag_set = set()
    for (t_str,) in tag_results:
        if t_str:
            for t in t_str.split(","):
                t_clean = t.strip()
                if t_clean:
                    tag_set.add(t_clean)
    sorted_tags = sorted(list(tag_set))

    # 4. Tùy chọn giới tính
    gender_options = [
        {"id": "all", "label": "Tất cả giới tính"},
        {"id": "male", "label": "Nam (Anh)"},
        {"id": "female", "label": "Nữ (Chị)"},
        {"id": "unknown", "label": "Chưa rõ (Anh/Chị)"}
    ]

    return BroadcastOptionsResponse(
        pages=sorted_pages,
        zalo_pages=sorted(p for p in sorted_pages if p in ZALO_PAGE_NAMES),
        employees=sorted_employees,
        tags=sorted_tags,
        gender_options=gender_options
    )


@router.post("/preview", response_model=BroadcastPreviewResponse)
def preview_broadcast(req: BroadcastPreviewRequest, db: Session = Depends(get_db)):
    """Xem trước danh sách người nhận và tin nhắn mẫu đã cá nhân hóa trước khi gửi."""
    query = db.query(
        DimLead.id.label("lead_id"),
        DimLead.customer_id,
        DimLead.name,
        DimLead.phone_number,
        DimLead.page_id,
        DimLead.first_created_at,
        FactLeadActivity.conversation_id,
        FactLeadActivity.status_tag,
        FactLeadActivity.assigned_users
    ).join(FactLeadActivity, DimLead.id == FactLeadActivity.lead_id)

    # Lọc Kênh
    if req.page_id and req.page_id.strip() and req.page_id != "all":
        clean_pid = req.page_id.strip()
        canonical = resolve_canonical_page_name(clean_pid, fallback=clean_pid)
        query = query.filter(or_(DimLead.page_id == clean_pid, DimLead.page_id == canonical))

    # Lọc Nhân viên
    if req.employee and req.employee.strip() and req.employee != "all":
        query = query.filter(FactLeadActivity.assigned_users.ilike(f"%{req.employee.strip()}%"))

    # Lọc Tags
    if req.tag and req.tag.strip() and req.tag != "all":
        query = query.filter(FactLeadActivity.status_tag.ilike(f"%{req.tag.strip()}%"))

    # Lọc Tên khách
    if req.name_filter and req.name_filter.strip():
        query = query.filter(DimLead.name.ilike(f"%{req.name_filter.strip()}%"))

    # Lọc số ngày tương tác gần nhất
    if req.days_ago and req.days_ago > 0:
        cutoff = get_vn_now() - timedelta(days=req.days_ago)
        query = query.filter(DimLead.first_created_at >= cutoff)

    query = query.order_by(DimLead.first_created_at.desc())
    all_candidates = query.limit(req.limit * 4).all()

    # Loại trừ đã gửi trong chiến dịch này
    already_sent = set()
    if req.exclude_already_sent and req.campaign_name:
        sent_logs = db.query(BotAutoReplyLog.conversation_id).filter(
            BotAutoReplyLog.case_id == req.campaign_name,
            BotAutoReplyLog.status == "SENT"
        ).all()
        already_sent = {str(r[0]) for r in sent_logs if r[0]}

    recipients: List[BroadcastRecipientItem] = []
    total_matching = 0

    for r in all_candidates:
        conv_id = str(r.conversation_id) if r.conversation_id else None
        if not conv_id or (req.exclude_already_sent and conv_id in already_sent):
            continue

        inferred_gen = infer_vietnamese_gender(r.name)
        if req.gender and req.gender != "all" and inferred_gen != req.gender:
            continue

        total_matching += 1

        if len(recipients) < req.limit:
            title_cap, _ = get_gender_title(inferred_gen)
            item_data = {
                "lead_id": r.lead_id,
                "customer_id": r.customer_id,
                "conversation_id": conv_id,
                "name": r.name or "",
                "gender": inferred_gen,
                "phone_number": r.phone_number,
                "page_id": str(r.page_id),
                "status_tag": r.status_tag,
                "assigned_users": r.assigned_users
            }
            rendered = render_personalized_template(req.template, item_data)

            p_url = build_pancake_url(
                conversation_id=conv_id,
                customer_id=r.customer_id,
                page_name_or_id=r.page_id
            )

            recipients.append(BroadcastRecipientItem(
                lead_id=r.lead_id,
                customer_id=r.customer_id,
                conversation_id=conv_id,
                name=r.name or "N/A",
                gender=inferred_gen,
                gender_title=title_cap,
                phone_number=r.phone_number,
                page_id=str(r.page_id),
                status_tag=r.status_tag,
                assigned_users=r.assigned_users,
                rendered_message=rendered,
                first_created_at=r.first_created_at.strftime("%Y-%m-%d %H:%M") if r.first_created_at else None,
                pancake_url=p_url
            ))

    return BroadcastPreviewResponse(
        total_matching=total_matching,
        limit=req.limit,
        recipients=recipients
    )


@router.post("/start")
def start_broadcast(req: BroadcastStartRequest, background_tasks: BackgroundTasks):
    """Bắt đầu chạy chiến dịch gửi tin hàng loạt trong nền (hỗ trợ cả Live và Dry-run)."""
    if not req.campaign_name or not req.campaign_name.strip():
        raise HTTPException(status_code=400, detail="Vui lòng đặt Tên chiến dịch.")
    if not req.template or not req.template.strip():
        raise HTTPException(status_code=400, detail="Vui lòng nhập Nội dung tin nhắn.")

    task_id = f"task_{int(time.time())}_{random.randint(100, 999)}"

    task_state = {
        "task_id": task_id,
        "campaign_name": req.campaign_name.strip(),
        "is_running": True,
        "total": 0,
        "processed": 0,
        "success": 0,
        "failed": 0,
        "dry_run": req.dry_run,
        "current_recipient": None,
        "started_at": get_vn_now().strftime("%Y-%m-%d %H:%M:%S"),
        "finished_at": None,
        "logs": []
    }

    with _BROADCAST_LOCK:
        _BROADCAST_TASKS[task_id] = task_state

    # Chạy worker trong background
    worker_thread = threading.Thread(
        target=_run_broadcast_worker,
        args=(task_id, req.dict()),
        daemon=True
    )
    worker_thread.start()

    logger.info(f"Đã khởi động Broadcast Task '{task_id}' (Chiến dịch: {req.campaign_name}, Dry-run: {req.dry_run})")
    return {"status": "STARTED", "task_id": task_id, "campaign_name": req.campaign_name}


@router.get("/status/{task_id}", response_model=BroadcastStatusResponse)
def get_broadcast_status(task_id: str):
    """Lấy tiến độ gửi tin real-time của một tác vụ đang chạy."""
    with _BROADCAST_LOCK:
        task = _BROADCAST_TASKS.get(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Không tìm thấy tác vụ gửi tin này.")
        return BroadcastStatusResponse(**task)


@router.post("/stop/{task_id}")
def stop_broadcast(task_id: str):
    """Dừng khẩn cấp một tác vụ gửi tin đang chạy."""
    with _BROADCAST_LOCK:
        task = _BROADCAST_TASKS.get(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Không tìm thấy tác vụ.")
        task["is_running"] = False
        task["finished_at"] = get_vn_now().strftime("%Y-%m-%d %H:%M:%S")
        return {"status": "STOPPED", "task_id": task_id}


@router.get("/history")
def get_broadcast_history(
    campaign_name: Optional[str] = None,
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db)
):
    """
    Lấy lịch sử từng lần chạy bot:
    - Bảng tổng hợp theo từng chiến dịch (Campaign Summary)
    - Danh sách chi tiết từng tin nhắn đã gửi (Detailed Logs)
    """
    # 1. Chi tiết logs
    log_query = db.query(
        BotAutoReplyLog.id,
        BotAutoReplyLog.case_id.label("campaign_name"),
        BotAutoReplyLog.conversation_id,
        BotAutoReplyLog.customer_id,
        BotAutoReplyLog.page_id,
        BotAutoReplyLog.reply_message.label("message"),
        BotAutoReplyLog.status,
        BotAutoReplyLog.error_message,
        BotAutoReplyLog.sent_at,
        DimLead.name.label("customer_name"),
        DimLead.phone_number
    ).outerjoin(
        DimLead,
        BotAutoReplyLog.customer_id == DimLead.customer_id
    )

    if campaign_name and campaign_name.strip() and campaign_name != "all":
        log_query = log_query.filter(BotAutoReplyLog.case_id == campaign_name.strip())

    recent_logs_rows = log_query.order_by(desc(BotAutoReplyLog.sent_at)).limit(limit).all()

    logs_list: List[BroadcastHistoryItem] = []
    for r in recent_logs_rows:
        logs_list.append(BroadcastHistoryItem(
            id=r.id,
            campaign_name=r.campaign_name,
            conversation_id=r.conversation_id,
            customer_id=r.customer_id,
            customer_name=r.customer_name or "N/A",
            phone_number=r.phone_number,
            page_id=r.page_id,
            message=r.message,
            status=r.status,
            error_message=r.error_message,
            sent_at=r.sent_at.strftime("%Y-%m-%d %H:%M:%S") if r.sent_at else "",
            pancake_url=build_pancake_url(r.conversation_id, r.customer_id, r.page_id)
        ))

    # 2. Thống kê theo chiến dịch (Group by case_id)
    campaign_stats_query = db.query(
        BotAutoReplyLog.case_id,
        BotAutoReplyLog.page_id,
        func.count(BotAutoReplyLog.id).label("total"),
        func.sum(func.case((BotAutoReplyLog.status == "SENT", 1), else_=0)).label("sent_cnt"),
        func.sum(func.case((BotAutoReplyLog.status == "FAILED", 1), else_=0)).label("failed_cnt"),
        func.sum(func.case((BotAutoReplyLog.status == "DRY_RUN", 1), else_=0)).label("dry_cnt"),
        func.min(BotAutoReplyLog.sent_at).label("first_sent"),
        func.max(BotAutoReplyLog.sent_at).label("last_sent")
    ).group_by(BotAutoReplyLog.case_id, BotAutoReplyLog.page_id).order_by(desc("last_sent")).limit(30).all()

    campaigns: List[BroadcastCampaignSummary] = []
    for c in campaign_stats_query:
        sent_c = int(c.sent_cnt or 0)
        failed_c = int(c.failed_cnt or 0)
        dry_c = int(c.dry_cnt or 0)
        total_c = int(c.total or 0)

        camp_status = "Hoàn thành"
        if failed_c > 0 and sent_c == 0:
            camp_status = "Thất bại"
        elif dry_c == total_c:
            camp_status = "Mô phỏng (Dry-run)"

        campaigns.append(BroadcastCampaignSummary(
            campaign_name=c.case_id,
            page_id=c.page_id,
            total_messages=total_c,
            success_count=sent_c,
            failed_count=failed_c,
            dry_run_count=dry_c,
            first_sent_at=c.first_sent.strftime("%Y-%m-%d %H:%M:%S") if c.first_sent else None,
            last_sent_at=c.last_sent.strftime("%Y-%m-%d %H:%M:%S") if c.last_sent else None,
            status=camp_status
        ))

    return {
        "campaigns": campaigns,
        "logs": logs_list
    }
