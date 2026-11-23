import React, { useEffect, useMemo, useState } from 'react';
import {
  CheckCircle2,
  AlertTriangle,
  XCircle,
  Upload,
  FolderOpen,
  FileSpreadsheet,
  Sparkles,
  Copy,
  Check,
  Code2,
  Edit3,
  Trash2,
  Plus,
  Search,
  Database,
  X,
  Loader2,
  KeyRound,
  Layers,
  List,
} from 'lucide-react';
import { showAppToast } from '../utils/toast';

interface GradeRecord {
  id: string;
  student_file: string;
  table_name: string;
  status: string;
  feedback: string;
  student_code: string;
  expected_code: string;
  creator: string;
  file_type: string;
}

interface GroupedStudentResult {
  student_file: string;
  creator: string;
  file_type: string;
  finalStatus: string;
  finalFeedback: string;
  tables: GradeRecord[];
}

interface AnswerFileItem {
  id: number;
  course: string;
  session_number: number;
  file_path: string;
  file_name: string;
  table_count?: number;
  exists: boolean;
}

const API_BASE = (import.meta as any).env?.VITE_API_URL || '';

function cleanCoreFeedback(text: string): string {
  if (!text) return '';
  return text
    .split('\n')
    .filter((l) => {
      const lower = l.toLowerCase();
      if (lower.includes('chào') && lower.includes('trợ giảng')) return false;
      if (lower.includes('chúc') && (lower.includes('học tốt') || lower.includes('thành công'))) return false;
      return true;
    })
    .join('\n')
    .trim();
}

function buildAggregatedFeedback(tables: GradeRecord[]): { finalStatus: string; finalFeedback: string } {
  const allCorrect = tables.every((t) => t.status.includes('Đúng hoàn toàn'));
  if (allCorrect) {
    const rawFeedbacks = tables
      .map((t) => cleanCoreFeedback(t.feedback))
      .filter(Boolean)
      .join('\n');
    const uniqueLines = Array.from(
      new Set(
        rawFeedbacks
          .split('\n')
          .map((l) => l.trim())
          .filter(Boolean)
      )
    ).join('\n');
    const body = uniqueLines || '- Mình đã thực hành các thao tác rất đúng và chính xác rồi ạ';
    return {
      finalStatus: 'Đúng hoàn toàn',
      finalFeedback: `Em chào chị, các bạn trợ giảng đã xem BTVN của mình, em gửi lại mình feedback nhé ạ:\n\n${body}\n\nChị cố gắng tiếp tục duy trì làm BTVN để mình có thể hiểu bài hơn nhé ạ.`,
    };
  }

  const issues: string[] = [];
  tables.forEach((t) => {
    if (!t.status.includes('Đúng hoàn toàn')) {
      const core = cleanCoreFeedback(t.feedback) || '- Có lỗi sai trong quá trình thực hiện.';
      issues.push(`[ Bảng '${t.table_name}' ]:\n${core}`);
    }
  });
  return {
    finalStatus: 'Có lỗi sai',
    finalFeedback: `Em chào chị, các bạn trợ giảng đã xem BTVN của mình, em gửi lại mình feedback nhé ạ:\n\n${issues.join(
      '\n\n'
    )}\n\nChị xem lại bài làm và có vướng mắc thì nhắn lên nhóm support 1-1 nhé ạ.\nChị cố gắng tiếp tục duy trì làm BTVN để mình có thể hiểu bài hơn nhé ạ.`,
  };
}

export const BtvnGraderDashboard: React.FC = () => {
  const [hasGeminiKey, setHasGeminiKey] = useState<boolean>(true);
  const [maskedKey, setMaskedKey] = useState<string>('');

  // Answer selection
  const [answerFilesList, setAnswerFilesList] = useState<AnswerFileItem[]>([]);
  const [answerMode, setAnswerMode] = useState<'saved' | 'upload'>('saved');
  const [selectedAnswerId, setSelectedAnswerId] = useState<string>('');
  const [uploadedAnswerFiles, setUploadedAnswerFiles] = useState<File[]>([]);

  // Student files
  const [studentFiles, setStudentFiles] = useState<File[]>([]);

  // Grading state & results
  const [isGrading, setIsGrading] = useState(false);
  const [gradeError, setGradeError] = useState<string | null>(null);
  const [records, setRecords] = useState<GradeRecord[]>([]);
  const [customFeedbacks, setCustomFeedbacks] = useState<Record<string, string>>({});
  const [viewMode, setViewMode] = useState<'grouped' | 'tables'>('grouped');
  const [statusFilter, setStatusFilter] = useState<string>('ALL');
  const [searchTerm, setSearchTerm] = useState<string>('');
  const [copiedKey, setCopiedKey] = useState<string | null>(null);

  // Modals
  const [diffTables, setDiffTables] = useState<{ fileName: string; tables: GradeRecord[] } | null>(null);
  const [editTarget, setEditTarget] = useState<{ key: string; text: string; isGrouped: boolean } | null>(null);

  // Manage Answer Modal
  const [showManageModal, setShowManageModal] = useState(false);
  const [newCourse, setNewCourse] = useState<'Power Query' | 'Power BI'>('Power Query');
  const [newSession, setNewSession] = useState<number>(1);
  const [newAnswerFiles, setNewAnswerFiles] = useState<File[]>([]);
  const [isUploadingAnswer, setIsUploadingAnswer] = useState(false);

  const authHeaders = (): Record<string, string> => {
    const token = localStorage.getItem('auth_token');
    return token ? { Authorization: `Bearer ${token}` } : {};
  };

  const fetchSettings = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/btvn/settings`, { headers: authHeaders() });
      if (res.ok) {
        const data = await res.json();
        setHasGeminiKey(Boolean(data.has_gemini_key));
        setMaskedKey(data.masked_key || '');
      }
    } catch {
      // ignore
    }
  };

  const fetchAnswerFiles = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/btvn/answer_files`, { headers: authHeaders() });
      if (res.ok) {
        const data: AnswerFileItem[] = await res.json();
        setAnswerFilesList(data);
        if (data.length > 0 && !selectedAnswerId) {
          setSelectedAnswerId(String(data[0].id));
        }
      }
    } catch {
      // ignore
    }
  };

  useEffect(() => {
    fetchSettings();
    fetchAnswerFiles();
  }, []);

  const handleStartGrade = async () => {
    if (studentFiles.length === 0) {
      setGradeError('Vui lòng chọn ít nhất 1 file hoặc thư mục bài làm của học viên.');
      return;
    }
    setGradeError(null);
    setIsGrading(true);

    try {
      const formData = new FormData();
      studentFiles.forEach((f) => {
        const relName = (f as any).webkitRelativePath || f.name;
        formData.append('student_files', f, relName);
      });

      if (answerMode === 'saved' && selectedAnswerId) {
        formData.append('answer_file_id', selectedAnswerId);
      } else if (answerMode === 'upload' && uploadedAnswerFiles.length > 0) {
        uploadedAnswerFiles.forEach((f) => {
          const relName = (f as any).webkitRelativePath || f.name;
          formData.append('answer_files', f, relName);
        });
      }

      const res = await fetch(`${API_BASE}/api/btvn/upload_grade`, {
        method: 'POST',
        headers: authHeaders(),
        body: formData,
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: 'Lỗi chấm bài' }));
        throw new Error(err.detail || 'Lỗi chấm bài');
      }

      const data = await res.json();
      setRecords(data.records || []);
      setCustomFeedbacks({});
      if (typeof data.has_gemini_key === 'boolean') {
        setHasGeminiKey(data.has_gemini_key);
      }
    } catch (err: any) {
      setGradeError(err.message || 'Đã xảy ra lỗi khi chấm bài.');
    } finally {
      setIsGrading(false);
    }
  };

  const handleUploadAnswer = async (e: React.FormEvent) => {
    e.preventDefault();
    if (newAnswerFiles.length === 0) return;
    setIsUploadingAnswer(true);
    try {
      const formData = new FormData();
      formData.append('course', newCourse);
      formData.append('session_number', String(newSession));
      newAnswerFiles.forEach((f) => {
        formData.append('files', f);
        formData.append('paths', (f as any).webkitRelativePath || f.name);
      });

      const res = await fetch(`${API_BASE}/api/btvn/answer_files`, {
        method: 'POST',
        headers: authHeaders(),
        body: formData,
      });
      if (!res.ok) throw new Error('Upload thất bại');
      setNewAnswerFiles([]);
      await fetchAnswerFiles();
    } catch (err: any) {
      showAppToast(err.message || 'Lỗi upload đáp án', 'error');
    } finally {
      setIsUploadingAnswer(false);
    }
  };

  const handleDeleteAnswer = async (id: number) => {
    if (!confirm('Xóa file đáp án này?')) return;
    await fetch(`${API_BASE}/api/btvn/answer_files/${id}`, {
      method: 'DELETE',
      headers: authHeaders(),
    });
    await fetchAnswerFiles();
  };

  const handleCopyFeedback = (key: string, text: string) => {
    navigator.clipboard.writeText(text);
    setCopiedKey(key);
    setTimeout(() => setCopiedKey(null), 1500);
  };

  const groupedResults: GroupedStudentResult[] = useMemo(() => {
    const map: Record<string, GradeRecord[]> = {};
    records.forEach((r) => {
      const fname = r.student_file || 'Unknown';
      if (!map[fname]) map[fname] = [];
      map[fname].push(r);
    });
    return Object.entries(map).map(([student_file, tables]) => {
      const { finalStatus, finalFeedback } = buildAggregatedFeedback(tables);
      return {
        student_file,
        creator: tables[0]?.creator || 'Unknown',
        file_type: tables[0]?.file_type || '',
        finalStatus,
        finalFeedback: customFeedbacks[student_file] ?? finalFeedback,
        tables,
      };
    });
  }, [records, customFeedbacks]);

  const stats = useMemo(() => {
    const totalFiles = groupedResults.length;
    const totalTables = records.length;
    const exactFiles = groupedResults.filter((g) => g.finalStatus === 'Đúng hoàn toàn').length;
    const wrongFiles = totalFiles - exactFiles;
    return { totalFiles, totalTables, exactFiles, wrongFiles };
  }, [groupedResults, records]);

  const filteredGrouped = useMemo(() => {
    return groupedResults.filter((g) => {
      const matchStatus =
        statusFilter === 'ALL' ||
        (statusFilter === 'EXACT' && g.finalStatus === 'Đúng hoàn toàn') ||
        (statusFilter === 'WRONG' && g.finalStatus !== 'Đúng hoàn toàn');
      const q = searchTerm.trim().toLowerCase();
      const matchSearch =
        !q ||
        g.student_file.toLowerCase().includes(q) ||
        (g.creator || '').toLowerCase().includes(q) ||
        g.tables.some((t) => t.table_name.toLowerCase().includes(q));
      return matchStatus && matchSearch;
    });
  }, [groupedResults, statusFilter, searchTerm]);

  const filteredRecords = useMemo(() => {
    return records.filter((r) => {
      const matchStatus =
        statusFilter === 'ALL' ||
        (statusFilter === 'EXACT' && r.status.includes('Đúng hoàn toàn')) ||
        (statusFilter === 'WRONG' && !r.status.includes('Đúng hoàn toàn'));
      const q = searchTerm.trim().toLowerCase();
      const matchSearch =
        !q ||
        r.student_file.toLowerCase().includes(q) ||
        r.table_name.toLowerCase().includes(q) ||
        (r.creator || '').toLowerCase().includes(q);
      return matchStatus && matchSearch;
    });
  }, [records, statusFilter, searchTerm]);

  const renderStatusBadge = (status: string) => {
    if (status === 'Đúng hoàn toàn') {
      return (
        <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-medium bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300">
          <CheckCircle2 className="w-3.5 h-3.5" /> {status}
        </span>
      );
    }
    if (status.includes('Lệch cực nhỏ')) {
      return (
        <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-medium bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300">
          <AlertTriangle className="w-3.5 h-3.5" /> {status}
        </span>
      );
    }
    return (
      <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-medium bg-rose-100 text-rose-800 dark:bg-rose-900/40 dark:text-rose-300">
        <XCircle className="w-3.5 h-3.5" /> {status}
      </span>
    );
  };

  return (
    <div className="space-y-6">
      {/* Header Banner */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 bg-white dark:bg-slate-900 p-5 rounded-2xl border border-slate-200 dark:border-slate-800 shadow-sm">
        <h2 className="text-xl font-bold text-slate-900 dark:text-white flex items-center gap-2">
          <Sparkles className="w-5 h-5 text-indigo-500" />
          Chấm Bài Tập Về Nhà Power BI / Power Query (Gemini AI)
        </h2>
        <div className="flex items-center gap-3">
          <div
            className={`inline-flex items-center gap-2 px-3 py-1.5 rounded-xl text-xs font-medium border ${
              hasGeminiKey
                ? 'bg-emerald-50 text-emerald-700 border-emerald-200 dark:bg-emerald-950/40 dark:text-emerald-300 dark:border-emerald-800'
                : 'bg-rose-50 text-rose-700 border-rose-200 dark:bg-rose-950/40 dark:text-rose-300 dark:border-rose-800'
            }`}
          >
            <KeyRound className="w-3.5 h-3.5" />
            {hasGeminiKey ? `Gemini API: Đã kết nối (${maskedKey || 'OK'})` : 'Chưa cấu hình GEMINI_API_KEY'}
          </div>
          <button
            onClick={() => setShowManageModal(true)}
            className="inline-flex items-center gap-2 px-3.5 py-2 rounded-xl text-sm font-medium bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 dark:hover:bg-slate-700 text-slate-700 dark:text-slate-200 transition"
          >
            <Database className="w-4 h-4" /> Quản lý Đáp án
          </button>
        </div>
      </div>

      {/* Upload & Config Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* 1. Chọn Đáp án */}
        <div className="bg-white dark:bg-slate-900 p-5 rounded-2xl border border-slate-200 dark:border-slate-800 shadow-sm space-y-4">
          <div className="flex items-center justify-between">
            <h3 className="font-semibold text-slate-900 dark:text-white">1. Chọn Đáp Án Chuẩn</h3>
            <div className="flex bg-slate-100 dark:bg-slate-800 p-1 rounded-lg text-xs">
              <button
                onClick={() => setAnswerMode('saved')}
                className={`px-3 py-1 rounded-md font-medium transition ${
                  answerMode === 'saved'
                    ? 'bg-white dark:bg-slate-700 text-indigo-600 dark:text-indigo-400 shadow-sm'
                    : 'text-slate-600 dark:text-slate-400'
                }`}
              >
                Đáp án đã lưu
              </button>
              <button
                onClick={() => setAnswerMode('upload')}
                className={`px-3 py-1 rounded-md font-medium transition ${
                  answerMode === 'upload'
                    ? 'bg-white dark:bg-slate-700 text-indigo-600 dark:text-indigo-400 shadow-sm'
                    : 'text-slate-600 dark:text-slate-400'
                }`}
              >
                Tải file mới
              </button>
            </div>
          </div>

          {answerMode === 'saved' ? (
            <div>
              <select
                value={selectedAnswerId}
                onChange={(e) => setSelectedAnswerId(e.target.value)}
                className="w-full px-3.5 py-2.5 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800 text-sm text-slate-900 dark:text-white focus:ring-2 focus:ring-indigo-500 outline-none"
              >
                <option value="">-- Không dùng đáp án (AI tự đánh giá logic) --</option>
                {answerFilesList.map((a) => (
                  <option key={a.id} value={a.id}>
                    [{a.course}] Buổi {a.session_number} — {a.file_name}{' '}
                    {a.table_count ? `(${a.table_count} bảng)` : ''} {!a.exists ? '(Thiếu dữ liệu)' : ''}
                  </option>
                ))}
              </select>
            </div>
          ) : (
            <div className="border-2 border-dashed border-slate-200 dark:border-slate-700 rounded-xl p-4 text-center space-y-2">
              <FileSpreadsheet className="w-8 h-8 text-indigo-500 mx-auto" />
              <p className="text-sm text-slate-600 dark:text-slate-300">
                Chọn file đáp án (.pbix, .xlsx) hoặc thư mục .Dataset
              </p>
              <input
                type="file"
                multiple
                accept=".pbix,.xlsx,.tmdl,.bim"
                onChange={(e) => setUploadedAnswerFiles(Array.from(e.target.files || []))}
                className="block w-full text-xs text-slate-500 file:mr-3 file:py-1.5 file:px-3 file:rounded-lg file:border-0 file:text-xs file:font-medium file:bg-indigo-50 file:text-indigo-700 hover:file:bg-indigo-100 dark:file:bg-indigo-950 dark:file:text-indigo-300"
              />
              {uploadedAnswerFiles.length > 0 && (
                <p className="text-xs text-emerald-600 dark:text-emerald-400 font-medium">
                  Đã chọn {uploadedAnswerFiles.length} file đáp án
                </p>
              )}
            </div>
          )}
        </div>

        {/* 2. Tải bài làm học viên */}
        <div className="bg-white dark:bg-slate-900 p-5 rounded-2xl border border-slate-200 dark:border-slate-800 shadow-sm space-y-4">
          <h3 className="font-semibold text-slate-900 dark:text-white">2. Tải Bài Làm Học Viên</h3>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <label className="flex flex-col items-center justify-center p-4 border-2 border-dashed border-slate-200 dark:border-slate-700 rounded-xl cursor-pointer hover:border-indigo-400 transition">
              <Upload className="w-6 h-6 text-indigo-500 mb-1.5" />
              <span className="text-xs font-medium text-slate-700 dark:text-slate-200">Chọn nhiều File (.pbix, .xlsx)</span>
              <input
                type="file"
                multiple
                accept=".pbix,.xlsx"
                className="hidden"
                onChange={(e) => setStudentFiles(Array.from(e.target.files || []))}
              />
            </label>

            <label className="flex flex-col items-center justify-center p-4 border-2 border-dashed border-slate-200 dark:border-slate-700 rounded-xl cursor-pointer hover:border-indigo-400 transition">
              <FolderOpen className="w-6 h-6 text-amber-500 mb-1.5" />
              <span className="text-xs font-medium text-slate-700 dark:text-slate-200">Chọn cả Thư mục bài làm</span>
              <input
                type="file"
                multiple
                {...({ webkitdirectory: '', directory: '' } as any)}
                className="hidden"
                onChange={(e) =>
                  setStudentFiles(
                    Array.from(e.target.files || []).filter(
                      (f) =>
                        f.name.toLowerCase().endsWith('.pbix') ||
                        f.name.toLowerCase().endsWith('.xlsx') ||
                        f.name.toLowerCase().endsWith('.tmdl') ||
                        f.name.toLowerCase().endsWith('.bim')
                    )
                  )
                }
              />
            </label>
          </div>

          <div className="flex items-center justify-between pt-1">
            <span className="text-xs text-slate-500 dark:text-slate-400">
              {studentFiles.length > 0 ? `Đã chọn ${studentFiles.length} file hợp lệ` : 'Chưa có file nào được chọn'}
            </span>
            <button
              onClick={handleStartGrade}
              disabled={isGrading || studentFiles.length === 0}
              className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-semibold bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 text-white shadow-sm transition"
            >
              {isGrading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Sparkles className="w-4 h-4" />}
              {isGrading ? 'Đang chấm bằng Gemini...' : 'Bắt đầu chấm bài'}
            </button>
          </div>

          {gradeError && (
            <div className="p-3 rounded-xl bg-rose-50 dark:bg-rose-950/40 border border-rose-200 dark:border-rose-800 text-xs text-rose-700 dark:text-rose-300">
              {gradeError}
            </div>
          )}
        </div>
      </div>

      {/* Results Section */}
      {records.length > 0 && (
        <div className="space-y-4">
          {/* Stats */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
            <div className="bg-white dark:bg-slate-900 p-4 rounded-2xl border border-slate-200 dark:border-slate-800">
              <div className="text-xs text-slate-500 dark:text-slate-400">Tổng số bài nộp</div>
              <div className="text-2xl font-bold text-slate-900 dark:text-white mt-1">{stats.totalFiles}</div>
            </div>
            <div className="bg-white dark:bg-slate-900 p-4 rounded-2xl border border-slate-200 dark:border-slate-800">
              <div className="text-xs text-slate-500 dark:text-slate-400">Tổng số bảng (Queries)</div>
              <div className="text-2xl font-bold text-indigo-600 dark:text-indigo-400 mt-1">{stats.totalTables}</div>
            </div>
            <div className="bg-white dark:bg-slate-900 p-4 rounded-2xl border border-emerald-200 dark:border-emerald-900/50">
              <div className="text-xs text-emerald-600 dark:text-emerald-400">Bài Đúng hoàn toàn</div>
              <div className="text-2xl font-bold text-emerald-600 dark:text-emerald-400 mt-1">{stats.exactFiles}</div>
            </div>
            <div className="bg-white dark:bg-slate-900 p-4 rounded-2xl border border-rose-200 dark:border-rose-900/50">
              <div className="text-xs text-rose-600 dark:text-rose-400">Bài Có lỗi sai</div>
              <div className="text-2xl font-bold text-rose-600 dark:text-rose-400 mt-1">{stats.wrongFiles}</div>
            </div>
          </div>

          {/* Filter & View Mode Bar */}
          <div className="flex flex-col sm:flex-row gap-3 items-center justify-between bg-white dark:bg-slate-900 p-4 rounded-2xl border border-slate-200 dark:border-slate-800">
            <div className="flex flex-wrap items-center gap-2">
              <div className="flex bg-slate-100 dark:bg-slate-800 p-1 rounded-lg text-xs mr-2">
                <button
                  onClick={() => setViewMode('grouped')}
                  className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-md font-medium transition ${
                    viewMode === 'grouped'
                      ? 'bg-white dark:bg-slate-700 text-indigo-600 dark:text-indigo-400 shadow-sm'
                      : 'text-slate-600 dark:text-slate-400'
                  }`}
                >
                  <Layers className="w-3.5 h-3.5" /> Gộp theo Bài nộp
                </button>
                <button
                  onClick={() => setViewMode('tables')}
                  className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-md font-medium transition ${
                    viewMode === 'tables'
                      ? 'bg-white dark:bg-slate-700 text-indigo-600 dark:text-indigo-400 shadow-sm'
                      : 'text-slate-600 dark:text-slate-400'
                  }`}
                >
                  <List className="w-3.5 h-3.5" /> Chi tiết từng Bảng
                </button>
              </div>

              {[
                { id: 'ALL', label: 'Tất cả' },
                { id: 'EXACT', label: 'Đúng hoàn toàn' },
                { id: 'WRONG', label: 'Có lỗi sai' },
              ].map((tab) => (
                <button
                  key={tab.id}
                  onClick={() => setStatusFilter(tab.id)}
                  className={`px-3 py-1.5 rounded-lg text-xs font-medium transition ${
                    statusFilter === tab.id
                      ? 'bg-indigo-600 text-white'
                      : 'bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300 hover:bg-slate-200 dark:hover:bg-slate-700'
                  }`}
                >
                  {tab.label}
                </button>
              ))}
            </div>
            <div className="relative w-full sm:w-64">
              <Search className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
              <input
                type="text"
                placeholder="Tìm file, bảng, tác giả..."
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                className="w-full pl-9 pr-3 py-1.5 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800 text-xs text-slate-900 dark:text-white outline-none"
              />
            </div>
          </div>

          {/* Results Table */}
          <div className="bg-white dark:bg-slate-900 rounded-2xl border border-slate-200 dark:border-slate-800 overflow-hidden shadow-sm">
            <div className="overflow-x-auto">
              {viewMode === 'grouped' ? (
                <table className="w-full text-left border-collapse">
                  <thead>
                    <tr className="border-b border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-800/50 text-xs font-semibold text-slate-600 dark:text-slate-300">
                      <th className="p-3.5">File Bài nộp</th>
                      <th className="p-3.5">Tác giả</th>
                      <th className="p-3.5">Số bảng</th>
                      <th className="p-3.5">Trạng thái</th>
                      <th className="p-3.5">Nhận xét tổng hợp (Gửi học viên)</th>
                      <th className="p-3.5 text-right">Thao tác</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100 dark:divide-slate-800 text-sm">
                    {filteredGrouped.map((g) => (
                      <tr key={g.student_file} className="hover:bg-slate-50 dark:hover:bg-slate-800/40">
                        <td className="p-3.5 align-top">
                          <div className="font-medium text-slate-900 dark:text-white break-all">{g.student_file}</div>
                          <div className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">{g.file_type}</div>
                        </td>
                        <td className="p-3.5 align-top text-xs text-slate-700 dark:text-slate-300">{g.creator}</td>
                        <td className="p-3.5 align-top text-xs font-mono text-indigo-600 dark:text-indigo-400">
                          {g.tables.length} bảng
                        </td>
                        <td className="p-3.5 align-top whitespace-nowrap">{renderStatusBadge(g.finalStatus)}</td>
                        <td className="p-3.5 align-top text-xs text-slate-700 dark:text-slate-300 whitespace-pre-line max-w-xl">
                          {g.finalFeedback}
                        </td>
                        <td className="p-3.5 align-top text-right whitespace-nowrap">
                          <div className="inline-flex items-center gap-1.5">
                            <button
                              onClick={() => handleCopyFeedback(g.student_file, g.finalFeedback)}
                              title="Copy nhận xét"
                              className="p-1.5 rounded-lg bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 dark:hover:bg-slate-700 text-slate-600 dark:text-slate-300"
                            >
                              {copiedKey === g.student_file ? (
                                <Check className="w-4 h-4 text-emerald-500" />
                              ) : (
                                <Copy className="w-4 h-4" />
                              )}
                            </button>
                            <button
                              onClick={() =>
                                setEditTarget({ key: g.student_file, text: g.finalFeedback, isGrouped: true })
                              }
                              title="Sửa nhận xét"
                              className="p-1.5 rounded-lg bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 dark:hover:bg-slate-700 text-slate-600 dark:text-slate-300"
                            >
                              <Edit3 className="w-4 h-4" />
                            </button>
                            <button
                              onClick={() => setDiffTables({ fileName: g.student_file, tables: g.tables })}
                              title="Xem Code tất cả bảng"
                              className="p-1.5 rounded-lg bg-indigo-50 hover:bg-indigo-100 dark:bg-indigo-950/50 dark:hover:bg-indigo-900/50 text-indigo-600 dark:text-indigo-400"
                            >
                              <Code2 className="w-4 h-4" />
                            </button>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : (
                <table className="w-full text-left border-collapse">
                  <thead>
                    <tr className="border-b border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-800/50 text-xs font-semibold text-slate-600 dark:text-slate-300">
                      <th className="p-3.5">File / Học viên</th>
                      <th className="p-3.5">Bảng (Query)</th>
                      <th className="p-3.5">Trạng thái</th>
                      <th className="p-3.5">Nhận xét (Feedback)</th>
                      <th className="p-3.5 text-right">Thao tác</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100 dark:divide-slate-800 text-sm">
                    {filteredRecords.map((r, idx) => (
                      <tr key={`${r.student_file}-${r.table_name}-${idx}`} className="hover:bg-slate-50 dark:hover:bg-slate-800/40">
                        <td className="p-3.5 align-top">
                          <div className="font-medium text-slate-900 dark:text-white break-all">{r.student_file}</div>
                          <div className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
                            {r.file_type} • Tác giả: {r.creator || 'Unknown'}
                          </div>
                        </td>
                        <td className="p-3.5 align-top font-mono text-xs text-indigo-600 dark:text-indigo-400">
                          {r.table_name}
                        </td>
                        <td className="p-3.5 align-top whitespace-nowrap">{renderStatusBadge(r.status)}</td>
                        <td className="p-3.5 align-top text-xs text-slate-700 dark:text-slate-300 whitespace-pre-line max-w-md">
                          {r.feedback}
                        </td>
                        <td className="p-3.5 align-top text-right whitespace-nowrap">
                          <div className="inline-flex items-center gap-1.5">
                            <button
                              onClick={() => handleCopyFeedback(r.id || String(idx), r.feedback)}
                              title="Copy nhận xét"
                              className="p-1.5 rounded-lg bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 dark:hover:bg-slate-700 text-slate-600 dark:text-slate-300"
                            >
                              {copiedKey === (r.id || String(idx)) ? (
                                <Check className="w-4 h-4 text-emerald-500" />
                              ) : (
                                <Copy className="w-4 h-4" />
                              )}
                            </button>
                            <button
                              onClick={() => setDiffTables({ fileName: r.student_file, tables: [r] })}
                              title="Xem Code Diff"
                              className="p-1.5 rounded-lg bg-indigo-50 hover:bg-indigo-100 dark:bg-indigo-950/50 dark:hover:bg-indigo-900/50 text-indigo-600 dark:text-indigo-400"
                            >
                              <Code2 className="w-4 h-4" />
                            </button>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Code Diff Modal */}
      {diffTables && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
          <div className="bg-white dark:bg-slate-900 rounded-2xl border border-slate-200 dark:border-slate-800 w-full max-w-5xl max-h-[85vh] flex flex-col overflow-hidden">
            <div className="flex items-center justify-between p-4 border-b border-slate-200 dark:border-slate-800">
              <h3 className="font-semibold text-slate-900 dark:text-white">
                Đối chiếu M Code — {diffTables.fileName}
              </h3>
              <button onClick={() => setDiffTables(null)} className="p-1 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800">
                <X className="w-5 h-5" />
              </button>
            </div>
            <div className="p-4 overflow-y-auto space-y-6">
              {diffTables.tables.map((t, i) => (
                <div key={i} className="space-y-2 border-b border-slate-200 dark:border-slate-800 pb-5 last:border-b-0">
                  <div className="flex items-center justify-between">
                    <span className="font-mono text-sm font-bold text-indigo-600 dark:text-indigo-400">
                      Bảng: {t.table_name}
                    </span>
                    {renderStatusBadge(t.status)}
                  </div>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <div>
                      <div className="text-xs font-semibold text-slate-500 mb-1.5">CODE HỌC VIÊN</div>
                      <pre className="p-3 rounded-xl bg-slate-950 text-slate-100 text-xs overflow-x-auto whitespace-pre-wrap">
                        {t.student_code || '(Trống)'}
                      </pre>
                    </div>
                    <div>
                      <div className="text-xs font-semibold text-emerald-600 mb-1.5">CODE ĐÁP ÁN CHUẨN</div>
                      <pre className="p-3 rounded-xl bg-slate-950 text-emerald-300 text-xs overflow-x-auto whitespace-pre-wrap">
                        {t.expected_code || '(Không có đáp án đối chiếu)'}
                      </pre>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Edit Feedback Modal */}
      {editTarget !== null && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
          <div className="bg-white dark:bg-slate-900 rounded-2xl border border-slate-200 dark:border-slate-800 w-full max-w-lg p-5 space-y-4">
            <div className="flex items-center justify-between">
              <h3 className="font-semibold text-slate-900 dark:text-white">Chỉnh sửa nhận xét</h3>
              <button onClick={() => setEditTarget(null)} className="p-1 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800">
                <X className="w-5 h-5" />
              </button>
            </div>
            <textarea
              rows={7}
              value={editTarget.text}
              onChange={(e) => setEditTarget({ ...editTarget, text: e.target.value })}
              className="w-full p-3 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800 text-sm text-slate-900 dark:text-white outline-none"
            />
            <div className="flex justify-end gap-2">
              <button
                onClick={() => setEditTarget(null)}
                className="px-4 py-2 rounded-xl text-sm bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300"
              >
                Hủy
              </button>
              <button
                onClick={() => {
                  setCustomFeedbacks((prev) => ({ ...prev, [editTarget.key]: editTarget.text }));
                  setEditTarget(null);
                }}
                className="px-4 py-2 rounded-xl text-sm font-medium bg-indigo-600 text-white"
              >
                Lưu thay đổi
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Manage Answers Modal */}
      {showManageModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
          <div className="bg-white dark:bg-slate-900 rounded-2xl border border-slate-200 dark:border-slate-800 w-full max-w-2xl max-h-[85vh] flex flex-col overflow-hidden">
            <div className="flex items-center justify-between p-4 border-b border-slate-200 dark:border-slate-800">
              <h3 className="font-semibold text-slate-900 dark:text-white">Quản lý File Đáp Án (Lưu M Code vào DB)</h3>
              <button onClick={() => setShowManageModal(false)} className="p-1 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800">
                <X className="w-5 h-5" />
              </button>
            </div>
            <div className="p-4 overflow-y-auto space-y-5">
              <form
                onSubmit={handleUploadAnswer}
                className="grid grid-cols-1 sm:grid-cols-4 gap-3 bg-slate-50 dark:bg-slate-800/50 p-3.5 rounded-xl border border-slate-200 dark:border-slate-700"
              >
                <select
                  value={newCourse}
                  onChange={(e) => setNewCourse(e.target.value as any)}
                  className="px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 text-xs"
                >
                  <option value="Power Query">Power Query</option>
                  <option value="Power BI">Power BI</option>
                </select>
                <input
                  type="number"
                  min={1}
                  value={newSession}
                  onChange={(e) => setNewSession(Number(e.target.value))}
                  placeholder="Buổi"
                  className="px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 text-xs"
                />
                <input
                  type="file"
                  multiple
                  accept=".pbix,.xlsx,.tmdl,.bim"
                  onChange={(e) => setNewAnswerFiles(Array.from(e.target.files || []))}
                  className="text-xs self-center"
                />
                <button
                  type="submit"
                  disabled={newAnswerFiles.length === 0 || isUploadingAnswer}
                  className="inline-flex items-center justify-center gap-1.5 px-3 py-2 rounded-lg bg-indigo-600 text-white text-xs font-medium disabled:opacity-50"
                >
                  <Plus className="w-3.5 h-3.5" /> {isUploadingAnswer ? 'Đang tải...' : 'Lưu Đáp Án'}
                </button>
              </form>

              <div className="divide-y divide-slate-100 dark:divide-slate-800">
                {answerFilesList.length === 0 ? (
                  <p className="text-xs text-slate-500 text-center py-6">Chưa có đáp án nào được lưu.</p>
                ) : (
                  answerFilesList.map((a) => (
                    <div key={a.id} className="flex items-center justify-between py-2.5 text-sm">
                      <div>
                        <span className="font-medium text-slate-900 dark:text-white">
                          [{a.course}] Buổi {a.session_number}
                        </span>
                        <span className="text-xs text-slate-500 ml-2">
                          {a.file_name} {a.table_count ? `• ${a.table_count} bảng M Code trong DB` : ''}
                        </span>
                      </div>
                      <button
                        onClick={() => handleDeleteAnswer(a.id)}
                        className="p-1.5 rounded-lg text-rose-500 hover:bg-rose-50 dark:hover:bg-rose-950/40"
                      >
                        <Trash2 className="w-4 h-4" />
                      </button>
                    </div>
                  ))
                )}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
