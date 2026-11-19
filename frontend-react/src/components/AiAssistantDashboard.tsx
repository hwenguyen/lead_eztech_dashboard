import React, { useState, useEffect, useRef, useMemo } from 'react';
import {
  Send,
  BookOpen,
  Plus,
  Trash2,
  Database,
  Sparkles,
  KeyRound,
  RefreshCw,
  CheckCircle2,
  AlertCircle,
  Copy,
  Check,
  ArrowUpRight,
  RotateCcw,
  X,
  MessageSquare,
  Wallet,
  ShieldCheck,
  Upload,
  CornerDownLeft,
} from 'lucide-react';
import {
  fetchAiAssistants,
  fetchAiDocuments,
  ingestAiDocument,
  deleteAiDocument,
  seedAiDocuments,
  updateAiApiKey,
  sendAiChatMessage,
  type AiAssistantProfile,
  type AiDocumentItem,
} from '../services/api';

interface ChatTurn {
  role: 'user' | 'assistant';
  content: string;
  model?: string;
  sources?: { doc_name: string; category: string; score: number }[];
  tools_used?: string[];
}

type AssistantId = 'sale' | 'ke_toan' | 'quy_trinh';

const CATEGORY_LABELS: Record<string, string> = {
  sale: 'AI Sale & Khóa học',
  ke_toan: 'AI Kế toán & Công nợ',
  quy_trinh: 'AI Quy trình & SLA',
  chung: 'Tài liệu dùng chung (Tất cả AI)',
};

const DEFAULT_ASSISTANTS: { id: AssistantId; name: string }[] = [
  { id: 'sale', name: 'AI Sale & Khóa Học' },
  { id: 'ke_toan', name: 'AI Kế Toán & Công Nợ' },
  { id: 'quy_trinh', name: 'AI Quy Trình & SLA' },
];

const getAssistantIcon = (id: string, className = 'w-4 h-4') => {
  if (id === 'ke_toan') return <Wallet className={className} />;
  if (id === 'quy_trinh') return <ShieldCheck className={className} />;
  return <MessageSquare className={className} />;
};

const extractScriptSection = (content: string): string | null => {
  const parts = content.split(/\n\s*(?:---|\*\*\*)\s*\n/);
  if (parts.length < 2) return null;
  let body = parts[1].trim();
  const trailingNoteIdx = body.search(/\n\s*\*{0,2}Gợi ý cho Sale\s*:/i);
  if (trailingNoteIdx > 0) {
    body = body.slice(0, trailingNoteIdx).trim();
  }
  return body.length > 15 ? body : null;
};

const renderInlineMarkdown = (text: string): React.ReactNode[] => {
  const parts = text.split(/(\*\*[^*]+\*\*|`[^`]+`|https?:\/\/[^\s)]+)/g);
  return parts.map((part, i) => {
    if (part.startsWith('**') && part.endsWith('**') && part.length > 4) {
      return (
        <strong key={i} className="font-semibold text-navy">
          {part.slice(2, -2)}
        </strong>
      );
    }
    if (part.startsWith('`') && part.endsWith('`') && part.length > 2) {
      return (
        <code
          key={i}
          className="px-1.5 py-0.5 rounded-md bg-slate-200/70 text-[12px] font-mono text-navy"
        >
          {part.slice(1, -1)}
        </code>
      );
    }
    if (/^https?:\/\//.test(part)) {
      return (
        <a
          key={i}
          href={part}
          target="_blank"
          rel="noopener noreferrer"
          className="text-eztech hover:underline font-medium break-all"
        >
          {part}
        </a>
      );
    }
    return <React.Fragment key={i}>{part}</React.Fragment>;
  });
};

const FormattedAnswer: React.FC<{ content: string }> = ({ content }) => {
  const lines = content.split('\n');
  return (
    <div className="space-y-2 text-[13.5px] leading-[1.65] text-navy">
      {lines.map((line, idx) => {
        const trimmed = line.trim();
        if (!trimmed) return <div key={idx} className="h-1.5" />;
        if (trimmed === '---' || trimmed === '***') {
          return (
            <div key={idx} className="py-1.5 flex items-center gap-2">
              <div className="h-px flex-1 bg-slate-200" />
              <span className="w-1.5 h-1.5 rounded-full bg-eztech/40" />
              <div className="h-px flex-1 bg-slate-200" />
            </div>
          );
        }
        const hMatch = trimmed.match(/^(#{1,4})\s+(.*)$/);
        if (hMatch) {
          return (
            <div key={idx} className="font-bold text-navy text-[14.5px] pt-1.5 tracking-tight">
              {renderInlineMarkdown(hMatch[2])}
            </div>
          );
        }
        const olMatch = trimmed.match(/^(\d+)[.)]\s+(.*)$/);
        if (olMatch) {
          return (
            <div key={idx} className="flex items-start gap-2 pl-1">
              <span className="min-w-[20px] h-5 rounded-md bg-eztech-light text-eztech text-[11px] font-bold flex items-center justify-center mt-0.5 shrink-0 tabular-nums">
                {olMatch[1]}
              </span>
              <span className="flex-1">{renderInlineMarkdown(olMatch[2])}</span>
            </div>
          );
        }
        const ulMatch = trimmed.match(/^[-*•+]\s+(.*)$/);
        if (ulMatch) {
          return (
            <div key={idx} className="flex items-start gap-2 pl-1.5">
              <span className="w-1.5 h-1.5 rounded-full bg-eztech mt-[9px] shrink-0" />
              <span className="flex-1">{renderInlineMarkdown(ulMatch[1])}</span>
            </div>
          );
        }
        return <p key={idx}>{renderInlineMarkdown(trimmed)}</p>;
      })}
    </div>
  );
};

export const AiAssistantDashboard: React.FC = () => {
  const [assistants, setAssistants] = useState<AiAssistantProfile[]>([]);
  const [selectedAssistantId, setSelectedAssistantId] = useState<AssistantId>('sale');
  const [documents, setDocuments] = useState<AiDocumentItem[]>([]);

  const [chatHistories, setChatHistories] = useState<Record<string, ChatTurn[]>>({
    sale: [],
    ke_toan: [],
    quy_trinh: [],
  });
  const [sampleSeed, setSampleSeed] = useState<number>(() => Math.random());
  const [question, setQuestion] = useState<string>('');
  const [chatLoading, setChatLoading] = useState<boolean>(false);
  const [errorMsg, setErrorMsg] = useState<string>('');
  const [statusMsg, setStatusMsg] = useState<string>('');
  const [copiedKey, setCopiedKey] = useState<string | null>(null);

  // Form nạp tài liệu RAG
  const [showDocManager, setShowDocManager] = useState<boolean>(false);
  const [docName, setDocName] = useState<string>('');
  const [docCategory, setDocCategory] = useState<string>('sale');
  const [docContent, setDocContent] = useState<string>('');
  const [ingesting, setIngesting] = useState<boolean>(false);

  // Cấu hình Gemini API Key
  const [showKeyForm, setShowKeyForm] = useState<boolean>(false);
  const [newApiKey, setNewApiKey] = useState<string>('');
  const [savingKey, setSavingKey] = useState<boolean>(false);

  const chatFormRef = useRef<HTMLFormElement | null>(null);
  const chatInputRef = useRef<HTMLTextAreaElement | null>(null);
  const chatEndRef = useRef<HTMLDivElement | null>(null);

  const loadMetadata = async () => {
    try {
      const [astRes, docRes] = await Promise.all([fetchAiAssistants(), fetchAiDocuments()]);
      setAssistants(astRes.assistants);
      setDocuments(docRes.documents);
    } catch (err: any) {
      setErrorMsg(err?.response?.data?.detail || 'Không thể tải cấu hình AI RAG.');
    }
  };

  useEffect(() => {
    loadMetadata();
  }, []);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }, [chatHistories, selectedAssistantId, chatLoading]);

  useEffect(() => {
    const el = chatInputRef.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, 220)}px`;
  }, [question, selectedAssistantId]);

  const currentAssistant =
    assistants.find((a) => a.id === selectedAssistantId) || {
      id: selectedAssistantId,
      name: CATEGORY_LABELS[selectedAssistantId] || 'AI Nội Bộ',
      badge: '',
      description: '',
      categories: [selectedAssistantId, 'chung'],
      sample_questions: [],
      doc_count: 0,
    };

  const currentTurns = chatHistories[selectedAssistantId] || [];

  const randomSampleQuestions = useMemo(() => {
    const pool = [...(currentAssistant.sample_questions || [])];
    for (let i = pool.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [pool[i], pool[j]] = [pool[j], pool[i]];
    }
    return pool.slice(0, 3);
  }, [currentAssistant.sample_questions, selectedAssistantId, sampleSeed]);

  const handleCopyText = async (text: string, key: string) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopiedKey(key);
      window.setTimeout(() => {
        setCopiedKey((prev) => (prev === key ? null : prev));
      }, 1800);
    } catch {
      setErrorMsg('Trình duyệt không hỗ trợ sao chép tự động.');
    }
  };

  const handlePickSample = (sq: string) => {
    setQuestion(sq);
    window.requestAnimationFrame(() => {
      chatInputRef.current?.focus();
    });
  };

  const handleSendChat = async (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = question.trim();
    if (!trimmed || chatLoading) return;

    setErrorMsg('');
    const prevTurns = chatHistories[selectedAssistantId] || [];
    const updatedTurns: ChatTurn[] = [...prevTurns, { role: 'user', content: trimmed }];
    setChatHistories((prev) => ({ ...prev, [selectedAssistantId]: updatedTurns }));
    setQuestion('');
    setChatLoading(true);

    try {
      const res = await sendAiChatMessage({
        assistant_id: selectedAssistantId,
        question: trimmed,
        history: prevTurns.map((t) => ({ role: t.role, content: t.content })),
      });
      setChatHistories((prev) => ({
        ...prev,
        [selectedAssistantId]: [
          ...updatedTurns,
          {
            role: 'assistant',
            content: res.answer,
            model: res.model,
            sources: res.sources,
            tools_used: res.tools_used,
          },
        ],
      }));
    } catch (err: any) {
      setErrorMsg(
        err?.response?.data?.detail ||
          'Lỗi khi gọi Gemini API. Vui lòng thử lại hoặc kiểm tra GEMINI_API_KEY.'
      );
    } finally {
      setChatLoading(false);
    }
  };

  const handleChatTextareaKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      if (e.nativeEvent.isComposing || e.keyCode === 229) {
        return;
      }
      chatFormRef.current?.requestSubmit();
    }
  };

  const handleIngestDocument = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!docName.trim() || !docContent.trim() || ingesting) return;
    setIngesting(true);
    setErrorMsg('');
    setStatusMsg('');
    try {
      const res = await ingestAiDocument({
        doc_name: docName.trim(),
        category: docCategory,
        content: docContent.trim(),
      });
      setStatusMsg(`Đã nạp "${res.doc_name}" (${res.chunks_added} đoạn vector RAG).`);
      setDocName('');
      setDocContent('');
      await loadMetadata();
    } catch (err: any) {
      setErrorMsg(err?.response?.data?.detail || 'Không thể nạp tài liệu.');
    } finally {
      setIngesting(false);
    }
  };

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const text = await file.text();
    if (!docName) {
      setDocName(file.name.replace(/\.[^.]+$/, ''));
    }
    setDocContent(text);
  };

  const handleDeleteDoc = async (docId: string, name: string) => {
    if (!window.confirm(`Xóa tài liệu "${name}" khỏi kho RAG?`)) return;
    try {
      await deleteAiDocument(docId);
      setStatusMsg(`Đã xóa tài liệu "${name}".`);
      await loadMetadata();
    } catch (err: any) {
      setErrorMsg(err?.response?.data?.detail || 'Không thể xóa tài liệu.');
    }
  };

  const handleSeedDocs = async () => {
    setIngesting(true);
    setErrorMsg('');
    try {
      const res = await seedAiDocuments();
      setStatusMsg(res.message);
      await loadMetadata();
    } catch (err: any) {
      setErrorMsg(err?.response?.data?.detail || 'Lỗi khi nạp tài liệu mẫu.');
    } finally {
      setIngesting(false);
    }
  };

  const handleSaveApiKey = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newApiKey.trim() || savingKey) return;
    setSavingKey(true);
    setErrorMsg('');
    try {
      await updateAiApiKey(newApiKey.trim());
      setNewApiKey('');
      setShowKeyForm(false);
      setStatusMsg('Đã cập nhật Gemini API Key thành công.');
    } catch (err: any) {
      setErrorMsg(err?.response?.data?.detail || 'Không thể lưu API Key.');
    } finally {
      setSavingKey(false);
    }
  };

  const tabItems = assistants.length > 0 ? assistants : (DEFAULT_ASSISTANTS as AiAssistantProfile[]);

  return (
    <div className="space-y-4">
      {/* Thanh điều hướng AI hiện đại (Segmented Pill + Công cụ) */}
      <div className="bg-white rounded-2xl border border-slate-200/80 shadow-card p-2.5 sm:px-3.5 sm:py-2.5 space-y-2.5">
        <div className="flex flex-wrap items-center justify-between gap-2.5">
          <div
            role="tablist"
            aria-label="Chọn trợ lý AI chuyên biệt"
            className="inline-flex items-center gap-1 p-1 rounded-xl bg-slate-100 overflow-x-auto max-w-full"
          >
            {tabItems.map((ast) => {
              const selected = selectedAssistantId === ast.id;
              return (
                <button
                  key={ast.id}
                  id={`tab-ai-${ast.id}`}
                  type="button"
                  role="tab"
                  aria-selected={selected}
                  onClick={() => {
                    setSelectedAssistantId(ast.id as AssistantId);
                    setDocCategory(ast.id);
                    setSampleSeed(Math.random());
                  }}
                  className={`flex items-center gap-2 px-3.5 py-2 rounded-lg text-xs font-semibold whitespace-nowrap transition-all duration-200 cursor-pointer active:scale-[0.98] ${
                    selected
                      ? 'gradient-brand text-white shadow-sm'
                      : 'text-slate-600 hover:text-navy hover:bg-white'
                  }`}
                >
                  <span className={selected ? 'text-gold-400' : 'text-slate-400'}>
                    {getAssistantIcon(ast.id, 'w-3.5 h-3.5')}
                  </span>
                  <span>{ast.name}</span>
                </button>
              );
            })}
          </div>

          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => {
                setShowDocManager((v) => !v);
                setShowKeyForm(false);
              }}
              className={`px-3 py-2 rounded-xl text-xs font-semibold border transition-all duration-200 flex items-center gap-1.5 cursor-pointer active:scale-[0.98] ${
                showDocManager
                  ? 'bg-eztech-light border-eztech-border text-eztech'
                  : 'bg-white border-slate-200 text-navy hover:bg-slate-50 hover:border-slate-300'
              }`}
            >
              <BookOpen className="w-3.5 h-3.5 text-eztech" />
              <span>{showDocManager ? 'Đóng tài liệu' : 'Tài liệu RAG'}</span>
              {documents.length > 0 && (
                <span className="text-[11px] font-mono tabular-nums opacity-70">
                  ({documents.length})
                </span>
              )}
            </button>

            <button
              type="button"
              onClick={() => {
                setShowKeyForm((v) => !v);
                setShowDocManager(false);
              }}
              className={`px-3 py-2 rounded-xl text-xs font-semibold border transition-all duration-200 flex items-center gap-1.5 cursor-pointer active:scale-[0.98] ${
                showKeyForm
                  ? 'bg-amber-50 border-amber-200 text-amber-700'
                  : 'bg-white border-slate-200 text-slate-700 hover:bg-slate-50 hover:border-slate-300'
              }`}
            >
              <KeyRound className="w-3.5 h-3.5 text-amber-600" />
              <span>API Key</span>
            </button>
          </div>
        </div>

        {/* Form đổi API Key */}
        {showKeyForm && (
          <form
            onSubmit={handleSaveApiKey}
            aria-labelledby="api-key-form-heading"
            className="ai-animate-panel p-3.5 bg-slate-50 rounded-xl border border-slate-200 flex flex-wrap items-end gap-3"
          >
            <div className="flex-1 min-w-[240px]">
              <label
                htmlFor="gemini-api-key-input"
                id="api-key-form-heading"
                className="block text-xs font-semibold text-navy mb-1.5"
              >
                Gemini API Key mới
              </label>
              <input
                id="gemini-api-key-input"
                name="api_key"
                type="password"
                required
                value={newApiKey}
                onChange={(e) => setNewApiKey(e.target.value)}
                autoCorrect="off"
                autoCapitalize="none"
                spellCheck={false}
                placeholder="Dán mã Gemini API Key..."
                className="w-full px-3.5 py-2 text-xs bg-white border border-slate-300 rounded-xl focus:outline-none focus:ring-2 focus:ring-eztech text-navy"
              />
            </div>
            <div className="flex items-center gap-2">
              <button
                type="submit"
                disabled={savingKey}
                className="px-4 py-2 rounded-xl text-xs font-semibold gradient-brand text-white hover:opacity-95 disabled:opacity-50 transition-all cursor-pointer active:scale-[0.98]"
              >
                {savingKey ? 'Đang lưu...' : 'Lưu API Key'}
              </button>
              <button
                type="button"
                onClick={() => setShowKeyForm(false)}
                className="p-2 rounded-xl text-slate-400 hover:text-navy hover:bg-slate-200 transition-colors cursor-pointer"
                aria-label="Đóng biểu mẫu API Key"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
          </form>
        )}

        {/* Thông báo trạng thái / lỗi */}
        {statusMsg && (
          <div
            role="status"
            className="ai-animate-panel flex items-center justify-between gap-2 px-3.5 py-2.5 rounded-xl bg-emerald-50 border border-emerald-200 text-emerald-800 text-xs"
          >
            <div className="flex items-center gap-2">
              <CheckCircle2 className="w-4 h-4 shrink-0" />
              <span>{statusMsg}</span>
            </div>
            <button
              type="button"
              onClick={() => setStatusMsg('')}
              className="p-0.5 rounded-md hover:bg-emerald-100 transition-colors cursor-pointer"
              aria-label="Đóng thông báo"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          </div>
        )}
        {errorMsg && (
          <div
            role="alert"
            className="ai-animate-panel flex items-center justify-between gap-2 px-3.5 py-2.5 rounded-xl bg-rose-50 border border-rose-200 text-rose-700 text-xs"
          >
            <div className="flex items-center gap-2">
              <AlertCircle className="w-4 h-4 shrink-0" />
              <span>{errorMsg}</span>
            </div>
            <button
              type="button"
              onClick={() => setErrorMsg('')}
              className="p-0.5 rounded-md hover:bg-rose-100 transition-colors cursor-pointer"
              aria-label="Đóng cảnh báo lỗi"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          </div>
        )}
      </div>

      {/* Khu vực Quản lý Tài liệu RAG */}
      {showDocManager && (
        <div className="ai-animate-panel grid grid-cols-1 lg:grid-cols-2 gap-4">
          {/* Form thêm tài liệu mới */}
          <form
            onSubmit={handleIngestDocument}
            aria-labelledby="ingest-doc-heading"
            className="bg-white rounded-2xl border border-slate-200/80 shadow-card p-5 space-y-3.5"
          >
            <div className="flex items-center justify-between gap-2">
              <h4
                id="ingest-doc-heading"
                className="text-xs font-bold text-navy uppercase tracking-wider flex items-center gap-2"
              >
                <span className="w-6 h-6 rounded-lg bg-eztech-light text-eztech flex items-center justify-center">
                  <Plus className="w-3.5 h-3.5" />
                </span>
                <span>Nạp tài liệu mới vào kho RAG</span>
              </h4>
              <label
                htmlFor="rag-file-upload"
                className="px-2.5 py-1.5 rounded-lg text-[11px] font-semibold bg-eztech-light text-eztech hover:opacity-90 transition-opacity cursor-pointer flex items-center gap-1.5"
              >
                <Upload className="w-3.5 h-3.5" />
                <span>Tải file (.txt, .md, .csv)</span>
                <input
                  id="rag-file-upload"
                  name="rag_file"
                  type="file"
                  accept=".txt,.md,.csv,.json"
                  onChange={handleFileUpload}
                  className="sr-only"
                />
              </label>
            </div>

            <div>
              <label htmlFor="rag-doc-name" className="block text-xs font-semibold text-navy mb-1.5">
                Tên tài liệu <span aria-hidden="true">*</span>
              </label>
              <input
                id="rag-doc-name"
                name="doc_name"
                type="text"
                required
                value={docName}
                onChange={(e) => setDocName(e.target.value)}
                placeholder="VD: Bảng giá khóa học Data Analyst T11/2026"
                className="w-full px-3.5 py-2 text-xs bg-white border border-slate-300 rounded-xl focus:outline-none focus:ring-2 focus:ring-eztech text-navy"
              />
            </div>

            <fieldset className="space-y-1.5">
              <legend className="text-xs font-semibold text-navy">
                Phân bổ cho Trợ lý AI <span aria-hidden="true">*</span>
              </legend>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 pt-1">
                {(['sale', 'ke_toan', 'quy_trinh', 'chung'] as const).map((cat) => {
                  const isChecked = docCategory === cat;
                  return (
                    <label
                      key={cat}
                      htmlFor={`cat-radio-${cat}`}
                      className={`flex items-center gap-2 px-3 py-2 rounded-xl border text-xs font-medium cursor-pointer transition-all ${
                        isChecked
                          ? 'bg-eztech-light border-eztech-border text-eztech font-semibold'
                          : 'bg-slate-50 border-slate-200 text-navy hover:border-slate-300'
                      }`}
                    >
                      <input
                        id={`cat-radio-${cat}`}
                        type="radio"
                        name="category"
                        value={cat}
                        checked={isChecked}
                        onChange={() => setDocCategory(cat)}
                        className="accent-navy"
                      />
                      <span className="truncate">{CATEGORY_LABELS[cat]}</span>
                    </label>
                  );
                })}
              </div>
            </fieldset>

            <div>
              <label
                htmlFor="rag-doc-content"
                className="block text-xs font-semibold text-navy mb-1.5"
              >
                Nội dung tài liệu <span aria-hidden="true">*</span>
              </label>
              <textarea
                id="rag-doc-content"
                name="content"
                required
                rows={5}
                value={docContent}
                onChange={(e) => setDocContent(e.target.value)}
                placeholder="Dán nội dung kịch bản sale, thông tin khóa học, học phí hoặc quy trình vào đây..."
                className="w-full px-3.5 py-2.5 text-xs bg-white border border-slate-300 rounded-xl focus:outline-none focus:ring-2 focus:ring-eztech text-navy custom-scrollbar"
              />
            </div>

            <div className="flex flex-wrap items-center justify-between gap-2 pt-1">
              <button
                type="button"
                onClick={handleSeedDocs}
                disabled={ingesting}
                className="px-3.5 py-2 rounded-xl text-xs font-semibold border border-slate-200 text-slate-600 hover:bg-slate-50 transition-colors cursor-pointer"
              >
                Khôi phục tài liệu mẫu
              </button>
              <button
                type="submit"
                disabled={ingesting}
                className="px-4 py-2 rounded-xl text-xs font-semibold gradient-brand text-white shadow-sm hover:opacity-95 disabled:opacity-50 transition-all cursor-pointer active:scale-[0.98] flex items-center gap-1.5"
              >
                {ingesting ? (
                  <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                ) : (
                  <Plus className="w-3.5 h-3.5" />
                )}
                <span>{ingesting ? 'Đang tạo Vector...' : 'Lưu & Nhúng Vector'}</span>
              </button>
            </div>
          </form>

          {/* Danh sách tài liệu hiện có */}
          <div className="bg-white rounded-2xl border border-slate-200/80 shadow-card p-5 flex flex-col">
            <div className="flex items-center justify-between mb-3.5">
              <h4 className="text-xs font-bold text-navy uppercase tracking-wider flex items-center gap-2">
                <span className="w-6 h-6 rounded-lg bg-eztech-light text-eztech flex items-center justify-center">
                  <Database className="w-3.5 h-3.5" />
                </span>
                <span>Kho tài liệu đã nhúng ({documents.length})</span>
              </h4>
              <button
                type="button"
                onClick={() => setShowDocManager(false)}
                className="p-1.5 rounded-lg text-slate-400 hover:text-navy hover:bg-slate-100 transition-colors cursor-pointer"
                aria-label="Đóng quản lý tài liệu"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
            <div className="flex-1 overflow-y-auto max-h-[360px] space-y-2.5 pr-1 custom-scrollbar">
              {documents.length === 0 ? (
                <div className="py-12 text-center space-y-2">
                  <Database className="w-8 h-8 text-slate-300 mx-auto" />
                  <p className="text-xs text-slate-400">
                    Chưa có tài liệu nào. Hãy khôi phục tài liệu mẫu hoặc thêm mới ở bên trái.
                  </p>
                </div>
              ) : (
                documents.map((doc) => (
                  <div
                    key={doc.doc_id}
                    className="p-3.5 rounded-xl border border-slate-200/80 bg-slate-50/70 hover:border-eztech-border transition-colors flex items-start justify-between gap-3"
                  >
                    <div className="space-y-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="text-xs font-bold text-navy">{doc.doc_name}</span>
                        <span className="px-2 py-0.5 text-[10px] font-semibold rounded-md bg-eztech-light text-eztech">
                          {CATEGORY_LABELS[doc.category] || doc.category}
                        </span>
                        <span className="text-[11px] text-slate-400 tabular-nums">
                          {doc.chunk_count} đoạn • {doc.has_embedding ? 'Vector 768d' : 'Keyword'}
                        </span>
                      </div>
                      <p className="text-[11.5px] text-slate-500 line-clamp-2 leading-relaxed">
                        {doc.preview}
                      </p>
                    </div>
                    <button
                      type="button"
                      onClick={() => handleDeleteDoc(doc.doc_id, doc.doc_name)}
                      className="p-1.5 text-slate-400 hover:text-rose-600 hover:bg-rose-50 rounded-lg transition-colors shrink-0 cursor-pointer"
                      title="Xóa tài liệu"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
      )}

      {/* Khung Chat chính */}
      <div
        role="tabpanel"
        aria-labelledby={`tab-ai-${selectedAssistantId}`}
        className="relative bg-white rounded-2xl border border-slate-200/80 shadow-card flex flex-col h-[calc(100vh-195px)] min-h-[540px] max-h-[820px] overflow-hidden"
      >
        {/* Thanh trạng thái ánh sáng mượt trên đỉnh khung chat */}
        <div
          className={`h-[2.5px] w-full shrink-0 transition-opacity duration-300 ${
            chatLoading ? 'ai-shimmer-bar opacity-100' : 'gradient-brand opacity-80'
          }`}
        />

        {/* Header gọn gàng, sạch sẽ */}
        <div className="px-5 py-3 border-b border-slate-100 flex items-center justify-between gap-3 bg-white shrink-0">
          <div className="flex items-center gap-2.5 min-w-0">
            <div className="w-8 h-8 rounded-xl gradient-brand text-white flex items-center justify-center shadow-xs shrink-0">
              {getAssistantIcon(currentAssistant.id, 'w-4 h-4 text-gold-400')}
            </div>
            <span className="text-sm font-bold text-navy tracking-tight truncate">
              {currentAssistant.name}
            </span>
          </div>

          {currentTurns.length > 0 && (
            <button
              type="button"
              onClick={() => {
                setChatHistories((prev) => ({ ...prev, [selectedAssistantId]: [] }));
                setSampleSeed(Math.random());
              }}
              className="inline-flex items-center gap-1.5 text-xs text-slate-500 hover:text-rose-600 font-semibold px-3 py-1.5 rounded-xl hover:bg-rose-50 transition-all cursor-pointer active:scale-[0.98]"
            >
              <RotateCcw className="w-3.5 h-3.5" />
              <span>Hội thoại mới</span>
            </button>
          )}
        </div>

        {/* Khu vực hiển thị hội thoại */}
        <div className="flex-1 overflow-y-auto px-4 sm:px-6 py-5 custom-scrollbar">
          {currentTurns.length === 0 ? (
            <div
              key={selectedAssistantId}
              className="h-full flex flex-col items-center justify-center max-w-3xl mx-auto py-6 text-center"
            >
              {/* Biểu tượng AI nổi với vầng sáng đồng bộ theme EzTech */}
              <div className="relative mb-5">
                <div className="ai-welcome-glow absolute -inset-10 rounded-full pointer-events-none" />
                <div className="ai-animate-pulse-ring absolute inset-0 rounded-2xl border-2 border-brand-400/40 pointer-events-none" />
                <div className="ai-animate-float relative w-14 h-14 rounded-2xl gradient-brand text-white flex items-center justify-center shadow-brand">
                  <Sparkles className="w-7 h-7 text-gold-400" />
                </div>
              </div>

              <div className="ai-animate-fade-up space-y-1.5 mb-7 max-w-xl">
                <h3 className="text-lg sm:text-xl font-bold text-navy tracking-tight">
                  Xin chào! Bắt đầu cùng {currentAssistant.name}
                </h3>
                <p className="text-[13px] text-slate-500 leading-relaxed">
                  Nhập câu hỏi hoặc dán SĐT khách hàng bên dưới, hoặc chọn nhanh một gợi ý.
                </p>
              </div>

              {randomSampleQuestions.length > 0 && (
                <div className="w-full space-y-3">
                  <div className="grid grid-cols-1 md:grid-cols-3 gap-3 text-left">
                    {randomSampleQuestions.map((sq, idx) => (
                      <button
                        key={`${selectedAssistantId}-${sampleSeed}-${idx}`}
                        type="button"
                        onClick={() => handlePickSample(sq)}
                        style={{ animationDelay: `${70 + idx * 70}ms` }}
                        className="ai-animate-fade-up group relative p-4 rounded-2xl border border-slate-200/80 bg-slate-50/70 hover:bg-white hover:border-eztech-border hover:shadow-card-hover hover:-translate-y-0.5 transition-all duration-200 flex flex-col justify-between gap-3 cursor-pointer text-left"
                      >
                        <span className="text-[13px] leading-relaxed text-navy font-medium line-clamp-3">
                          {sq}
                        </span>
                        <div className="flex items-center justify-between pt-1">
                          <span className="text-[11px] font-semibold text-eztech opacity-80 group-hover:opacity-100 transition-opacity">
                            Chọn gợi ý
                          </span>
                          <span className="w-6 h-6 rounded-lg bg-eztech-light text-eztech flex items-center justify-center transition-transform duration-200 group-hover:translate-x-0.5 group-hover:-translate-y-0.5">
                            <ArrowUpRight className="w-3.5 h-3.5" />
                          </span>
                        </div>
                      </button>
                    ))}
                  </div>

                  {(currentAssistant.sample_questions?.length || 0) > 3 && (
                    <button
                      type="button"
                      onClick={() => setSampleSeed(Math.random())}
                      className="inline-flex items-center gap-1.5 text-xs font-medium text-slate-500 hover:text-eztech px-3 py-1.5 rounded-lg hover:bg-eztech-light transition-colors cursor-pointer"
                    >
                      <RefreshCw className="w-3 h-3" />
                      <span>Đổi gợi ý khác</span>
                    </button>
                  )}
                </div>
              )}
            </div>
          ) : (
            <div className="max-w-4xl mx-auto space-y-5">
              {currentTurns.map((turn, idx) => {
                const isUser = turn.role === 'user';
                const scriptSection = !isUser ? extractScriptSection(turn.content) : null;
                const copyAllId = `all-${idx}`;
                const copyScriptId = `script-${idx}`;

                return (
                  <div
                    key={idx}
                    className={`ai-animate-fade-up flex items-start gap-3 ${
                      isUser ? 'justify-end' : 'justify-start'
                    }`}
                  >
                    {!isUser && (
                      <div className="hidden sm:flex w-8 h-8 rounded-xl gradient-brand text-white items-center justify-center shrink-0 mt-0.5 shadow-xs">
                        <Sparkles className="w-4 h-4 text-gold-400" />
                      </div>
                    )}

                    <div
                      className={`max-w-[92%] sm:max-w-[82%] rounded-2xl ${
                        isUser
                          ? 'gradient-brand text-white px-4 py-3 rounded-br-md shadow-sm text-[13.5px] leading-relaxed'
                          : 'bg-slate-50 border border-slate-200/80 px-4 sm:px-5 py-3.5 rounded-tl-md shadow-xs'
                      }`}
                    >
                      {isUser ? (
                        <div className="whitespace-pre-wrap">{turn.content}</div>
                      ) : (
                        <>
                          <FormattedAnswer content={turn.content} />
                          <div className="mt-3 pt-2.5 border-t border-slate-200/70 flex flex-wrap items-center justify-end gap-2">
                            {scriptSection && (
                              <button
                                type="button"
                                onClick={() => handleCopyText(scriptSection, copyScriptId)}
                                className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-[11.5px] font-semibold transition-all cursor-pointer active:scale-[0.97] ${
                                  copiedKey === copyScriptId
                                    ? 'bg-emerald-50 text-emerald-700 border border-emerald-200'
                                    : 'bg-eztech-light text-eztech hover:opacity-90'
                                }`}
                              >
                                {copiedKey === copyScriptId ? (
                                  <Check className="w-3.5 h-3.5" />
                                ) : (
                                  <Copy className="w-3.5 h-3.5" />
                                )}
                                <span>
                                  {copiedKey === copyScriptId
                                    ? 'Đã sao chép tin nhắn'
                                    : 'Sao chép tin nhắn'}
                                </span>
                              </button>
                            )}
                            <button
                              type="button"
                              onClick={() => handleCopyText(turn.content, copyAllId)}
                              className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-[11.5px] font-medium transition-all cursor-pointer active:scale-[0.97] ${
                                copiedKey === copyAllId
                                  ? 'bg-emerald-50 text-emerald-700 border border-emerald-200'
                                  : 'text-slate-500 hover:text-navy hover:bg-slate-200'
                              }`}
                            >
                              {copiedKey === copyAllId ? (
                                <Check className="w-3.5 h-3.5" />
                              ) : (
                                <Copy className="w-3.5 h-3.5" />
                              )}
                              <span>
                                {copiedKey === copyAllId
                                  ? 'Đã sao chép'
                                  : scriptSection
                                    ? 'Sao chép tất cả'
                                    : 'Sao chép'}
                              </span>
                            </button>
                          </div>
                        </>
                      )}
                    </div>
                  </div>
                );
              })}

              {chatLoading && (
                <div className="ai-animate-fade-up flex items-start gap-3 justify-start" role="status">
                  <div className="hidden sm:flex w-8 h-8 rounded-xl gradient-brand text-white items-center justify-center shrink-0 mt-0.5 shadow-xs">
                    <Sparkles className="w-4 h-4 text-gold-400 animate-pulse" />
                  </div>
                  <div className="bg-slate-50 border border-slate-200/80 rounded-2xl rounded-tl-md px-4 py-3 flex items-center gap-3">
                    <div className="flex items-center gap-1.5">
                      <span
                        className="ai-dot w-2 h-2 rounded-full bg-brand-500"
                        style={{ animationDelay: '0ms' }}
                      />
                      <span
                        className="ai-dot w-2 h-2 rounded-full bg-gold-500"
                        style={{ animationDelay: '160ms' }}
                      />
                      <span
                        className="ai-dot w-2 h-2 rounded-full bg-brand-400"
                        style={{ animationDelay: '320ms' }}
                      />
                    </div>
                    <span className="text-xs font-medium text-slate-500">
                      {currentAssistant.name} đang tra cứu dữ liệu &amp; soạn phản hồi...
                    </span>
                  </div>
                </div>
              )}
              <div ref={chatEndRef} />
            </div>
          )}
        </div>

        {/* Khung soạn câu hỏi hiện đại (IME-safe Enter submit) */}
        <form
          ref={chatFormRef}
          onSubmit={handleSendChat}
          className="px-4 sm:px-6 py-3.5 border-t border-slate-100 bg-white shrink-0"
        >
          <div className="max-w-4xl mx-auto">
            <label htmlFor="ai-chat-input" className="sr-only">
              Câu hỏi cho {currentAssistant.name}
            </label>
            <div className="ai-composer rounded-2xl border p-2.5 pl-4 flex flex-col gap-2">
              <textarea
                ref={chatInputRef}
                id="ai-chat-input"
                name="question"
                rows={1}
                required
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                onKeyDown={handleChatTextareaKeyDown}
                placeholder={`Hỏi ${currentAssistant.name} hoặc dán SĐT khách hàng để tra cứu...`}
                className="w-full min-h-[42px] max-h-[220px] overflow-y-auto bg-transparent text-[13.5px] leading-relaxed text-navy placeholder:text-slate-400 focus:outline-none resize-none custom-scrollbar"
              />
              <div className="flex items-center justify-between gap-2 pt-0.5">
                <span className="hidden sm:inline-flex items-center gap-1.5 text-[11px] text-slate-400 select-none">
                  <CornerDownLeft className="w-3 h-3" />
                  <span>Enter gửi · Shift + Enter xuống dòng</span>
                </span>
                <button
                  type="submit"
                  disabled={chatLoading || !question.trim()}
                  className="ml-auto group inline-flex items-center gap-1.5 px-4 py-2 rounded-xl gradient-brand text-white text-xs font-semibold shadow-sm hover:shadow-brand hover:opacity-95 disabled:opacity-40 disabled:shadow-none transition-all duration-200 cursor-pointer active:scale-[0.97]"
                >
                  <span>{chatLoading ? 'Đang gửi...' : 'Gửi'}</span>
                  <Send className="w-3.5 h-3.5 transition-transform duration-200 group-hover:translate-x-0.5 group-hover:-translate-y-0.5" />
                </button>
              </div>
            </div>
          </div>
        </form>
      </div>
    </div>
  );
};
