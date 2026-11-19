import os
import re
import io
import json
import difflib
import zipfile
import shutil
import tempfile
import xml.etree.ElementTree as ET
from typing import List, Optional, Dict, Any
import requests
import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database.db import get_db
from database.models import BtvnAnswerFile
from backend.ai_rag import get_gemini_api_key
from backend.btvn_grader import (
    grade_with_ai,
    grade_with_ai_no_answer,
    grade_batch_with_ai,
    match_tables_with_ai,
)

router = APIRouter(prefix="/api/btvn", tags=["BTVN Grader"])

ANSWER_STORAGE_DIR = os.path.join(os.getcwd(), "uploads", "btvn_answers")
os.makedirs(ANSWER_STORAGE_DIR, exist_ok=True)

def extract_creator(zip_path: str, file_name: str = "") -> str:
    creator = "Unknown"
    last_mod = ""
    try:
        with zipfile.ZipFile(zip_path, 'r') as z:
            if "docProps/core.xml" in z.namelist():
                root = ET.fromstring(z.read("docProps/core.xml"))
                
                c_node = root.find('.//{http://purl.org/dc/elements/1.1/}creator')
                if c_node is not None and c_node.text:
                    creator = c_node.text.strip()
                    
                m_node = root.find('.//{http://schemas.openxmlformats.org/package/2006/metadata/core-properties}lastModifiedBy')
                if m_node is not None and m_node.text:
                    last_mod = m_node.text.strip()
    except Exception:
        pass
        
    if creator.lower() == "admin" or creator == "Unknown":
        if file_name:
            import re, os
            path_parts = file_name.replace('\\', '/').split('/')
            extracted_name = ""
            for part in path_parts:
                match = re.search(r'BTVN[-_\s]+([a-zA-ZÀ-ỹ\s]+)', part, re.IGNORECASE)
                if match:
                    extracted = match.group(1).strip()
                    if extracted.lower() not in ["bi", "power bi", "excel", "buổi", "buoi", "data"]:
                        extracted_name = extracted
                        break
            if extracted_name:
                return extracted_name
                
        if last_mod and last_mod.lower() != "admin":
            return last_mod
            
        if file_name:
            import os
            return os.path.splitext(os.path.basename(file_name))[0]
            
    return creator

# --- Core Extraction Logic ---
def extract_excel_mcode(xlsx_path: str, file_name: str = "") -> tuple:
    creator = extract_creator(xlsx_path, file_name)
    try:
        mashup_bytes = None
        with zipfile.ZipFile(xlsx_path, "r") as outer_zip:
            xml_files = [f for f in outer_zip.namelist() if "customXml/item" in f and f.endswith(".xml")]
            for xml_file in xml_files:
                xml_data = outer_zip.read(xml_file)
                try:
                    root = ET.fromstring(xml_data)
                except ET.ParseError:
                    continue
                mashup_node = None
                for elem in root.iter():
                    if elem.tag.endswith("DataMashup"):
                        mashup_node = elem
                        break
                if mashup_node is not None and mashup_node.text:
                    mashup_bytes = base64.b64decode(mashup_node.text)
                    break

        if not mashup_bytes or len(mashup_bytes) < 8:
            return {}, creator

        payload_len = struct.unpack("<I", mashup_bytes[4:8])[0]
        inner_zip_bytes = mashup_bytes[8 : 8 + payload_len]
        section_m_text = None

        with zipfile.ZipFile(io.BytesIO(inner_zip_bytes)) as inner_zip:
            for inner_file in inner_zip.namelist():
                if inner_file.lower().endswith("section1.m"):
                    section_m_text = inner_zip.read(inner_file).decode("utf-8-sig")
                    break

        if not section_m_text:
            return {}, creator

        queries = {}
        pattern = r"shared\s+(?:#\"([^\"]+)\"|([a-zA-Z0-9_\.]+))\s*="
        matches = list(re.finditer(pattern, section_m_text))
        for i, match in enumerate(matches):
            table_name = match.group(1) or match.group(2)
            start_idx = match.end()
            end_idx = matches[i + 1].start() if i + 1 < len(matches) else len(section_m_text)
            full_steps = section_m_text[start_idx:end_idx].strip()
            if full_steps.endswith(";"):
                full_steps = full_steps[:-1].strip()
            queries[table_name] = full_steps
        return queries, creator
    except Exception as e:
        print(f"Excel error: {e}")
        return {}, creator

def extract_pbix_mcode(pbix_path: str, file_name: str) -> tuple:
    creator = extract_creator(pbix_path, file_name)
    queries = {}
    temp_workspace = tempfile.mkdtemp()
    try:
        temp_pbix_path = os.path.join(temp_workspace, file_name)
        import shutil, subprocess
        shutil.copy2(pbix_path, temp_pbix_path)
        
        # Run pbi-tools on Windows
        subprocess.run(
            [SETTINGS.get("PBI_TOOLS_PATH", "pbi-tools"), "extract", temp_pbix_path, "-modelSerialization", "Tmdl"],
            capture_output=True, text=True, check=True
        )

        extracted_folder_name = file_name[:-5]
        extracted_root = os.path.join(temp_workspace, extracted_folder_name)
        
        for root_dir, _, files in os.walk(extracted_root):
            for file_tmdl in files:
                if file_tmdl.endswith(".tmdl"):
                    file_path = os.path.join(root_dir, file_tmdl)
                    try:
                        with open(file_path, "r", encoding="utf-8-sig") as f:
                            content = f.read()
                            
                        if file_tmdl.lower() == "expressions.tmdl":
                            parts = re.split(r"^\s*expression\s+", content, flags=re.MULTILINE)
                            for part in parts[1:]:
                                match = re.match(r"([^=]+)=\s*(.*)", part, re.DOTALL)
                                if match:
                                    name = match.group(1).strip().strip("'").strip('"')
                                    body = match.group(2).strip()
                                    if body.startswith("```"):
                                        pieces = body.split("```")
                                        code = pieces[1].strip() if len(pieces) > 1 else body[3:].strip()
                                    else:
                                        code = re.split(r"^\s*(?:annotation|lineageTag|column|measure|queryGroup)\s*[:=]", body, flags=re.MULTILINE)[0].strip()
                                    queries[name] = code
                        else:
                            table_name = os.path.splitext(file_tmdl)[0]
                            match = re.search(r"^\s*(?:expression|source)\s*=\s*(.*)", content, re.MULTILINE | re.DOTALL)
                            if match:
                                body = match.group(1).strip()
                                if body.startswith("```"):
                                    pieces = body.split("```")
                                    code = pieces[1].strip() if len(pieces) > 1 else body[3:].strip()
                                else:
                                    code = re.split(r"^\s*(?:annotation|lineageTag|column|measure|partition|hierarchy|queryGroup)\s*[:=]", body, flags=re.MULTILINE)[0].strip()
                                queries[table_name] = code
                    except Exception:
                        pass
    except subprocess.CalledProcessError as e:
        print(f"PBI error: {e.stderr or e.stdout}")
        return {"ERROR": f"PBI extract failed (Requires Windows): {e.stderr or e.stdout}"}, creator
    except Exception as e:
        print(f"PBI error: {e}")
        return {"ERROR": str(e)}, creator
    finally:
        import shutil
        shutil.rmtree(temp_workspace, ignore_errors=True)
    return queries, creator

def extract_pbip_mcode(dataset_dir: str) -> tuple:
    creator = "Unknown"
    creator_path = os.path.join(dataset_dir, "creator.txt")
    if os.path.exists(creator_path):
        with open(creator_path, "r", encoding="utf-8") as f:
            creator = f.read().strip()
            
    queries = {}
    for root_dir, _, files in os.walk(dataset_dir):
        for file_tmdl in files:
            if file_tmdl.endswith(".tmdl"):
                file_path = os.path.join(root_dir, file_tmdl)
                try:
                    with open(file_path, "r", encoding="utf-8-sig") as f:
                        content = f.read()
                        
                    if file_tmdl.lower() == "expressions.tmdl":
                        parts = re.split(r"^\s*expression\s+", content, flags=re.MULTILINE)
                        for part in parts[1:]:
                            match = re.match(r"([^=]+)=\s*(.*)", part, re.DOTALL)
                            if match:
                                name = match.group(1).strip().strip("'").strip('"')
                                body = match.group(2).strip()
                                if body.startswith("```"):
                                    pieces = body.split("```")
                                    code = pieces[1].strip() if len(pieces) > 1 else body[3:].strip()
                                else:
                                    code = re.split(r"^\s*(?:annotation|lineageTag|column|measure|queryGroup)\s*[:=]", body, flags=re.MULTILINE)[0].strip()
                                queries[name] = code
                    else:
                        table_name = os.path.splitext(file_tmdl)[0]
                        match = re.search(r"^\s*(?:expression|source)\s*=\s*(.*)", content, re.MULTILINE | re.DOTALL)
                        if match:
                            body = match.group(1).strip()
                            if body.startswith("```"):
                                pieces = body.split("```")
                                code = pieces[1].strip() if len(pieces) > 1 else body[3:].strip()
                            else:
                                code = re.split(r"^\s*(?:annotation|lineageTag|column|measure|partition|hierarchy|queryGroup)\s*[:=]", body, flags=re.MULTILINE)[0].strip()
                            queries[table_name] = code
                except Exception:
                    pass
    return queries, creator
        


def remove_source_lines(code: str) -> str:
    lines = code.splitlines()
    filtered = []
    skip = False
    for line in lines:
        stripped = line.strip()
        if not skip:
            if re.match(r'^(Source|Nguồn)\s*=', stripped, re.IGNORECASE):
                skip = True
                continue
            filtered.append(line)
        else:
            if re.match(r'^(#"[^"]+"\s*=|[a-zA-Z0-9_]+\s*=)', stripped) or stripped == "in":
                skip = False
                filtered.append(line)
            else:
                continue
    return "\n".join(filtered)

def remove_annotations(code: str) -> str:
    if not code: return ""
    return re.sub(r'(?i)\bmeta\s*\[.*?\]', '', code, flags=re.DOTALL)

def format_mcode_for_ui(code: str) -> str:
    if not code: return ""
    lines = code.splitlines()
    formatted = []
    for line in lines:
        stripped = line.strip()
        if not stripped: continue
        if stripped.lower() == "let" or stripped.lower() == "in" or stripped.lower().startswith("in "):
            formatted.append(stripped)
        else:
            formatted.append("    " + stripped)
    return "\n".join(formatted)

def clean_code_for_compare(code: str) -> str:
    if not code: return ""
    code = remove_source_lines(code)
    code = remove_annotations(code)
    return re.sub(r'\s+', '', code).lower()



def parse_and_normalize(mcode):
    """Parse M code into normalized step expressions for comparison.
    
    Normalizations applied:
    - Strip step names → replace with __STEP__
    - Lowercase function names (Table.SelectRows → table.selectrows)
    - Remove trailing commas
    - Compress whitespace
    - Sort column lists inside ReorderColumns/SelectColumns/RemoveColumns
    - Skip 'Changed Type' / 'Đã Thay Đổi Loại' steps (redundant type changes)
    - Strip meta annotations
    """
    if not mcode:
        return [], {}
    
    # Pre-clean: remove annotations
    mcode = remove_annotations(mcode)
    
    lines = [l.strip() for l in mcode.splitlines() if l.strip() and l.lower() not in ["let", "in"]]
    norm_steps = []
    norm_to_name = {}
    step_names = []
    
    # First pass: extract step names
    for line in lines:
        match = re.match(r'^#?"([^"]+)"\s*=\s*(.*)', line)
        if not match:
            match = re.match(r'^([a-zA-Z0-9_]+)\s*=\s*(.*)', line)
        if match:
            step_names.append(match.group(1))
            
    # Sort step names by length descending to replace longest first
    step_names.sort(key=len, reverse=True)
    
    # Regex to detect Changed Type steps
    changed_type_re = re.compile(
        r'table\.transformcolumntypes\s*\(', re.IGNORECASE
    )
    # Regex to detect column-list functions whose argument order doesn't matter
    column_list_re = re.compile(
        r'(table\.(?:reordercolumns|selectcolumns|removecolumns|removematchingrows))\s*\(',
        re.IGNORECASE
    )
    
    def sort_column_args(expr):
        """Sort quoted column names inside { } to ignore column ordering."""
        def sort_braces(m):
            inner = m.group(1)
            items = [x.strip() for x in inner.split(',')]
            items.sort(key=lambda x: x.lower())
            return '{' + ', '.join(items) + '}'
        return re.sub(r'\{([^{}]+)\}', sort_braces, expr)
    
    # Second pass: normalize expressions
    for line in lines:
        match = re.match(r'^#?"([^"]+)"\s*=\s*(.*)', line)
        if not match:
            match = re.match(r'^([a-zA-Z0-9_]+)\s*=\s*(.*)', line)
        
        if match:
            name = match.group(1)
            expr = match.group(2)
            
            # Remove trailing comma
            if expr.endswith(','):
                expr = expr[:-1].strip()
                
            # Replace all step name references in the expression
            for sname in step_names:
                expr = expr.replace(f'#"{sname}"', '__STEP__')
                if re.match(r'^[a-zA-Z0-9_]+$', sname):
                    expr = re.sub(fr'\b{re.escape(sname)}\b', '__STEP__', expr)
            
            # Compress spaces
            expr = re.sub(r'\s+', ' ', expr).strip()
            
            # Lowercase the entire expression for case-insensitive comparison
            expr_lower = expr.lower()
            
            # Skip Changed Type steps (redundant type coercions)
            if changed_type_re.search(expr_lower):
                # Check if the name also suggests it's a type change step
                name_lower = name.lower()
                is_type_step = any(kw in name_lower for kw in [
                    'changed type', 'đã thay đổi loại', 'changedtype', 'đổi kiểu'
                ])
                if is_type_step:
                    continue  # Skip this step entirely
            
            # Sort column lists for order-insensitive comparison
            if column_list_re.search(expr_lower):
                expr_lower = sort_column_args(expr_lower)
            
            norm_steps.append(expr_lower)
            if expr_lower not in norm_to_name:
                norm_to_name[expr_lower] = name
                
    return norm_steps, norm_to_name

def get_diff_feedback(student_code: str, expected_code: str) -> tuple:
    """Compare student vs expected code and return (missing, extra, is_identical).
    
    Returns:
        tuple: (missing_steps: list[str], extra_steps: list[str], is_identical: bool)
    """
    if not student_code or not expected_code:
        return [], [], False
        
    s_steps, s_map = parse_and_normalize(student_code)
    e_steps, e_map = parse_and_normalize(expected_code)
    
    # Quick check: if normalized steps are identical, it's a match
    if s_steps == e_steps:
        return [], [], True
    
    diff = list(difflib.ndiff(e_steps, s_steps))
    
    missing = []
    extra = []
    
    for line in diff:
        if line.startswith('- '):
            expr = line[2:]
            name = e_map.get(expr, expr)
            if len(name) > 50: name = name[:50] + "..."
            if name not in missing:
                missing.append(name)
        elif line.startswith('+ '):
            expr = line[2:]
            name = s_map.get(expr, expr)
            if len(name) > 50: name = name[:50] + "..."
            if name not in extra:
                extra.append(name)
                
    return missing, extra, False

def format_diff_message(missing: list, extra: list) -> str:
    """Format missing/extra steps into a human-readable feedback string."""
    msg = ""
    if missing:
        missing_str = ', '.join(missing[:2])
        if len(missing) > 2:
            missing_str += " và một số bước khác"
        msg += f"\n  - Lỗi: Bạn đang thực hiện thiếu bước '{missing_str}'"
    if extra:
        extra_str = ', '.join(extra[:2])
        if len(extra) > 2:
            extra_str += " và một số bước khác"
        msg += f"\n  - Lỗi: Dư hoặc làm sai ở bước '{extra_str}'"
    return msg

def filter_queries(queries: dict) -> dict:
    valid = {}
    for table_name, full_steps in queries.items():
        name_lower = table_name.strip().lower()
        steps_clean = full_steps.strip()
        if not steps_clean or steps_clean.isspace(): continue

        if name_lower.startswith("datetabletemplate") or name_lower.startswith("localdatetable"): continue

        is_transform_sample = ("transform sample file" in name_lower or "biến đổi tệp mẫu" in name_lower)
        is_bad_name = (
            re.match(r"^(sample file|tệp mẫu|transform file|chuyển đổi tệp|chuyển đổi tệp mẫu)(\s*\(\d+\))?$", name_lower) is not None
            or name_lower.startswith("parameter") or name_lower.startswith("tham số")
        )
        is_binary_function = bool(re.search(r"\(\s*Parameter\d*\s+as\s+binary\s*\)\s*=>", steps_clean))
        is_sample_binding = "FunctionQueryBinding" in steps_clean
        is_param_query = "isparameterquery=true" in steps_clean.lower()

        if is_bad_name or is_binary_function or is_sample_binding or is_param_query:
            if not is_transform_sample:
                continue
        
        valid[table_name] = full_steps
    return valid

def process_queries_for_records(student_queries: dict, answer_queries: dict, display_name: str, file_type: str, records: list, creator: str = "Unknown", api_key: Optional[str] = None):
    valid_s_queries = filter_queries(student_queries)
    file_type_label = "Power BI Project (.pbip)" if file_type == ".pbip" else ("Power BI" if file_type == ".pbix" else "Excel")

    # ===== CASE 1: No answer key at all → AI no-answer for each query =====
    if not answer_queries:
        for s_name, f_steps in valid_s_queries.items():
            status = "Chưa có đáp án"
            feedback = ""
            
            try:
                ai_result = grade_with_ai_no_answer(f_steps, s_name, api_key=api_key)
                if ai_result and "status" in ai_result and "feedback" in ai_result:
                    status = ai_result["status"]
                    feedback = ai_result["feedback"]
            except Exception:
                pass
                
            records.append({
                "id": f"{display_name}_{s_name}",
                "student_file": display_name,
                "creator": creator,
                "file_type": file_type_label,
                "table_name": s_name,
                "status": status,
                "feedback": feedback,
                "student_code": format_mcode_for_ui(remove_annotations(remove_source_lines(f_steps))),
                "expected_code": "",
                "diff_msg": ""
            })
        return

    # ===== CASE 2: Has answer key → 3-tier deterministic/AI grading =====

    # Step 1: Compute pairwise scores for matching student queries to answer queries
    scores = []
    for s_name, s_code in valid_s_queries.items():
        s_clean = clean_code_for_compare(s_code)
        s_name_clean = re.sub(r'[^a-zA-Z0-9]', '', s_name).lower()
        
        for a_name, a_code in answer_queries.items():
            a_clean = clean_code_for_compare(a_code)
            a_name_clean = re.sub(r'[^a-zA-Z0-9]', '', a_name).lower()
            
            sim = difflib.SequenceMatcher(None, s_clean, a_clean).ratio()
            name_sim = difflib.SequenceMatcher(None, s_name.lower(), a_name.lower()).ratio()
            name_sim_clean = difflib.SequenceMatcher(None, s_name_clean, a_name_clean).ratio()
            best_name_sim = max(name_sim, name_sim_clean)
            
            if s_clean == a_clean and s_clean:
                sim = 1.0
                
            if s_name_clean == a_name_clean and s_name_clean != "":
                final_score = sim + 3.0
            elif best_name_sim > 0.8:
                final_score = sim + best_name_sim * 2.0
            elif best_name_sim > 0.6:
                final_score = sim + best_name_sim * 1.0
            else:
                final_score = sim + best_name_sim * 0.5
                
            scores.append((final_score, sim, s_name, a_name))

    scores.sort(key=lambda x: x[0], reverse=True)

    matched_s = set()
    matched_a = set()
    pairs = []

    for score, raw_sim, s_name, a_name in scores:
        if s_name not in matched_s and a_name not in matched_a:
            # Phase 1: Deterministic High-Confidence Match
            if score >= 1.2 or raw_sim > 0.85:
                pairs.append((s_name, a_name, raw_sim))
                matched_s.add(s_name)
                matched_a.add(a_name)

    # Phase 2: AI Fallback Match for remaining tables
    unmapped_s = {k: v for k, v in valid_s_queries.items() if k not in matched_s}
    unmapped_a = {k: v for k, v in answer_queries.items() if k not in matched_a}
    
    if unmapped_s and unmapped_a:
        try:
            from backend.btvn_grader import match_tables_with_ai
            ai_mapping = match_tables_with_ai(unmapped_s, unmapped_a, api_key=api_key)
            
            for s_name, a_name in ai_mapping.items():
                if s_name not in matched_s and a_name not in matched_a:
                    raw_sim = next((p[1] for p in scores if p[2] == s_name and p[3] == a_name), 0.0)
                    pairs.append((s_name, a_name, raw_sim))
                    matched_s.add(s_name)
                    matched_a.add(a_name)
        except Exception as e:
            print(f"[Hybrid Mapping] Lỗi gọi AI: {e}")

    # Phase 3: Greedy Fallback (Code Similarity)
    # Nếu AI bỏ sót hoặc lỗi, ta ghép các bảng còn lại dựa trên điểm số giống nhau của code (raw_sim) hoặc tên (score)
    for score, raw_sim, s_name, a_name in scores:
        if s_name not in matched_s and a_name not in matched_a:
            if score >= 0.1 or raw_sim >= 0.05:  # Tiêu chuẩn hạ thấp để vét cạn
                pairs.append((s_name, a_name, raw_sim))
                matched_s.add(s_name)
                matched_a.add(a_name)

    # Step 2: Classify each student query into tiers A and C
    tier_a = []  # Deterministic match → no AI needed
    tier_c = []  # Diff exists → needs AI
    unmatched = []  # No matching answer query
    
    for s_name, f_steps in valid_s_queries.items():
        match = next((p for p in pairs if p[0] == s_name), None)
        
        if not match:
            # Query doesn't match any answer → deterministic feedback (no AI)
            unmatched.append(s_name)
            continue
            
        a_name = match[1]
        expected_mcode = answer_queries[a_name]
        
        name_reminder = ""
        if s_name.lower() != a_name.lower():
            name_reminder = f"\n- Lưu ý: Chị nhớ đổi lại tên bảng thành '{a_name}' cho đúng yêu cầu nhé!"
        
        # --- Tier A: Exact match (after normalization) ---
        if clean_code_for_compare(f_steps) == clean_code_for_compare(expected_mcode):
            tier_a.append((s_name, a_name, f_steps, expected_mcode, name_reminder))
            continue
        
        # --- Check with advanced normalization ---
        missing, extra, is_identical = get_diff_feedback(f_steps, expected_mcode)
        
        if is_identical:
            # Normalized steps are identical (different only in naming/types/ordering)
            tier_a.append((s_name, a_name, f_steps, expected_mcode, name_reminder))
        else:
            # --- Tier C: Diff exists, use AI to judge for concise, smart feedback ---
            tier_c.append((s_name, a_name, f_steps, expected_mcode, name_reminder))
    
    # Step 3: Process Tier A — Deterministic "Đúng hoàn toàn" (no AI)
    for s_name, a_name, f_steps, expected_mcode, name_reminder in tier_a:
        records.append({
            "id": f"{display_name}_{s_name}",
            "student_file": display_name,
            "creator": creator,
            "file_type": file_type_label,
            "table_name": s_name,
            "status": "Đúng hoàn toàn",
            "feedback": f"- Bài làm đã thực hiện chính xác các bước.{name_reminder}",
            "student_code": format_mcode_for_ui(remove_annotations(remove_source_lines(f_steps))),
            "expected_code": format_mcode_for_ui(remove_annotations(remove_source_lines(expected_mcode))),
            "diff_msg": ""
        })
    
    # Step 4: Process Tier C — Batch AI call for mismatched tables
    if tier_c:
        ai_results_map = {}
        
        try:
            from backend.btvn_grader import grade_batch_with_ai
            batch_input = [
                {"table_name": s_name, "student_code": f_steps, "expected_code": expected_mcode}
                for s_name, a_name, f_steps, expected_mcode, name_reminder in tier_c
            ]
            batch_results = grade_batch_with_ai(batch_input, api_key=api_key)
            
            if batch_results:
                for r in batch_results:
                    ai_results_map[r["table_name"]] = r
        except Exception as e:
            print(f"[Batch AI] Lỗi: {e}")
        
        for s_name, a_name, f_steps, expected_mcode, name_reminder in tier_c:
            ai_result = ai_results_map.get(s_name)
            
            if ai_result and "status" in ai_result and "feedback" in ai_result:
                status = ai_result["status"]
                feedback = ai_result["feedback"]
                if name_reminder:
                    feedback += name_reminder
                diff_msg = " [AI]"
            else:
                # Fallback: use deterministic diff
                missing, extra, _ = get_diff_feedback(f_steps, expected_mcode)
                diff_msg = format_diff_message(missing, extra)
                status = "Sai logic/Sai steps"
                feedback = f"- Lỗi sai: Bảng '{s_name}' đang thực hiện thiếu hoặc sai bước so với đáp án '{a_name}'.{diff_msg}{name_reminder}\n- Cách sửa: Bạn hãy xem lại và chỉnh sửa nhé!"
            
            records.append({
                "id": f"{display_name}_{s_name}",
                "student_file": display_name,
                "creator": creator,
                "file_type": file_type_label,
                "table_name": s_name,
                "status": status,
                "feedback": feedback,
                "student_code": format_mcode_for_ui(remove_annotations(remove_source_lines(f_steps))),
                "expected_code": format_mcode_for_ui(remove_annotations(remove_source_lines(expected_mcode))),
                "diff_msg": diff_msg
            })
    
    # Step 6: Process unmatched queries — deterministic feedback (no AI waste)
    for s_name in unmatched:
        f_steps = valid_s_queries[s_name]
        records.append({
            "id": f"{display_name}_{s_name}",
            "student_file": display_name,
            "creator": creator,
            "file_type": file_type_label,
            "table_name": s_name,
            "status": "Tên bảng sai/Dư bảng",
            "feedback": f"- Bảng '{s_name}': Bảng này không khớp với bất kỳ bảng nào trong đáp án. Có thể bạn đặt sai tên hoặc bảng này dư thừa.\n- Cách sửa: Kiểm tra lại tên bảng cho đúng với yêu cầu bài tập nhé!",
            "student_code": format_mcode_for_ui(remove_annotations(remove_source_lines(f_steps))),
            "expected_code": "",
            "diff_msg": ""
        })



def _extract_queries_from_path(target_path: str) -> Dict[str, str]:
    extracted: Dict[str, str] = {}
    if os.path.isdir(target_path):
        if target_path.endswith(".Dataset"):
            q, _ = extract_pbip_mcode(target_path)
            for k, v in q.items():
                if v and not v.isspace():
                    extracted[k] = v
        for root_dir, dirs, files in os.walk(target_path):
            for d in dirs:
                full_d = os.path.join(root_dir, d)
                if d.endswith(".Dataset"):
                    q, _ = extract_pbip_mcode(full_d)
                    for k, v in q.items():
                        if v and not v.isspace():
                            extracted[k] = v
            for file in files:
                fp = os.path.join(root_dir, file)
                ext = os.path.splitext(file)[1].lower()
                q = {}
                if ext == ".pbix":
                    q, _ = extract_pbix_mcode(fp, file)
                elif ext == ".xlsx":
                    q, _ = extract_excel_mcode(fp, fp)
                for k, v in q.items():
                    if v and not v.isspace():
                        extracted[k] = v
    elif os.path.isfile(target_path):
        ext = os.path.splitext(target_path)[1].lower()
        q = {}
        if ext == ".pbix":
            q, _ = extract_pbix_mcode(target_path, os.path.basename(target_path))
        elif ext == ".xlsx":
            q, _ = extract_excel_mcode(target_path, target_path)
        for k, v in q.items():
            if v and not v.isspace():
                extracted[k] = v
    return filter_queries(extracted)


@router.get("/settings")
def get_btvn_settings(db: Session = Depends(get_db)):
    key = get_gemini_api_key(db)
    masked = f"{key[:6]}...{key[-4:]}" if key and len(key) > 10 else ("***" if key else "")
    return {
        "has_gemini_key": bool(key),
        "masked_key": masked,
        "provider": "Gemini",
    }


@router.post("/upload_grade")
async def grade_upload(
    student_files: List[UploadFile] = File(...),
    answer_files: Optional[List[UploadFile]] = File(None),
    answer_file_id: Optional[int] = Form(None),
    db: Session = Depends(get_db),
):
    api_key = get_gemini_api_key(db)
    temp_workspace = tempfile.mkdtemp()
    temp_input = os.path.join(temp_workspace, "input")
    temp_dapan = os.path.join(temp_workspace, "dapan")
    os.makedirs(temp_input, exist_ok=True)
    os.makedirs(temp_dapan, exist_ok=True)

    try:
        answer_queries: Dict[str, str] = {}
        if answer_file_id:
            ans_record = db.query(BtvnAnswerFile).filter(BtvnAnswerFile.id == answer_file_id).first()
            if ans_record:
                if ans_record.queries_json and isinstance(ans_record.queries_json, dict) and len(ans_record.queries_json) > 0:
                    answer_queries = filter_queries(dict(ans_record.queries_json))
                elif os.path.exists(ans_record.file_path):
                    answer_queries = _extract_queries_from_path(ans_record.file_path)
                    if answer_queries:
                        ans_record.queries_json = answer_queries
                        db.commit()
                else:
                    raise HTTPException(
                        status_code=400,
                        detail=f"File đáp án '[{ans_record.course}] Buổi {ans_record.session_number}' không còn tồn tại trên server và chưa có dữ liệu M Code trong DB. Vui lòng upload lại đáp án."
                    )
        elif answer_files:
            for ans in answer_files:
                if ans and ans.filename:
                    safe_filename = ans.filename.replace("\\", "/").lstrip("/")
                    ans_path = os.path.join(temp_dapan, safe_filename)
                    os.makedirs(os.path.dirname(ans_path), exist_ok=True)
                    content = await ans.read()
                    with open(ans_path, "wb") as f:
                        f.write(content)
            answer_queries = _extract_queries_from_path(temp_dapan)

        for sf in student_files:
            if not sf.filename:
                continue
            safe_filename = sf.filename.replace("\\", "/").lstrip("/")
            sf_path = os.path.join(temp_input, safe_filename)
            os.makedirs(os.path.dirname(sf_path), exist_ok=True)
            content = await sf.read()
            with open(sf_path, "wb") as f:
                f.write(content)

        records: List[Dict[str, Any]] = []
        processed_datasets = set()

        for root_dir, dirs, files in os.walk(temp_input):
            for d in dirs:
                if d.endswith(".Dataset"):
                    full_d = os.path.join(root_dir, d)
                    processed_datasets.add(full_d)
                    queries, creator = extract_pbip_mcode(full_d)
                    display_name = os.path.relpath(full_d, temp_input)
                    if not queries:
                        records.append({
                            "id": f"{display_name}_error",
                            "student_file": display_name,
                            "creator": creator,
                            "file_type": "Power BI Project (.pbip)",
                            "table_name": "(Không có Query)",
                            "status": "Lỗi/Không có Code",
                            "feedback": "Không tìm thấy file model.bim/.tmdl hoặc không có M Code trong thư mục .Dataset.",
                            "student_code": "",
                            "expected_code": "",
                            "diff_msg": "",
                        })
                    else:
                        process_queries_for_records(queries, answer_queries, display_name, ".pbip", records, creator, api_key=api_key)

            for file in files:
                file_path = os.path.join(root_dir, file)
                if any(file_path.startswith(ds) for ds in processed_datasets):
                    continue
                ext = os.path.splitext(file)[1].lower()
                if ext not in (".pbix", ".xlsx"):
                    continue
                display_name = os.path.relpath(file_path, temp_input)
                if ext == ".pbix":
                    queries, creator = extract_pbix_mcode(file_path, display_name)
                else:
                    queries, creator = extract_excel_mcode(file_path, display_name)

                if not queries:
                    records.append({
                        "id": f"{display_name}_error",
                        "student_file": display_name,
                        "creator": creator,
                        "file_type": "Power BI" if ext == ".pbix" else "Excel",
                        "table_name": "(Không có Query)",
                        "status": "Lỗi/Không có Code",
                        "feedback": "Không thể trích xuất M Code từ file này (file không có Power Query hoặc định dạng nén mới cần chuyển sang .pbip/.xlsx).",
                        "student_code": "",
                        "expected_code": "",
                        "diff_msg": "",
                    })
                else:
                    process_queries_for_records(queries, answer_queries, display_name, ext, records, creator, api_key=api_key)

        return {
            "records": records,
            "has_answer_key": bool(answer_queries),
            "has_gemini_key": bool(api_key),
        }
    finally:
        shutil.rmtree(temp_workspace, ignore_errors=True)


@router.get("/answer_files")
def get_answer_files(db: Session = Depends(get_db)):
    files = db.query(BtvnAnswerFile).order_by(BtvnAnswerFile.course, BtvnAnswerFile.session_number).all()
    return [
        {
            "id": f.id,
            "course": f.course,
            "session_number": f.session_number,
            "file_path": f.file_path,
            "file_name": os.path.basename(f.file_path),
            "table_count": len(f.queries_json) if isinstance(f.queries_json, dict) else 0,
            "exists": bool((isinstance(f.queries_json, dict) and len(f.queries_json) > 0) or os.path.exists(f.file_path)),
        }
        for f in files
    ]


@router.post("/answer_files")
async def upload_answer_file(
    course: str = Form(...),
    session_number: int = Form(...),
    file: Optional[UploadFile] = File(None),
    files: Optional[List[UploadFile]] = File(None),
    paths: Optional[List[str]] = Form(None),
    db: Session = Depends(get_db),
):
    safe_course = re.sub(r"[^a-zA-Z0-9_-]", "_", course)
    dest_dir = os.path.join(ANSWER_STORAGE_DIR, f"{safe_course}_buoi_{session_number}")
    if os.path.exists(dest_dir):
        shutil.rmtree(dest_dir, ignore_errors=True)
    os.makedirs(dest_dir, exist_ok=True)

    upload_list = files if files else ([file] if file else [])
    if not upload_list:
        raise HTTPException(status_code=400, detail="Vui lòng chọn file hoặc thư mục đáp án.")

    if len(upload_list) == 1 and (not paths or len(paths[0].replace("\\", "/").split("/")) <= 1):
        single = upload_list[0]
        safe_name = os.path.basename(single.filename or "answer.xlsx")
        final_path = os.path.join(dest_dir, safe_name)
        content = await single.read()
        with open(final_path, "wb") as f:
            f.write(content)
    else:
        folder_name = f"{safe_course}_Buoi{session_number}.Dataset"
        final_path = os.path.join(dest_dir, folder_name)
        os.makedirs(final_path, exist_ok=True)
        for idx, up_file in enumerate(upload_list):
            rel_path = (paths[idx] if paths and idx < len(paths) else up_file.filename) or f"file_{idx}"
            clean_path = rel_path.replace("\\", "/").lstrip("/")
            full_fp = os.path.join(final_path, clean_path)
            os.makedirs(os.path.dirname(full_fp), exist_ok=True)
            content = await up_file.read()
            with open(full_fp, "wb") as f:
                f.write(content)

    extracted_queries = _extract_queries_from_path(final_path)

    existing = (
        db.query(BtvnAnswerFile)
        .filter(BtvnAnswerFile.course == course, BtvnAnswerFile.session_number == session_number)
        .first()
    )
    if existing:
        existing.file_path = final_path
        existing.queries_json = extracted_queries
        db.commit()
        db.refresh(existing)
        return {
            "id": existing.id,
            "course": existing.course,
            "session_number": existing.session_number,
            "file_name": os.path.basename(final_path),
            "table_count": len(extracted_queries),
        }

    new_ans = BtvnAnswerFile(
        course=course,
        session_number=session_number,
        file_path=final_path,
        queries_json=extracted_queries,
    )
    db.add(new_ans)
    db.commit()
    db.refresh(new_ans)
    return {
        "id": new_ans.id,
        "course": new_ans.course,
        "session_number": new_ans.session_number,
        "file_name": os.path.basename(final_path),
        "table_count": len(extracted_queries),
    }


@router.delete("/answer_files/{answer_id}")
def delete_answer_file(answer_id: int, db: Session = Depends(get_db)):
    ans = db.query(BtvnAnswerFile).filter(BtvnAnswerFile.id == answer_id).first()
    if not ans:
        raise HTTPException(status_code=404, detail="Không tìm thấy đáp án")
    if ans.file_path and os.path.exists(ans.file_path):
        try:
            if os.path.isdir(ans.file_path):
                shutil.rmtree(ans.file_path, ignore_errors=True)
            else:
                os.remove(ans.file_path)
        except Exception:
            pass
    db.delete(ans)
    db.commit()
    return {"ok": True}

