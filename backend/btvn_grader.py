import json
import logging
import os
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

GEMINI_MODELS = [
    "gemini-2.5-flash",
    "gemini-2.0-flash",
    "gemini-1.5-flash",
]

SYSTEM_PROMPT = """
Bạn là một trợ giảng môn học Power BI (Data Analytics). 
Nhiệm vụ của bạn là chấm điểm bài tập về nhà phần Power Query M Code của học viên.
Bạn sẽ được cung cấp "Code Của Học Viên" và "Code Đáp Án Chuẩn".
Mục tiêu là CHỈ ĐỐI CHIẾU NỘI DUNG CÁC BƯỚC (STEPS) transform data, không bắt bẻ cách viết dấu phẩy hay thụt lề. 
Học viên có thể đặt tên bước khác đáp án một chút, hoặc gom bước, chia bước, miễn là logic dữ liệu đầu ra đúng bản chất và giải thích ngắn tại sao sai.

ĐẶC BIỆT LƯU Ý: 
1. Tuyệt đối BỎ QUA các lỗi hoặc sự sai lệch liên quan đến Tham số (Parameter). 
2. BỎ QUA sự sai lệch về Tên Biến hoặc Tên Bước (Step Name) do cách đặt tên khác nhau, nhưng PHẢI KIỂM TRA CHẶT CHẼ TÊN HÀM (ví dụ: bắt buộc phải dùng Table.Group thay vì Table.SelectRows nếu đáp án yêu cầu gom nhóm).
3. Tuyệt đối BỎ QUA sự khác biệt về đường dẫn file (File Path) trên máy cá nhân trong bước Source.
4. BỎ QUA các bước "Changed Type" (Đổi kiểu dữ liệu) bị dư thừa, miễn là logic tính toán cuối cùng vẫn đúng. TUYỆT ĐỐI KHÔNG giải thích dông dài kiểu "bước này không ảnh hưởng đến logic tính toán cuối cùng".
5. BỎ QUA thứ tự các cột trong một bước (ví dụ: Reordered Columns, Removed Columns). 
6. KHÔNG ĐƯỢC nhắc đến các cụm từ như "so với đáp án", "khác với đáp án", "code mẫu". Hãy nhận xét trực tiếp (ví dụ: "Chị đang thiếu bước lọc dữ liệu...").
7. Trong Feedback, tuyệt đối KHÔNG ĐƯỢC dùng từ "code", hãy thay bằng "bài làm" (ví dụ: "bài làm của chị").
8. TRẢ LỜI CỰC KỲ NGẮN GỌN. Hãy lập luận phân tích logic từng bước (Chain-of-Thought) để tìm ra đúng bản chất lỗi sai. KHÔNG lặp lại các câu vô nghĩa như "Bài làm của chị đã thực hiện đầy đủ các bước..."
9. ĐẶC BIỆT QUAN TRỌNG: CHỈ QUAN TÂM ĐẾN KẾT QUẢ ĐẦU RA (FINAL RESULT). NẾU HỌC VIÊN CÓ CÁCH LÀM KHÁC (Đổi thứ tự, gộp bước, dùng hàm tương đương) NHƯNG KẾT QUẢ CUỐI CÙNG VẪN ĐÚNG THÌ PHẢI CHẤM LÀ "Đúng hoàn toàn". BỎ QUA TẤT CẢ CÁC LỖI VẶT.

Hãy trả về duy nhất một chuỗi JSON hợp lệ với cấu trúc sau. 
LƯU Ý QUAN TRỌNG: KHÔNG ĐƯỢC XUỐNG DÒNG TRONG CHUỖI JSON (Raw newlines). Hãy dùng ký tự `\\n` để ngắt dòng trong chuỗi `feedback`. KHÔNG giải thích gì thêm:
{
  "status": "...",
  "feedback": "..."
}

Trong đó:
- "status": CHỈ ĐƯỢC CHỌN 1 TRONG 3 GIÁ TRỊ: "Đúng hoàn toàn", "Đúng hoàn toàn (Lệch cực nhỏ)", "Sai logic/Sai steps".
- "feedback": Nhận xét cực kỳ ngắn gọn trình bày dưới dạng gạch đầu dòng. MẶC ĐỊNH luôn luôn xưng hô bản thân là "em" và gọi học viên là "chị". TUYỆT ĐỊNH KHÔNG thêm các câu chào hỏi vào feedback. 
LƯU Ý QUAN TRỌNG CHO MỤC FEEDBACK: Nếu "status" là "Đúng hoàn toàn", BẠN CHỈ ĐƯỢC PHÉP IN RA ĐÚNG 1 CÂU DUY NHẤT LÀ: "- Bài làm đã thực hiện chính xác các bước." - KHÔNG liệt kê các bước đã làm, KHÔNG khen ngợi dài dòng.

Ví dụ (CHÚ Ý CÁCH DÙNG \\n):
{"status": "Sai logic/Sai steps", "feedback": "- Ở bước lọc dữ liệu, bài làm đang bị thiếu điều kiện X.\\n- Chị hãy thêm hàm Z vào để kết quả chuẩn xác hơn nhé."}
"""

SYSTEM_PROMPT_NO_ANSWER = """
Bạn là một trợ giảng môn học Power BI (Data Analytics). 
Nhiệm vụ của bạn là đánh giá nhanh đoạn Power Query M Code của học viên KHI KHÔNG CÓ CODE ĐÁP ÁN ĐỂ ĐỐI CHIẾU.
Mục tiêu là kiểm tra xem bài làm có viết đúng cú pháp không, logic các bước biến đổi dữ liệu có hợp lý và tối ưu không.

ĐẶC BIỆT LƯU Ý: 
1. Không có code chuẩn để so sánh, nên hãy đánh giá dựa trên kinh nghiệm chung về Power Query.
2. Tìm các lỗi sai cú pháp rõ ràng, bước bị trùng lặp, hoặc sử dụng hàm không hợp lý.
3. Nếu bài làm trông bình thường, logic mạch lạc và không có lỗi hiển nhiên, hãy coi như đúng.
4. Trong Feedback, tuyệt đối KHÔNG ĐƯỢC nhắc đến từ "code", hãy thay bằng "bài làm" (ví dụ: "bài làm của chị").

Hãy trả về duy nhất một chuỗi JSON hợp lệ với cấu trúc sau. 
LƯU Ý QUAN TRỌNG: KHÔNG ĐƯỢC XUỐNG DÒNG TRONG CHUỖI JSON (Raw newlines). Hãy dùng ký tự `\\n` để ngắt dòng trong chuỗi `feedback`. KHÔNG giải thích gì thêm:
{
  "status": "...",
  "feedback": "..."
}

Trong đó:
- "status": CHỈ ĐƯỢC CHỌN 1 TRONG 2 GIÁ TRỊ: "Đúng hoàn toàn", "Sai logic/Sai steps".
- "feedback": Nhận xét cực kỳ ngắn gọn trình bày dưới dạng gạch đầu dòng. MẶC ĐỊNH luôn luôn xưng hô bản thân là "em" và gọi học viên là "chị". Nếu đúng hoàn toàn, CHỈ CẦN ghi "- Bài làm đã thực hiện chính xác các bước." - TUYỆT ĐỐI KHÔNG liệt kê các bước đã làm, TUYỆT ĐỐI KHÔNG thêm câu khen ngợi.
"""


def _resolve_api_key(api_key: Optional[str] = None) -> str:
    if api_key and api_key.strip():
        return api_key.strip()
    return os.getenv("GEMINI_API_KEY", "").strip()


def _call_gemini_json(system_prompt: str, user_prompt: str, api_key: Optional[str] = None) -> Optional[Dict[str, Any]]:
    key = _resolve_api_key(api_key)
    if not key:
        logger.warning("[BTVN Gemini] Chưa cấu hình GEMINI_API_KEY")
        return None

    payload = {
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
        "generationConfig": {
            "temperature": 0.0,
            "responseMimeType": "application/json",
        },
    }

    last_error = None
    for model_name in GEMINI_MODELS:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={key}"
        try:
            resp = requests.post(url, json=payload, timeout=45)
            if resp.status_code != 200:
                last_error = f"{model_name}: HTTP {resp.status_code} - {resp.text[:200]}"
                logger.warning(last_error)
                continue
            data = resp.json()
            candidates = data.get("candidates") or []
            if not candidates:
                last_error = f"{model_name}: no candidates"
                continue
            parts = candidates[0].get("content", {}).get("parts", [])
            text = "".join(p.get("text", "") for p in parts).strip()
            if not text:
                last_error = f"{model_name}: empty response"
                continue
            return json.loads(text)
        except Exception as e:
            last_error = f"{model_name}: {e}"
            logger.warning(f"[BTVN Gemini] {last_error}")
            continue

    logger.error(f"[BTVN Gemini] All models failed: {last_error}")
    return None


def grade_with_ai(student_code: str, expected_code: str, table_name: str, api_key: Optional[str] = None) -> Optional[dict]:
    user_prompt = f"""
Tên Bảng đang chấm: {table_name}

=== CODE ĐÁP ÁN CHUẨN ===
{expected_code}

=== CODE CỦA HỌC VIÊN ===
{student_code}
"""
    return _call_gemini_json(SYSTEM_PROMPT, user_prompt, api_key=api_key)


def grade_with_ai_no_answer(student_code: str, table_name: str, api_key: Optional[str] = None) -> Optional[dict]:
    user_prompt = f"""
Tên Bảng đang chấm: {table_name}

=== CODE CỦA HỌC VIÊN ===
{student_code}
"""
    return _call_gemini_json(SYSTEM_PROMPT_NO_ANSWER, user_prompt, api_key=api_key)


def grade_batch_with_ai(tables: List[dict], api_key: Optional[str] = None) -> Optional[List[dict]]:
    if not tables:
        return []
    key = _resolve_api_key(api_key)
    if not key:
        return None

    batch_prompt = """
Bạn là một trợ giảng môn học Power BI (Data Analytics). 
Nhiệm vụ của bạn là chấm điểm bài tập về nhà phần Power Query M Code của học viên cho NHIỀU BẢNG CÙNG LÚC.
Mục tiêu là CHỈ ĐỐI CHIẾU NỘI DUNG CÁC BƯỚC (STEPS) transform data, không bắt bẻ cách viết dấu phẩy hay thụt lề. 
Học viên có thể đặt tên bước khác đáp án một chút, hoặc gom bước, chia bước, miễn là logic dữ liệu đầu ra đúng bản chất và giải thích ngắn tại sao sai.

ĐẶC BIỆT LƯU Ý: 
1. Tuyệt đối BỎ QUA các lỗi hoặc sự sai lệch liên quan đến Tham số (Parameter). 
2. BỎ QUA sự sai lệch về Tên Biến hoặc Tên Bước (Step Name) do cách đặt tên khác nhau, nhưng PHẢI KIỂM TRA CHẶT CHẼ TÊN HÀM (ví dụ: bắt buộc phải dùng Table.Group thay vì Table.SelectRows nếu đáp án yêu cầu gom nhóm).
3. Tuyệt đối BỎ QUA sự khác biệt về đường dẫn file (File Path) trên máy cá nhân trong bước Source.
4. BỎ QUA các bước "Changed Type" (Đổi kiểu dữ liệu) bị dư thừa, miễn là logic tính toán cuối cùng vẫn đúng.
5. BỎ QUA thứ tự các cột trong một bước (ví dụ: Reordered Columns, Removed Columns). 
6. KHÔNG ĐƯỢC nhắc đến các cụm từ như "so với đáp án", "khác với đáp án", "code mẫu". Hãy nhận xét trực tiếp (ví dụ: "Chị đang thiếu bước lọc dữ liệu...").
7. Trong Feedback, tuyệt đối KHÔNG ĐƯỢC dùng từ "code", hãy thay bằng "bài làm" (ví dụ: "bài làm của chị").
8. TRẢ LỜI CỰC KỲ NGẮN GỌN.
9. ĐẶC BIỆT QUAN TRỌNG: CHỈ QUAN TÂM ĐẾN KẾT QUẢ ĐẦU RA (FINAL RESULT). NẾU HỌC VIÊN CÓ CÁCH LÀM KHÁC NHƯNG KẾT QUẢ CUỐI CÙNG VẪN ĐÚNG THÌ PHẢI CHẤM LÀ "Đúng hoàn toàn".

Hãy trả về duy nhất một JSON Object chứa mảng "results" với cấu trúc sau:
{
  "results": [
    {
      "table_name": "Tên bảng",
      "status": "...",
      "feedback": "..."
    }
  ]
}
"""
    tables_text = ""
    for i, t in enumerate(tables, 1):
        tables_text += f"\n--- BẢNG {i}: {t['table_name']} ---\n"
        if t.get("expected_code"):
            tables_text += f"=== CODE ĐÁP ÁN CHUẨN ===\n{t['expected_code']}\n"
        else:
            tables_text += "=== CODE ĐÁP ÁN CHUẨN ===\n(Không có đáp án, hãy tự đánh giá logic)\n"
        tables_text += f"=== CODE CỦA HỌC VIÊN ===\n{t['student_code']}\n"

    res_json = _call_gemini_json(batch_prompt, tables_text, api_key=key)
    if res_json and isinstance(res_json.get("results"), list):
        return res_json["results"]
    return None


def match_tables_with_ai(student_queries: dict, answer_queries: dict, api_key: Optional[str] = None) -> dict:
    if not student_queries or not answer_queries:
        return {}
    key = _resolve_api_key(api_key)
    if not key:
        return {}

    prompt = f"""
Bạn là một trợ giảng Power BI.
Học viên nộp bài gồm các bảng (và đoạn M Code tương ứng):
{json.dumps({k: v[:250] for k, v in student_queries.items()}, ensure_ascii=False, indent=2)}

Trong khi đó, Đáp án chuẩn có các bảng sau:
{json.dumps({k: v[:250] for k, v in answer_queries.items()}, ensure_ascii=False, indent=2)}

Nhiệm vụ của bạn: Hãy đối chiếu (mapping) xem tên bảng nào của Học viên tương ứng với tên bảng nào trong Đáp án chuẩn dựa trên tên bảng hoặc nội dung M Code (cùng nguồn dữ liệu, cùng mục đích biến đổi).
CHỈ ghép nối những bảng thực sự tương ứng. Bảng nào của học viên không có trong đáp án thì không ghép (bỏ qua hoặc không đưa vào JSON).

Trả về DUY NHẤT một JSON Object có cấu trúc key là "Tên bảng học viên" và value là "Tên bảng đáp án chuẩn".
Ví dụ: {{"Du_lieu_ban_hang": "FactSales", "Bang_Khach_Hang": "DimCustomer"}}
"""
    res = _call_gemini_json(
        "Bạn là trợ lý ánh xạ tên bảng Power Query. Chỉ trả về JSON object hợp lệ.",
        prompt,
        api_key=key,
    )
    return res if isinstance(res, dict) else {}
