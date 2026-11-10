import os
import sys
import re
from typing import Optional, List, Dict, Any, Set

# Đảm bảo in tiếng Việt an toàn trên console
try:
    if sys.stdout.encoding.lower() != 'utf-8':
        sys.stdout.reconfigure(encoding='utf-8')
    if sys.stderr.encoding.lower() != 'utf-8':
        sys.stderr.reconfigure(encoding='utf-8')
except Exception:
    pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd
from database.db import SessionLocal
from database.models import DimLead, FactLeadActivity, DealWin
from etl.utils import is_zalo_channel, build_pancake_url, resolve_canonical_page_name
from match_pancake_link import clean_phone


def run_filter(input_file: str, output_file: str):
    print(f"\n📂 Đang đọc dữ liệu từ: {input_file}")
    df = pd.read_csv(input_file)
    print(f"   Tổng số dòng dữ liệu ban đầu: {len(df):,}")

    df['_clean_sdt'] = df['SĐT'].apply(clean_phone)
    valid_phones = set(p for p in df['_clean_sdt'].dropna().unique() if p)
    print(f"   Số SĐT hợp lệ duy nhất: {len(valid_phones):,}")

    db = SessionLocal()
    da_la_hv_reasons: Dict[str, str] = {}
    all_assigned_fallback: Dict[str, str] = {}

    try:
        print("🔍 Đang quét SĐT có CHÍNH XÁC tag 'Đã là học viên'...")
        # CHỈ LỌC BỎ NHỮNG AI CÓ TAG 'Đã là học viên'
        rows_tag = (
            db.query(DimLead.phone_number, DimLead.page_id, FactLeadActivity.status_tag)
            .join(FactLeadActivity, DimLead.id == FactLeadActivity.lead_id)
            .filter(DimLead.phone_number.in_(valid_phones))
            .all()
        )
        for p, page_id, tag in rows_tag:
            if tag:
                tags = [t.strip().lower() for t in str(tag).split(',') if t.strip()]
                if 'đã là học viên' in tags:
                    pname = resolve_canonical_page_name(page_id)
                    da_la_hv_reasons[p] = f"Có tag: Đã là học viên (tại page {pname})"

        da_la_hv_phones = set(da_la_hv_reasons.keys())
        print(f"✅ Đã nhận diện {len(da_la_hv_phones):,} SĐT CÓ TAG 'Đã là học viên' (SẼ LỌC BỎ).")
        print(f"✅ Số SĐT GIỮ LẠI: {len(valid_phones - da_la_hv_phones):,} SĐT.")

        # Tra cứu hội thoại Pancake và NV được phân
        print("\n🔍 Đang tra cứu hội thoại Pancake và NV được phân cho các PAGE ZALO (pzl_)...")
        rows_conv = (
            db.query(
                DimLead.phone_number,
                DimLead.page_id,
                DimLead.customer_id,
                DimLead.first_created_at,
                DimLead.name,
                FactLeadActivity.conversation_id,
                FactLeadActivity.status_tag,
                FactLeadActivity.assigned_users
            )
            .join(FactLeadActivity, DimLead.id == FactLeadActivity.lead_id)
            .filter(DimLead.phone_number.in_(valid_phones))
            .order_by(DimLead.first_created_at.desc())
            .all()
        )

        zl_matched_data: Dict[str, List[Dict[str, Any]]] = {}
        for p, page_id, customer_id, first_created_at, name, conv_id, status_tag, assigned_users in rows_conv:
            assigned_str = (assigned_users or '').strip()
            if assigned_str and p not in all_assigned_fallback:
                all_assigned_fallback[p] = assigned_str

            # CHỈ LẤY CÁC PAGE ZALO
            if not is_zalo_channel(page_id, conv_id):
                continue

            url = build_pancake_url(conv_id, customer_id, page_id)
            page_name = resolve_canonical_page_name(page_id)
            date_str = first_created_at.strftime('%d/%m/%Y %H:%M') if first_created_at else ''

            item = {
                'link_pancake': url,
                'ten_khach': name or '',
                'page': page_name,
                'ngay_tao': date_str,
                'tag': status_tag or '',
                'assigned': assigned_str,
                'conversation_id': conv_id,
            }
            if p not in zl_matched_data:
                zl_matched_data[p] = []
            zl_matched_data[p].append(item)

        # Fallback thêm từ DealWin.care_by nếu có
        dw_care_rows = (
            db.query(DealWin.phone_number, DealWin.care_by)
            .filter(DealWin.phone_number.in_(valid_phones), DealWin.care_by != None)
            .all()
        )
        for p, care in dw_care_rows:
            if care and care.strip() and p not in all_assigned_fallback:
                all_assigned_fallback[p] = care.strip()

        print(f"✅ Có {len(zl_matched_data):,} SĐT có hội thoại Zalo trên Pancake.")

    finally:
        db.close()

    def get_zl_info(s, key, fallback=''):
        if not s or s not in zl_matched_data:
            return fallback
        return zl_matched_data[s][0].get(key, fallback)

    def get_zl_all_links(s):
        if not s or s not in zl_matched_data:
            return ''
        links = [it['link_pancake'] for it in zl_matched_data[s] if it.get('link_pancake')]
        unique_links = list(dict.fromkeys(links))
        return "\n".join(unique_links)

    def get_zl_count(s):
        if not s or s not in zl_matched_data:
            return 0
        return len(zl_matched_data[s])

    def get_assigned(s):
        if not s:
            return ''
        # 1. Ưu tiên lấy từ hội thoại Zalo (tìm hội thoại có nhân viên được gán)
        if s in zl_matched_data:
            for it in zl_matched_data[s]:
                if it.get('assigned'):
                    return it['assigned']
        # 2. Fallback từ các kênh hội thoại khác hoặc DealWin
        if s in all_assigned_fallback:
            return all_assigned_fallback[s]
        return ''

    # Gắn cột vào dữ liệu
    df['Tag_Da_La_Hoc_Vien'] = df['_clean_sdt'].apply(lambda s: 'Đã là học viên' if s in da_la_hv_phones else 'Không')
    df['Ly_Do_Loc'] = df['_clean_sdt'].apply(lambda s: da_la_hv_reasons.get(s, ''))
    df['NV được phân'] = df['_clean_sdt'].apply(get_assigned)
    df['Link_Pancake_ZL'] = df['_clean_sdt'].apply(lambda s: get_zl_info(s, 'link_pancake'))
    df['Ten_Pancake_ZL'] = df['_clean_sdt'].apply(lambda s: get_zl_info(s, 'ten_khach'))
    df['Page_Zalo'] = df['_clean_sdt'].apply(lambda s: get_zl_info(s, 'page'))
    df['Ngay_Hoi_Thoai_ZL'] = df['_clean_sdt'].apply(lambda s: get_zl_info(s, 'ngay_tao'))
    df['Trang_Thai_Tag_ZL'] = df['_clean_sdt'].apply(lambda s: get_zl_info(s, 'tag'))
    df['So_Hoi_Thoai_ZL'] = df['_clean_sdt'].apply(get_zl_count)
    df['Tat_Ca_Link_ZL'] = df['_clean_sdt'].apply(get_zl_all_links)

    df.drop(columns=['_clean_sdt'], inplace=True, errors='ignore')

    # Định vị cột: Đưa cột 'NV được phân' lên trước Link Pancake để người dùng xem dễ nhất
    desired_cols = [
        'Họ và tên', 'SĐT', 'Vị trí ngành nghề', 'NV được phân',
        'Link_Pancake_ZL', 'Ten_Pancake_ZL', 'Page_Zalo', 'Ngay_Hoi_Thoai_ZL',
        'Trang_Thai_Tag_ZL', 'So_Hoi_Thoai_ZL', 'Tat_Ca_Link_ZL'
    ]

    # 1. Bị loại (Chỉ những ai có tag 'Đã là học viên')
    df_excluded = df[df['Tag_Da_La_Hoc_Vien'] == 'Đã là học viên'].copy()
    excluded_cols = desired_cols + ['Tag_Da_La_Hoc_Vien', 'Ly_Do_Loc']
    df_excluded = df_excluded[[c for c in excluded_cols if c in df_excluded.columns]]

    # 2. Giữ lại (Tất cả còn lại)
    df_kept = df[df['Tag_Da_La_Hoc_Vien'] == 'Không'].copy()
    df_kept = df_kept[[c for c in desired_cols if c in df_kept.columns]]

    # 3. Danh sách Giữ lại và ĐÃ CÓ LINK ZALO (để mở chat liền)
    df_kept_has_zl = df_kept[df_kept['Link_Pancake_ZL'].notna() & (df_kept['Link_Pancake_ZL'] != '')].copy()

    print(f"\n📊 KẾT QUẢ CUỐI CÙNG:")
    print(f"   - Tổng số dòng giữ lại: {len(df_kept):,} dòng")
    print(f"     + ĐÃ CÓ LINK ZALO: {len(df_kept_has_zl):,} dòng (mở chat Pancake ZL ngay)")
    assigned_count = (df_kept_has_zl['NV được phân'] != '').sum()
    print(f"     + Đã có thông tin NV được phân: {assigned_count:,} / {len(df_kept_has_zl):,} ({assigned_count / len(df_kept_has_zl) * 100:.1f}%)")
    print(f"     + Chưa có hội thoại Zalo: {len(df_kept) - len(df_kept_has_zl):,} dòng")
    print(f"   - Bị lọc bỏ (chỉ tag 'Đã là học viên'): {len(df_excluded):,} dòng ({len(da_la_hv_phones)} SĐT)")

    with pd.ExcelWriter(output_file, engine='openpyxl') as writer:
        df_kept_has_zl.to_excel(writer, sheet_name='Giu_Lai_Co_Link_ZL', index=False)
        df_kept.to_excel(writer, sheet_name='Toan_Bo_Danh_Sach_Giu_Lai', index=False)
        df_excluded.to_excel(writer, sheet_name='Loc_Bo_Tag_Da_La_HV', index=False)

    print(f"\n🎉 Đã xuất kết quả thành công ra:")
    print(f"👉 {os.path.abspath(output_file)}\n")


if __name__ == '__main__':
    run_filter('danh_sach_sdt_check.csv', 'danh_sach_sdt_chua_la_hv_page_zl.xlsx')
