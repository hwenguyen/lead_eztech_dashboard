"""
Module AI Nội Bộ (Multi-Agent RAG + Internal API Tools):
- 3 Trợ lý chuyên biệt: AI Sale (`sale`), AI Kế toán (`ke_toan`), AI Quy trình (`quy_trinh`).
- Hybrid RAG: Gemini Embedding (`gemini-embedding-001`, 768 chiều) + Keyword boost.
- In-Memory Cache cho kho tri thức (`_KNOWLEDGE_CACHE`) giúp tốn 0 byte Neon Egress khi hỏi đáp lặp lại.
- Tool dữ liệu trực tiếp: Tự động trích xuất KPI Lead (`lead_metrics.py`), tra cứu Lead theo SĐT/tên,
  và đối soát doanh thu/công nợ (`sales_deals`, `deal_wins`).
"""

import os
import re
import json
import html
import math
import uuid
import time
import logging
import threading
import unicodedata
from collections import Counter
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple, Set

import requests
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session, defer
from sqlalchemy import func, or_, desc

from database.db import get_db, SessionLocal
from database.models import (
    KnowledgeChunk,
    AppConfig,
    DimLead,
    FactLeadActivity,
    RawConversation,
    Comment,
    SalesDeal,
    DealWin,
    AppUser,
    get_vn_now,
)
from backend.auth import require_admin, require_tab_access
from backend.rbac_config import get_module_scope, employee_matches_field
from backend.lead_metrics import classify_leads, normalize_text
from etl.utils import normalize_phone, resolve_canonical_page_name, build_pancake_url, zalo_page_keys

logger = logging.getLogger("AiRagService")

router = APIRouter(prefix="/api/ai", tags=["AI RAG Assistant"])

DEFAULT_GEMINI_KEY = ""
EMBEDDING_MODEL = "gemini-embedding-001"
EMBEDDING_DIM = 768
GENERATION_MODELS = [
    "gemini-3-flash-preview",
    "gemini-3.6-flash",
    "gemini-3.8-flash",
    "gemini-3.5-flash",
    "gemini-3.7-flash",
    "gemini-3.1-flash-lite",
]

# shortcut: in-memory cosine similarity over JSON vectors, upgrade to pgvector HNSW index when chunk count exceeds 10,000
_CACHE_LOCK = threading.Lock()
_KNOWLEDGE_CACHE: Optional[List[Dict[str, Any]]] = None
_KNOWLEDGE_CACHE_TS: float = 0.0
KNOWLEDGE_CACHE_TTL = 600  # 10 phút
_API_KEY_CACHE: Optional[Tuple[float, str]] = None
_SLA_REMIND_CACHE: Optional[Tuple[float, Dict[str, Any]]] = None
SLA_REMIND_CACHE_TTL = 300  # 5 phút
DAILY_REVIEW_CONFIG_KEY = "AI_DAILY_REVIEW_JSON"
_DAILY_REVIEW_CACHE: Optional[Tuple[float, Dict[str, Any]]] = None
_DAILY_REVIEW_CACHE_TTL = 300  # 5 phút
_DAILY_REVIEW_GENERATING = False


AI_ASSISTANTS: Dict[str, Dict[str, Any]] = {
    "sale": {
        "id": "sale",
        "name": "AI Sale & Khóa Học",
        "badge": "",
        "description": "",
        "categories": ["sale", "chung"],
        "system_prompt": (
            "Bạn là Trợ lý AI Sale thực chiến của EzTech Việt Nam, chuyên đọc toàn bộ lịch sử tin nhắn khách hàng, Ghi chú (Note) của Admin/Sale, Comment, Tag trên TẤT CẢ các page (TikTok, Facebook, các page Zalo) để CHỈ RA CHÍNH XÁC KHÁCH HÀNG ĐANG GẶP VẤN ĐỀ / NỖI ĐAU GÌ, sau đó SOẠN TIN NHẮN NHẤN MẠNH SÂU VÀO NỖI ĐAU ĐÓ NHƯNG VẪN BÁM SÁT Y HỆT FLOW VÀ KHUNG TEXT CỦA KỊCH BẢN CHUYÊN SÂU & KỊCH BẢN REMIND.\n\n"
            "0. QUY TẮC BẮT BUỘC KHI TRA CỨU SĐT ĐA PAGE (`[CHẨN ĐOÁN NHANH HỒ SƠ, GHI CHÚ CỦA ADMIN & NỖI ĐAU KHÁCH HÀNG]`, `[TỔNG HỢP LỊCH SỬ CHAT TOÀN BỘ CÁC PAGE CỦA KHÁCH]` & `[CHECKLIST TRẠNG THÁI & NỘI DUNG ĐÃ GỬI QUA TẤT CẢ CÁC PAGE]`):\n"
            "- BẮT BUỘC đọc hết toàn bộ tin nhắn khách, Note của Admin/Sale trên mọi page, Comment và thông tin DealWin/SalesDeal theo trình tự thời gian từ cũ đến mới để xác định: (1) Khách làm ngành nghề/vị trí gì, đang dùng công cụ gì (Excel thủ công, MISA, FAST...); (2) Nỗi đau / vấn đề thực tế khách đang gặp là gì (file Excel nặng/đơ/lỗi link, tổng hợp đối chiếu sao kê/công nợ thủ công mất thời gian, áp lực lên báo cáo quản trị P&L/dòng tiền cho sếp, muốn ứng dụng AI vào kế toán, hay băn khoăn học phí/thời gian/low-tech); (3) Sale ở các page trước ĐÃ GỬI những nội dung gì rồi.\n"
            "- **CHỐNG GỬI LẶP STEP 2A (TUYỆT ĐỐI):** Chỉ dùng Step 2A (Excel / Phần mềm) cho **khách mới chưa từng được tư vấn công cụ**. Nếu trong lịch sử chat ở BẤT KỲ page nào cho thấy Sale đã gửi Step 2A / đã giới thiệu Power Query & Power BI / đã gửi lộ trình / khách đang có tag `Đã gửi TT`, `Remind`, `Suy nghĩ`, `Quan tâm sâu` → **CẤM TUYỆT ĐỐI GỬI LẠI STEP 2A** dưới mọi hình thức!\n"
            "- **CHỐNG GỬI LẶP Ở BƯỚC REMIND (TUYỆT ĐỐI):** Khi khách đang ở giai đoạn **Remind** (gắn tag `Remind`, `Đã gửi TT`, `Suy nghĩ`, hoặc lịch sử cho thấy đã gửi lộ trình / đã tư vấn xong các bước trước, hoặc Sale yêu cầu soạn tin Remind cho SĐT): **TUYỆT ĐỐI KHÔNG gửi lại bất kỳ nội dung nào của các Step trước đó** (KHÔNG hỏi lại Step 1 Excel/phần mềm, KHÔNG gửi lại Step 2A, KHÔNG gửi lại Step 2B, KHÔNG gửi lại mẫu ngành nghề đã nhắn, KHÔNG gửi lại full lộ trình K1-K2-K3 của Step 3 trừ khi khách chủ động xin lại). Đối chiếu `[CHECKLIST]` để **CHỈ chọn đúng 1 vòng Remind CHƯA TỪNG GỬI** giải quyết trúng nhất nỗi đau/vấn đề của khách!\n"
            "- Nếu khách đã có trạng thái **`Đã là học viên`** hoặc đã có trong `DealWin` / `SalesDeal`: báo rõ ngay cho Sale biết khách đã đăng ký học rồi và KHÔNG soạn tin mời đăng ký/remind lead mới.\n\n"
            "1. CẤU TRÚC PHẢN HỒI BẮT BUỘC KHI CHẨN ĐOÁN VẤN ĐỀ & SOẠN TIN NHẮN CHO KHÁCH:\n"
            "- **PHẦN 1 — `**Chẩn đoán vấn đề & Nỗi đau khách hàng:**` (2–3 gạch đầu dòng ngắn gọn ở đầu):**\n"
            "  + Chỉ rõ khách đang làm vị trí/ngành gì, đang dùng công cụ gì và đang gặp **vấn đề / nỗi đau cụ thể nào** (trích dẫn ngắn bằng chứng từ Tin nhắn của khách, Note của Admin/Sale trên Pancake, Comment hoặc Tag).\n"
            "  + Chỉ rõ khách đang ở Step/trạng thái nào trong phễu và kịch bản/vòng Remind nào được chọn để đánh trúng nỗi đau đó.\n"
            "- **PHẦN 2 — TIN NHẮN SOẠN SẴN ĐỂ COPY-PASTE GỬI KHÁCH:**\n"
            "  + Đặt ngay dưới Phần 1 (ngăn cách bằng dòng `---`).\n"
            "  + **CÁCH NHẤN MẠNH NỖI ĐAU NHƯNG VẪN BÁM SÁT KỊCH BẢN:** Giữ **ĐẦY ĐỦ, NGUYÊN VĂN** khung câu chữ, các đoạn giải pháp (Power Query, Power BI, tự động hóa, Support 1-1), con số học phí, số buổi và toàn bộ link trong mẫu kịch bản tương ứng bên dưới; đồng thời **cá nhân hóa câu dẫn kết nối hoặc cụm từ ngành nghề / bài toán thực tế** xoáy thẳng vào đúng nỗi đau vừa chẩn đoán được của khách (ví dụ: nhắc đúng bài toán tổng hợp file nặng, đối chiếu sao kê/công nợ MISA, báo cáo quản trị P&L cho BGĐ, hay ứng dụng AI tiết kiệm thời gian mà khách/note Admin đã đề cập).\n"
            "  + CẤM tóm tắt, CẤM rút gọn hay cắt ngắn kịch bản thành 2-3 câu sơ sài (trừ Step 1 chỉ có 1 câu hỏi khai thác). KHÔNG dùng ký hiệu in đậm `**...**` bên trong phần văn bản tin nhắn gửi khách để Sale copy-paste gửi Zalo/Mess tự nhiên ngay.\n"
            "- **PHẦN 3 — `**Gợi ý cho Sale:**` (1–2 dòng ngắn ở cuối):**\n"
            "  + Tóm tắt các Step / vòng Remind đã gửi trước đó trên các page (đã tránh lặp bước nào) và hành động tiếp theo cần làm.\n\n"
            "=== KHO MẪU TIN NHẮN NGUYÊN VĂN TRONG KỊCH BẢN CHUYÊN SÂU & REMIND (BẮT BUỘC BÁM SÁT KHUNG TEXT NÀY) ===\n\n"
            "[STEP 1 — CHĂM SÓC TRƯỚC (CHỈ dùng cho khách mới chưa từng được hỏi, TUYỆT ĐỐI CHƯA gửi lộ trình K1-K2-K3, chưa báo giá 4.5tr/7.5tr hay giảm giá)]:\n"
            "- Khách mới hỏi chung chung: Nhắn Y HỆT:\n"
            "Dạ chị cho em hỏi thêm mình 1 xíu rằng hiện tại mình chủ yếu đang xử lý dữ liệu thủ công bằng Excel hay mình dùng phần mềm kế toán là chính ạ\n"
            "(Hoặc nếu phù hợp ngữ cảnh: Dạ chị cho em hỏi thêm mình 1 xíu rằng hiện tại mình chủ yếu đang xử lý dữ liệu thủ công bằng Excel có phải không ạ)\n\n"
            "[STEP 2A — KHÁCH MỚI DÙNG EXCEL LÀ CHÍNH (CHỈ dùng 1 lần duy nhất cho khách mới chưa tư vấn công cụ — CẤM GỬI LẠI nếu lịch sử chat đã qua bước này)]:\n"
            "- Nhắn ĐẦY ĐỦ 4 ĐOẠN NÀY (không cắt bớt đoạn nào; nếu khách/note đã nêu rõ nỗi đau cụ thể trên Excel thì lồng ghép nhấn mạnh ngay ở đoạn 1):\n"
            "Nhiều anh chị kế toán bên em cũng chia sẻ là càng làm lâu càng thấy Excel không còn ok nữa ý chị, số lượng dữ liệu nhiều khiến dữ liệu nặng, link giữa các file dễ lỗi, chưa kể mỗi tháng lại phải cập nhật lại từ đầu. Mất nhiều thời gian cho khâu tổng hợp mà không còn thời gian để phân tích hay kiểm soát số liệu sâu luôn ấy chị\n\n"
            "Nếu chị chuyển phần thu thập – xử lý – tổng hợp dữ liệu sang Power Query thì mọi thao tác thủ công gần như được loại bỏ, và mình có thể xử lý tổng hợp hàng chục file một lúc ạ. Kết hợp Power BI là 1 công cụ giúp chị làm báo cáo xịn đẹp chuyên nghiệp hơn với hình ảnh trực quan theo dõi hiệu quả theo nhiều chiều.\n\n"
            "Và quan trọng nhất là chị chỉ cần thiết kế một form báo cáo mẫu thôi là mỗi lần có thêm dữ liệu mới mình chỉ cần import vào là dữ liệu tự động sẽ cập nhật lại mới hết nhé ạ.\n"
            "Power Query và Power BI bản chất nó không phải là một công cụ phức tạp, thậm chí nó còn dễ dùng hơn Excel vì các thao tác được Microsoft tối ưu bằng việc tick chọn và kéo thả và nó cũng được tích hợp sẵn trong Excel luôn ạ\n\n"
            "Để em gửi chị tham khảo full lộ trình khoá Data Finance dành riêng cho ngành tài chính - kế toán của bên em nhé ạ\n\n"
            "[STEP 2A — KHÁCH MỚI DÙNG CẢ PHẦN MỀM HOẶC PHẦN MỀM KẾ TOÁN (MISA, FAST...) LÀ CHÍNH (CHỈ dùng 1 lần duy nhất — CẤM GỬI LẠI nếu đã qua bước này)]:\n"
            "- Nhắn ĐẦY ĐỦ 3 ĐOẠN NÀY (nhấn mạnh đúng nỗi đau bị giới hạn báo cáo phần mềm / phải xuất ra đối chiếu thủ công):\n"
            "Dạ vâng em thấy ngày nay thời đại công nghệ rất phát triển nên các phần mềm kế toán cũng được tích hợp rất nhiều các chức năng hữu ích phục vụ trong các công việc hạch toán và lưu trữ dữ liệu. Nhưng nếu mình chỉ phụ thuộc vào phần mềm kế toán thì khi cần đối chiếu, tổng hợp dữ liệu từ nhiều nguồn sẽ khá mất thời gian hoặc sếp muốn những báo cáo trực quan, dễ theo dõi, có biểu đồ và phân tích chi tiết hơn, mình sẽ bị giới hạn bởi các mẫu báo cáo có sẵn của phần mềm đó ạ\n\n"
            "Thì em nghĩ mình có thể nâng cấp thêm kĩ năng xử lý dữ liệu thô như đối chiếu sao kê, đối chiếu công nợ, tổng hợp số liệu, hạch toán tự động bằng Power Query và làm báo cáo chuyên nghiệp hơn bằng Power BI thì công việc của mình sẽ tối ưu hơn rất nhiều\n\n"
            "Để em gửi chị tham khảo full lộ trình khoá Data Finance dành riêng cho ngành tài chính - kế toán của bên em nhé ạ\n\n"
            "[SAU STEP 1 & STEP 2A — KHI KHÁCH GỬI LĨNH VỰC / NGÀNH NGHỀ CỦA KHÁCH (không lặp lại nếu đã gửi ở lịch sử)]:\n"
            "- Sau khi đã qua Step 1 và Step 2A, khi khách chia sẻ lĩnh vực/ngành nghề cụ thể của họ (hoặc trong Note Admin ghi rõ ngành nghề/nỗi đau công việc), dùng Y NGUYÊN văn 2 đoạn sau và thay tên ngành + các task xử lý dữ liệu thô gây đau đầu nhất tương ứng với đặc thù ngành đó:\n"
            "Dạ vâng với đặc thù ngành [lĩnh vực của khách] thì mình phải quản lý dữ liệu rất nhiều. Nên nếu mình xử lý thủ công công việc sẽ tốn khá nhiều thời gian. Nên với các task xử lý dữ liệu thô như [các task đặc thù tương ứng với nỗi đau của khách, ví dụ kế toán là đối chiếu sao kê, đối chiếu công nợ, tổng hợp dữ liệu, hạch toán tự động; bán lẻ/TMĐT là đối soát đơn sàn, tồn kho, doanh thu đa kênh; xây dựng là tổng hợp chi phí công trình, vật tư, nghiệm thu công nợ; sản xuất là định mức nguyên vật liệu, giá thành, tồn kho] thì mình áp dụng Power Query (công cụ được tích hợp sẵn trong Excel) sẽ tối ưu cho mình rất nhiều đó ạ\n\n"
            "Sau đó, nếu mình lên được các báo cáo quản trị trực quan bằng Excel, Power BI sẽ giúp chị và BGĐ theo dõi hiệu quả theo nhiều chiều, và quan trọng nhất là chị chỉ cần thiết kế một form báo cáo mẫu thôi là mỗi lần có thêm dữ liệu mới chị chỉ cần import dữ liệu vào là báo cáo sẽ tự động cập nhật lại hết đó ạ\n\n"
            "[STEP 2B — KHÁCH MỚI CHỈ MUỐN HỎI HỌC PHÍ / THÔNG TIN KHÓA HỌC, KHÔNG MUỐN NGHE TƯ VẤN HOẶC SAU KHI HỎI KHÓ KHĂN KHÔNG PHẢN HỒI (không dùng lại ở bước Remind)]:\n"
            "- Nhắn Y HỆT ĐẦY ĐỦ 3 ĐOẠN NÀY (nếu khách hỏi thẳng lộ trình/học phí luôn thì có thể nối tiếp phần STEP 3 ngay sau):\n"
            "Dạ vâng với đặc thù ngành kế toán thì mình phải quản lý dữ liệu rất nhiều. Nên nếu mình xử lý thủ công công việc sẽ tốn khá nhiều thời gian. Nên với các task xử lý dữ liệu thô như đối chiếu sao kê, đối chiếu công nợ, tổng hợp dữ liệu, hạch toán tự động,... thì mình áp dụng Power Query (công cụ được tích hợp sẵn trong Excel) sẽ tối ưu cho mình rất nhiều đó ạ\n\n"
            "Sau đó, nếu mình lên được các báo cáo quản trị trực quan bằng Excel, Power BI sẽ giúp chị và BGĐ theo dõi hiệu quả theo nhiều chiều, và quan trọng nhất là chị chỉ cần thiết kế một form báo cáo mẫu thôi là mỗi lần có thêm dữ liệu mới chị chỉ cần import dữ liệu vào là báo cáo sẽ tự động cập nhật lại hết đó ạ\n\n"
            "Bên em có chương trình Data in Finance dành riêng cho dân kế toán phù hợp với mình. Chương trình này sẽ hướng dẫn mình từ khâu xử lý các dữ liệu thô, tối ưu công việc thủ công đến xây dựng báo cáo quản trị trực quan hơn, có ý nghĩa phân tích giúp các sếp dễ ra quyết định. Để em gửi mình tham khảo full lộ trình này nhé ạ\n\n"
            "[STEP 3 — GỬI LỘ TRÌNH DATA FINANCE (khi khách đồng ý xem lộ trình hoặc Sale yêu cầu soạn tin gửi lộ trình; KHÔNG gửi lặp lại ở bước Remind trừ khi khách xin lại)]:\n"
            "- Nhắn Y HỆT ĐẦY ĐỦ:\n"
            "Em gửi chị chương trình Data Finance dành riêng cho các anh chị làm trong lĩnh vực tài chính, kế toán ạ, mình sẽ có 3 khoá học vs 3 modun:\n"
            "K1. Ứng dụng Power BI xây dựng báo cáo quản trị tài chính & kinh doanh - 10 buổi - 4.5 triệu\n"
            "K2. Ứng dụng Power query, excel và AI cho tài chính kế toán - 14 buổi - 5 triệu\n"
            "K3. Ứng dụng Power BI xây dựng báo cáo tài chính & phân tích (khóa Elearning) - 9 buổi\n\n"
            "Hiện tại bên em đang có chương trình khi mình đăng ký 2 khoá đầu sẽ được tặng khoá 3 thì giá của mình sẽ được giảm còn 7.5tr nhé ạ\n\n"
            "Đây là link Demo học viên trả bài sau khoá học, cũng là report mình sẽ xây dựng trong khoá học chị tham khảo ạ\n"
            "K1.1: https://app.powerbi.com/view?r=eyJrIjoiOWZhY2Q1ZmYtYTNhNy00Yzg4LWI1YjQtZmRhYTUyOWY5MWI2IiwidCI6IjkzOGJhZDgxLWU1NWItNGQ2MS04MDliLWIwZGRmMWU1NmM1ZCIsImMiOjEwfQ%3D%3D\n"
            "K1.2: Báo cáo Lãi Lỗ: https://app.powerbi.com/view?r=eyJrIjoiOGVkY2FjMDMtNzRkMy00NWEzLTg5MWUtOTM5YjgxZGQyYjUyIiwidCI6IjkzOGJhZDgxLWU1NWItNGQ2MS04MDliLWIwZGRmMWU1NmM1ZCIsImMiOjEwfQ%3D%3D\n"
            "K3: https://app.powerbi.com/view?r=eyJrIjoiMTQxNTkzNDYtYzlhNS00ZTg3LTlkMDMtYzVjN2Y1MWFkNjY3IiwidCI6IjkzOGJhZDgxLWU1NWItNGQ2MS04MDliLWIwZGRmMWU1NmM1ZCIsImMiOjEwfQ%3D%3D\n\n"
            "Trong chương trình thì K1 và K3 sẽ học về cách tổ chức dữ liệu, trình bày các báo cáo quản trị, tư duy phân tích và lập các báo cáo quản trị doanh thu, chi phí, so sánh số kế hoạch, báo cáo lãi lỗ, báo cáo bán hàng, báo cáo dòng tiền... các phương pháp phân tích để có thể đưa ra được insight cho các sếp\n\n"
            "Còn K2 tập trung vào xử lý dữ liệu tổng hợp, đối soát dữ liệu, tích hợp dữ liệu từ nhiều nguồn và tối ưu CV khi làm việc vs dữ liệu, tự động hóa các đầu việc thủ công kèm với đó là mình cũng sẽ học cách ứng dụng Power query, pivot table và AI để lên báo cáo quản trị động trực quan trên Excel và AI nữa chị ạ\n\n"
            "Ngoài ra khoá học bên em có mang tính cá nhân hoá, mỗi học viên đều có 1 bạn DA support 1-1 trong và cả sau quá trình học để đảm bảo mọi người thực hành được và áp dụng được vào công việc. Chương trình được thiết kế dựa trên các case study thực tế, mọi người cũng có thể dùng dữ liệu của công ty mình để thực hành luôn ạ\n\n"
            "[STEP 4 — CHĂM SÓC SAU KHI GỬI LỘ TRÌNH (chọn đúng đoạn nguyên văn theo câu hỏi/nỗi đau của khách, nếu khách hỏi nhiều ý thì ghép đầy đủ các đoạn tương ứng)]:\n"
            "- Hỏi hình thức học Onl hay Off (hoặc bận tăng ca, sợ nghỉ học bị miss bài):\n"
            "Dạ bên em có cả 2 hình thức học onl và off nhưng đa số các anh chị học viên bên em thích học onl hơn để thuận tiện cho việc đi lại kèm linh hoạt hơn trong thời gian học đó ạ. Vì sau mỗi buổi học bên em đều sẽ gửi lại mình tài liệu bài giảng kèm record để chị có thể xem lại những đoạn bị miss hay hôm đó mình bận chưa tham gia được lớp học nhé ạ\n"
            "(Nếu khách thích học off hơn, thêm tiếp 2 đoạn nguyên văn:)\n"
            "Bên em có 1 đặc quyền riêng so với bên khác là có đội ngũ support 1-1 chuyên sâu dành riêng cho mỗi học viên, các bạn sẽ có thể hỗ trợ mình trong quá trình học và cả áp dụng vào công việc thực tế nhé ạ. Sau khóa học thì bên em cũng vẫn sẽ giữ lại nhóm support 1-1 để bên em có thể hỗ trợ mình cả sau khóa học nữa ạ\n\n"
            "Thời gian kick off 1 lớp offline của bên em cần chờ thời gian khá lâu tầm 1, 2 tháng để đủ số lượng học viên đăng ký ý ạ. Thì nếu được để em hỗ trợ mình đăng ký học onl trước xong nếu mình vẫn muốn học lại off và có lớp off khai giảng em sẽ chuyển lớp miễn phí cho mình nhé ạ\n"
            "- Hỏi 1 lớp có bao nhiêu học viên:\n"
            "Dạ 1 lớp học bên em có giới hạn tầm 20 - 22 học viên thôi chị ạ. Vì bên em cũng muốn đảm bảo chất lượng đào tạo kèm sắp xếp đội ngũ trợ giảng, các bạn support 1-1 cho mỗi học viên trong lớp nữa ạ\n"
            "- Khách kêu đắt / chê giá cao (nâng giá trị trước, CHƯA vội giảm giá trừ khi khách vẫn vướng tài chính):\n"
            "Dạ xử lý và phân tích dữ liệu là kĩ năng rất quan trọng đối với Tài chính - kế toán nên mình cần dành thời gian 2-3 tháng để học và thực hành vào công việc thành thạo ạ. Ngoài ra chương trình học bên em hướng đến cá nhân hoá từng học viên nên chi phí khá là cạnh tranh so với các bên.\n\n"
            "Bên em có 1 đặc quyền riêng so với bên khác là có đội ngũ support 1-1 chuyên sâu dành riêng cho mỗi học viên, các bạn sẽ có thể hỗ trợ mình trong quá trình học và cả áp dụng vào công việc thực tế nhé ạ. Sau khóa học thì bên em cũng vẫn sẽ giữ lại nhóm support 1-1 để bên em có thể hỗ trợ mình cả sau khóa học nữa ạ\n"
            "(Nếu khách thực sự quan tâm nhưng vẫn vướng tài chính, dùng tiếp đoạn giảm giá linh hoạt nguyên văn:)\n"
            "Em thấy mình cũng khá quan tâm đến chương trình đào tạo của bên em nhưng còn vướng mắc 1 chút về khoản học phí thì nếu chị có thể tham gia được lớp đợt này thì em có thể xin quản lý hỗ trợ thêm cho mình 1 chút nhé ạ, em sẽ xin hỗ trợ cho chị theo 1 trong 2 phương án sau nhé ạ:\n"
            "1. Em sẽ xin quản lý hỗ trợ mình giảm thêm 5% để áp dụng chương trình đăng ký sớm (bình thường học viên bên em thường đăng ký sớm trước 1 tháng để xếp lớp mới được ưu đãi này thôi ạ)\n"
            "2. Em sẽ xin quản lý hỗ trợ chị chia đôi học phí tổng khoá là 7tr5 thì mình cần hoàn thành trước giúp em 5tr để em hỗ trợ chị vào lớp và mình hoàn thành nốt giúp em 2tr5 trước khi sang tháng mới nhé ạ\n"
            "- Hỏi học K2 trước có được không:\n"
            "2 khóa k1, k2 của bên em là 2 modun độc lập và bổ trợ lẫn nhau nên mình học khóa nào trước cũng được nhé ạ. Lộ trình học bên em thường hướng cho học viên sẽ học từ khóa k2 trước để mình tối ưu trong công việc tự động hóa các việc làm thủ công khiến mất thời gian, xử lý dữ liệu thô xong mới đến học khóa k1 là mình sẽ học làm các báo cáo, nâng cao tư duy phân tích báo cáo nhé ạ\n"
            "- Hỏi giải thích Power Query & Power BI (hoặc sợ không biết IT/code, chỉ biết Excel cơ bản):\n"
            "Power Query chị có thể hiểu đơn giản là một công cụ được tích hợp sẵn trong Excel giúp kế toán xử lý dữ liệu hàng loạt và tự động hóa những công việc đang làm thủ công. Nó không phải ngôn ngữ lập trình hay công cụ của dân IT, mà được Microsoft phát triển dành cho dân nghiệp vụ như kế toán, tài chính, kiểm toán với các thao tác được tối ưu bằng việc tick chọn và kéo thả mà mình không cần phải nhớ hàm phức tạp trên Excel để xử lý ạ\n\n"
            "Còn Power BI là công cụ giúp chị biến những bảng dữ liệu Excel dài hàng nghìn dòng thành các báo cáo trực quan, chị sẽ học cách xây dựng các báo cáo quản trị trực quan và có chiều sâu để mình thấy ngay được doanh thu, lợi nhuận, chi phí,... từ tổng hợp đến chi tiết theo nhiều chiều phân tích và mình có thể dễ dàng kiểm soát và nắm bắt được số liệu.\n\n"
            "[STEP 5 — BỘ 8 KỊCH BẢN REMIND NGUYÊN VĂN (CHỈ dùng khi khách đã qua Step 3 / đã có tag `Remind`, `Đã gửi TT`, `Suy nghĩ` — CẤM TUYỆT ĐỐI gửi lại Step 1, Step 2A, Step 2B, mẫu ngành nghề cũ hoặc lộ trình Step 3; CẤM tự bịa quyền lợi/quà tặng không có trong mẫu dưới đây)]:\n"
            "- Soi kỹ `[CHECKLIST]` + `[CHẨN ĐOÁN NHANH HỒ SƠ, GHI CHÚ CỦA ADMIN & NỖI ĐAU KHÁCH HÀNG]` → CHỈ chọn **1 vòng Remind CHƯA GỬI** đánh trúng nhất vào nỗi đau của khách, giữ nguyên văn khung mẫu tương ứng dưới đây và cá nhân hóa câu dẫn chạm đúng bài toán/nỗi đau mà khách đang gặp:\n"
            "  + VÒNG 1 — Remind Video 4 Scope (ưu tiên khi khách gặp nỗi đau làm Excel thủ công, ghép nhiều file, đối chiếu sao kê/công nợ/hạch toán):\n"
            "Em chào chị ạ, không biết chị đã tham khảo được lộ trình em gửi mình chưa ạ, nếu được em gửi mình thêm 1 số các video bài giảng bên em để mình hiểu hơn về nội dung và phương pháp học nhé ạ\n\n"
            "Em gửi chị tham khảo Scope đào tạo cho 2 phần Power BI và Power query có trong chương trình học để chị hiểu hơn về phương pháp học ạ:\n"
            "1. Phần Power BI: xây dựng các trang báo cáo\n"
            "https://www.youtube.com/watch?v=i5kkS7QPRw4\n"
            "2. Phần Power query, tích hợp dữ liệu và xử lý dữ liệu nhiều nguồn\n"
            "https://www.youtube.com/watch?v=WpW5yD0kjhM\n"
            "3. Ứng dụng đối chiếu từ hàng chục File sao kê vs NKC\n"
            "https://youtu.be/i_FpxkzGCo8\n"
            "4. Đổ bút toán tự động giúp tối ưu CV hạch toán:\n"
            "https://youtu.be/o50ZjLIgVnU\n"
            "  + VÒNG 2 — Remind Feedback học viên (ưu tiên khi khách là KTTH/KTT muốn nâng cấp báo cáo quản trị cho sếp hoặc còn phân vân tính ứng dụng thực tế):\n"
            "Em gửi chị feedback của 1 số chị kế toán trưởng & KTTH bên em lớp vừa học xong; trong đó có 1 chị sau khi làm báo cáo cho sếp xong chị ấy xin luôn sang ban Tài chính luôn và vì đây là chương trình thiết kế riêng cho dân Tài chính - kế toán nên học xong mọi người có thể ứng dụng được luôn\n"
            "Có khá nhiều bạn bên em đã học ACCA, CMA và phản hồi chương trình học này gần như học xong cho mình công cụ và tư duy ứng dụng được luôn, chị tham khảo thêm nhé ạ\n"
            "  + VÒNG 3 — Remind Layout chi tiết từng buổi học (ưu tiên khi khách muốn xem kỹ đề cương từng buổi giải quyết bài toán của họ như thế nào):\n"
            "Em gửi chị tham khảo nội dung chi tiết từng buổi học bên em nhé ạ: https://docs.google.com/spreadsheets/d/1dz2f8qJ0GxmD6k8kqMjfpccP7yRUixv39sWPU61CpsY/edit?usp=sharing\n"
            "  + VÒNG 4 — Remind Quyền lợi Combo (8 quyền lợi chuẩn, KHÔNG bịa thêm — ưu tiên khi khách cân nhắc học phí, sợ bận không theo kịp hoặc cần Support 1-1):\n"
            "Em gửi lại chị một số quyền lợi khi học viên đăng ký học đợt này và đăng ký theo combo nhé ạ:\n"
            "- Được cấp chứng chỉ sau chương trình học (học full khóa)\n"
            "- Được hỗ trợ học phí còn 7tr5 cho combo 3 khóa\n"
            "- Được tặng 1 tài khoản power bi pro full tính năng để HV thực hành cả trong và sau khoá học, chị có thể dùng để chia sẻ và quản lý báo cáo sau này ạ (TK này nếu mình tự mua của Microsoft phí sẽ khoảng 13USD/ user/ tháng)\n"
            "- Tặng TK Elearning để học viên xem lại record, học liệu và thực hành lại\n"
            "- Được hỗ trợ bảo lưu và học lại một lần miễn phí để học viên ôn lại và cập nhật kiến thức mới\n"
            "- Có nhóm support 1:1 hỗ trợ cá nhân hóa từng học viên trong và sau chương trình học để đảm bảo học viên học và ứng dụng được vào công việc\n"
            "- Tham gia cộng đồng học viên và sử dụng miễn phí các tools do EzTech phát triển\n"
            "- Tham gia các buổi đào tạo bonus miễn phí dành riêng cho học viên để trau dồi và nâng cao kỹ năng sau chương trình\n"
            "  + VÒNG 5 — Remind Bộ 100 file quản trị + Tool Hóa đơn & EzExcel (ưu tiên khi khách gặp nỗi đau thiếu form biểu mẫu chuẩn theo ngành hoặc cực với hóa đơn/hàm Excel):\n"
            "Đợt này thì bên em cũng phát triển rất nhiều tools hỗ trợ cho kế toán trong quá trình làm việc nữa. Và học viên sẽ được tặng miễn phí các file quản lý hoặc bộ dữ liệu mẫu trên Excel và nhiều file thực tế do EzTech xây dựng có hẳn kho bộ 100 file quản lý với từng bài toán nghiệp vụ cho từng ngành, mình có thể lấy áp dụng hoặc tùy biến theo đúng doanh nghiệp của mình, thay vì phải tự thiết kế từ đầu ạ.\n"
            "Đây cũng là đặc quyền riêng của học viên bên em thôi, những anh chị chưa là học viên sẽ mất thêm phí từ 2-5tr/ dịch vụ ấy ạ\n"
            "- Tool hóa đơn: https://www.tiktok.com/@tuananhdata/video/7626154405628284180?is_from_webapp=1&sender_device=pc\n"
            "- Tool Excel: https://www.tiktok.com/@tuananhdata/video/7681529166591692039?is_from_webapp=1&sender_device=pc\n"
            "  + VÒNG 6 — Remind Lịch khai giảng mới / Update K2 14 buổi tích hợp AI (ưu tiên khi khách quan tâm ứng dụng AI vào kế toán & Excel để giảm thời gian làm thủ công):\n"
            "Em chào chị ạ, hiện tại bên em vừa có cập nhật nội dung đào tạo khoá Power Query lên 14 buổi trong đó có thêm các buổi học về Ứng dụng AI thực chiến cho kế toán cũng như Excel để mình có thể nâng cao hiệu suất công việc, tối ưu thời gian phải xử lý và lên báo cáo thủ công ạ. Nếu chị đăng ký full combo em vẫn có thể giữ cho mình được mức giá là 7tr5 nhé chị ạ. Chị tham khảo, cần thêm thông tin về lịch khai giảng sắp tới cũng như các tài liệu chia sẻ về AI chị nhắn em hỗ trợ nhé ạ\n"
            "  + VÒNG 7 — Remind Lead ghosting lâu (Tặng Bộ Prompt Mẫu AI & tài liệu miễn phí giúp tiết kiệm 80% thời gian):\n"
            "Em chào anh chị ạ, không biết đợt này mình có đang phải làm việc với dữ liệu và lên báo cáo nhiều không anh chị ạ. Bên em đang có một số tài liệu chia sẻ về Ứng dụng của Power Query, Excel và AI trong công việc, em gửi anh chị nhé ạ\n\n"
            "Em gửi mình 1 vài tài liệu tham khảo về Ứng dụng Power Query, Excel và AI trong xử lý dữ liệu và lên báo cáo quản trị (giúp tiết kiệm 80% thời gian và công sức làm dữ liệu và lên báo cáo) nhé ạ:\n"
            "- Tài liệu \"Bộ Prompt Mẫu AI trong công việc\": https://drive.google.com/file/d/14Guoh66hilevrACxgwoasfvqyevu-8PJ/view?usp=sharing\n"
            "- Ứng dụng đối chiếu từ hàng chục File sao kê vs NKC: https://youtu.be/i_FpxkzGCo8\n"
            "- Làm form đổ tự động hạch toán lên phần mềm hàng trăm chứng từ: https://youtu.be/o50ZjLIgVnU\n"
            "- Tài liệu tham khảo: https://drive.google.com/file/d/1t_wdFwHMs3YxaSydRdbVom3v99zRcMi3/view?usp=sharing\n"
            "- Link demo bộ tài liệu tài chính và quản trị doanh nghiệp: https://docs.google.com/spreadsheets/d/176d4NOAgfvJbg0gRenA9TM3b9W-PuXKEc2Sv--JzTUo/edit?gid=0#gid=0\n"
            "  + VÒNG 8 — Remind Data Talk / Workshop miễn phí cuối tuần:\n"
            "Em chào chị, cuối tuần này bên em có 1 buổi workshop miễn phí về ứng dụng AI, Power Query và Power BI trong việc tối ưu các công việc tài chính kế toán thủ công. Không biết tối chủ nhật tuần này chị có sắp xếp được thời gian tham gia không để em hỗ trợ mình đăng ký nhận link Zoom nhé ạ\n"
            "- Với các câu hỏi khác (Case MISA, Chứng chỉ, MacBook/Excel cũ, AI làm hết rồi sao phải học): lấy ĐÚNG nguyên văn từ `[TÀI LIỆU NỘI BỘ (KHO TRI THỨC RAG)]`.\n\n"
            "- QUY CÁCH TRẢ LỜI:\n"
            "  + Giữ đúng 100 phần trăm giá, số buổi, link, STK và chính sách từ RAG.\n"
            "  + KHÔNG in đậm `**...**` bên trong nội dung tin nhắn gửi khách (chỉ dùng in đậm ở mục `**Chẩn đoán vấn đề & Nỗi đau khách hàng:**` và `**Gợi ý cho Sale:**`).\n"
            "  + TUYỆT ĐỐI KHÔNG ghi `[Nguồn: ...]` ở bất kỳ đâu.\n\n"
            "2. KHI SALE HỎI TRA CỨU NỘI BỘ (số liệu Lead/SĐT, hỏi quy trình/chính sách):\n"
            "- Trả lời thẳng, ngắn gọn, chính xác theo dữ liệu hệ thống và tài liệu RAG, không chèn `[Nguồn: ...]`."
        ),
        "sample_questions": [
            "Khách nhắn: Em ơi tư vấn cho chị khóa học kế toán bên em với",
            "Khách nhắn: Chị chủ yếu làm thủ công bằng Excel thôi em ạ, file nặng lắm",
            "Khách nhắn: Chị đang dùng MISA rồi thì có cần học thêm Power Query với Power BI không?",
            "Khách nhắn: Chị thấy học phí 7tr5 hơi cao em ạ, với chị hay tăng ca tối sợ không theo kịp lịch học",
            "Khách nhắn: Em ơi chị dùng MacBook với chỉ biết Excel cơ bản thôi có học được khóa kế toán không?",
            "Khách nhắn: Cho chị hỏi học K2 trước rồi mới học K1 có được không em?",
            "Khách nhắn: Giờ có AI làm hết rồi sao vẫn phải đi học vậy em?",
            "Khách nhắn: Bên em có lớp học offline không hay chỉ học online?",
            "Phân tích nỗi đau từ tin nhắn & note Admin, soạn tin Remind cho SĐT 09xxxxxxxx",
            "Tóm tắt chỉ số Lead và SĐT 7 ngày qua theo từng nhân viên",
        ],
    },
    "ke_toan": {
        "id": "ke_toan",
        "name": "AI Kế Toán & Công Nợ",
        "badge": "Thu chi & Deal Win",
        "description": "Hỏi cách xuất hóa đơn theo từng case, chọn tài khoản nhận tiền, mốc chốt 4h chiều, hoàn cọc và đối soát công nợ.",
        "categories": ["ke_toan", "chung"],
        "system_prompt": (
            "Bạn là Trợ lý AI Kế toán & Quản lý Công nợ nội bộ của EzTech Việt Nam.\n"
            "Nhiệm vụ:\n"
            "1. Khi nhân viên hỏi một tình huống thu tiền / xuất hóa đơn (ví dụ: 'case này xuất hóa đơn như nào, qua tài khoản gì, thời điểm như nào?'), HÃY TRẢ LỜI RÕ ĐỦ 4 Ý:\n"
            "   - **Tài khoản nhận tiền:** Chỉ rõ gửi **Tài khoản công ty** (`9999336666` VP Bank - bắt buộc cho khoản >= 7 triệu hoặc cần xuất hóa đơn) hay **MoMo** (chia đợt cá nhân không hóa đơn / lẻ khóa không hóa đơn / cọc trước 1-2tr).\n"
            "   - **Cách xuất & Mẫu hóa đơn:** Chỉ rõ mẫu **TEZ** (công ty), **TEE** (cá nhân / khách lẻ không lấy HĐ lưu bán người tiêu dùng), hay **Không xuất**, và nhắc lấy đủ thông tin bắt buộc + báo người phụ trách xuất hóa đơn.\n"
            "   - **Thời điểm & Mốc chốt:** Nhắc rõ điền deal theo **ngày thực tế thu tiền**, nhập web trước **4h chiều (16h00)** để kế toán chốt trong ngày (phát sinh sau 4h vẫn nhập nhưng xử lý sang hôm sau; báo khách chuyển và điền thông tin trước 4h).\n"
            "   - **Lưu ý đặc biệt (nếu có):** Ví dụ quy trình hoàn cọc ĐNTT `BM.01-QT.KTNS.01` nếu cọc qua MoMo trước khi công ty đi lệnh, hoặc xuất hóa đơn theo số tiền nhận được từng đợt nếu chia học phí xuất công ty.\n"
            "2. Khi hỏi số liệu doanh thu / công nợ / bảo lưu / hoàn học phí: Trả lời chính xác theo dữ liệu `sales_deals` / `deal_wins` và tài liệu RAG, định dạng VNĐ dễ đọc, tuyệt đối không suy đoán số tiền và không chèn `[Nguồn: ...]`."
        ),
        "sample_questions": [
            "Khách đóng combo 7tr5 hoặc 7tr125 nhưng không cần lấy hóa đơn thì thu qua tài khoản nào, xuất hóa đơn sao?",
            "Khách chia học phí 2 đợt và muốn xuất hóa đơn về công ty thì thu qua TK nào, xuất hóa đơn lúc nào?",
            "Khách đăng ký học lẻ 1 khóa và không xuất hóa đơn thì nhận qua đâu, có cần nhập web trước 4h chiều không?",
            "Quy trình xuất hóa đơn cho công ty khi khách đã cọc trước 1-2 triệu qua MoMo?",
            "Mốc thời gian 4h chiều chốt hóa đơn hằng ngày quy định như nào, sau 4h xử lý sao?",
            "Tổng hợp doanh thu đã thu và công nợ còn phải thu hiện tại",
            "Phân biệt khi nào dùng mẫu hóa đơn TEZ và khi nào dùng mẫu TEE?",
            "Quy định bảo lưu, chuyển nhượng và hoàn học phí cho học viên?",
        ],
    },
    "quy_trinh": {
        "id": "quy_trinh",
        "name": "AI Quy Trình & SLA",
        "badge": "Metric & Insight SLA",
        "description": "Đọc thông số thực tế từ các Dashboard (Tổng quan, Facebook, TikTok, Work Report, Remind SLA, Deal Win) để phân tích điểm nghẽn và đề xuất hành động, hoặc tra cứu quy trình vận hành.",
        "categories": ["quy_trinh", "chung"],
        "system_prompt": (
            "Bạn là Trợ lý AI Quy trình, Metric Dashboard & SLA Vận hành của EzTech Việt Nam.\n"
            "Nhiệm vụ gồm 2 chế độ:\n\n"
            "1. PHÂN TÍCH METRIC DASHBOARD & ĐƯA RA INSIGHT SLA (khi câu hỏi hỏi về thông số, KPI thực tế, hiệu suất kênh/nhân viên, tồn đọng Remind, so sánh kỳ hoặc yêu cầu nhận định/insight và trong ngữ cảnh có `[DỮ LIỆU DASHBOARD ...]`):\n"
            "- BẮT BUỘC dùng 100% con số thật có trong `[DỮ LIỆU DASHBOARD ...]` và đối chiếu với các ngưỡng cảnh báo SLA trong `[TÀI LIỆU NỘI BỘ (KHO TRI THỨC RAG)]`. TUYỆT ĐỐI KHÔNG tự bịa hay suy đoán số liệu không xuất hiện trong dữ liệu hệ thống.\n"
            "- Trình bày gọn, sắc bén theo đúng khung 4 phần:\n"
            "  1) **Bức tranh số liệu thực tế:** Nêu rõ kỳ phân tích, tóm tắt các chỉ số cốt lõi từ những Dashboard liên quan (Tổng Lead, SĐT, CR%, so sánh kỳ trước, Facebook Ads/Post/Organic, TikTok Video/Organic, Deal Win, Remind aging).\n"
            "  2) **Điểm nghẽn & Cảnh báo SLA:** Chỉ đích danh kênh/page, nhân viên hoặc bước phễu đang vượt ngưỡng cảnh báo (ví dụ: tỷ lệ Lead `Chưa phân công` > 5% hoặc > 10%, kênh có CR < 40%, `Remind > 7 ngày` vượt > 20% hoặc > 40%, chênh lệch CR giữa các nhân viên > 20 điểm %, tỷ lệ chốt Deal/SĐT < 10%).\n"
            "  3) **Nguyên nhân gốc rễ:** Đối chiếu trực tiếp với quy trình vận hành EzTech (bỏ sót gán Sale khiến hội thoại dừng dưới 4 tin, dồn tải vào 1 nhân viên, chưa chuyển sang Zalo / chưa đeo bám đủ vòng Remind 3 lần, hoặc lỗi gắn tag).\n"
            "  4) **Đề xuất hành động ưu tiên:** Đưa 2 đến 4 hành động cụ thể, gắn rõ tên kênh/page/nhân sự cần xử lý và mục tiêu chỉ số cải thiện.\n\n"
            "2. TRA CỨU QUY TRÌNH, ĐỊNH NGHĨA CHỈ SỐ & QUY TẮC TAG/BOT:\n"
            "- Khi hỏi thuần về công thức, định nghĩa KPI, quy tắc gắn tag Pancake, chốt chặn Bot hoặc quy trình lớp học: trả lời chuẩn xác, từng bước rõ ràng theo tài liệu RAG.\n"
            "- TUYỆT ĐỐI KHÔNG chèn `[Nguồn: ...]` ở bất kỳ đâu trong câu trả lời."
        ),
        "sample_questions": [
            "Đọc thông số toàn bộ các Dashboard 7 ngày qua và chỉ ra điểm nghẽn SLA lớn nhất?",
            "Phân tích hiệu quả Facebook vs TikTok 30 ngày qua (Ads, Video, Organic) và đề xuất tối ưu?",
            "Kiểm tra tồn đọng Chăm sóc Lead (Remind > 7 ngày) và Lead chưa phân công hiện tại?",
            "Đánh giá hiệu suất từng nhân viên Sale 7 ngày qua (Lead, SĐT, tỷ lệ chuyển đổi, Deal Win)?",
            "Cách tính Lead Mới, Lead Contact Lại và SĐT thu được trên Dashboard?",
            "Chuỗi trạng thái gắn Tag CRM chuẩn từ Có thông tin đến Đã là học viên?",
            "Khi nào Bot tự động dừng trả lời và quy trình vận hành lớp học Trước - Trong - Sau khóa?",
        ],
    },
}


DEFAULT_SEED_DOCS: List[Dict[str, str]] = [
    {
        "doc_name": "Kịch bản Tư vấn, Chẩn đoán Nỗi đau & Xử lý Từ chối Sale EzTech",
        "category": "sale",
        "content": (
            "1. Quy trình Retrieve & Chẩn đoán Nỗi đau khách hàng trước khi soạn tin:\n"
            "- Bắt buộc đối chiếu 4 nguồn: Tin nhắn khách trên mọi page (TikTok, FB, Zalo), Ghi chú (Notes) của Admin/Sale trên Pancake, Bình luận (Comment) và Tag/Form DealWin.\n"
            "- Các nhóm vấn đề/nỗi đau trọng tâm của khách:\n"
            "  + Quá tải thao tác thủ công trên Excel (file nặng/đơ, link nhiều file dễ lỗi, mỗi tháng làm lại từ đầu) -> Nhấn mạnh Power Query xử lý hàng chục file tự động & thiết kế 1 form báo cáo mẫu import dữ liệu tự cập nhật (Step 2A Excel / Remind Vòng 1, Vòng 5, Vòng 7).\n"
            "  + Dùng phần mềm kế toán (MISA, FAST...) bị giới hạn báo cáo mẫu, xuất ra đối chiếu sao kê/công nợ/đổ bút toán thủ công -> Nhấn mạnh Step 2A Phần mềm / Case thực tế MISA / Remind Vòng 1 (Video Scope 3 & 4).\n"
            "  + Áp lực lên Báo cáo quản trị / Dashboard trực quan đa chiều (P&L, dòng tiền, doanh thu, chi phí) cho Sếp/BGĐ -> Nhấn mạnh K1 & K3 Power BI, link Demo báo cáo học viên hoặc Remind Vòng 2 (Feedback KTT/KTTH), Vòng 3 (Layout chi tiết) hoặc giải pháp B2C đóng gói sẵn.\n"
            "  + Muốn ứng dụng AI vào kế toán & Excel -> Nhấn mạnh K2 cập nhật 14 buổi tích hợp AI thực chiến (Remind Vòng 6), tặng Bộ Prompt Mẫu AI (Vòng 7) hoặc mời Workshop miễn phí cuối tuần (Vòng 8).\n\n"
            "2. Nguyên tắc soạn tin nhắn nhấn mạnh nỗi đau nhưng bám sát kịch bản:\n"
            "- Luôn chỉ ra rõ khách đang gặp vấn đề/nỗi đau gì ở phần Chẩn đoán đầu câu trả lời.\n"
            "- Khi soạn tin nhắn gửi khách: giữ nguyên văn khung chữ, thông số học phí, số buổi, link demo và 8 quyền lợi trong Kịch bản chuyên sâu & Bộ 8 vòng Remind; đồng thời cá nhân hóa câu dẫn kết nối và cụm từ ngành nghề/bài toán thực tế xoáy thẳng vào đúng nỗi đau của khách.\n\n"
            "3. Xử lý từ chối thường gặp:\n"
            "- Khách báo 'Bận không có thời gian': Nhấn mạnh lộ trình học linh hoạt, có video record xem lại trọn đời, bảo lưu/học lại 1 lần miễn phí, nhóm hỗ trợ 1-1 giải đáp trực tiếp trên bài tập thực tế.\n"
            "- Khách báo 'Sợ không theo kịp vì không biết code/IT': Khẳng định Power Query tích hợp sẵn trong Excel, thao tác bằng tick chọn và kéo thả, thiết kế riêng cho dân Kế toán - Tài chính.\n"
            "- Khách báo 'Học phí cao': Nâng giá trị cốt lõi + đặc quyền Support 1-1 trong và sau khóa học; hỗ trợ 2 phương án: giảm 5% đăng ký sớm hoặc chia đôi học phí 7tr5 (đóng trước 5tr vào lớp, 2tr5 trước khi sang tháng mới)."
        ),
    },
    {
        "doc_name": "Quy định Đối soát Deal Win, Công nợ & Hóa đơn",
        "category": "ke_toan",
        "content": (
            "1. Quy trình đồng bộ Deal Win sang Nhập Deal & Công nợ:\n"
            "- Khi học viên chuyển khoản thành công, Sale điền thông tin học viên vào Sheet/Form Deal Win và gắn tag 'Đã là học viên' trên Pancake.\n"
            "- Hệ thống tự động kéo học viên từ bảng deal_wins sang bảng sales_deals với trạng thái 'Chờ bổ sung' nếu chưa điền đủ Số tiền thu / Lớp học / Nhóm CS 1-1.\n"
            "- Kế toán và Sale vào tab 'Nhập Deal & Công Nợ' để cập nhật: Tổng tiền (phai_thu / tong_tien), Đã thu (da_thu), Chương trình học, Lớp học, Ngày thu AR.\n\n"
            "2. Công thức tính Công nợ trên hệ thống:\n"
            "- Còn nợ (con_no) = Phải thu (phai_thu) - Đã thu (da_thu) - Đã thu nợ cũ.\n"
            "- Các trạng thái chuẩn: 'Đã hoàn thành' (khi còn nợ = 0), 'Còn nợ' (khi còn nợ > 0), 'Chờ bổ sung' (mới đồng bộ từ Deal Win), 'Bảo lưu', 'Hoàn học phí'.\n\n"
            "3. Chính sách Đặt cọc, Bảo lưu & Xuất hóa đơn:\n"
            "- Học viên đóng cọc cần ghi rõ Ngày hẹn thu AR (ngay_thu_ar) để Kế toán và Sale theo dõi nhắc hạn.\n"
            "- Bảo lưu: Học viên được hỗ trợ bảo lưu sang khóa kế tiếp khi có lý do chính đáng và báo trước cho bộ phận CSKH.\n"
            "- Xuất hóa đơn điện tử: Thực hiện tại tab 'Xuất hoá đơn' trên Dashboard sau khi Kế toán xác nhận khoản thu đã khớp sao kê ngân hàng."
        ),
    },
    {
        "doc_name": "Quy chuẩn Chỉ số KPI, Ngưỡng SLA Dashboard & Vận hành EzTech",
        "category": "quy_trinh",
        "content": (
            "1. Định nghĩa chuẩn các chỉ số KPI trên các Dashboard EzTech:\n"
            "- Lead Mới: Khách hàng có thời điểm tạo hội thoại lần đầu (first_created_at) nằm trong kỳ báo cáo.\n"
            "- Lead Contact Lại: Khách hàng tạo TRƯỚC kỳ báo cáo, nhưng có phát sinh tin nhắn (của khách hoặc nhân viên) trong kỳ.\n"
            "- Tổng Lead = Lead Mới + Lead Contact Lại (không trùng lặp).\n"
            "- SĐT thu được: Mỗi số điện thoại chuẩn hóa chỉ tính 1 lần duy nhất vào thời điểm khách gửi số lần đầu (phone_at). Bao gồm cả khách có số điện thoại hoặc được gắn tag 'đã add'. Tỷ lệ SĐT / Lead Mới (%) = SĐT Mới / Lead Mới.\n"
            "- Facebook Analytics tách 3 kênh: Quảng cáo (Ads), Bài viết (Post/Comment), Tự nhiên (Organic Inbox).\n"
            "- TikTok Analytics tách 2 kênh: Từ Video (Post) và Tự nhiên (Organic Inbox).\n\n"
            "2. Bộ Ngưỡng Cảnh Báo SLA & Benchmark Phân Tích Insight:\n"
            "- Lead Chưa phân công (assigned_users trống): Tốt < 5%, Cảnh báo 5-10%, Báo động đỏ > 10% (Lead chưa phân công thường có tỷ lệ ra SĐT thấp hơn ~3.5 lần so với Lead có Sale nhận).\n"
            "- Tỷ lệ ra SĐT kênh nguồn: Mục tiêu tổng >= 50%; TikTok tốt 50-62%, Facebook tốt 40-48%; dưới 35% là cần rà soát.\n"
            "- Tồn đọng Remind (> 7 ngày chưa tương tác lại): Tốt < 20%, Cảnh báo 20-40%, Báo động đỏ > 40%.\n"
            "- Tỷ lệ chốt Deal Win / Tổng SĐT: Mục tiêu 15-25%; dưới 10% là nghẽn ở chặng chăm sóc Zalo.\n\n"
            "3. Quy tắc phạm vi Page, Gắn Tag Pancake & Chốt chặn Bot:\n"
            "- Mặc định khi xem 'Tất cả page nguồn lead': Tính mọi Fanpage Facebook & TikTok, TRỪ page Zalo cá nhân và lọc bỏ nhóm chat Zalo (pzl_g_...).\n"
            "- Nhóm Đào tạo: 'Đào tạo' hoặc 'HV TCKT'. Nhóm Lead Other: 'Lead Other', 'Support Other' hoặc 'HV Khác'.\n"
            "- Chuỗi Tag Zalo chuẩn: Có thông tin -> Đã gửi TT -> Remind -> Suy nghĩ (sau 3 lần remind) -> Quan tâm sâu -> Đồng ý học -> Đã là học viên (+ Còn CN nếu còn công nợ).\n"
            "- Chốt chặn Bot tự động: Bot dừng trả lời nếu có tag học viên/khóa học hoặc khách nhắn từ khóa hỏi học phí, lộ trình, khai giảng để Sale tư vấn 1-1."
        ),
    },
]


def clear_ai_knowledge_cache():
    global _KNOWLEDGE_CACHE, _KNOWLEDGE_CACHE_TS, _API_KEY_CACHE, _SLA_REMIND_CACHE, _DAILY_REVIEW_CACHE
    with _CACHE_LOCK:
        _KNOWLEDGE_CACHE = None
        _KNOWLEDGE_CACHE_TS = 0.0
        _API_KEY_CACHE = None
        _SLA_REMIND_CACHE = None
        _DAILY_REVIEW_CACHE = None


def get_gemini_api_key(db: Session) -> str:
    global _API_KEY_CACHE
    now = time.time()
    if _API_KEY_CACHE and (now - _API_KEY_CACHE[0] < 300):
        return _API_KEY_CACHE[1]

    key = ""
    try:
        cfg = db.query(AppConfig).filter(AppConfig.config_key == "GEMINI_API_KEY").first()
        if cfg and cfg.config_value and cfg.config_value.strip():
            key = cfg.config_value.strip()
    except Exception:
        pass

    if not key:
        key = os.getenv("GEMINI_API_KEY", "").strip() or DEFAULT_GEMINI_KEY

    _API_KEY_CACHE = (now, key)
    return key


def mask_api_key(key: str) -> str:
    if not key or len(key) < 12:
        return "Chưa cấu hình"
    return f"{key[:7]}...{key[-5:]}"


def split_text_into_chunks(text: str, max_chars: int = 800, overlap: int = 120) -> List[str]:
    cleaned = re.sub(r"\r\n?", "\n", (text or "").strip())
    if not cleaned:
        return []
    paragraphs = [p.strip() for p in re.split(r"\n{2,}", cleaned) if p.strip()]
    chunks: List[str] = []
    current = ""

    for para in paragraphs:
        if len(current) + len(para) + 2 <= max_chars:
            current = f"{current}\n\n{para}".strip() if current else para
        else:
            if current:
                chunks.append(current)
            if len(para) <= max_chars:
                current = para
            else:
                step = max(200, max_chars - overlap)
                for idx in range(0, len(para), step):
                    piece = para[idx : idx + max_chars].strip()
                    if piece:
                        chunks.append(piece)
                current = ""
    if current:
        chunks.append(current)
    return chunks


def embed_texts(texts: List[str], api_key: str) -> List[Optional[List[float]]]:
    if not texts:
        return []
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{EMBEDDING_MODEL}:batchEmbedContents?key={api_key}"
    requests_payload = [
        {
            "model": f"models/{EMBEDDING_MODEL}",
            "content": {"parts": [{"text": t[:3000]}]},
            "outputDimensionality": EMBEDDING_DIM,
        }
        for t in texts
    ]
    try:
        resp = requests.post(url, json={"requests": requests_payload}, timeout=20)
        if resp.status_code == 200:
            embeddings = resp.json().get("embeddings", [])
            return [emb.get("values") for emb in embeddings]
        logger.warning(f"Gemini batchEmbedContents status {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        logger.warning(f"Gemini embedding error: {e}")
    return [None for _ in texts]


def cosine_similarity(v1: Optional[List[float]], v2: Optional[List[float]]) -> float:
    if not v1 or not v2 or len(v1) != len(v2):
        return 0.0
    dot = sum(a * b for a, b in zip(v1, v2))
    n1 = math.sqrt(sum(a * a for a in v1))
    n2 = math.sqrt(sum(b * b for b in v2))
    if n1 == 0.0 or n2 == 0.0:
        return 0.0
    return dot / (n1 * n2)


def _load_knowledge_cache(db: Session) -> List[Dict[str, Any]]:
    global _KNOWLEDGE_CACHE, _KNOWLEDGE_CACHE_TS
    now = time.time()
    with _CACHE_LOCK:
        if _KNOWLEDGE_CACHE is not None and (now - _KNOWLEDGE_CACHE_TS < KNOWLEDGE_CACHE_TTL):
            return _KNOWLEDGE_CACHE

    rows = db.query(KnowledgeChunk).order_by(KnowledgeChunk.id.asc()).all()
    items = [
        {
            "id": r.id,
            "doc_id": r.doc_id,
            "doc_name": r.doc_name,
            "category": r.category,
            "chunk_index": r.chunk_index,
            "content": r.content,
            "embedding": r.embedding,
            "norm_content": normalize_text(f"{r.doc_name} {r.content}"),
            "created_by": r.created_by,
            "created_at": r.created_at.strftime("%Y-%m-%d %H:%M") if r.created_at else "",
        }
        for r in rows
    ]
    with _CACHE_LOCK:
        _KNOWLEDGE_CACHE = items
        _KNOWLEDGE_CACHE_TS = now
    return items


def retrieve_relevant_chunks(
    db: Session,
    query_text: str,
    categories: List[str],
    api_key: str,
    top_k: int = 6,
) -> List[Dict[str, Any]]:
    all_chunks = _load_knowledge_cache(db)
    target_chunks = [c for c in all_chunks if c["category"] in categories]
    if not target_chunks:
        return []

    query_vecs = embed_texts([query_text], api_key)
    query_vec = query_vecs[0] if query_vecs else None
    norm_q = normalize_text(query_text)
    q_tokens = [tok for tok in norm_q.split() if len(tok) >= 2]

    scored: List[Tuple[float, Dict[str, Any]]] = []
    for chunk in target_chunks:
        vec_score = cosine_similarity(query_vec, chunk.get("embedding")) if query_vec else 0.0
        kw_hits = sum(1 for tok in q_tokens if tok in chunk["norm_content"])
        kw_score = (kw_hits / len(q_tokens)) if q_tokens else 0.0
        final_score = (vec_score * 0.75) + (kw_score * 0.25) if query_vec else kw_score
        if final_score > 0.08 or len(target_chunks) <= top_k:
            scored.append((final_score, chunk))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [
        {
            "doc_id": item["doc_id"],
            "doc_name": item["doc_name"],
            "category": item["category"],
            "content": item["content"],
            "score": round(score, 3),
        }
        for score, item in scored[:top_k]
    ]


def _strip_accents(s: str) -> str:
    """Chuyển tiếng Việt có dấu sang không dấu lowercase để bắt từ khóa và tên nhân sự ổn định."""
    if not s:
        return ""
    s_norm = unicodedata.normalize("NFD", s.strip().lower()).replace("đ", "d")
    return "".join(ch for ch in s_norm if unicodedata.category(ch) != "Mn")


def _resolve_quy_trinh_period(ascii_q: str, now_vn: datetime) -> Tuple[datetime, datetime, datetime, datetime, str]:
    """Xác định kỳ hiện tại & kỳ liền trước cùng độ dài dựa trên câu hỏi."""
    today_start = now_vn.replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = now_vn.replace(hour=23, minute=59, second=59, microsecond=999999)

    if "hom qua" in ascii_q:
        start = today_start - timedelta(days=1)
        end = start.replace(hour=23, minute=59, second=59, microsecond=999999)
        label = "Hôm qua"
    elif "hom nay" in ascii_q:
        start, end = today_start, today_end
        label = "Hôm nay"
    elif "thang nay" in ascii_q:
        start = today_start.replace(day=1)
        end = today_end
        label = "Tháng này"
    elif "tuan nay" in ascii_q:
        start = today_start - timedelta(days=today_start.weekday())
        end = today_end
        label = "Tuần này"
    elif "tuan truoc" in ascii_q:
        this_mon = today_start - timedelta(days=today_start.weekday())
        start = this_mon - timedelta(days=7)
        end = (this_mon - timedelta(days=1)).replace(hour=23, minute=59, second=59, microsecond=999999)
        label = "Tuần trước"
    else:
        m_days = re.search(r"(\d+)\s*ngay", ascii_q)
        if m_days:
            days = min(max(int(m_days.group(1)), 1), 90)
        elif "30 ngay" in ascii_q or "1 thang" in ascii_q or "thang qua" in ascii_q:
            days = 30
        elif "14 ngay" in ascii_q or "2 tuan" in ascii_q:
            days = 14
        else:
            days = 7
        start = today_start - timedelta(days=days - 1)
        end = today_end
        label = f"{days} ngày gần nhất"

    span = end - start
    prev_end = (start - timedelta(seconds=1)).replace(microsecond=999999)
    prev_start = (prev_end - span).replace(hour=0, minute=0, second=0, microsecond=0)
    return start, end, prev_start, prev_end, label


def _get_sla_remind_snapshot(db: Session, now_vn: datetime) -> Dict[str, Any]:
    """Đọc snapshot tồn đọng Chăm sóc Lead (Remind aging) & tỷ lệ chưa phân công (cache RAM 5 phút, không kéo tag_timeline)."""
    global _SLA_REMIND_CACHE
    now_ts = time.time()
    with _CACHE_LOCK:
        if _SLA_REMIND_CACHE and (now_ts - _SLA_REMIND_CACHE[0] < SLA_REMIND_CACHE_TTL):
            return _SLA_REMIND_CACHE[1]

    rows = (
        db.query(
            FactLeadActivity.status_tag,
            FactLeadActivity.assigned_users,
            FactLeadActivity.contacted_at,
            DimLead.first_created_at,
            DimLead.page_id,
        )
        .join(DimLead, FactLeadActivity.lead_id == DimLead.id)
        .filter(~FactLeadActivity.conversation_id.like("pzl_g_%"))
        .all()
    )

    zalo_keys = zalo_page_keys()
    crm_stages = [
        ("Có thông tin", "co thong tin"),
        ("Đã gửi TT", "da gui tt"),
        ("Remind", "remind"),
        ("Suy nghĩ", "suy nghi"),
        ("Quan tâm sâu", "quan tam sau"),
        ("Đồng ý học", "dong y hoc"),
        ("Đã là học viên", "da la hoc vien"),
    ]
    stage_counts: Counter = Counter()
    remind_buckets = {"under_1": 0, "d1_3": 0, "d4_7": 0, "over_7": 0}
    remind_over7_emp: Counter = Counter()
    total_src = unassigned_src = total_zalo = unassigned_zalo = 0

    for status_tag, assigned_users, contacted_at, first_created_at, page_id in rows:
        pg_canon = resolve_canonical_page_name(page_id, fallback=page_id or "")
        is_zalo = page_id in zalo_keys or pg_canon in zalo_keys or "zalo" in (pg_canon or "").lower()
        has_emp = bool(assigned_users and assigned_users.strip())
        if is_zalo:
            total_zalo += 1
            if not has_emp:
                unassigned_zalo += 1
        else:
            total_src += 1
            if not has_emp:
                unassigned_src += 1

        norm_tags = _strip_accents(status_tag or "")
        for label, key in crm_stages:
            if key in norm_tags:
                stage_counts[label] += 1

        if "remind" in norm_tags:
            last_dt = contacted_at or first_created_at or now_vn
            if getattr(last_dt, "tzinfo", None) is not None:
                last_dt = last_dt.replace(tzinfo=None)
            days_int = int(max(0.0, (now_vn - last_dt).total_seconds()) // 86400.0)
            if days_int == 0:
                remind_buckets["under_1"] += 1
            elif days_int <= 3:
                remind_buckets["d1_3"] += 1
            elif days_int <= 7:
                remind_buckets["d4_7"] += 1
            else:
                remind_buckets["over_7"] += 1
                if has_emp:
                    for emp in [x.strip() for x in assigned_users.split(",") if x.strip()]:
                        remind_over7_emp[emp] += 1
                else:
                    remind_over7_emp["Chưa phân công"] += 1

    snap = {
        "total_src": total_src,
        "unassigned_src": unassigned_src,
        "total_zalo": total_zalo,
        "unassigned_zalo": unassigned_zalo,
        "stage_counts": dict(stage_counts),
        "remind_total": sum(remind_buckets.values()),
        "remind_buckets": remind_buckets,
        "remind_over7_top_emp": remind_over7_emp.most_common(6),
    }
    with _CACHE_LOCK:
        _SLA_REMIND_CACHE = (now_ts, snap)
    return snap


def _build_quy_trinh_dashboard_context(
    db: Session, question: str, ascii_q: str, now_vn: datetime
) -> Tuple[List[str], List[str]]:
    """Tổng hợp số liệu thực tế từ 6 Dashboard để AI Quy trình & SLA phân tích insight."""
    blocks: List[str] = []
    tools_used: List[str] = []
    start_dt, end_dt, prev_start, prev_end, period_label = _resolve_quy_trinh_period(ascii_q, now_vn)

    wants_fb = any(k in ascii_q for k in ("facebook", "fb", "ads", "quang cao", "bai viet"))
    wants_tt = any(k in ascii_q for k in ("tiktok", "video"))
    wants_remind = any(k in ascii_q for k in ("remind", "ton dong", "cham soc", "qua han", "bo quen", "sla"))
    wants_work_or_deal = any(k in ascii_q for k in ("nhan vien", "sale", "bao cao", "work", "deal", "chot", "doanh thu", "hieu suat"))
    wants_all = any(
        k in ascii_q
        for k in ("toan bo", "tong hop", "tong the", "insight", "dashboard", "diem nghen", "tinh hinh", "van hanh", "thong so", "so lieu", "kpi", "so sanh", "phan tich", "danh gia")
    ) or not (wants_fb or wants_tt or wants_remind or wants_work_or_deal)

    # 1. Tổng quan & Chỉ số (Lead, SĐT, CR%, Chưa phân công, Nhân sự, So sánh kỳ trước)
    period_phones_total = 0
    if wants_all or wants_work_or_deal or not (wants_fb and not wants_tt and not wants_remind):
        try:
            cur_leads = classify_leads(db, start_dt, end_dt)
            prev_leads = classify_leads(db, prev_start, prev_end)

            def _agg_leads(lmap: Dict[Any, Any]) -> Dict[str, Any]:
                new_l = rec_l = new_p = rec_p = un_l = un_p = as_l = as_p = 0
                emp_stats: Dict[str, Dict[str, int]] = {}
                page_stats: Dict[str, Dict[str, int]] = {}
                tag_cat = Counter({"Đào tạo": 0, "Lead Other": 0, "Other": 0})
                for ld in lmap.values():
                    emp = ld.primary_employee or "Chưa phân công"
                    pg = resolve_canonical_page_name(ld.page_id, fallback=ld.page_id or "Khác")
                    has_ph = bool(ld.has_phone and ld.phone_event_at)
                    if ld.is_new:
                        new_l += 1
                        if has_ph:
                            new_p += 1
                    else:
                        rec_l += 1
                        if has_ph:
                            rec_p += 1
                    if emp == "Chưa phân công":
                        un_l += 1
                        if has_ph:
                            un_p += 1
                    else:
                        as_l += 1
                        if has_ph:
                            as_p += 1
                        es = emp_stats.setdefault(emp, {"total": 0, "new": 0, "phones": 0})
                        es["total"] += 1
                        if ld.is_new:
                            es["new"] += 1
                        if has_ph:
                            es["phones"] += 1

                    ps = page_stats.setdefault(pg, {"total": 0, "new": 0, "phones": 0, "unassigned": 0})
                    ps["total"] += 1
                    if ld.is_new:
                        ps["new"] += 1
                    if has_ph:
                        ps["phones"] += 1
                    if emp == "Chưa phân công":
                        ps["unassigned"] += 1

                    tags_norm = {_strip_accents(t) for t in ld.tags}
                    if tags_norm & {"dao tao", "hv tckt"}:
                        tag_cat["Đào tạo"] += 1
                    elif tags_norm & {"lead other", "support other", "hv khac"}:
                        tag_cat["Lead Other"] += 1
                    else:
                        tag_cat["Other"] += 1

                tot_l = new_l + rec_l
                tot_p = new_p + rec_p
                return {
                    "total": tot_l, "new": new_l, "recontact": rec_l,
                    "phones": tot_p, "new_phones": new_p, "recontact_phones": rec_p,
                    "cr_new": round(new_p / new_l * 100, 1) if new_l else 0.0,
                    "cr_total": round(tot_p / tot_l * 100, 1) if tot_l else 0.0,
                    "unassigned": un_l,
                    "unassigned_pct": round(un_l / tot_l * 100, 1) if tot_l else 0.0,
                    "unassigned_cr": round(un_p / un_l * 100, 1) if un_l else 0.0,
                    "assigned_cr": round(as_p / as_l * 100, 1) if as_l else 0.0,
                    "emp_stats": emp_stats, "page_stats": page_stats, "tag_cat": dict(tag_cat),
                }

            cur_s = _agg_leads(cur_leads)
            prev_s = _agg_leads(prev_leads)
            period_phones_total = cur_s["phones"]

            emp_rows = sorted(cur_s["emp_stats"].items(), key=lambda x: x[1]["total"], reverse=True)
            emp_lines = [
                f"  + {name}: {v['total']} lead ({v['new']} mới), {v['phones']} SĐT (CR {round(v['phones']/v['total']*100, 1) if v['total'] else 0.0}%)"
                for name, v in emp_rows[:12]
            ]
            page_rows = sorted(cur_s["page_stats"].items(), key=lambda x: x[1]["total"], reverse=True)
            page_lines = [
                f"  + {pg}: {v['total']} lead ({v['new']} mới), {v['phones']} SĐT (CR {round(v['phones']/v['total']*100, 1) if v['total'] else 0.0}%), chưa phân công {v['unassigned']}"
                for pg, v in page_rows[:10]
            ]
            d_lead = cur_s["total"] - prev_s["total"]
            d_phone = cur_s["phones"] - prev_s["phones"]
            d_cr = round(cur_s["cr_total"] - prev_s["cr_total"], 1)

            blocks.append(
                f"[DỮ LIỆU DASHBOARD TỔNG QUAN & CHỈ SỐ ({period_label}: {start_dt.strftime('%d/%m/%Y')} - {end_dt.strftime('%d/%m/%Y')})]\n"
                f"- Tổng Lead: {cur_s['total']} (Mới: {cur_s['new']}, Contact lại: {cur_s['recontact']}) | So kỳ trước: {d_lead:+d} lead\n"
                f"- Tổng SĐT thu được: {cur_s['phones']} (SĐT Mới: {cur_s['new_phones']}, Contact lại: {cur_s['recontact_phones']}) | So kỳ trước: {d_phone:+d} SĐT\n"
                f"- Tỷ lệ SĐT/Lead Mới: {cur_s['cr_new']}% | SĐT/Tổng Lead: {cur_s['cr_total']}% (So kỳ trước: {d_cr:+.1f} điểm %)\n"
                f"- Lead Chưa phân công trong kỳ: {cur_s['unassigned']}/{cur_s['total']} ({cur_s['unassigned_pct']}%) | CR chưa phân công: {cur_s['unassigned_cr']}% vs Đã phân công: {cur_s['assigned_cr']}%\n"
                f"- Phân loại Tag: Đào tạo={cur_s['tag_cat'].get('Đào tạo', 0)}, Lead Other={cur_s['tag_cat'].get('Lead Other', 0)}, Other={cur_s['tag_cat'].get('Other', 0)}\n"
                f"- Theo Page nguồn:\n" + ("\n".join(page_lines) or "  + Chưa có dữ liệu") + "\n"
                f"- Theo Nhân viên Sale:\n" + ("\n".join(emp_lines) or "  + Chưa có dữ liệu")
            )
            tools_used.append(f"Dashboard Tổng quan ({period_label})")
        except Exception as e:
            logger.warning(f"Quy trinh overview metric error: {e}")

    # 2. Facebook Analytics
    if wants_all or wants_fb:
        try:
            from backend.facebook_metrics import get_facebook_metrics

            fb = get_facebook_metrics(start_date=start_dt, end_date=end_dt, db=db)
            s = fb.get("summary", {})
            ch = fb.get("channel_breakdown", {})
            top_posts = fb.get("top_posts", [])[:3]
            post_lines = [
                f"  + Bài ({p.get('inserted_at', '-')}) | {p.get('lead_count', 0)} lead, {p.get('phone_count', 0)} SĐT, {p.get('deal_count', 0)} deal: {(p.get('message') or '')[:80]}"
                for p in top_posts
            ]
            blocks.append(
                f"[DỮ LIỆU DASHBOARD FACEBOOK ANALYTICS ({start_dt.strftime('%d/%m/%Y')} - {end_dt.strftime('%d/%m/%Y')})]\n"
                f"- Bài viết: {s.get('total_posts', 0)} bài | Reactions: {s.get('total_reactions', 0)} (TB {s.get('avg_reactions_per_post', 0)}/bài) | Comments: {s.get('total_comments', 0)} (SĐT từ comment: {s.get('comment_phones', 0)})\n"
                f"- Lead FB: {s.get('total_leads', 0)} (Mới: {s.get('new_leads', 0)}, Contact lại: {s.get('recontact_leads', 0)}) | SĐT: {s.get('phone_leads', 0)} (CR SĐT: {s.get('phone_conversion_rate', 0)}%) | Deal Win: {s.get('deal_wins', 0)} (CR Deal/SĐT: {s.get('deal_conversion_rate', 0)}%)\n"
                f"- Kênh Ads: {ch.get('ads', {}).get('leads', 0)} lead, {ch.get('ads', {}).get('phones', 0)} SĐT (CR {ch.get('ads', {}).get('conversion_rate', 0)}%)\n"
                f"- Kênh Bài viết (Post): {ch.get('post', {}).get('leads', 0)} lead, {ch.get('post', {}).get('phones', 0)} SĐT (CR {ch.get('post', {}).get('conversion_rate', 0)}%)\n"
                f"- Kênh Tự nhiên (Organic Inbox): {ch.get('organic', {}).get('leads', 0)} lead, {ch.get('organic', {}).get('phones', 0)} SĐT (CR {ch.get('organic', {}).get('conversion_rate', 0)}%)\n"
                f"- Top bài viết FB:\n" + ("\n".join(post_lines) or "  + Chưa có bài viết trong kỳ")
            )
            tools_used.append("Facebook Analytics")
        except Exception as e:
            logger.warning(f"Quy trinh FB metric error: {e}")

    # 3. TikTok Analytics
    if wants_all or wants_tt:
        try:
            from backend.tiktok_metrics import get_tiktok_metrics

            tt = get_tiktok_metrics(start_date=start_dt, end_date=end_dt, db=db)
            s = tt.get("summary", {})
            ch = tt.get("channel_breakdown", {})
            top_vids = tt.get("top_posts", [])[:3]
            vid_lines = [
                f"  + Video ({v.get('inserted_at', '-')}) | {v.get('lead_count', 0)} lead, {v.get('phone_count', 0)} SĐT, {v.get('deal_count', 0)} deal: {(v.get('message') or '')[:80]}"
                for v in top_vids
            ]
            blocks.append(
                f"[DỮ LIỆU DASHBOARD TIKTOK ANALYTICS ({start_dt.strftime('%d/%m/%Y')} - {end_dt.strftime('%d/%m/%Y')})]\n"
                f"- Video: {s.get('total_posts', 0)} video | Tim: {s.get('total_reactions', 0)} | Share: {s.get('total_shares', 0)} | Comments: {s.get('total_comments', 0)} (SĐT từ comment: {s.get('comment_phones', 0)})\n"
                f"- Lead TikTok: {s.get('total_leads', 0)} (Mới: {s.get('new_leads', 0)}, Contact lại: {s.get('recontact_leads', 0)}) | SĐT: {s.get('phone_leads', 0)} (CR SĐT: {s.get('phone_conversion_rate', 0)}%) | Deal Win: {s.get('deal_wins', 0)} (CR Deal/SĐT: {s.get('deal_conversion_rate', 0)}%)\n"
                f"- Kênh Từ Video: {ch.get('post', {}).get('leads', 0)} lead, {ch.get('post', {}).get('phones', 0)} SĐT (CR {ch.get('post', {}).get('conversion_rate', 0)}%)\n"
                f"- Kênh Tự nhiên (Organic Inbox): {ch.get('organic', {}).get('leads', 0)} lead, {ch.get('organic', {}).get('phones', 0)} SĐT (CR {ch.get('organic', {}).get('conversion_rate', 0)}%)\n"
                f"- Top video TikTok:\n" + ("\n".join(vid_lines) or "  + Chưa có video trong kỳ")
            )
            tools_used.append("TikTok Analytics")
        except Exception as e:
            logger.warning(f"Quy trinh TikTok metric error: {e}")

    # 4. Chăm sóc Lead / Remind & SLA Aging
    if wants_all or wants_remind:
        try:
            snap = _get_sla_remind_snapshot(db, now_vn)
            rb = snap["remind_buckets"]
            r_tot = snap["remind_total"]
            over7_pct = round(rb["over_7"] / r_tot * 100, 1) if r_tot else 0.0
            src_un_pct = round(snap["unassigned_src"] / snap["total_src"] * 100, 1) if snap["total_src"] else 0.0
            zalo_un_pct = round(snap["unassigned_zalo"] / snap["total_zalo"] * 100, 1) if snap["total_zalo"] else 0.0
            top_over7 = ", ".join(f"{k}: {v}" for k, v in snap["remind_over7_top_emp"]) or "Không có"
            stages_str = ", ".join(f"{k}: {v}" for k, v in snap["stage_counts"].items()) or "Chưa có"
            blocks.append(
                f"[DỮ LIỆU DASHBOARD CHĂM SÓC LEAD & SLA TỒN ĐỌNG (TOÀN HỆ THỐNG HIỆN TẠI)]\n"
                f"- Hội thoại chưa phân công nhân viên: Kênh nguồn {snap['unassigned_src']}/{snap['total_src']} ({src_un_pct}%) | Kênh Zalo {snap['unassigned_zalo']}/{snap['total_zalo']} ({zalo_un_pct}%)\n"
                f"- Phân bổ Tag CRM hiện có: {stages_str}\n"
                f"- Tồn đọng tệp tag Remind ({r_tot} khách): <1 ngày={rb['under_1']}, 1-3 ngày={rb['d1_3']}, 4-7 ngày={rb['d4_7']}, >7 ngày quá hạn={rb['over_7']} ({over7_pct}%)\n"
                f"- Top nhân viên có Remind > 7 ngày: {top_over7}"
            )
            tools_used.append("Chăm sóc Lead (Remind SLA)")
        except Exception as e:
            logger.warning(f"Quy trinh Remind SLA error: {e}")

    # 5. Báo cáo công việc & Deal Win (kèm lọc riêng nhân viên nếu có tên trong câu hỏi)
    if wants_all or wants_work_or_deal:
        try:
            from backend.work_report import get_work_report

            wr_all = get_work_report(start_date=start_dt, end_date=end_dt, employee=None, db=db)
            matched_emp = None
            for emp_name in wr_all.get("employees_list", []):
                if _strip_accents(emp_name) and _strip_accents(emp_name) in ascii_q:
                    matched_emp = emp_name
                    break

            wr = get_work_report(start_date=start_dt, end_date=end_dt, employee=matched_emp, db=db) if matched_emp else wr_all
            ls = wr.get("lead_stats", {})
            st = wr.get("student_stats", {})
            ins = wr.get("insights", {}).get("formatted_lines", [])
            deal_cnt = st.get("total_deals", 0)
            deal_cr = round(deal_cnt / period_phones_total * 100, 1) if (not matched_emp and period_phones_total > 0) else (
                round(deal_cnt / ls.get("total", {}).get("phone_leads", 0) * 100, 1) if ls.get("total", {}).get("phone_leads", 0) > 0 else 0.0
            )
            closer_cnt: Counter = Counter()
            for stu in st.get("students", []):
                for cb in [x.strip() for x in (stu.get("care_by") or "Chưa rõ").split(",") if x.strip()]:
                    closer_cnt[cb] += 1
            closers_str = ", ".join(f"{k}: {v} deal" for k, v in closer_cnt.most_common(6)) or "Chưa có"

            blocks.append(
                f"[DỮ LIỆU BÁO CÁO CÔNG VIỆC & DEAL WIN ({wr.get('employee', 'Tất cả')}: {start_dt.strftime('%d/%m/%Y')} - {end_dt.strftime('%d/%m/%Y')})]\n"
                f"- {ls.get('tiktok', {}).get('formatted_line', '')}\n"
                f"- {ls.get('facebook', {}).get('formatted_line', '')}\n"
                f"- Zalo chăm sóc: {ls.get('zalo', {}).get('total_contacted', 0)} hội thoại, {ls.get('zalo', {}).get('phone_leads', 0)} SĐT\n"
                f"- Deal Win trong kỳ: {deal_cnt} học viên (Tỷ lệ Deal/SĐT: {deal_cr}%) | Thực thu: {int(st.get('total_revenue', 0)):,}đ | Tổng giá trị HĐ: {int(st.get('total_contract_value', 0)):,}đ\n"
                f"- Top Sale chốt Deal trong kỳ: {closers_str}\n"
                f"- Nhận định học viên: {' | '.join(ins) if ins else 'Chưa có dữ liệu học viên mới'}"
            )
            tools_used.append("Báo cáo công việc & Deal Win")
        except Exception as e:
            logger.warning(f"Quy trinh work_report error: {e}")

    return blocks, tools_used


def _format_msg_time_vn(raw_ts: Optional[str]) -> str:
    """Chuyển ISO timestamp UTC từ Pancake sang giờ VN (DD/MM HH:MM) dễ đọc."""
    if not raw_ts or not isinstance(raw_ts, str):
        return ""
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})", raw_ts.strip())
    if not m:
        return ""
    try:
        dt_utc = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4)), int(m.group(5)))
        return (dt_utc + timedelta(hours=7)).strftime("%d/%m/%Y %H:%M")
    except Exception:
        return ""


def _clean_note_html(raw_val: Any) -> str:
    """Làm sạch HTML/newline trong ghi chú của Admin/Sale trên Pancake."""
    if not raw_val:
        return ""
    txt = html.unescape(str(raw_val))
    txt = re.sub(r"<br\s*/?>", " | ", txt, flags=re.IGNORECASE)
    txt = re.sub(r"<[^>]+>", " ", txt)
    return re.sub(r"\s+", " ", txt).strip()


def _extract_notes_from_raw_list(notes_list: Any, page_label: str, seen_set: Set[str], out_lines: List[str]) -> None:
    """Trích xuất danh sách ghi chú Admin từ mảng notes của Pancake (conversation hoặc page_customer)."""
    if isinstance(notes_list, str):
        try:
            notes_list = json.loads(notes_list)
        except Exception:
            notes_list = []
    if not isinstance(notes_list, list):
        return
    for nt in notes_list:
        if not isinstance(nt, dict) or nt.get("removed_at"):
            continue
        msg = _clean_note_html(nt.get("message"))
        if not msg:
            continue
        key = msg.lower()
        if key in seen_set:
            continue
        seen_set.add(key)
        cb = nt.get("created_by") if isinstance(nt.get("created_by"), dict) else {}
        author = cb.get("fb_name") or cb.get("name") or nt.get("author") or "Admin"
        out_lines.append(f"- [{page_label}] (Note của {author}): {msg[:350]}")


def _diagnose_customer_pain_points(customer_texts: List[str], note_texts: List[str], tag_texts: List[str]) -> List[str]:
    """Chẩn đoán tự động các vấn đề / nỗi đau của khách từ tin nhắn khách, Note của Admin và Tag."""
    combined_ascii = _strip_accents(" \n ".join(customer_texts + note_texts + tag_texts))
    if not combined_ascii.strip():
        return []

    rules = [
        (
            "Quá tải thao tác thủ công trên Excel (file nặng/đơ, link nhiều file dễ lỗi, mất nhiều thời gian tổng hợp số liệu lặp lại)",
            ("thu cong", "excel nang", "file nang", "treo may", "do may", "link giua cac file", "nhieu file", "mat thoi gian", "ton thoi gian", "nhap lieu", "copy paste", "excel chi du dung", "excel co ban"),
        ),
        (
            "Đang dùng phần mềm kế toán (MISA, FAST, Bravo, ERP/SAP) nhưng bị giới hạn báo cáo mẫu, phải xuất ra đối chiếu sao kê / công nợ / đổ bút toán thủ công",
            ("misa", "fast", "bravo", "erp", "sap", "phan mem ke toan", "sao ke", "so phu", "nkc", "nhat ky chung", "doi chieu", "doi soat", "cong no", "hach toan"),
        ),
        (
            "Áp lực lên Báo cáo quản trị / Dashboard trực quan đa chiều (Lãi lỗ P&L, Dòng tiền, Doanh thu, Chi phí, BCTC) cho Sếp / BGĐ ra quyết định",
            ("bao cao quan tri", "bcqt", "lai lo", "p&l", "pnl", "dong tien", "bctc", "bao cao tai chinh", "dashboard", "cho sep", "bgd", "ban giam doc", "ke toan truong", "ktt", "ktth", "ke toan tong hop", "phan tich so lieu", "phan tich du lieu"),
        ),
        (
            "Muốn ứng dụng AI kết hợp Excel / Power Query để tự động hóa và tăng hiệu suất làm việc",
            ("ung dung ai", "ap dung ai", "ap dung them ai", "hoc ai", "prompt ai", "chatgpt", "cong nghe vao cong viec"),
        ),
        (
            "Đặc thù ngành nghề có khối lượng dữ liệu thô phân mảnh lớn (Bán lẻ/TMĐT, Xây dựng/BĐS, Sản xuất, Chuỗi/Cảng/Logistics)",
            ("xay dung", "bat dong san", "bds", "san xuat", "gia thanh", "dinh muc", "ton kho", "thuong mai dien tu", "tmdt", "shopee", "tiktok shop", "ban le", "chuoi", "logistics", "cang"),
        ),
        (
            "Băn khoăn về Học phí / Chi phí đầu tư (cần nhấn mạnh giá trị thực chiến, Support 1-1, 8 quyền lợi Combo hoặc phương án giảm 5% / chia 2 đợt)",
            ("hoc phi cao", "hoi cao", "dat", "gia cao", "chua du tai chinh", "chia dot", "tra gop", "giam gia", "uu dai"),
        ),
        (
            "Lo ngại thiếu thời gian (hay tăng ca tối, bận việc/con nhỏ, sợ nghỉ học miss bài) hoặc sợ không biết IT/code, dùng MacBook/Excel cũ",
            ("tang ca", "ban", "khong co thoi gian", "con nho", "so khong theo kip", "khong biet code", "khong ranh it", "macbook", "may mac", "excel cu", "record", "hoc lai", "bao luu"),
        ),
    ]
    detected: List[str] = []
    for label, kws in rules:
        if any(k in combined_ascii for k in kws):
            detected.append(label)
    return detected


def _fetch_live_pancake_notes(page_id_or_name: str, conv_id: str) -> List[Dict[str, Any]]:
    """Thử lấy nhanh ghi chú (notes) trực tiếp từ Pancake API cho hội thoại nếu payload trong DB chưa lưu notes (timeout 3.5s)."""
    try:
        from etl.pancake_client import PancakeClient

        client = PancakeClient()
        ptoken, resolved_pid, _ = client._get_page_access_token(page_id_or_name, conv_id)
        if not ptoken or not resolved_pid or not conv_id:
            return []
        url = f"https://pages.fm/api/public_api/v1/pages/{resolved_pid}/conversations/{conv_id}/messages"
        resp = client.session.get(url, params={"page_access_token": ptoken}, timeout=3.5)
        if resp.status_code == 200:
            notes = resp.json().get("notes")
            if isinstance(notes, list):
                return notes
    except Exception as e:
        logger.debug(f"Live pancake notes fetch skipped for {conv_id}: {e}")
    return []


def _build_sale_phone_context(
    db: Session,
    raw_d: str,
    phone_filter_fn,
    scoped_emp: Optional[str] = None,
) -> Tuple[List[str], List[str]]:
    """Đọc TOÀN BỘ hội thoại 1-1 trên TẤT CẢ các page (TikTok, FB, Zalo), Note của Admin, Comment và DealWin theo SĐT."""
    blocks: List[str] = []
    tools: List[str] = []
    digit_q = raw_d[-9:]

    leads = (
        db.query(DimLead, FactLeadActivity)
        .outerjoin(FactLeadActivity, FactLeadActivity.lead_id == DimLead.id)
        .filter(
            phone_filter_fn(DimLead.phone_number, raw_d),
            or_(FactLeadActivity.conversation_id.is_(None), ~FactLeadActivity.conversation_id.like("pzl_g_%")),
        )
        .all()
    )

    if scoped_emp and leads:
        # Cho phép xem nếu khách chưa phân công nhân viên ở bất kỳ page nào hoặc có ít nhất 1 hội thoại gắn với scoped_emp
        has_own_or_unassigned = any(
            (not act or not act.assigned_users or not act.assigned_users.strip() or act.assigned_users.strip().lower() == "chưa phân công")
            or employee_matches_field(act.assigned_users, scoped_emp)
            for _, act in leads
        )
        if not has_own_or_unassigned:
            dw_own = db.query(DealWin.care_by).filter(phone_filter_fn(DealWin.phone_number, raw_d)).all()
            sd_own = db.query(SalesDeal.nv_cs).filter(phone_filter_fn(SalesDeal.sdt, raw_d)).all()
            if any(employee_matches_field(c, scoped_emp) for (c,) in dw_own + sd_own):
                has_own_or_unassigned = True

        if not has_own_or_unassigned:
            return (
                [
                    f"[GIỚI HẠN PHẠM VI DỮ LIỆU CÁ NHÂN]\n"
                    f"- Khách hàng có SĐT kết thúc bằng {digit_q} hiện đang thuộc phụ trách riêng của nhân sự khác.\n"
                    f"- Tài khoản của bạn ({scoped_emp}) chỉ được phép tra cứu chi tiết lịch sử tin nhắn của khách hàng do mình phụ trách hoặc khách chưa phân công."
                ],
                [f"Chặn phạm vi dữ liệu SĐT ({digit_q})"],
            )

    # Sắp xếp toàn bộ hồ sơ/hội thoại theo trình tự thời gian từ cũ đến mới
    def _row_sort_key(pair):
        ld, act = pair
        dt = (act.contacted_at if act and act.contacted_at else None) or ld.first_created_at or datetime.min
        if getattr(dt, "tzinfo", None) is not None:
            dt = dt.replace(tzinfo=None)
        return dt

    leads.sort(key=_row_sort_key)

    conv_ids: List[str] = []
    conv_meta: Dict[str, Tuple[str, Optional[FactLeadActivity], DimLead]] = {}
    customer_ids: Set[str] = set()
    all_tags_list: List[str] = []
    admin_note_lines: List[str] = []
    seen_notes: Set[str] = set()
    customer_utterances: List[str] = []

    if leads:
        lines = [f"[KẾT QUẢ TRA CỨU LEAD THEO SĐT TRÊN TẤT CẢ CÁC PAGE ({len(leads)} hội thoại)]"]
        for ld, act in leads:
            page_name = resolve_canonical_page_name(ld.page_id, fallback=ld.page_id or "Khác")
            cid = act.conversation_id if act else None
            p_url = build_pancake_url(ld.page_id, cid)
            last_dt = (act.contacted_at if act and act.contacted_at else ld.first_created_at)
            last_str = last_dt.strftime("%d/%m/%Y %H:%M") if last_dt else "-"
            tag_str = act.status_tag if act and act.status_tag else "Chưa gắn"
            lines.append(
                f"- Page: {page_name} | Khách: {ld.name or 'Chưa rõ'} | SĐT: {ld.phone_number} | "
                f"Tag: {tag_str} | Sale: {act.assigned_users if act and act.assigned_users else 'Chưa phân'} | "
                f"Số tin: {act.message_count if act else 0} | Tương tác cuối: {last_str} | Link: {p_url or 'N/A'}"
            )
            if ld.customer_id:
                customer_ids.add(ld.customer_id)
            if act and act.status_tag:
                all_tags_list.append(act.status_tag)
            if cid and cid not in conv_meta:
                conv_ids.append(cid)
                conv_meta[cid] = (page_name, act, ld)
        blocks.append("\n".join(lines))
        tools.append(f"Tra cứu SĐT đa page ({digit_q}, {len(leads)} hội thoại)")

    # Kiểm tra trạng thái đã đăng ký học (DealWin / SalesDeal) & lấy Note/Kỳ vọng của khách
    is_enrolled = False
    try:
        dw_rows = (
            db.query(DealWin)
            .options(defer(DealWin.raw_data))
            .filter(phone_filter_fn(DealWin.phone_number, raw_d))
            .limit(3)
            .all()
        )
        sd_rows = db.query(SalesDeal).filter(phone_filter_fn(SalesDeal.sdt, raw_d)).limit(3).all()
        if dw_rows or sd_rows:
            enr_lines = ["[TRẠNG THÁI ĐĂNG KÝ HỌC / DEAL WIN]"]
            for dw in dw_rows:
                if dw.is_student:
                    is_enrolled = True
                enr_lines.append(
                    f"- DealWin: {dw.full_name or '-'} | Đã là HV: {'Có' if dw.is_student else 'Chưa'} | "
                    f"Ngành: {dw.industry or '-'} | Vị trí: {dw.job_title or '-'} | Kỳ vọng: {(dw.expectation or '-')[:160]} | Sale: {dw.care_by or '-'}"
                )
                if dw.industry or dw.job_title or dw.expectation:
                    note_str = f"Ngành: {dw.industry or '-'} | Vị trí: {dw.job_title or '-'} | Kỳ vọng: {dw.expectation or '-'}"
                    admin_note_lines.append(f"- [Form Học viên / DealWin]: {note_str[:300]}")
            for sd in sd_rows:
                is_enrolled = True
                enr_lines.append(
                    f"- SalesDeal: {sd.ho_ten} | Chương trình: {sd.chuong_trinh or '-'} | Lớp: {sd.lop or '-'} | "
                    f"Đã thu: {int(sd.da_thu or 0):,}đ | Còn nợ: {int(sd.con_no or 0):,}đ | NV CS: {sd.nv_cs or '-'}"
                )
                if sd.note or sd.ky_vong or sd.linh_vuc:
                    sd_info = f"Lĩnh vực: {sd.linh_vuc or '-'} | Kỳ vọng: {sd.ky_vong or '-'} | Note Admin: {sd.note or '-'}"
                    admin_note_lines.append(f"- [SalesDeal Note]: {sd_info[:300]}")
            blocks.append("\n".join(enr_lines))
            tools.append("Kiểm tra DealWin/SalesDeal")
    except Exception as e:
        logger.warning(f"Sale phone DealWin/SalesDeal lookup error: {e}")

    # Đọc Comment trên bài viết/video (FB/TikTok) + Note của Admin đính kèm trong Comment.payload.page_customer.notes
    try:
        cmt_filters = [phone_filter_fn(Comment.phone_number, raw_d)]
        if customer_ids:
            cmt_filters.append(Comment.customer_id.in_(list(customer_ids)))
        cmts = (
            db.query(
                Comment.page_id,
                Comment.page_name,
                Comment.message,
                Comment.inserted_at,
                Comment.post_url,
                Comment.payload["page_customer"]["notes"],
            )
            .filter(or_(*cmt_filters))
            .order_by(Comment.inserted_at.asc())
            .limit(10)
            .all()
        )
        if cmts:
            c_lines = ["[BÌNH LUẬN CỦA KHÁCH TRÊN BÀI VIẾT / VIDEO]"]
            for c_pid, c_pname, c_msg, c_dt, c_url, c_notes in cmts:
                pg_lbl = c_pname or resolve_canonical_page_name(c_pid, fallback=c_pid or "Khác")
                dt_str = c_dt.strftime("%d/%m/%Y %H:%M") if c_dt else "-"
                msg_clean = re.sub(r"\s+", " ", (c_msg or "")).strip()
                if msg_clean:
                    c_lines.append(f"- [{dt_str}] ({pg_lbl}): {msg_clean[:300]}")
                    customer_utterances.append(f"({pg_lbl} Comment) {msg_clean[:240]}")
                if c_notes:
                    _extract_notes_from_raw_list(c_notes, pg_lbl, seen_notes, admin_note_lines)
            if len(c_lines) > 1:
                blocks.append("\n".join(c_lines))
                tools.append("Lịch sử Comment")
    except Exception as e:
        logger.warning(f"Sale phone Comment lookup error: {e}")

    # Đọc TOÀN BỘ tin nhắn + Note của Admin hiện có trong DB trên TẤT CẢ các hội thoại (không cắt [:2] hay [-12:])
    all_sale_ascii_parts: List[str] = []
    chat_sections: List[str] = []
    total_chars = 0
    MAX_TOTAL_CHAT_CHARS = 35000

    if conv_ids:
        raw_rows = (
            db.query(
                RawConversation.pancake_id,
                RawConversation.page_id,
                RawConversation.payload["messages"],
                RawConversation.payload["notes"],
                RawConversation.payload["page_customer"]["notes"],
            )
            .filter(RawConversation.pancake_id.in_(conv_ids))
            .all()
        )
        raw_map = {pid: (pg, msgs, n1, n2) for pid, pg, msgs, n1, n2 in raw_rows}
        pages_read = 0
        live_note_fetches = 0

        for cid in conv_ids:
            if cid not in raw_map:
                continue
            page_id_val, msgs, raw_notes_1, raw_notes_2 = raw_map[cid]
            page_label, act_obj, _ = conv_meta.get(cid, (resolve_canonical_page_name(page_id_val), None, None))

            # Trích xuất Note của Admin từ DB; nếu DB cũ chưa có cột notes trên hội thoại Zalo thì gọi nhẹ Pancake API
            before_notes_cnt = len(admin_note_lines)
            if raw_notes_1:
                _extract_notes_from_raw_list(raw_notes_1, page_label, seen_notes, admin_note_lines)
            if raw_notes_2:
                _extract_notes_from_raw_list(raw_notes_2, page_label, seen_notes, admin_note_lines)
            if len(admin_note_lines) == before_notes_cnt and live_note_fetches < 2:
                is_zalo_conv = cid.startswith("pzl_") or "zalo" in (page_label or "").lower()
                if is_zalo_conv or len(conv_ids) == 1:
                    live_note_fetches += 1
                    live_notes = _fetch_live_pancake_notes(page_id_val, cid)
                    if live_notes:
                        _extract_notes_from_raw_list(live_notes, page_label, seen_notes, admin_note_lines)

            if isinstance(msgs, str):
                try:
                    msgs = json.loads(msgs)
                except Exception:
                    msgs = []
            if not isinstance(msgs, list) or not msgs:
                continue

            # Đảm bảo thứ tự tin nhắn trong mỗi hội thoại từ cũ -> mới
            msgs_sorted = sorted(
                [m for m in msgs if isinstance(m, dict)],
                key=lambda m: str(m.get("inserted_at") or m.get("created_at") or ""),
            )
            db_cnt = len(msgs_sorted)
            total_cnt = act_obj.message_count if act_obj and act_obj.message_count else db_cnt
            tag_info = f" | Tag: {act_obj.status_tag}" if act_obj and act_obj.status_tag else ""
            sale_info = f" | Sale: {act_obj.assigned_users}" if act_obj and act_obj.assigned_users else ""
            cnt_note = f"{db_cnt} tin" if db_cnt >= total_cnt else f"{db_cnt}/{total_cnt} tin gần nhất trong DB"

            sec_lines = [f"--- Hội thoại trên {page_label} ({cnt_note}{tag_info}{sale_info}) ---"]
            for m in msgs_sorted:
                raw_txt = html.unescape(str(m.get("message") or m.get("original_message") or ""))
                raw_txt = re.sub(r"<br\s*/?>", "\n", raw_txt, flags=re.IGNORECASE)
                clean_txt = re.sub(r"<[^>]+>", " ", raw_txt)
                clean_txt = re.sub(r"[ \t]+", " ", clean_txt)
                clean_txt = re.sub(r"\n{2,}", "\n", clean_txt).strip()
                if not clean_txt:
                    clean_txt = "[Đã gửi ảnh/file/đính kèm]"

                raw_role = (m.get("role") or "").strip().lower()
                is_customer = raw_role in ("khách hàng", "khach hang", "customer", "user")
                sender_role = "Khách" if is_customer else "Sale/Admin"
                if is_customer and clean_txt != "[Đã gửi ảnh/file/đính kèm]":
                    customer_utterances.append(f"({page_label}) {clean_txt[:300]}")
                elif not is_customer and clean_txt != "[Đã gửi ảnh/file/đính kèm]":
                    all_sale_ascii_parts.append(_strip_accents(clean_txt))

                ts_str = _format_msg_time_vn(m.get("inserted_at") or m.get("created_at"))
                prefix = f"[{ts_str}] {sender_role}" if ts_str else sender_role
                line_text = f"{prefix}: {clean_txt[:1200]}"
                if total_chars + len(line_text) > MAX_TOTAL_CHAT_CHARS:
                    sec_lines.append("... (lược bớt do vượt giới hạn độ dài ngữ cảnh)")
                    break
                sec_lines.append(line_text)
                total_chars += len(line_text)

            if len(sec_lines) > 1:
                chat_sections.append("\n".join(sec_lines))
                pages_read += 1

        if chat_sections:
            tools.append(f"Toàn bộ lịch sử chat ({pages_read} hội thoại đa page)")

    if admin_note_lines:
        tools.append(f"Ghi chú của Admin/Sale ({len(admin_note_lines)} note)")

    # Tổng hợp khối Chẩn đoán nhanh Hồ sơ, Note của Admin & Nỗi đau khách hàng
    detected_pains = _diagnose_customer_pain_points(customer_utterances, admin_note_lines, all_tags_list)
    if leads or admin_note_lines or customer_utterances:
        diag_lines = ["[CHẨN ĐOÁN NHANH HỒ SƠ, GHI CHÚ CỦA ADMIN & NỖI ĐAU KHÁCH HÀNG]"]
        if admin_note_lines:
            diag_lines.append("1. Ghi chú (Notes) của Admin / Sale trên hệ thống:")
            diag_lines.extend(admin_note_lines[:12])
        else:
            diag_lines.append("1. Ghi chú (Notes) của Admin / Sale: Chưa có ghi chú riêng trên Pancake.")

        if customer_utterances:
            diag_lines.append("2. Các tin nhắn / chia sẻ trực tiếp của Khách hàng:")
            for cu in customer_utterances[-10:]:
                diag_lines.append(f"- {cu}")
        else:
            diag_lines.append("2. Tin nhắn của Khách hàng: Chưa có tin nhắn văn bản chi tiết.")

        if detected_pains:
            diag_lines.append("3. Vấn đề & Nỗi đau trọng tâm phát hiện được (BẮT BUỘC nhấn mạnh khi soạn tin):")
            for dp in detected_pains:
                diag_lines.append(f"- 🎯 {dp}")
            tools.append("Chẩn đoán nỗi đau khách hàng")
        else:
            diag_lines.append(
                "3. Vấn đề & Nỗi đau trọng tâm: Khách chưa bộc lộ rõ nỗi đau chi tiết -> Cần bám sát kịch bản khai thác hoặc nhấn mạnh nỗi đau phổ biến của kế toán (xử lý dữ liệu Excel thủ công mất thời gian, đối chiếu sao kê/công nợ, lên báo cáo quản trị tự động)."
            )
        blocks.append("\n".join(diag_lines))

    # Xây dựng checklist xác định tự động các bước & vòng Remind ĐÃ GỬI xuyên suốt mọi page
    all_sale_ascii = "\n".join(all_sale_ascii_parts)
    all_tags_ascii = _strip_accents(" , ".join(all_tags_list))

    sent_steps: List[str] = []
    if any(k in all_sale_ascii for k in ("thu cong bang excel", "phan mem ke toan la chinh", "xu ly du lieu thu cong")):
        sent_steps.append("Step 1 (Hỏi Excel hay phần mềm)")
    if any(k in all_sale_ascii for k in ("excel khong con ok", "link giua cac file de loi", "phu thuoc vao phan mem ke toan", "tick chon va keo tha", "form bao cao mau", "power query")):
        sent_steps.append("Step 2A / Tư vấn công cụ Power Query & Power BI (CẤM GỬI LẠI)")
    if any(k in all_sale_ascii for k in ("app.powerbi.com/view", "7.5tr", "7,5tr", "7tr5", "k1.", "k2.", "k3.")) or "da gui tt" in all_tags_ascii:
        sent_steps.append("Step 3 (Lộ trình K1-K2-K3 / Giá combo / Demo)")

    remind_checks = [
        ("Vòng 1: Video 4 Scope", ("i5kks7qprw4", "wpw5yd0kjhm", "scope dao tao", "4 scope")),
        ("Vòng 2: Feedback học viên", ("acca", "cma", "feedback")),
        ("Vòng 3: Layout chi tiết từng buổi", ("1dz2f8qj0gxmd6k8kqmjfpccp7yruixv39swpu61cpsy", "chi tiet tung buoi")),
        ("Vòng 4: Quyền lợi Combo (8 ý)", ("power bi pro", "13usd", "quyen loi khi hoc vien")),
        ("Vòng 5: Kho 100 bộ file + Tool Hóa đơn/EzExcel", ("100 file", "100 bo file", "7626154405628284180", "ezexcel", "tool hoa don")),
        ("Vòng 6: Lịch khai giảng / Update K2 14 buổi AI", ("14 buoi", "khai giang")),
        ("Vòng 7: Tặng Bộ Prompt AI & tài liệu ghost lâu", ("14guoh66hilevracxgwoasfvqyevu", "prompt mau ai", "tiet kiem 80%")),
        ("Vòng 8: Data Talk / Workshop / Học thử", ("data talk", "workshop", "hoc thu")),
    ]
    sent_reminds: List[str] = []
    unsent_reminds: List[str] = []
    for r_label, kws in remind_checks:
        if any(k in all_sale_ascii for k in kws) or (r_label.startswith("Vòng 8") and "data talk" in all_tags_ascii):
            sent_reminds.append(r_label)
        else:
            unsent_reminds.append(r_label)

    in_remind_stage = (
        any(t in all_tags_ascii for t in ("remind", "da gui tt", "suy nghi", "quan tam sau"))
        or any("Step 3" in s for s in sent_steps)
    )
    if "da la hoc vien" in all_tags_ascii:
        is_enrolled = True

    if leads or chat_sections:
        chk_lines = ["[CHECKLIST TRẠNG THÁI & NỘI DUNG ĐÃ GỬI QUA TẤT CẢ CÁC PAGE]"]
        if is_enrolled:
            chk_lines.append("- ⚠️ KHÁCH ĐÃ LÀ HỌC VIÊN / ĐÃ CHỐT DEAL — KHÔNG gửi tin bán hàng hay Remind lead mới!")
        chk_lines.append(f"- Các Step tư vấn ĐÃ GỬI: {', '.join(sent_steps) if sent_steps else 'Chưa phát hiện trong tin nhắn DB'}")
        chk_lines.append(f"- Các vòng Remind ĐÃ GỬI (KHÔNG gửi lặp): {', '.join(sent_reminds) if sent_reminds else 'Chưa gửi vòng nào'}")
        chk_lines.append(f"- Các vòng Remind CHƯA GỬI (ưu tiên chọn 1 vòng phù hợp nhất): {', '.join(unsent_reminds) if unsent_reminds else 'Đã gửi đủ 8 vòng — chuyển hỏi thăm nhẹ nhàng theo bối cảnh'}")
        if in_remind_stage:
            chk_lines.append("- ⚠️ QUY TẮC CỨNG: Khách đang ở bước REMIND / SAU LỘ TRÌNH → CẤM TUYỆT ĐỐI gửi lại Step 1, Step 2A (Excel/phần mềm), Step 2B, mẫu ngành nghề cũ hoặc lộ trình Step 3!")
        elif any("Step 2A" in s for s in sent_steps):
            chk_lines.append("- ⚠️ QUY TẮC CỨNG: Đã qua Step 2A → CẤM GỬI LẠI Step 2A!")
        blocks.append("\n".join(chk_lines))

    if chat_sections:
        blocks.append("[TỔNG HỢP LỊCH SỬ CHAT TOÀN BỘ CÁC PAGE CỦA KHÁCH (CŨ → MỚI)]\n" + "\n\n".join(chat_sections))

    return blocks, tools


def build_live_data_context(
    db: Session,
    assistant_id: str,
    question: str,
    scoped_emp: Optional[str] = None,
) -> Tuple[str, List[str]]:
    """Trích xuất dữ liệu thực tế từ DB theo đúng trợ lý (Sale / Kế toán / Quy trình & SLA) mà không quét bảng thừa."""
    tools_used: List[str] = []
    context_blocks: List[str] = []
    now_vn = get_vn_now()
    norm_q = normalize_text(question)
    ascii_q = _strip_accents(question)

    # Bóc số điện thoại nếu câu hỏi có chứa dãy 4-11 chữ số
    phone_matches = re.findall(r"(?:\+?84|0)?\d[\d\s\.\-]{3,11}\d", question)
    search_digits = [re.sub(r"\D", "", m) for m in phone_matches if len(re.sub(r"\D", "", m)) >= 4]

    def _phone_filter(col, raw_digits: str):
        if len(raw_digits) >= 9:
            last9 = raw_digits[-9:]
            norm_p = normalize_phone(raw_digits)
            candidates = list({p for p in (norm_p, f"0{last9}", f"84{last9}", f"+84{last9}", raw_digits) if p})
            return col.in_(candidates)
        return col.like(f"%{raw_digits}%")

    if assistant_id == "sale":
        if search_digits:
            wants_kpi = any(
                kw in ascii_q
                for kw in ("kpi", "thong ke", "nhan vien", "7 ngay", "tuan", "hom nay", "ti le", "ty le", "bao nhieu lead", "tong lead")
            )
        else:
            wants_kpi = any(
                kw in ascii_q
                for kw in ("lead", "sdt", "so dien thoai", "kpi", "bao nhieu", "tong", "nhan vien", "thong ke", "7 ngay", "tuan", "hom nay", "ti le", "ty le")
            )
        if wants_kpi:
            try:
                start_7d = (now_vn - timedelta(days=7)).replace(hour=0, minute=0, second=0, microsecond=0)
                end_now = now_vn.replace(hour=23, minute=59, second=59, microsecond=999999)
                leads_map = classify_leads(db, start_7d, end_now, employee=scoped_emp)
                new_leads = recontact_leads = new_phone = recontact_phone = 0
                emp_counts: Dict[str, int] = {}
                phone_emp_counts: Dict[str, int] = {}
                for ld in leads_map.values():
                    emp = ld.primary_employee or "Chưa phân công"
                    if ld.is_new:
                        new_leads += 1
                        emp_counts[emp] = emp_counts.get(emp, 0) + 1
                        if ld.has_phone:
                            new_phone += 1
                    else:
                        recontact_leads += 1
                        if ld.has_phone:
                            recontact_phone += 1
                    if ld.has_phone:
                        phone_emp_counts[emp] = phone_emp_counts.get(emp, 0) + 1

                total_leads = new_leads + recontact_leads
                total_phone = new_phone + recontact_phone
                emp_stats = ", ".join(f"{k}: {v} lead mới" for k, v in list(emp_counts.items())[:8])
                phone_emp = ", ".join(f"{k}: {v} SĐT" for k, v in list(phone_emp_counts.items())[:8])
                context_blocks.append(
                    f"[DỮ LIỆU LEAD 7 NGÀY QUA ({start_7d.strftime('%d/%m/%Y')} - {now_vn.strftime('%d/%m/%Y')})]\n"
                    f"- Tổng Lead: {total_leads} (Lead Mới: {new_leads}, Contact Lại: {recontact_leads})\n"
                    f"- Tổng SĐT thu được: {total_phone} (SĐT Mới: {new_phone}, SĐT Contact Lại: {recontact_phone})\n"
                    f"- Phân bổ Lead Mới theo nhân sự: {emp_stats or 'Chưa có'}\n"
                    f"- Phân bổ SĐT theo nhân sự: {phone_emp or 'Chưa có'}"
                )
                tools_used.append("KPI Lead 7 ngày (lead_metrics)")
            except Exception as e:
                logger.warning(f"Sale KPI tool error: {e}")

        if search_digits:
            phone_blocks, phone_tools = _build_sale_phone_context(db, search_digits[0], _phone_filter, scoped_emp=scoped_emp)
            context_blocks.extend(phone_blocks)
            tools_used.extend(phone_tools)

    elif assistant_id == "ke_toan":
        wants_finance_stats = bool(search_digits) or any(
            kw in ascii_q
            for kw in ("doanh thu", "tong hop", "bao nhieu", "cong no", "con no", "da thu", "phai thu", "chua dong", "so lieu", "bao cao", "hien tai")
        )
        if wants_finance_stats:
            try:
                sd_base = db.query(SalesDeal)
                dw_base = db.query(DealWin)
                if scoped_emp:
                    sd_base = sd_base.filter(SalesDeal.nv_cs.ilike(f"%{scoped_emp}%"))
                    dw_base = dw_base.filter(DealWin.care_by.ilike(f"%{scoped_emp}%"))

                totals = sd_base.with_entities(
                    func.count(SalesDeal.id),
                    func.coalesce(func.sum(SalesDeal.tong_tien), 0),
                    func.coalesce(func.sum(SalesDeal.da_thu), 0),
                    func.coalesce(func.sum(SalesDeal.con_no), 0),
                ).first()
                deal_win_count = dw_base.with_entities(func.count(DealWin.id)).scalar() or 0
                debt_count = sd_base.filter(SalesDeal.con_no > 0).with_entities(func.count(SalesDeal.id)).scalar() or 0
                scope_label = f"CỦA CÁ NHÂN {scoped_emp.upper()}" if scoped_emp else "TRÊN HỆ THỐNG"
                if totals:
                    cnt, tong_tien, da_thu, con_no = totals
                    context_blocks.append(
                        f"[TỔNG HỢP DOANH THU & CÔNG NỢ {scope_label}]\n"
                        f"- Tổng số học viên (Deal Win): {deal_win_count:,} học viên\n"
                        f"- Tổng số bản ghi Nhập Deal (sales_deals): {cnt:,} deal\n"
                        f"- Tổng học phí phải thu: {int(tong_tien):,} VNĐ\n"
                        f"- Tổng tiền đã thu: {int(da_thu):,} VNĐ\n"
                        f"- Tổng công nợ còn phải thu: {int(con_no):,} VNĐ ({debt_count} deal còn nợ)"
                    )
                    tools_used.append("Tổng hợp Doanh thu & Công nợ (sales_deals)")

                if "no" in ascii_q or "chua dong" in ascii_q or "con no" in ascii_q or search_digits:
                    q_deals = db.query(SalesDeal)
                    if scoped_emp:
                        q_deals = q_deals.filter(SalesDeal.nv_cs.ilike(f"%{scoped_emp}%"))
                    if search_digits:
                        q_deals = q_deals.filter(_phone_filter(SalesDeal.sdt, search_digits[0]))
                    else:
                        q_deals = q_deals.filter(SalesDeal.con_no > 0)
                    top_deals = q_deals.order_by(desc(SalesDeal.con_no), desc(SalesDeal.id)).limit(8).all()
                    if top_deals:
                        d_lines = [f"[DANH SÁCH DEAL / CÔNG NỢ CHI TIẾT {scope_label}]"]
                        for d in top_deals:
                            d_lines.append(
                                f"- Học viên: {d.ho_ten} | SĐT: {d.sdt} | Chương trình: {d.chuong_trinh or 'Chưa rõ'} | "
                                f"Lớp: {d.lop or '-'} | Đã thu: {int(d.da_thu or 0):,}đ | Còn nợ: {int(d.con_no or 0):,}đ | "
                                f"Hạn AR: {d.ngay_thu_ar or '-'} | NV CS: {d.nv_cs or '-'}"
                            )
                        context_blocks.append("\n".join(d_lines))
                        tools_used.append("Chi tiết Công nợ học viên")
            except Exception as e:
                logger.warning(f"Accounting tool error: {e}")

    elif assistant_id == "quy_trinh":
        is_pure_rule_query = any(
            k in ascii_q for k in ("cach tinh", "dinh nghia", "quy tac", "chuoi trang thai", "khi nao bot", "vi sao mac dinh")
        ) and not any(
            k in ascii_q
            for k in ("insight", "thong so", "so lieu", "thuc te", "hien tai", "ngay qua", "hom nay", "hom qua", "tuan", "thang", "ton dong", "diem nghen", "hieu suat", "danh gia", "phan tich")
        )
        wants_dashboard_metrics = not is_pure_rule_query and any(
            kw in ascii_q
            for kw in (
                "metric", "thong so", "chi so", "so lieu", "dashboard", "insight", "sla",
                "phan tich", "danh gia", "bao cao", "hieu suat", "nhan vien", "sale",
                "kenh", "facebook", "fb", "tiktok", "remind", "ton dong", "chua phan cong",
                "bo sot", "ty le", "ti le", "chuyen doi", "convert", "deal", "xu huong",
                "so sanh", "diem nghen", "tinh hinh", "tuan", "ngay", "thang", "hom nay",
                "hom qua", "hien tai", "thuc te", "top", "kpi", "qua han", "bo quen",
            )
        )
        if wants_dashboard_metrics:
            if scoped_emp:
                start_7d = (now_vn - timedelta(days=7)).replace(hour=0, minute=0, second=0, microsecond=0)
                end_now = now_vn.replace(hour=23, minute=59, second=59, microsecond=999999)
                emp_leads = classify_leads(db, start_7d, end_now, employee=scoped_emp)
                n_new = sum(1 for ld in emp_leads.values() if ld.is_new)
                n_rec = sum(1 for ld in emp_leads.values() if ld.is_recontact)
                n_ph = sum(1 for ld in emp_leads.values() if ld.has_phone)
                context_blocks.append(
                    f"[SỐ LIỆU CÁ NHÂN 7 NGÀY QUA CỦA {scoped_emp.upper()} (Phạm vi dữ liệu cá nhân)]\n"
                    f"- Tổng Lead phụ trách: {n_new + n_rec} (Mới: {n_new}, Contact lại: {n_rec})\n"
                    f"- Số Lead có SĐT: {n_ph}"
                )
                tools_used.append(f"KPI Cá nhân ({scoped_emp})")
            else:
                dash_blocks, dash_tools = _build_quy_trinh_dashboard_context(db, question, ascii_q, now_vn)
                context_blocks.extend(dash_blocks)
                tools_used.extend(dash_tools)

    return "\n\n".join(context_blocks), tools_used


def call_gemini_generate(
    system_prompt: str,
    user_prompt: str,
    history: List[Dict[str, str]],
    api_key: str,
    temperature: float = 0.25,
    enable_search: bool = False,
) -> Tuple[str, str, bool]:
    contents: List[Dict[str, Any]] = []
    for msg in history[-6:]:
        role = "model" if msg.get("role") == "assistant" else "user"
        text_val = (msg.get("content") or "").strip()
        if text_val:
            contents.append({"role": role, "parts": [{"text": text_val[:2000]}]})

    contents.append({"role": "user", "parts": [{"text": user_prompt}]})

    base_payload: Dict[str, Any] = {
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "contents": contents,
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": 4096,
            "thinkingConfig": {"thinkingBudget": 0},
        },
    }

    def _post_gemini(model_name: str, body: Dict[str, Any]) -> requests.Response:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
        resp = requests.post(url, json=body, timeout=20)
        if resp.status_code == 400 and "thinking" in resp.text.lower():
            no_think = {**body, "generationConfig": {"temperature": temperature, "maxOutputTokens": 4096}}
            resp = requests.post(url, json=no_think, timeout=20)
        return resp

    last_error = ""
    for model_name in GENERATION_MODELS:
        try:
            used_search = False
            resp = None
            if enable_search:
                search_payload = {**base_payload, "tools": [{"google_search": {}}]}
                resp = _post_gemini(model_name, search_payload)
                if resp.status_code == 200:
                    used_search = True
                elif resp.status_code in (400, 403, 429):
                    # Nếu gói API chưa mở Search Grounding hoặc model không hỗ trợ tools thì lùi về generateContent chuẩn
                    resp = _post_gemini(model_name, base_payload)
            else:
                resp = _post_gemini(model_name, base_payload)

            if resp is not None and resp.status_code == 200:
                data = resp.json()
                candidates = data.get("candidates") or []
                if candidates:
                    finish_reason = candidates[0].get("finishReason")
                    if finish_reason and finish_reason != "STOP":
                        logger.warning(f"Gemini {model_name} finishReason={finish_reason}")
                    parts = candidates[0].get("content", {}).get("parts") or []
                    answer = "".join(p.get("text", "") for p in parts).strip()
                    if answer:
                        gm = candidates[0].get("groundingMetadata") or {}
                        actually_searched = used_search and bool(gm.get("webSearchQueries") or gm.get("groundingChunks"))
                        return answer, model_name, actually_searched
            last_error = f"{model_name} HTTP {resp.status_code if resp is not None else 'ERR'}: {(resp.text[:180] if resp is not None else '')}"
            logger.warning(f"Gemini model {model_name} fallback: {last_error}")
        except Exception as e:
            last_error = f"{model_name} exception: {e}"
            logger.warning(f"Gemini request error on {model_name}: {e}")

    raise HTTPException(
        status_code=502,
        detail=f"Không thể kết nối Gemini API lúc này ({last_error}). Vui lòng kiểm tra lại GEMINI_API_KEY hoặc thử lại sau ít giây.",
    )


def seed_default_knowledge_if_empty(db: Session) -> int:
    count = db.query(func.count(KnowledgeChunk.id)).scalar() or 0
    if count > 0:
        return 0
    return _ingest_documents_list(db, DEFAULT_SEED_DOCS, created_by="system_seed")


def _ingest_documents_list(db: Session, docs: List[Dict[str, str]], created_by: str = "admin") -> int:
    api_key = get_gemini_api_key(db)
    total_chunks = 0
    for doc in docs:
        doc_name = (doc.get("doc_name") or "").strip()
        category = (doc.get("category") or "sale").strip()
        content = (doc.get("content") or "").strip()
        if not doc_name or not content:
            continue

        chunks = split_text_into_chunks(content)
        if not chunks:
            continue

        embeddings = embed_texts(chunks, api_key)
        doc_id = f"doc_{uuid.uuid4().hex[:10]}"
        for idx, (chunk_text, emb) in enumerate(zip(chunks, embeddings)):
            db.add(
                KnowledgeChunk(
                    doc_id=doc_id,
                    doc_name=doc_name,
                    category=category,
                    chunk_index=idx,
                    content=chunk_text,
                    embedding=emb,
                    created_by=created_by,
                )
            )
            total_chunks += 1

    db.commit()
    clear_ai_knowledge_cache()
    return total_chunks


# ───────────────────────── Pydantic Schemas ─────────────────────────


class ChatMessageInput(BaseModel):
    role: str = Field(..., description="user hoặc assistant")
    content: str


class ChatRequest(BaseModel):
    assistant_id: str = Field("sale", description="sale | ke_toan | quy_trinh")
    question: str = Field(..., min_length=1, max_length=8000)
    history: List[ChatMessageInput] = Field(default_factory=list)


class IngestDocumentRequest(BaseModel):
    doc_name: str = Field(..., min_length=2, max_length=200)
    category: str = Field("sale", description="sale | ke_toan | quy_trinh | chung")
    content: str = Field(..., min_length=10)


class ApiKeyConfigRequest(BaseModel):
    api_key: str = Field(..., min_length=10)


# ───────────────────────── API Routes ─────────────────────────


@router.get("/assistants", dependencies=[Depends(require_tab_access("ai_assistant"))])
def list_assistants(db: Session = Depends(get_db)):
    try:
        seed_default_knowledge_if_empty(db)
    except Exception as e:
        logger.warning(f"Auto-seed warning: {e}")

    all_chunks = _load_knowledge_cache(db)
    doc_map: Dict[str, Set[str]] = {"sale": set(), "ke_toan": set(), "quy_trinh": set(), "chung": set()}
    for c in all_chunks:
        cat = c["category"]
        if cat in doc_map:
            doc_map[cat].add(c["doc_id"])

    assistants_out = []
    for aid, info in AI_ASSISTANTS.items():
        cats = info["categories"]
        doc_ids = set()
        for cat in cats:
            doc_ids |= doc_map.get(cat, set())
        assistants_out.append(
            {
                **info,
                "doc_count": len(doc_ids),
            }
        )

    key = get_gemini_api_key(db)
    return {
        "assistants": assistants_out,
        "total_chunks": len(all_chunks),
        "masked_api_key": mask_api_key(key),
        "has_api_key": bool(key),
    }


@router.get("/documents", dependencies=[Depends(require_tab_access("ai_assistant"))])
def list_documents(category: Optional[str] = Query(None), db: Session = Depends(get_db)):
    all_chunks = _load_knowledge_cache(db)
    docs_by_id: Dict[str, Dict[str, Any]] = {}
    for c in all_chunks:
        if category and c["category"] != category:
            continue
        did = c["doc_id"]
        if did not in docs_by_id:
            docs_by_id[did] = {
                "doc_id": did,
                "doc_name": c["doc_name"],
                "category": c["category"],
                "chunk_count": 0,
                "preview": c["content"][:220] + ("..." if len(c["content"]) > 220 else ""),
                "has_embedding": bool(c.get("embedding")),
                "created_at": c["created_at"],
            }
        docs_by_id[did]["chunk_count"] += 1

    return {"documents": list(docs_by_id.values())}


@router.post("/documents", dependencies=[Depends(require_admin)])
def ingest_document(req: IngestDocumentRequest, db: Session = Depends(get_db)):
    if req.category not in ("sale", "ke_toan", "quy_trinh", "chung"):
        raise HTTPException(status_code=400, detail="Danh mục không hợp lệ (chọn sale, ke_toan, quy_trinh hoặc chung).")

    added = _ingest_documents_list(
        db,
        [{"doc_name": req.doc_name, "category": req.category, "content": req.content}],
        created_by="user",
    )
    return {"status": "ok", "chunks_added": added, "doc_name": req.doc_name}


@router.post("/seed", dependencies=[Depends(require_admin)])
def seed_sample_documents(db: Session = Depends(get_db)):
    existing_names = {c["doc_name"] for c in _load_knowledge_cache(db)}
    to_add = [d for d in DEFAULT_SEED_DOCS if d["doc_name"] not in existing_names]
    if not to_add:
        return {"status": "ok", "chunks_added": 0, "message": "Tài liệu mẫu đã có sẵn trong kho tri thức."}
    added = _ingest_documents_list(db, to_add, created_by="system_seed")
    return {"status": "ok", "chunks_added": added, "message": f"Đã nạp thêm {len(to_add)} tài liệu mẫu ({added} đoạn)."}


@router.delete("/documents/{doc_id}", dependencies=[Depends(require_admin)])
def delete_document(doc_id: str, db: Session = Depends(get_db)):
    deleted = db.query(KnowledgeChunk).filter(KnowledgeChunk.doc_id == doc_id).delete(synchronize_session=False)
    db.commit()
    clear_ai_knowledge_cache()
    return {"status": "ok", "deleted_chunks": deleted}


@router.post("/config", dependencies=[Depends(require_admin)])
def update_ai_config(req: ApiKeyConfigRequest, db: Session = Depends(get_db)):
    clean_key = req.api_key.strip()
    cfg = db.query(AppConfig).filter(AppConfig.config_key == "GEMINI_API_KEY").first()
    if cfg:
        cfg.config_value = clean_key
    else:
        db.add(AppConfig(config_key="GEMINI_API_KEY", config_value=clean_key))
    db.commit()
    clear_ai_knowledge_cache()
    return {"status": "ok", "masked_api_key": mask_api_key(clean_key)}


@router.post("/chat")
def chat_with_assistant(
    req: ChatRequest,
    current_user: AppUser = Depends(require_tab_access("ai_assistant")),
    db: Session = Depends(get_db),
):
    assistant = AI_ASSISTANTS.get(req.assistant_id) or AI_ASSISTANTS["sale"]
    api_key = get_gemini_api_key(db)

    is_personal = get_module_scope(current_user, "ai_assistant") == "personal"
    scoped_emp = (current_user.full_name or current_user.username).strip() if is_personal else None

    # 1. Lấy dữ liệu trực tiếp từ hệ thống (KPI Lead, SĐT đa page + Note Admin, hoặc Công nợ Kế toán)
    live_data_context, tools_used = build_live_data_context(db, assistant["id"], req.question, scoped_emp=scoped_emp)

    # 2. Mở rộng câu truy vấn RAG bằng nội dung chẩn đoán nỗi đau / note Admin (nếu có) để bốc trúng kịch bản
    rag_query = req.question
    if assistant["id"] == "sale" and "[CHẨN ĐOÁN NHANH HỒ SƠ, GHI CHÚ CỦA ADMIN & NỖI ĐAU KHÁCH HÀNG]" in live_data_context:
        diag_part = live_data_context.split("[CHẨN ĐOÁN NHANH HỒ SƠ, GHI CHÚ CỦA ADMIN & NỖI ĐAU KHÁCH HÀNG]", 1)[1]
        diag_part = diag_part.split("\n[", 1)[0][:1200]
        rag_query = f"{req.question}\n{diag_part}"

    retrieved_chunks = retrieve_relevant_chunks(
        db=db,
        query_text=rag_query,
        categories=assistant["categories"],
        api_key=api_key,
        top_k=6,
    )

    # 3. Ghép ngữ cảnh gửi cho Gemini
    context_parts: List[str] = []
    if live_data_context:
        context_parts.append(f"=== DỮ LIỆU HỆ THỐNG TRỰC TIẾP (THỜI GIAN THỰC) ===\n{live_data_context}")

    if retrieved_chunks:
        rag_text = "\n\n".join(
            f"[Tài liệu: {c['doc_name']} | Danh mục: {c['category']}]\n{c['content']}"
            for c in retrieved_chunks
        )
        context_parts.append(f"=== TÀI LIỆU NỘI BỘ (KHO TRI THỨC RAG) ===\n{rag_text}")

    composed_prompt = (
        f"{chr(10).join(context_parts)}\n\n"
        f"=== CÂU HỎI CỦA NHÂN VIÊN ===\n{req.question}\n\n"
        f"Hãy trả lời dựa trên dữ liệu hệ thống và tài liệu nội bộ ở trên."
    )

    is_sale = assistant["id"] == "sale"
    answer, model_used, searched_web = call_gemini_generate(
        system_prompt=assistant["system_prompt"],
        user_prompt=composed_prompt,
        history=[m.model_dump() for m in req.history],
        api_key=api_key,
        temperature=0.65 if is_sale else 0.25,
        enable_search=False,
    )
    if searched_web:
        tools_used.append("Google Search Grounding")

    return {
        "assistant_id": assistant["id"],
        "assistant_name": assistant["name"],
        "answer": answer,
        "model": model_used,
        "sources": [
            {"doc_name": c["doc_name"], "category": c["category"], "score": c["score"]}
            for c in retrieved_chunks
        ],
        "tools_used": tools_used,
    }


# ───────────────────────── Daily AI Performance Review ─────────────────────────


def _collect_recent_customer_messages_sample(db: Session, now_vn: datetime, limit_convs: int = 20) -> str:
    """Lấy mẫu ngắn tin nhắn & bình luận khách hàng gần nhất (7 ngày, ẩn SĐT) để rút insight nhu cầu/nỗi đau."""
    since_dt = (now_vn - timedelta(days=7)).replace(hour=0, minute=0, second=0, microsecond=0)
    samples: List[str] = []
    seen_norm: Set[str] = set()

    def _mask_phone(t: str) -> str:
        return re.sub(r"(?:\+?84|0)\d[\d\s\.\-]{7,11}\d", "[SĐT]", t)

    try:
        recent_acts = (
            db.query(FactLeadActivity.conversation_id, DimLead.page_id)
            .join(DimLead, FactLeadActivity.lead_id == DimLead.id)
            .filter(
                FactLeadActivity.contacted_at >= since_dt,
                ~FactLeadActivity.conversation_id.like("pzl_g_%"),
            )
            .order_by(desc(FactLeadActivity.contacted_at))
            .limit(limit_convs)
            .all()
        )
        cids = [cid for cid, _ in recent_acts if cid]
        if cids:
            raw_rows = (
                db.query(RawConversation.page_id, RawConversation.payload["messages"])
                .filter(RawConversation.pancake_id.in_(cids))
                .all()
            )
            for pg_id, msgs in raw_rows:
                if isinstance(msgs, str):
                    try:
                        msgs = json.loads(msgs)
                    except Exception:
                        msgs = []
                if not isinstance(msgs, list):
                    continue
                pg_lbl = resolve_canonical_page_name(pg_id, fallback=pg_id or "Khác")
                picked = 0
                for m in msgs:
                    if not isinstance(m, dict):
                        continue
                    role = (m.get("role") or "").strip().lower()
                    if role not in ("khách hàng", "khach hang", "customer", "user"):
                        continue
                    raw_txt = html.unescape(str(m.get("message") or m.get("original_message") or ""))
                    clean = re.sub(r"<[^>]+>", " ", raw_txt)
                    clean = _mask_phone(re.sub(r"\s+", " ", clean).strip())
                    if len(clean) < 12:
                        continue
                    key = clean[:60].lower()
                    if key in seen_norm:
                        continue
                    seen_norm.add(key)
                    samples.append(f"- ({pg_lbl}) {clean[:180]}")
                    picked += 1
                    if picked >= 2 or len(samples) >= 24:
                        break
                if len(samples) >= 24:
                    break
    except Exception as e:
        logger.warning(f"Daily review customer message sample error: {e}")

    try:
        cmts = (
            db.query(Comment.page_name, Comment.message)
            .filter(Comment.inserted_at >= since_dt, Comment.message.isnot(None))
            .order_by(desc(Comment.inserted_at))
            .limit(12)
            .all()
        )
        for pg_name, msg in cmts:
            clean = _mask_phone(re.sub(r"\s+", " ", (msg or "")).strip())
            if len(clean) < 10:
                continue
            key = clean[:60].lower()
            if key in seen_norm:
                continue
            seen_norm.add(key)
            samples.append(f"- [Comment {pg_name or 'MXH'}] {clean[:160]}")
            if len(samples) >= 32:
                break
    except Exception as e:
        logger.warning(f"Daily review comment sample error: {e}")

    if not samples:
        return ""
    return "[MẪU TIN NHẮN & BÌNH LUẬN KHÁCH HÀNG GẦN ĐÂY (7 NGÀY)]\n" + "\n".join(samples)


def _parse_daily_review_json(raw_text: str) -> Dict[str, Any]:
    """Tách và chuẩn hoá JSON đánh giá từ phản hồi Gemini, luôn trả về đúng schema 4 phần."""
    cleaned = (raw_text or "").strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, flags=re.DOTALL)
    candidate = fence.group(1) if fence else cleaned
    if not fence:
        s_idx = candidate.find("{")
        e_idx = candidate.rfind("}")
        if s_idx != -1 and e_idx > s_idx:
            candidate = candidate[s_idx : e_idx + 1]

    def _as_list(val: Any) -> List[str]:
        if isinstance(val, list):
            return [str(x).strip() for x in val if str(x).strip()]
        if isinstance(val, str) and val.strip():
            return [ln.lstrip("-•*0123456789. ").strip() for ln in val.splitlines() if ln.strip()]
        return []

    try:
        parsed = json.loads(candidate)
        if isinstance(parsed, dict):
            status = str(parsed.get("summary_status") or "warning").strip().lower()
            if status not in ("good", "warning", "critical"):
                status = "warning"
            return {
                "summary_status": status,
                "headline": str(parsed.get("headline") or "").strip(),
                "overview": _as_list(parsed.get("overview")),
                "customer_insight": _as_list(parsed.get("customer_insight")),
                "process_sla": _as_list(parsed.get("process_sla")),
                "actions": _as_list(parsed.get("actions")),
            }
    except Exception:
        pass

    lines = [ln.lstrip("-•* ").strip() for ln in cleaned.splitlines() if ln.strip()]
    return {
        "summary_status": "warning",
        "headline": lines[0][:220] if lines else "Đã hoàn tất phân tích tổng quan hệ thống.",
        "overview": lines[1:5] if len(lines) > 1 else [cleaned[:500]],
        "customer_insight": [],
        "process_sla": [],
        "actions": [],
    }


def _load_saved_daily_review(db: Session) -> Optional[Dict[str, Any]]:
    global _DAILY_REVIEW_CACHE
    now_ts = time.time()
    with _CACHE_LOCK:
        if _DAILY_REVIEW_CACHE and (now_ts - _DAILY_REVIEW_CACHE[0] < _DAILY_REVIEW_CACHE_TTL):
            return _DAILY_REVIEW_CACHE[1]

    cfg = db.query(AppConfig).filter(AppConfig.config_key == DAILY_REVIEW_CONFIG_KEY).first()
    if not cfg or not cfg.config_value:
        return None
    try:
        data = json.loads(cfg.config_value)
        if isinstance(data, dict):
            with _CACHE_LOCK:
                _DAILY_REVIEW_CACHE = (now_ts, data)
            return data
    except Exception:
        return None
    return None


def generate_daily_review(db: Session) -> Dict[str, Any]:
    """Tổng hợp thông số từ toàn bộ Dashboard + mẫu tin nhắn khách, gọi Gemini đánh giá và lưu DB."""
    global _DAILY_REVIEW_CACHE
    now_vn = get_vn_now()
    api_key = get_gemini_api_key(db)
    if not api_key:
        raise HTTPException(status_code=400, detail="Chưa cấu hình GEMINI_API_KEY để tạo AI Đánh giá hằng ngày.")

    dash_blocks, dash_tools = _build_quy_trinh_dashboard_context(
        db,
        "Phân tích toàn bộ thông số Dashboard 7 ngày qua",
        "phan tich toan bo thong so dashboard 7 ngay qua",
        now_vn,
    )
    msg_sample = _collect_recent_customer_messages_sample(db, now_vn)
    if msg_sample:
        dash_blocks.append(msg_sample)
        dash_tools.append("Tin nhắn & bình luận khách (7 ngày)")

    sla_chunks = retrieve_relevant_chunks(
        db=db,
        query_text="Ngưỡng cảnh báo SLA chưa phân công tỷ lệ ra SĐT tồn đọng Remind Deal Win",
        categories=["quy_trinh", "chung"],
        api_key=api_key,
        top_k=4,
    )
    rag_rules = "\n\n".join(c["content"] for c in sla_chunks)

    system_prompt = (
        "Bạn là Giám đốc Vận hành & Phân tích Dữ liệu (BI/CRM Operations Director) của EzTech Việt Nam.\n"
        "Nhiệm vụ: Đọc toàn bộ thông số thực tế từ các Dashboard và mẫu tin nhắn khách hàng 7 ngày gần nhất, "
        "đối chiếu đúng bộ ngưỡng SLA của EzTech để xuất báo cáo đánh giá hiệu suất hằng ngày giúp cải thiện performance.\n\n"
        "QUY TẮC BẮT BUỘC:\n"
        "- Dùng 100% số liệu thật trong dữ liệu đầu vào, TUYỆT ĐỐI KHÔNG tự bịa số liệu hay tên nhân viên.\n"
        "- Viết cực kỳ súc tích, thực chiến, định lượng rõ con số (%, +/-, tên kênh, tên nhân viên), KHÔNG rào đón, KHÔNG ghi `[Nguồn: ...]`.\n"
        "- Đánh giá `summary_status`: `critical` nếu có chỉ số vượt ngưỡng báo động đỏ (như Chưa phân công >10% hoặc Remind >7 ngày >40% hoặc Deal/SĐT <10%), `warning` nếu có cảnh báo vàng, `good` nếu mọi chỉ số đều đạt chuẩn.\n"
        "- BẮT BUỘC trả về DUY NHẤT 1 JSON hợp lệ (không thêm chữ ngoài JSON) theo đúng cấu trúc:\n"
        "{\n"
        '  "summary_status": "good | warning | critical",\n'
        '  "headline": "1 câu tóm tắt ngắn gọn tình trạng performance hôm nay kèm 2 con số nổi bật nhất",\n'
        '  "overview": ["3-4 ý ngắn về Tổng Lead, SĐT, CR% so kỳ trước, TikTok vs Facebook (Ads/Video/Organic), Deal Win & Thực thu"],\n'
        '  "customer_insight": ["3-4 ý ngắn về Insight khách hàng: ngành nghề/vị trí nổi bật, nhu cầu & nỗi đau khách đang hỏi nhiều nhất từ tin nhắn/comment, chủ đề hút khách"],\n'
        '  "process_sla": ["3-4 ý ngắn về Quy trình & Điểm nghẽn SLA: tỷ lệ Lead chưa phân công + page bỏ sót, tồn đọng Remind >7 ngày + nhân sự tồn cao, chênh lệch hiệu suất Sale, đứt gãy chặng Zalo"],\n'
        '  "actions": ["3-5 hành động cụ thể ưu tiên triển khai ngay hôm nay để tăng performance (nêu rõ giao ai/kênh nào và mục tiêu)"]\n'
        "}"
    )

    user_prompt = (
        "=== DỮ LIỆU THỰC TẾ CÁC DASHBOARD HÔM NAY ===\n"
        + "\n\n".join(dash_blocks)
        + ("\n\n=== NGƯỠNG SLA & QUY CHUẨN NỘI BỘ ===\n" + rag_rules if rag_rules else "")
        + "\n\nHãy xuất JSON báo cáo đánh giá tổng quan, insight khách hàng, quy trình SLA và đề xuất cải thiện performance."
    )

    raw_answer, model_used, _ = call_gemini_generate(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        history=[],
        api_key=api_key,
        temperature=0.2,
        enable_search=False,
    )
    sections = _parse_daily_review_json(raw_answer)

    start_7d = (now_vn - timedelta(days=6)).strftime("%d/%m/%Y")
    end_today = now_vn.strftime("%d/%m/%Y")
    review_payload: Dict[str, Any] = {
        "date": now_vn.strftime("%Y-%m-%d"),
        "generated_at": now_vn.strftime("%d/%m/%Y %H:%M"),
        "period_label": f"7 ngày gần nhất ({start_7d} – {end_today})",
        "model": model_used,
        "sources": dash_tools,
        **sections,
    }

    encoded = json.dumps(review_payload, ensure_ascii=False)
    cfg = db.query(AppConfig).filter(AppConfig.config_key == DAILY_REVIEW_CONFIG_KEY).first()
    if cfg:
        cfg.config_value = encoded
    else:
        db.add(AppConfig(config_key=DAILY_REVIEW_CONFIG_KEY, config_value=encoded))
    db.commit()

    with _CACHE_LOCK:
        _DAILY_REVIEW_CACHE = (time.time(), review_payload)
    return review_payload


def _trigger_daily_review_bg() -> bool:
    """Kích hoạt tạo báo cáo AI hằng ngày ở luồng nền (single-flight: tránh gọi đúp khi nhiều người mở cùng lúc)."""
    global _DAILY_REVIEW_GENERATING
    with _CACHE_LOCK:
        if _DAILY_REVIEW_GENERATING:
            return False
        _DAILY_REVIEW_GENERATING = True

    def _worker():
        global _DAILY_REVIEW_GENERATING
        try:
            with SessionLocal() as bg_db:
                generate_daily_review(bg_db)
        except Exception as e:
            logger.warning(f"Background daily review generation error: {e}")
        finally:
            with _CACHE_LOCK:
                _DAILY_REVIEW_GENERATING = False

    threading.Thread(target=_worker, daemon=True, name="ai-daily-review").start()
    return True


@router.get("/daily-review", dependencies=[Depends(require_tab_access("overview"))])
def get_daily_review(db: Session = Depends(get_db)):
    """Trả về bản AI Đánh giá hiệu suất hằng ngày mới nhất; tự động kích hoạt tạo mới 1 lần/ngày khi sang ngày mới."""
    now_vn = get_vn_now()
    today_str = now_vn.strftime("%Y-%m-%d")
    saved = _load_saved_daily_review(db)
    is_today = bool(saved and saved.get("date") == today_str)
    has_key = bool(get_gemini_api_key(db))

    if not is_today and has_key:
        _trigger_daily_review_bg()

    with _CACHE_LOCK:
        generating = _DAILY_REVIEW_GENERATING

    return {
        "review": saved,
        "is_today": is_today,
        "generating": generating,
        "has_api_key": has_key,
    }


@router.post("/daily-review/refresh", dependencies=[Depends(require_tab_access("overview"))])
def refresh_daily_review(db: Session = Depends(get_db)):
    """Ép AI đọc lại toàn bộ thông số Dashboard và cập nhật bản đánh giá mới ngay lập tức (dùng cho nút bấm hoặc cron API)."""
    global _DAILY_REVIEW_GENERATING
    with _CACHE_LOCK:
        _DAILY_REVIEW_GENERATING = True
    try:
        review = generate_daily_review(db)
        return {
            "review": review,
            "is_today": True,
            "generating": False,
            "has_api_key": True,
        }
    finally:
        with _CACHE_LOCK:
            _DAILY_REVIEW_GENERATING = False
