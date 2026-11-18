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
from sqlalchemy.orm import Session
from sqlalchemy import func, or_, desc

from database.db import get_db
from database.models import (
    KnowledgeChunk,
    AppConfig,
    DimLead,
    FactLeadActivity,
    RawConversation,
    SalesDeal,
    DealWin,
    get_vn_now,
)
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


AI_ASSISTANTS: Dict[str, Dict[str, Any]] = {
    "sale": {
        "id": "sale",
        "name": "AI Sale & Khóa Học",
        "badge": "Soạn tin & Lead",
        "description": "Dán trực tiếp tin nhắn/câu hỏi của khách để AI soạn sẵn câu trả lời chuẩn Sale EzTech, hoặc hỏi số liệu Lead / SĐT.",
        "categories": ["sale", "chung"],
        "system_prompt": (
            "Bạn là Trợ lý AI Sale thực chiến của EzTech Việt Nam, chuyên hỗ trợ nhân viên Sale soạn tin nhắn trả lời khách hàng BÁM SÁT Y HỆT FLOW VÀ NGUYÊN VĂN TEXT của file Kịch bản chuyên sâu, đồng thời tra cứu số liệu Lead/SĐT.\n\n"
            "1. KHI SALE DÁN TIN NHẮN / CÂU HỎI CỦA KHÁCH HÀNG (hoặc hỏi cách trả lời khách):\n"
            "- NGUYÊN TẮC SỐ 1 (BẮT BUỘC): Xác định đúng Step/tình huống hiện tại của khách trong FLOW Kịch bản chuyên sâu dưới đây (TUYỆT ĐỐI KHÔNG NHẢY CÓC) và NHẮN Y HỆT NGUYÊN VĂN TEXT TRONG KỊCH BẢN CHUYÊN SÂU.\n"
            "- NGUYÊN TẮC SỐ 2: Tin nhắn soạn cho khách PHẢI ĐẦY ĐỦ, DÀI DẶN, NHẤN MẠNH SÂU VÀO KHÓ KHĂN (nỗi đau thực tế) VÀ GIẢI PHÁP (Power Query, Power BI, tự động hóa, Support 1-1) đúng như văn bản gốc trong Kịch bản chuyên sâu. CẤM tóm tắt, CẤM rút gọn hay tự ý cắt ngắn thành 2-3 câu sơ sài (trừ Step 1 chỉ có 1 câu hỏi khai thác). Chỉ đổi xưng hô anh/chị/em nếu khách thể hiện rõ xưng hô khác, ngoài ra giữ y hệt câu chữ gốc.\n"
            "- CẤM mở đầu sáo rỗng kiểu 'Dạ chào chị ạ, em rất vui khi chị quan tâm...' hay 'Cảm ơn chị đã liên hệ...'. Vào thẳng nguyên văn mẫu tin nhắn tương ứng.\n\n"
            "=== KHO MẪU TIN NHẮN NGUYÊN VĂN TRONG KỊCH BẢN CHUYÊN SÂU (BẮT BUỘC DÙNG Y HỆT TEXT NÀY) ===\n\n"
            "[STEP 1 — CHĂM SÓC TRƯỚC (TUYỆT ĐỐI CHƯA gửi lộ trình K1-K2-K3, chưa báo giá 4.5tr/7.5tr hay giảm giá)]:\n"
            "- Khách mới hỏi chung chung: Nhắn Y HỆT:\n"
            "Dạ chị cho em hỏi thêm mình 1 xíu rằng hiện tại mình chủ yếu đang xử lý dữ liệu thủ công bằng Excel hay mình dùng phần mềm kế toán là chính ạ\n"
            "(Hoặc nếu phù hợp ngữ cảnh: Dạ chị cho em hỏi thêm mình 1 xíu rằng hiện tại mình chủ yếu đang xử lý dữ liệu thủ công bằng Excel có phải không ạ)\n\n"
            "[STEP 2A — KHÁCH DÙNG EXCEL LÀ CHÍNH (hoặc kêu khó khăn tổng hợp, đối soát, link nhiều file Excel, file nặng, làm báo cáo Excel thủ công)]:\n"
            "- Nhắn Y HỆT ĐẦY ĐỦ 4 ĐOẠN NÀY (không cắt bớt đoạn nào để nhấn mạnh rõ khó khăn và giải pháp):\n"
            "Nhiều anh chị kế toán bên em cũng chia sẻ là càng làm lâu càng thấy Excel không còn ok nữa ý chị, số lượng dữ liệu nhiều khiến dữ liệu nặng, link giữa các file dễ lỗi, chưa kể mỗi tháng lại phải cập nhật lại từ đầu. Mất nhiều thời gian cho khâu tổng hợp mà không còn thời gian để phân tích hay kiểm soát số liệu sâu luôn ấy chị\n\n"
            "Nếu chị chuyển phần thu thập – xử lý – tổng hợp dữ liệu sang Power Query thì mọi thao tác thủ công gần như được loại bỏ, và mình có thể xử lý tổng hợp hàng chục file một lúc ạ. Kết hợp Power BI là 1 công cụ giúp chị làm báo cáo xịn đẹp chuyên nghiệp hơn với hình ảnh trực quan theo dõi hiệu quả theo nhiều chiều.\n\n"
            "Và quan trọng nhất là chị chỉ cần thiết kế một form báo cáo mẫu thôi là mỗi lần có thêm dữ liệu mới mình chỉ cần import vào là dữ liệu tự động sẽ cập nhật lại mới hết nhé ạ.\n"
            "Power Query và Power BI bản chất nó không phải là một công cụ phức tạp, thậm chí nó còn dễ dùng hơn Excel vì các thao tác được Microsoft tối ưu bằng việc tick chọn và kéo thả và nó cũng được tích hợp sẵn trong Excel luôn ạ\n\n"
            "Để em gửi chị tham khảo full lộ trình khoá Data Finance dành riêng cho ngành tài chính - kế toán của bên em nhé ạ\n\n"
            "[STEP 2A — KHÁCH DÙNG CẢ PHẦN MỀM HOẶC PHẦN MỀM KẾ TOÁN (MISA, FAST...) LÀ CHÍNH]:\n"
            "- Nhắn Y HỆT ĐẦY ĐỦ 3 ĐOẠN NÀY:\n"
            "Dạ vâng em thấy ngày nay thời đại công nghệ rất phát triển nên các phần mềm kế toán cũng được tích hợp rất nhiều các chức năng hữu ích phục vụ trong các công việc hạch toán và lưu trữ dữ liệu. Nhưng nếu mình chỉ phụ thuộc vào phần mềm kế toán thì khi cần đối chiếu, tổng hợp dữ liệu từ nhiều nguồn sẽ khá mất thời gian hoặc sếp muốn những báo cáo trực quan, dễ theo dõi, có biểu đồ và phân tích chi tiết hơn, mình sẽ bị giới hạn bởi các mẫu báo cáo có sẵn của phần mềm đó ạ\n\n"
            "Thì em nghĩ mình có thể nâng cấp thêm kĩ năng xử lý dữ liệu thô như đối chiếu sao kê, đối chiếu công nợ, tổng hợp số liệu, hạch toán tự động bằng Power Query và làm báo cáo chuyên nghiệp hơn bằng Power BI thì công việc của mình sẽ tối ưu hơn rất nhiều\n\n"
            "Để em gửi chị tham khảo full lộ trình khoá Data Finance dành riêng cho ngành tài chính - kế toán của bên em nhé ạ\n\n"
            "[SAU STEP 1 & STEP 2A — KHI KHÁCH GỬI LĨNH VỰC / NGÀNH NGHỀ CỦA KHÁCH]:\n"
            "- Sau khi đã qua Step 1 và Step 2A, khi khách chia sẻ lĩnh vực/ngành nghề cụ thể của họ, dùng Y NGUYÊN văn sau và chỉ thay tên ngành + các task xử lý dữ liệu thô tương ứng với đặc thù ngành đó:\n"
            "Dạ vâng với đặc thù ngành [lĩnh vực của khách] thì mình phải quản lý dữ liệu rất nhiều. Nên nếu mình xử lý thủ công công việc sẽ tốn khá nhiều thời gian. Nên với các task xử lý dữ liệu thô như [các task đặc thù tương ứng của ngành đó, ví dụ kế toán là đối chiếu sao kê, đối chiếu công nợ, tổng hợp dữ liệu, hạch toán tự động; bán lẻ/TMĐT là đối soát đơn sàn, tồn kho, doanh thu đa kênh; xây dựng là tổng hợp chi phí công trình, vật tư, nghiệm thu công nợ; sản xuất là định mức nguyên vật liệu, giá thành, tồn kho] thì mình áp dụng Power Query (công cụ được tích hợp sẵn trong Excel) sẽ tối ưu cho mình rất nhiều đó ạ\n\n"
            "[STEP 2B — KHÁCH CHỈ MUỐN HỎI HỌC PHÍ / THÔNG TIN KHÓA HỌC, KHÔNG MUỐN NGHE TƯ VẤN HOẶC SAU KHI HỎI KHÓ KHĂN KHÔNG PHẢN HỒI]:\n"
            "- Nhắn Y HỆT ĐẦY ĐỦ 3 ĐOẠN NÀY (nếu khách hỏi thẳng lộ trình/học phí luôn thì có thể nối tiếp phần STEP 3 ngay sau):\n"
            "Dạ vâng với đặc thù ngành kế toán thì mình phải quản lý dữ liệu rất nhiều. Nên nếu mình xử lý thủ công công việc sẽ tốn khá nhiều thời gian. Nên với các task xử lý dữ liệu thô như đối chiếu sao kê, đối chiếu công nợ, tổng hợp dữ liệu, hạch toán tự động,... thì mình áp dụng Power Query (công cụ được tích hợp sẵn trong Excel) sẽ tối ưu cho mình rất nhiều đó ạ\n\n"
            "Sau đó, nếu mình lên được các báo cáo quản trị trực quan bằng Excel, Power BI sẽ giúp chị và BGĐ theo dõi hiệu quả theo nhiều chiều, và quan trọng nhất là chị chỉ cần thiết kế một form báo cáo mẫu thôi là mỗi lần có thêm dữ liệu mới chị chỉ cần import dữ liệu vào là báo cáo sẽ tự động cập nhật lại hết đó ạ\n\n"
            "Bên em có chương trình Data in Finance dành riêng cho dân kế toán phù hợp với mình. Chương trình này sẽ hướng dẫn mình từ khâu xử lý các dữ liệu thô, tối ưu công việc thủ công đến xây dựng báo cáo quản trị trực quan hơn, có ý nghĩa phân tích giúp các sếp dễ ra quyết định. Để em gửi mình tham khảo full lộ trình này nhé ạ\n\n"
            "[STEP 3 — GỬI LỘ TRÌNH DATA FINANCE (khi khách đồng ý xem lộ trình hoặc Sale yêu cầu soạn tin gửi lộ trình)]:\n"
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
            "[STEP 4 — CHĂM SÓC SAU KHI GỬI LỘ TRÌNH (chọn đúng đoạn nguyên văn theo câu hỏi của khách, nếu khách hỏi nhiều ý thì ghép đầy đủ các đoạn tương ứng)]:\n"
            "- Hỏi hình thức học Onl hay Off:\n"
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
            "- Hỏi giải thích Power Query & Power BI:\n"
            "Power Query chị có thể hiểu đơn giản là một công cụ được tích hợp sẵn trong Excel giúp kế toán xử lý dữ liệu hàng loạt và tự động hóa những công việc đang làm thủ công. Nó không phải ngôn ngữ lập trình hay công cụ của dân IT, mà được Microsoft phát triển dành cho dân nghiệp vụ như kế toán, tài chính, kiểm toán với các thao tác được tối ưu bằng việc tick chọn và kéo thả mà mình không cần phải nhớ hàm phức tạp trên Excel để xử lý ạ\n\n"
            "Còn Power BI là công cụ giúp chị biến những bảng dữ liệu Excel dài hàng nghìn dòng thành các báo cáo trực quan, chị sẽ học cách xây dựng các báo cáo quản trị trực quan và có chiều sâu để mình thấy ngay được doanh thu, lợi nhuận, chi phí,... từ tổng hợp đến chi tiết theo nhiều chiều phân tích và mình có thể dễ dàng kiểm soát và nắm bắt được số liệu.\n"
            "- Với các câu hỏi khác (Scope video, Case MISA, Chứng chỉ, Feedback, 100 bộ file + tool, Quyền lợi Combo, MacBook/Excel cũ, AI làm hết rồi sao phải học): lấy ĐÚNG nguyên văn từ `[TÀI LIỆU NỘI BỘ (KHO TRI THỨC RAG)]`.\n\n"
            "- QUY CÁCH TRẢ LỜI:\n"
            "  + Nếu có `[LỊCH SỬ CHAT THẬT GẦN NHẤT VỚI KHÁCH HÀNG]`, đọc kỹ để biết khách đang ở Step mấy và không gửi lặp lại nội dung Sale vừa nhắn. Giữ đúng 100 phần trăm giá, số buổi, link, STK và chính sách từ RAG.\n"
            "  + KHÔNG in đậm `**...**` bên trong nội dung tin nhắn gửi khách (chỉ giữ nguyên cấu trúc xuống dòng/gạch đầu dòng nếu bản gốc trong Kịch bản chuyên sâu có sẵn như danh sách K1/K2/K3, quyền lợi hoặc MISA).\n"
            "  + Thêm 1 dòng ngắn `**Gợi ý cho Sale:**` ở cuối để báo khách đang ở Step mấy và bước tiếp theo cần làm (ví dụ: gửi file PDF lộ trình, ảnh 3 khóa K1-K2-K3, link demo). TUYỆT ĐỐI KHÔNG ghi `[Nguồn: ...]` ở bất kỳ đâu.\n\n"
            "2. KHI SALE HỎI TRA CỨU NỘI BỘ (số liệu Lead/SĐT, tra SĐT khách, hỏi quy trình/chính sách):\n"
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
        "doc_name": "Kịch bản Tư vấn & Xử lý Từ chối Sale EzTech",
        "category": "sale",
        "content": (
            "1. Đối tượng học viên mục tiêu của EzTech:\n"
            "- Kế toán viên, Kế toán tổng hợp, Kiểm toán, Tài chính doanh nghiệp muốn chuyển dịch hoặc nâng cấp kỹ năng Phân tích dữ liệu (Data Analytics: Excel nâng cao, Power BI, SQL, Python).\n"
            "- Nỗi đau thường gặp: Làm báo cáo thủ công tốn thời gian, file Excel nặng hay treo, sếp yêu cầu dashboard trực quan theo thời gian thực.\n\n"
            "2. Quy trình 5 bước tư vấn chốt Sale chuẩn:\n"
            "- Bước 1: Khai thác nhu cầu (Hỏi công việc hiện tại, công cụ đang dùng, mục tiêu học để làm báo cáo hay chuyển ngành).\n"
            "- Bước 2: Xin SĐT kết bạn Zalo tư vấn sâu và gửi đề cương + video học thử.\n"
            "- Bước 3: Gửi lộ trình cá nhân hóa + case study thực tế ngành Tài chính - Kế toán.\n"
            "- Bước 4: Báo học phí kèm ưu đãi đăng ký sớm / nhóm và chính sách cam kết đồng hành 1-1.\n"
            "- Bước 5: Chốt cọc giữ chỗ hoặc hoàn tất học phí, gắn tag 'Đã là học viên' trên Pancake và điền form Deal Win.\n\n"
            "3. Xử lý từ chối thường gặp:\n"
            "- Khách báo 'Bận không có thời gian': Nhấn mạnh lộ trình học linh hoạt, có video record xem lại trọn đời, nhóm hỗ trợ 1-1 giải đáp trực tiếp trên bài tập thực tế.\n"
            "- Khách báo 'Sợ không theo kịp vì không biết code/IT': Khẳng định giáo trình thiết kế riêng cho dân Kế toán - Tài chính, đi từ tư duy dữ liệu và bài toán thực tế, cầm tay chỉ việc từ con số 0.\n"
            "- Khách báo 'Học phí cao': Chia nhỏ chi phí theo tháng/buổi học và so sánh với giá trị tiết kiệm hàng chục giờ làm báo cáo mỗi tháng; hỗ trợ chính sách đóng thành 2 đợt nếu học viên khó khăn."
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
    global _KNOWLEDGE_CACHE, _KNOWLEDGE_CACHE_TS, _API_KEY_CACHE, _SLA_REMIND_CACHE
    with _CACHE_LOCK:
        _KNOWLEDGE_CACHE = None
        _KNOWLEDGE_CACHE_TS = 0.0
        _API_KEY_CACHE = None
        _SLA_REMIND_CACHE = None


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


def build_live_data_context(db: Session, assistant_id: str, question: str) -> Tuple[str, List[str]]:
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
        wants_kpi = any(
            kw in ascii_q
            for kw in ("lead", "sdt", "so dien thoai", "kpi", "bao nhieu", "tong", "nhan vien", "thong ke", "7 ngay", "tuan", "hom nay", "ti le", "ty le")
        )
        if wants_kpi:
            try:
                start_7d = (now_vn - timedelta(days=7)).replace(hour=0, minute=0, second=0, microsecond=0)
                end_now = now_vn.replace(hour=23, minute=59, second=59, microsecond=999999)
                leads_map = classify_leads(db, start_7d, end_now)
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
            raw_d = search_digits[0]
            digit_q = raw_d[-9:]
            leads = (
                db.query(DimLead, FactLeadActivity)
                .outerjoin(FactLeadActivity, FactLeadActivity.lead_id == DimLead.id)
                .filter(_phone_filter(DimLead.phone_number, raw_d))
                .order_by(desc(FactLeadActivity.contacted_at))
                .limit(5)
                .all()
            )
            if leads:
                lines = ["[KẾT QUẢ TRA CỨU LEAD THEO SĐT]"]
                conv_ids: List[str] = []
                for ld, act in leads:
                    page_name = resolve_canonical_page_name(ld.page_id)
                    p_url = build_pancake_url(ld.page_id, act.conversation_id if act else None)
                    lines.append(
                        f"- Khách: {ld.name or 'Chưa rõ'} | SĐT: {ld.phone_number} | Page: {page_name} | "
                        f"Tag: {act.status_tag if act else 'Chưa gắn'} | Sale: {act.assigned_users if act else 'Chưa phân'} | "
                        f"Link Pancake: {p_url or 'N/A'}"
                    )
                    if act and act.conversation_id and act.conversation_id not in conv_ids:
                        conv_ids.append(act.conversation_id)
                context_blocks.append("\n".join(lines))
                tools_used.append(f"Tra cứu SĐT ({digit_q})")

                # Chỉ SELECT đúng payload['messages'] (không kéo cả payload lớn như tag_timeline) để tối ưu Neon Egress
                if conv_ids:
                    raw_rows = (
                        db.query(RawConversation.page_id, RawConversation.payload["messages"])
                        .filter(RawConversation.pancake_id.in_(conv_ids[:2]))
                        .all()
                    )
                    chat_lines: List[str] = ["[LỊCH SỬ CHAT THẬT GẦN NHẤT VỚI KHÁCH HÀNG]"]
                    for page_id_val, msgs in raw_rows:
                        if isinstance(msgs, str):
                            try:
                                msgs = json.loads(msgs)
                            except Exception:
                                msgs = []
                        if not isinstance(msgs, list) or not msgs:
                            continue
                        page_label = resolve_canonical_page_name(page_id_val)
                        chat_lines.append(f"--- Hội thoại trên {page_label} ---")
                        for m in msgs[-12:]:
                            raw_txt = html.unescape(str(m.get("message") or m.get("original_message") or ""))
                            clean_txt = re.sub(r"<[^>]+>", " ", raw_txt)
                            clean_txt = re.sub(r"\s+", " ", clean_txt).strip()
                            if clean_txt:
                                sender_role = "Khách" if m.get("role") == "Khách hàng" else "Sale/Admin"
                                chat_lines.append(f"{sender_role}: {clean_txt[:280]}")
                    if len(chat_lines) > 1:
                        context_blocks.append("\n".join(chat_lines))
                        tools_used.append("Lịch sử chat khách (raw_conversations)")

    elif assistant_id == "ke_toan":
        wants_finance_stats = bool(search_digits) or any(
            kw in ascii_q
            for kw in ("doanh thu", "tong hop", "bao nhieu", "cong no", "con no", "da thu", "phai thu", "chua dong", "so lieu", "bao cao", "hien tai")
        )
        if wants_finance_stats:
            try:
                totals = db.query(
                    func.count(SalesDeal.id),
                    func.coalesce(func.sum(SalesDeal.tong_tien), 0),
                    func.coalesce(func.sum(SalesDeal.da_thu), 0),
                    func.coalesce(func.sum(SalesDeal.con_no), 0),
                ).first()
                deal_win_count = db.query(func.count(DealWin.id)).scalar() or 0
                debt_count = db.query(func.count(SalesDeal.id)).filter(SalesDeal.con_no > 0).scalar() or 0
                if totals:
                    cnt, tong_tien, da_thu, con_no = totals
                    context_blocks.append(
                        f"[TỔNG HỢP DOANH THU & CÔNG NỢ TRÊN HỆ THỐNG]\n"
                        f"- Tổng số học viên (Deal Win): {deal_win_count:,} học viên\n"
                        f"- Tổng số bản ghi Nhập Deal (sales_deals): {cnt:,} deal\n"
                        f"- Tổng học phí phải thu: {int(tong_tien):,} VNĐ\n"
                        f"- Tổng tiền đã thu: {int(da_thu):,} VNĐ\n"
                        f"- Tổng công nợ còn phải thu: {int(con_no):,} VNĐ ({debt_count} deal còn nợ)"
                    )
                    tools_used.append("Tổng hợp Doanh thu & Công nợ (sales_deals)")

                if "no" in ascii_q or "chua dong" in ascii_q or "con no" in ascii_q or search_digits:
                    q_deals = db.query(SalesDeal)
                    if search_digits:
                        q_deals = q_deals.filter(_phone_filter(SalesDeal.sdt, search_digits[0]))
                    else:
                        q_deals = q_deals.filter(SalesDeal.con_no > 0)
                    top_deals = q_deals.order_by(desc(SalesDeal.con_no), desc(SalesDeal.id)).limit(8).all()
                    if top_deals:
                        d_lines = ["[DANH SÁCH DEAL / CÔNG NỢ CHI TIẾT]"]
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


@router.get("/assistants")
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


@router.get("/documents")
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


@router.post("/documents")
def ingest_document(req: IngestDocumentRequest, db: Session = Depends(get_db)):
    if req.category not in ("sale", "ke_toan", "quy_trinh", "chung"):
        raise HTTPException(status_code=400, detail="Danh mục không hợp lệ (chọn sale, ke_toan, quy_trinh hoặc chung).")

    added = _ingest_documents_list(
        db,
        [{"doc_name": req.doc_name, "category": req.category, "content": req.content}],
        created_by="user",
    )
    return {"status": "ok", "chunks_added": added, "doc_name": req.doc_name}


@router.post("/seed")
def seed_sample_documents(db: Session = Depends(get_db)):
    existing_names = {c["doc_name"] for c in _load_knowledge_cache(db)}
    to_add = [d for d in DEFAULT_SEED_DOCS if d["doc_name"] not in existing_names]
    if not to_add:
        return {"status": "ok", "chunks_added": 0, "message": "Tài liệu mẫu đã có sẵn trong kho tri thức."}
    added = _ingest_documents_list(db, to_add, created_by="system_seed")
    return {"status": "ok", "chunks_added": added, "message": f"Đã nạp thêm {len(to_add)} tài liệu mẫu ({added} đoạn)."}


@router.delete("/documents/{doc_id}")
def delete_document(doc_id: str, db: Session = Depends(get_db)):
    deleted = db.query(KnowledgeChunk).filter(KnowledgeChunk.doc_id == doc_id).delete(synchronize_session=False)
    db.commit()
    clear_ai_knowledge_cache()
    return {"status": "ok", "deleted_chunks": deleted}


@router.post("/config")
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
def chat_with_assistant(req: ChatRequest, db: Session = Depends(get_db)):
    assistant = AI_ASSISTANTS.get(req.assistant_id) or AI_ASSISTANTS["sale"]
    api_key = get_gemini_api_key(db)

    # 1. Truy xuất các đoạn tài liệu RAG liên quan
    retrieved_chunks = retrieve_relevant_chunks(
        db=db,
        query_text=req.question,
        categories=assistant["categories"],
        api_key=api_key,
        top_k=6,
    )

    # 2. Lấy dữ liệu trực tiếp từ hệ thống (KPI Lead, SĐT, hoặc Công nợ Kế toán)
    live_data_context, tools_used = build_live_data_context(db, assistant["id"], req.question)

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
