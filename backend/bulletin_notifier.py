"""
Engine tổng hợp & gửi nhắc việc hàng ngày (11:00 và 15:00 giờ VN) và nhắc hẹn đúng giờ
qua tài khoản Zalo 'Eztech Consultant' (pzl_764881945463506349) cho từng nhân viên EzTech.
Tối ưu bảo vệ Neon Compute Units & chống spam Zalo (retry cap, backoff, giới hạn độ dài tin, active_weekdays).
"""

import logging
import os
import random
import threading
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from database.db import SessionLocal
from database.models import (
    AppUser,
    BulletinPost,
    DailyChecklist,
    DailyChecklistItem,
    EztechStaff,
    WorkReminder,
    ZaloReminderLog,
    get_vn_now,
)
from etl.bulletin_sync import EZTECH_CONSULTANT_PAGE_ID, get_bulletin_source_config
from etl.pancake_client import PancakeClient
from etl.pipeline import get_token_for_page

logger = logging.getLogger("BulletinNotifier")

MAX_ZALO_MSG_CHARS = 1800
MAX_EXACT_RETRIES = 2
EXACT_RETRY_BACKOFF_MIN = 15

_EXACT_LOCK = threading.Lock()
_NEXT_EXACT_DUE_AT: Optional[datetime] = None
_EXACT_CACHE_INITIALIZED = False


def get_dashboard_base_url(db: Optional[Session] = None) -> str:
    if db is not None:
        try:
            cfg = get_bulletin_source_config(db)
            cfg_url = str(cfg.get("dashboard_url") or "").strip()
            if cfg_url:
                return cfg_url.rstrip("/")
        except Exception:
            pass
    url = (
        os.getenv("FRONTEND_DASHBOARD_URL")
        or os.getenv("ALLOWED_ORIGINS", "").split(",")[0]
        or "https://pancake-react-dashboard.onrender.com"
    ).strip()
    if url == "*":
        url = "https://pancake-react-dashboard.onrender.com"
    return url.rstrip("/")


def invalidate_exact_reminder_cache():
    """Đánh dấu cần nạp lại mốc nhắc hẹn gần nhất khi có thao tác CRUD WorkReminder / Staff Zalo."""
    global _EXACT_CACHE_INITIALIZED
    with _EXACT_LOCK:
        _EXACT_CACHE_INITIALIZED = False


def ensure_recurring_checklists_for_date(
    db: Session,
    target_date: str,
    owner_user_id: Optional[int] = None,
    allow_any_date: bool = False,
) -> int:
    """
    Nhân bản các checklist đánh dấu lặp hàng ngày (is_recurring_daily=True, chưa xóa) sang target_date.
    Chỉ tự động sinh cho hôm nay và ngày mai để không ghi DB khi người dùng duyệt lịch quá khứ/tương lai xa.
    Tôn trọng bản ghi đã soft-delete (is_deleted=True) để không tạo lại checklist user vừa xóa hôm nay.
    """
    if not allow_any_date:
        today_dt = get_vn_now().date()
        try:
            t_dt = datetime.strptime(target_date, "%Y-%m-%d").date()
        except Exception:
            return 0
        if t_dt < today_dt or t_dt > (today_dt + timedelta(days=1)):
            return 0

    tpl_query = db.query(DailyChecklist).options(joinedload(DailyChecklist.items)).filter(
        DailyChecklist.is_recurring_daily == True,
        DailyChecklist.is_deleted == False,
        DailyChecklist.checklist_date < target_date,
    )
    if owner_user_id is not None:
        tpl_query = tpl_query.filter(DailyChecklist.owner_user_id == owner_user_id)

    templates = tpl_query.order_by(DailyChecklist.id.asc()).all()
    if not templates:
        return 0

    # Bao gồm cả bản ghi is_deleted=True trong existing_pairs để không tái sinh checklist user vừa xóa hôm nay
    existing_pairs = set()
    ex_query = db.query(
        DailyChecklist.recurring_template_id,
        DailyChecklist.owner_user_id,
        DailyChecklist.id,
    ).filter(DailyChecklist.checklist_date == target_date)
    if owner_user_id is not None:
        ex_query = ex_query.filter(DailyChecklist.owner_user_id == owner_user_id)

    for tpl_id, u_id, cid in ex_query.all():
        if tpl_id:
            existing_pairs.add((tpl_id, u_id))
        existing_pairs.add((cid, u_id))

    latest_by_root: Dict[Tuple[int, int], DailyChecklist] = {}
    for t in templates:
        root_id = t.recurring_template_id or t.id
        latest_by_root[(root_id, t.owner_user_id)] = t

    created = 0
    for (root_id, u_id), tpl in latest_by_root.items():
        if (root_id, u_id) in existing_pairs:
            continue
        if not tpl.items:
            continue
        new_cl = DailyChecklist(
            checklist_date=target_date,
            title=tpl.title,
            owner_user_id=u_id,
            created_by_user_id=tpl.created_by_user_id,
            source_post_id=tpl.source_post_id,
            is_recurring_daily=False,
            recurring_template_id=root_id,
            is_deleted=False,
            created_at=get_vn_now(),
            updated_at=get_vn_now(),
        )
        db.add(new_cl)
        db.flush()
        for idx, item in enumerate(tpl.items):
            db.add(
                DailyChecklistItem(
                    checklist_id=new_cl.id,
                    content=item.content,
                    is_done=False,
                    done_at=None,
                    sort_order=item.sort_order if item.sort_order is not None else idx,
                    note=item.note,
                    created_at=get_vn_now(),
                )
            )
        existing_pairs.add((root_id, u_id))
        created += 1

    if created > 0:
        db.commit()
    return created


def _append_capped_bullets(lines: List[str], items: List[str], max_chars: int) -> None:
    """Chèn danh sách bullet sao cho không vượt quá giới hạn ký tự Zalo."""
    used = 0
    shown = 0
    for item in items:
        bullet = f"• {item[:180]}"
        if used + len(bullet) + 1 > max_chars and shown > 0:
            remaining = len(items) - shown
            lines.append(f"• ... và {remaining} hạng mục khác (xem đầy đủ trên Dashboard)")
            return
        lines.append(bullet)
        used += len(bullet) + 1
        shown += 1


def _format_digest_message(
    staff_name: str,
    slot: str,
    target_date: str,
    done_lines: List[str],
    pending_lines: List[str],
    dashboard_url: str,
) -> str:
    """Tạo nội dung tin nhắn tổng hợp Đã hoàn thành & Chưa hoàn thành gửi qua Zalo Eztech Consultant (có chống tràn ký tự)."""
    try:
        date_vn = datetime.strptime(target_date, "%Y-%m-%d").strftime("%d/%m/%Y")
    except Exception:
        date_vn = target_date

    slot_label = "11:00" if slot == "11h" else ("15:00" if slot == "15h" else get_vn_now().strftime("%H:%M"))
    header = [
        f"[EzTech Nhắc Việc - {slot_label} | {date_vn}]",
        f"Chào {staff_name}, tổng hợp công việc hôm nay của bạn:",
        "",
    ]
    footer = [
        "",
        f"👉 Cập nhật tiến độ tại: {dashboard_url}/#/bulletin",
    ]

    budget = MAX_ZALO_MSG_CHARS - sum(len(x) + 1 for x in header + footer) - 120
    # Ưu tiên 65% không gian cho mục CHƯA hoàn thành, 35% cho mục ĐÃ hoàn thành
    done_budget = max(250, int(budget * 0.35))
    pending_budget = max(450, int(budget * 0.65))

    lines = list(header)
    lines.append(f"✅ ĐÃ HOÀN THÀNH ({len(done_lines)}):")
    if done_lines:
        _append_capped_bullets(lines, done_lines, done_budget)
    else:
        lines.append("• (Chưa có hạng mục nào hoàn thành)")

    lines.append("")
    lines.append(f"⏳ CHƯA HOÀN THÀNH ({len(pending_lines)}):")
    if pending_lines:
        _append_capped_bullets(lines, pending_lines, pending_budget)
    else:
        lines.append("• (Tuyệt vời! Bạn đã hoàn thành hết các hạng mục hôm nay)")

    lines.extend(footer)
    return "\n".join(lines)[:MAX_ZALO_MSG_CHARS]


def _collect_user_daily_summary(
    db: Session,
    user_id: int,
    target_date: str,
    slot: str,
) -> Tuple[List[str], List[str]]:
    """Thu thập danh sách hạng mục Đã hoàn thành và Chưa hoàn thành trong ngày của 1 nhân viên."""
    done_lines: List[str] = []
    pending_lines: List[str] = []

    checklists = (
        db.query(DailyChecklist)
        .options(joinedload(DailyChecklist.items))
        .filter(
            DailyChecklist.owner_user_id == user_id,
            DailyChecklist.checklist_date == target_date,
            DailyChecklist.is_deleted == False,
        )
        .order_by(DailyChecklist.id.asc())
        .all()
    )
    for cl in checklists:
        prefix = f"[Checklist: {cl.title}] " if cl.title else "[Checklist] "
        for item in cl.items:
            text = f"{prefix}{item.content}".strip()
            if item.is_done:
                done_lines.append(text)
            else:
                pending_lines.append(text)

    rem_query = db.query(WorkReminder).filter(
        WorkReminder.owner_user_id == user_id,
        WorkReminder.status != "cancelled",
        (
            (WorkReminder.due_date == target_date)
            | ((WorkReminder.due_date < target_date) & (WorkReminder.status.in_(["pending", "snoozed"])))
        ),
    )
    if slot == "11h":
        rem_query = rem_query.filter(WorkReminder.notify_11h == True)
    elif slot == "15h":
        rem_query = rem_query.filter(WorkReminder.notify_15h == True)

    reminders = rem_query.order_by(WorkReminder.remind_at.asc()).all()
    for rem in reminders:
        time_str = rem.remind_at.strftime("%H:%M") if rem.remind_at else ""
        if rem.status == "completed":
            done_lines.append(f"[Nhắc hẹn {time_str}] {rem.title}".strip())
        else:
            overdue_tag = f" (Quá hạn {rem.due_date})" if rem.due_date < target_date else ""
            pending_lines.append(f"[Nhắc hẹn {time_str}]{overdue_tag} {rem.title}".strip())

    return done_lines, pending_lines


def dispatch_daily_digest(
    db: Optional[Session] = None,
    slot: str = "11h",
    target_date: Optional[str] = None,
    user_id: Optional[int] = None,
    dry_run: bool = False,
    force: bool = False,
) -> Dict[str, Any]:
    """
    Gửi báo cáo tổng hợp hạng mục đã hoàn thành & chưa hoàn thành qua Zalo Eztech Consultant
    cho các nhân viên EzTech vào 11h và 15h hàng ngày (tôn trọng active_weekdays).
    """
    own_session = db is None
    session = db or SessionLocal()
    try:
        clean_slot = slot if slot in ("11h", "15h", "manual") else "manual"
        now_vn = get_vn_now()
        date_str = target_date or now_vn.strftime("%Y-%m-%d")

        cfg = get_bulletin_source_config(session)
        active_weekdays = cfg.get("active_weekdays", [0, 1, 2, 3, 4, 5])
        if not force and not dry_run and clean_slot in ("11h", "15h"):
            try:
                wd = datetime.strptime(date_str, "%Y-%m-%d").weekday()
                if wd not in active_weekdays:
                    return {
                        "success": True,
                        "slot": clean_slot,
                        "dispatch_date": date_str,
                        "dry_run": False,
                        "sent": 0,
                        "failed": 0,
                        "skipped": 0,
                        "results": [],
                        "message": f"Bỏ qua gửi nhắc tự động vì ngày {date_str} không nằm trong ngày làm việc cấu hình.",
                    }
            except Exception:
                pass

        dashboard_url = get_dashboard_base_url(session)
        ensure_recurring_checklists_for_date(session, target_date=date_str, owner_user_id=user_id, allow_any_date=True)

        staff_query = (
            session.query(EztechStaff, AppUser)
            .join(AppUser, EztechStaff.user_id == AppUser.id)
            .filter(
                EztechStaff.is_active == True,
                AppUser.is_active == True,
                EztechStaff.user_id.isnot(None),
            )
        )
        if user_id is not None:
            staff_query = staff_query.filter(EztechStaff.user_id == user_id)
        else:
            staff_query = staff_query.filter(EztechStaff.receive_daily_digest == True)

        staff_rows = staff_query.order_by(EztechStaff.full_name.asc()).all()
        if not staff_rows:
            return {
                "success": True,
                "slot": clean_slot,
                "dispatch_date": date_str,
                "dry_run": dry_run,
                "sent": 0,
                "failed": 0,
                "skipped": 0,
                "results": [],
                "message": "Chưa có nhân viên EzTech nào được cấu hình nhận nhắc Zalo.",
            }

        already_sent_users = set()
        if not force and not dry_run and clean_slot in ("11h", "15h"):
            sent_rows = (
                session.query(ZaloReminderLog.user_id)
                .filter(
                    ZaloReminderLog.dispatch_date == date_str,
                    ZaloReminderLog.slot == clean_slot,
                    ZaloReminderLog.status == "SENT",
                    ZaloReminderLog.user_id.isnot(None),
                )
                .all()
            )
            already_sent_users = {r[0] for r in sent_rows}

        page_token = get_token_for_page(EZTECH_CONSULTANT_PAGE_ID)
        client = PancakeClient(api_token=page_token) if not dry_run else None

        results: List[Dict[str, Any]] = []
        sent_cnt = 0
        failed_cnt = 0
        skipped_cnt = 0

        for staff, user in staff_rows:
            u_id = user.id
            display_name = (staff.full_name or user.full_name or user.username).strip()

            if u_id in already_sent_users:
                skipped_cnt += 1
                results.append({
                    "user_id": u_id,
                    "staff_name": display_name,
                    "status": "SKIPPED",
                    "reason": f"Đã gửi nhắc khung {clean_slot} ngày {date_str} trước đó.",
                })
                continue

            if not staff.zalo_conversation_id:
                skipped_cnt += 1
                results.append({
                    "user_id": u_id,
                    "staff_name": display_name,
                    "status": "SKIPPED",
                    "reason": "Chưa gắn conversation_id Zalo trên page Eztech Consultant.",
                })
                continue

            done_lines, pending_lines = _collect_user_daily_summary(session, u_id, date_str, clean_slot)
            if not done_lines and not pending_lines:
                skipped_cnt += 1
                if not dry_run:
                    session.add(
                        ZaloReminderLog(
                            dispatch_date=date_str,
                            slot=clean_slot,
                            user_id=u_id,
                            staff_id=staff.id,
                            conversation_id=staff.zalo_conversation_id,
                            message_text="(Không có hạng mục nào trong ngày)",
                            done_count=0,
                            pending_count=0,
                            status="SKIPPED",
                            error_message="Không có checklist hoặc nhắc hẹn trong ngày",
                            sent_at=get_vn_now(),
                        )
                    )
                    session.commit()
                results.append({
                    "user_id": u_id,
                    "staff_name": display_name,
                    "status": "SKIPPED",
                    "done_count": 0,
                    "pending_count": 0,
                    "reason": "Không có checklist hoặc nhắc hẹn trong ngày.",
                })
                continue

            msg_text = _format_digest_message(display_name, clean_slot, date_str, done_lines, pending_lines, dashboard_url)

            if dry_run:
                results.append({
                    "user_id": u_id,
                    "staff_name": display_name,
                    "conversation_id": staff.zalo_conversation_id,
                    "status": "DRY_RUN",
                    "done_count": len(done_lines),
                    "pending_count": len(pending_lines),
                    "preview_message": msg_text,
                })
                continue

            if sent_cnt > 0:
                time.sleep(random.uniform(3.5, 6.5))

            send_res = client.send_message(
                page_id=EZTECH_CONSULTANT_PAGE_ID,
                conversation_id=staff.zalo_conversation_id,
                message=msg_text,
                action="reply_inbox",
            )
            ok = bool(send_res.get("success"))
            err = None if ok else str(send_res.get("message") or send_res.get("description") or "Lỗi gửi tin Pancake")
            log_status = "SENT" if ok else "FAILED"

            if ok:
                sent_cnt += 1
            else:
                failed_cnt += 1

            session.add(
                ZaloReminderLog(
                    dispatch_date=date_str,
                    slot=clean_slot,
                    user_id=u_id,
                    staff_id=staff.id,
                    conversation_id=staff.zalo_conversation_id,
                    message_text=msg_text,
                    done_count=len(done_lines),
                    pending_count=len(pending_lines),
                    status=log_status,
                    error_message=err,
                    sent_at=get_vn_now(),
                )
            )
            session.commit()

            results.append({
                "user_id": u_id,
                "staff_name": display_name,
                "conversation_id": staff.zalo_conversation_id,
                "status": log_status,
                "done_count": len(done_lines),
                "pending_count": len(pending_lines),
                "error_message": err,
            })

        return {
            "success": True,
            "slot": clean_slot,
            "dispatch_date": date_str,
            "dry_run": dry_run,
            "sent": sent_cnt,
            "failed": failed_cnt,
            "skipped": skipped_cnt,
            "results": results,
            "message": (
                f"Đã mô phỏng gửi nhắc {clean_slot} cho {len(results)} nhân sự."
                if dry_run
                else f"Hoàn tất gửi nhắc {clean_slot}: {sent_cnt} thành công, {failed_cnt} lỗi, {skipped_cnt} bỏ qua."
            ),
        }
    except Exception as e:
        session.rollback()
        logger.error(f"Lỗi dispatch_daily_digest: {e}", exc_info=True)
        return {"success": False, "message": str(e), "sent": 0, "failed": 0, "skipped": 0, "results": []}
    finally:
        if own_session:
            session.close()


def dispatch_due_exact_reminders(
    db: Optional[Session] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """
    Quét và gửi tin nhắn Zalo đúng giờ cho các nhắc hẹn đã đến hạn (notify_exact_time=True).
    - INNER JOIN EztechStaff có zalo_conversation_id hợp lệ ngay trong SQL (0 egress thừa).
    - Giới hạn tối đa MAX_EXACT_RETRIES (2 lần) kèm backoff 15 phút để không bao giờ spam Zalo / đốt Neon CU.
    """
    own_session = db is None
    session = db or SessionLocal()
    try:
        now_vn = get_vn_now()
        window_start = now_vn - timedelta(hours=12)
        retry_cutoff = now_vn - timedelta(minutes=EXACT_RETRY_BACKOFF_MIN)

        due_rows = (
            session.query(WorkReminder, EztechStaff, AppUser)
            .join(AppUser, WorkReminder.owner_user_id == AppUser.id)
            .join(EztechStaff, EztechStaff.user_id == AppUser.id)
            .filter(
                WorkReminder.status == "pending",
                WorkReminder.notify_exact_time == True,
                WorkReminder.exact_notified_at.is_(None),
                WorkReminder.exact_retry_count < MAX_EXACT_RETRIES,
                or_(
                    WorkReminder.exact_last_error_at.is_(None),
                    WorkReminder.exact_last_error_at <= retry_cutoff,
                ),
                WorkReminder.remind_at <= now_vn,
                WorkReminder.remind_at >= window_start,
                AppUser.is_active == True,
                EztechStaff.is_active == True,
                EztechStaff.zalo_conversation_id.isnot(None),
                EztechStaff.zalo_conversation_id != "",
            )
            .order_by(WorkReminder.remind_at.asc())
            .all()
        )

        if not due_rows:
            return {"success": True, "sent": 0, "failed": 0, "skipped": 0, "results": []}

        dashboard_url = get_dashboard_base_url(session)
        page_token = get_token_for_page(EZTECH_CONSULTANT_PAGE_ID)
        client = PancakeClient(api_token=page_token) if not dry_run else None
        sent_cnt = 0
        failed_cnt = 0
        results: List[Dict[str, Any]] = []

        for rem, staff, user in due_rows:
            staff_name = (staff.full_name or user.full_name or user.username).strip()
            conv_id = str(staff.zalo_conversation_id).strip()

            time_str = rem.remind_at.strftime("%H:%M %d/%m")
            msg_lines = [
                f"⏰ [EzTech Nhắc Hẹn - {time_str}]",
                f"Chào {staff_name}, bạn có lịch nhắc hẹn đến giờ:",
                f"• {rem.title}",
            ]
            if rem.description:
                msg_lines.append(f"• Ghi chú: {rem.description.strip()[:280]}")
            if rem.source_post_id:
                post = session.query(BulletinPost.title, BulletinPost.boss_display_name).filter(
                    BulletinPost.id == rem.source_post_id
                ).first()
                if post:
                    msg_lines.append(f"• Từ bản tin ({post.boss_display_name}): {post.title}")
            msg_lines.append(f"👉 Cập nhật tại: {dashboard_url}/#/bulletin")
            msg_text = "\n".join(msg_lines)[:MAX_ZALO_MSG_CHARS]

            if dry_run:
                results.append({"reminder_id": rem.id, "status": "DRY_RUN", "preview_message": msg_text})
                continue

            if sent_cnt > 0:
                time.sleep(random.uniform(3.0, 5.5))

            send_res = client.send_message(
                page_id=EZTECH_CONSULTANT_PAGE_ID,
                conversation_id=conv_id,
                message=msg_text,
                action="reply_inbox",
            )
            ok = bool(send_res.get("success"))
            err = None if ok else str(send_res.get("message") or "Lỗi gửi tin Pancake")
            log_status = "SENT" if ok else "FAILED"

            if ok:
                rem.exact_notified_at = now_vn
                sent_cnt += 1
            else:
                rem.exact_retry_count = int(rem.exact_retry_count or 0) + 1
                rem.exact_last_error_at = now_vn
                failed_cnt += 1

            session.add(
                ZaloReminderLog(
                    dispatch_date=now_vn.strftime("%Y-%m-%d"),
                    slot="exact",
                    user_id=user.id,
                    staff_id=staff.id,
                    reminder_id=rem.id,
                    conversation_id=conv_id,
                    message_text=msg_text,
                    done_count=0,
                    pending_count=1,
                    status=log_status,
                    error_message=err,
                    sent_at=now_vn,
                )
            )
            session.commit()
            results.append({"reminder_id": rem.id, "status": log_status, "error_message": err})

        invalidate_exact_reminder_cache()
        return {
            "success": True,
            "sent": sent_cnt,
            "failed": failed_cnt,
            "skipped": 0,
            "results": results,
        }
    except Exception as e:
        session.rollback()
        logger.error(f"Lỗi dispatch_due_exact_reminders: {e}", exc_info=True)
        return {"success": False, "message": str(e), "sent": 0, "failed": 0, "skipped": 0, "results": []}
    finally:
        if own_session:
            session.close()


def send_test_zalo_to_staff(db: Session, user_id: int, custom_message: Optional[str] = None) -> Dict[str, Any]:
    """Gửi tin nhắn thử nghiệm qua Eztech Consultant cho 1 nhân viên cụ thể."""
    row = (
        db.query(EztechStaff, AppUser)
        .join(AppUser, EztechStaff.user_id == AppUser.id)
        .filter(AppUser.id == user_id)
        .first()
    )
    if not row:
        return {"success": False, "message": "Nhân viên chưa được thiết lập hồ sơ Zalo."}
    staff, user = row
    if not staff.zalo_conversation_id:
        return {"success": False, "message": "Nhân viên chưa có conversation_id Zalo trên page Eztech Consultant."}

    staff_name = (staff.full_name or user.full_name or user.username).strip()
    msg_text = (custom_message or "").strip() or (
        f"[EzTech Test Nhắc Việc]\n"
        f"Chào {staff_name}, đây là tin nhắn kiểm tra kết nối nhắc hẹn & checklist từ Zalo Eztech Consultant.\n"
        f"👉 Truy cập Bảng tin: {get_dashboard_base_url(db)}/#/bulletin"
    )
    page_token = get_token_for_page(EZTECH_CONSULTANT_PAGE_ID)
    client = PancakeClient(api_token=page_token)
    res = client.send_message(
        page_id=EZTECH_CONSULTANT_PAGE_ID,
        conversation_id=staff.zalo_conversation_id,
        message=msg_text,
        action="reply_inbox",
    )
    ok = bool(res.get("success"))
    err = None if ok else str(res.get("message") or res.get("description") or "Gửi tin thất bại")
    db.add(
        ZaloReminderLog(
            dispatch_date=get_vn_now().strftime("%Y-%m-%d"),
            slot="manual",
            user_id=user.id,
            staff_id=staff.id,
            conversation_id=staff.zalo_conversation_id,
            message_text=msg_text,
            done_count=0,
            pending_count=0,
            status="SENT" if ok else "FAILED",
            error_message=err,
            sent_at=get_vn_now(),
        )
    )
    db.commit()
    return {
        "success": ok,
        "message": "Đã gửi tin nhắn Zalo thử nghiệm thành công!" if ok else f"Gửi thất bại: {err}",
    }


def compute_next_exact_due_at(db: Session, now_vn: Optional[datetime] = None) -> Optional[datetime]:
    """
    Tính mốc thời gian gần nhất cần đánh thức worker kiểm tra nhắc hẹn đúng giờ.
    Chỉ xét các nhắc hẹn thuộc nhân viên ĐÃ có Zalo conversation_id hợp lệ và chưa vượt quá MAX_EXACT_RETRIES,
    cộng thêm backoff 15 phút nếu lần gửi trước vừa lỗi → đảm bảo Neon ngủ đông tuyệt đối khi không có lịch đến hạn.
    """
    now = now_vn or get_vn_now()
    rows = (
        db.query(WorkReminder.remind_at, WorkReminder.exact_last_error_at)
        .join(AppUser, WorkReminder.owner_user_id == AppUser.id)
        .join(EztechStaff, EztechStaff.user_id == AppUser.id)
        .filter(
            WorkReminder.status == "pending",
            WorkReminder.notify_exact_time == True,
            WorkReminder.exact_notified_at.is_(None),
            WorkReminder.exact_retry_count < MAX_EXACT_RETRIES,
            WorkReminder.remind_at >= now - timedelta(hours=12),
            AppUser.is_active == True,
            EztechStaff.is_active == True,
            EztechStaff.zalo_conversation_id.isnot(None),
            EztechStaff.zalo_conversation_id != "",
        )
        .all()
    )
    candidates: List[datetime] = []
    for r_at, err_at in rows:
        if not r_at:
            continue
        effective = r_at
        if err_at is not None:
            backoff_at = err_at + timedelta(minutes=EXACT_RETRY_BACKOFF_MIN)
            if backoff_at > effective:
                effective = backoff_at
        candidates.append(effective)
    return min(candidates) if candidates else None


def start_exact_reminder_worker_if_enabled():
    """
    Khởi động luồng kiểm tra nhắc hẹn đúng giờ (mỗi 60s) khi tiến trình web đang chạy.
    Dùng cache mốc thời gian gần nhất trong RAM để KHÔNG truy vấn Neon khi chưa có nhắc hẹn tới giờ.
    """
    if os.getenv("DISABLE_EXACT_REMINDER_WORKER", "").strip().lower() in ("true", "1", "yes"):
        return

    def _loop():
        global _NEXT_EXACT_DUE_AT, _EXACT_CACHE_INITIALIZED
        while True:
            try:
                now_vn = get_vn_now()
                should_query = False
                with _EXACT_LOCK:
                    if not _EXACT_CACHE_INITIALIZED:
                        should_query = True
                    elif _NEXT_EXACT_DUE_AT is not None and now_vn >= _NEXT_EXACT_DUE_AT:
                        should_query = True

                if should_query:
                    with SessionLocal() as db:
                        dispatch_due_exact_reminders(db=db, dry_run=False)
                        next_due = compute_next_exact_due_at(db, now_vn=get_vn_now())
                        with _EXACT_LOCK:
                            _NEXT_EXACT_DUE_AT = next_due
                            _EXACT_CACHE_INITIALIZED = True
            except Exception as exc:
                logger.debug(f"Exact reminder worker tick error: {exc}")
            time.sleep(60)

    t = threading.Thread(target=_loop, daemon=True, name="ExactReminderWorker")
    t.start()
