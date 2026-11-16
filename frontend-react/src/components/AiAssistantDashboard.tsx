import React, { useState, useEffect, useRef } from 'react';
import {
  Bot,
  Send,
  BookOpen,
  Plus,
  Trash2,
  Database,
  Sparkles,
  KeyRound,
  RefreshCw,
  FileText,
  CheckCircle2,
  AlertCircle,
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

const CATEGORY_LABELS: Record<string, string> = {
  sale: 'AI Sale & Khóa học',
  ke_toan: 'AI Kế toán & Công nợ',
  quy_trinh: 'AI Quy trình & SLA',
  chung: 'Tài liệu dùng chung (Tất cả AI)',
};

const renderInlineMarkdown = (text: string): React.ReactNode[] => {
  const parts = text.split(/(\*\*[^*]+\*\*|`[^`]+`|https?:\/\/[^\s)]+)/g);
  return parts.map((part, i) => {
    if (part.startsWith('**') && part.endsWith('**') && part.length > 4) {
      return <strong key={i} className="font-semibold text-navy">{part.slice(2, -2)}</strong>;
    }
    if (part.startsWith('`') && part.endsWith('`') && part.length > 2) {
      return <code key={i} className="px-1 py-0.5 rounded bg-slate-200/70 text-[11px] font-mono">{part.slice(1, -1)}</code>;
    }
    if (/^https?:\/\//.test(part)) {
      return (
        <a key={i} href={part} target="_blank" rel="noopener noreferrer" className="text-eztech underline break-all">
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
    <div className="space-y-1.5">
      {lines.map((line, idx) => {
        const trimmed = line.trim();
        if (!trimmed) return <div key={idx} className="h-1" />;
        if (trimmed === '---' || trimmed === '***') {
          return <hr key={idx} className="border-slate-200 my-1.5" />;
        }
        const hMatch = trimmed.match(/^(#{1,4})\s+(.*)$/);
        if (hMatch) {
          return (
            <div key={idx} className="font-bold text-navy text-[13px] pt-1">
              {renderInlineMarkdown(hMatch[2])}
            </div>
          );
        }
        const ulMatch = trimmed.match(/^[-*•]\s+(.*)$/);
        if (ulMatch) {
          return (
            <div key={idx} className="flex items-start gap-1.5 pl-2">
              <span className="text-eztech font-bold">•</span>
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
  const [selectedAssistantId, setSelectedAssistantId] = useState<'sale' | 'ke_toan' | 'quy_trinh'>('sale');
  const [documents, setDocuments] = useState<AiDocumentItem[]>([]);

  const [chatHistories, setChatHistories] = useState<Record<string, ChatTurn[]>>({
    sale: [],
    ke_toan: [],
    quy_trinh: [],
  });
  const [question, setQuestion] = useState<string>('');
  const [chatLoading, setChatLoading] = useState<boolean>(false);
  const [errorMsg, setErrorMsg] = useState<string>('');
  const [statusMsg, setStatusMsg] = useState<string>('');

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
    el.style.height = `${Math.min(el.scrollHeight, 260)}px`;
  }, [question, selectedAssistantId]);

  const currentAssistant =
    assistants.find((a) => a.id === selectedAssistantId) || {
      id: selectedAssistantId,
      name: CATEGORY_LABELS[selectedAssistantId] || 'AI Nội Bộ',
      badge: 'RAG + API',
      description: 'Trợ lý tra cứu tài liệu nội bộ và dữ liệu hệ thống.',
      categories: [selectedAssistantId, 'chung'],
      sample_questions: [],
      doc_count: 0,
    };

  const currentTurns = chatHistories[selectedAssistantId] || [];

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

  return (
    <div className="space-y-4">
      {/* Thanh điều hướng AI tinh gọn */}
      <div className="bg-white rounded-2xl border border-slate-200/80 shadow-card px-4 pt-3 pb-0 space-y-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div
            role="tablist"
            aria-label="Chọn trợ lý AI chuyên biệt"
            className="flex overflow-x-auto gap-2"
          >
            {(assistants.length > 0
              ? assistants
              : ([
                  { id: 'sale', name: 'AI Sale & Khóa Học' },
                  { id: 'ke_toan', name: 'AI Kế Toán & Công Nợ' },
                  { id: 'quy_trinh', name: 'AI Quy Trình & SLA' },
                ] as AiAssistantProfile[])
            ).map((ast) => {
              const selected = selectedAssistantId === ast.id;
              return (
                <button
                  key={ast.id}
                  id={`tab-ai-${ast.id}`}
                  type="button"
                  role="tab"
                  aria-selected={selected}
                  onClick={() => {
                    setSelectedAssistantId(ast.id);
                    setDocCategory(ast.id);
                  }}
                  className={`relative px-4 py-2 text-xs font-semibold whitespace-nowrap transition-colors cursor-pointer border-b-2 ${
                    selected
                      ? 'border-eztech text-eztech'
                      : 'border-transparent text-slate-600 hover:text-navy'
                  }`}
                >
                  {ast.name}
                </button>
              );
            })}
          </div>

          <div className="flex items-center gap-2 pb-2">
            <button
              type="button"
              onClick={() => setShowDocManager((v) => !v)}
              className="px-3 py-1.5 rounded-xl text-xs font-semibold border border-slate-200 bg-white hover:bg-slate-50 text-navy flex items-center gap-1.5 cursor-pointer"
            >
              <BookOpen className="w-3.5 h-3.5 text-eztech" />
              <span>{showDocManager ? 'Đóng Tài liệu' : 'Tài liệu RAG'}</span>
            </button>

            <button
              type="button"
              onClick={() => setShowKeyForm((v) => !v)}
              className="px-3 py-1.5 rounded-xl text-xs font-semibold border border-slate-200 bg-white hover:bg-slate-50 text-slate-700 flex items-center gap-1.5 cursor-pointer"
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
            className="p-3 mb-2 bg-slate-50 rounded-xl border border-slate-200 flex flex-wrap items-end gap-3"
          >
            <div className="flex-1 min-w-[240px]">
              <label htmlFor="gemini-api-key-input" id="api-key-form-heading" className="block text-xs font-semibold text-navy mb-1">
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
                className="w-full px-3 py-2 text-xs bg-white border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-eztech"
              />
            </div>
            <button
              type="submit"
              disabled={savingKey}
              className="px-4 py-2 rounded-lg text-xs font-semibold bg-navy text-white hover:bg-navy/90 disabled:opacity-50 cursor-pointer"
            >
              {savingKey ? 'Đang lưu...' : 'Lưu API Key'}
            </button>
          </form>
        )}

        {/* Thông báo trạng thái / lỗi */}
        {statusMsg && (
          <div role="status" className="flex items-center gap-2 px-3 py-2 mb-2 rounded-xl bg-emerald-50 border border-emerald-200 text-emerald-800 text-xs">
            <CheckCircle2 className="w-4 h-4 shrink-0" />
            <span>{statusMsg}</span>
          </div>
        )}
        {errorMsg && (
          <div role="alert" className="flex items-center gap-2 px-3 py-2 mb-2 rounded-xl bg-rose-50 border border-rose-200 text-rose-700 text-xs">
            <AlertCircle className="w-4 h-4 shrink-0" />
            <span>{errorMsg}</span>
          </div>
        )}
      </div>

      {/* Khu vực Quản lý Tài liệu RAG (Mở khi bấm nút Quản lý Tài liệu RAG) */}
      {showDocManager && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {/* Form thêm tài liệu mới */}
          <form
            onSubmit={handleIngestDocument}
            aria-labelledby="ingest-doc-heading"
            className="bg-white rounded-2xl border border-slate-200/80 shadow-card p-4 space-y-3"
          >
            <div className="flex items-center justify-between">
              <h4 id="ingest-doc-heading" className="text-xs font-bold text-navy uppercase tracking-wider flex items-center gap-1.5">
                <Plus className="w-4 h-4 text-eztech" />
                <span>Nạp Tài Liệu Mới Vào Kho RAG</span>
              </h4>
              <label
                htmlFor="rag-file-upload"
                className="text-[11px] font-semibold text-eztech hover:underline cursor-pointer flex items-center gap-1"
              >
                <FileText className="w-3.5 h-3.5" />
                <span>Tải từ file (.txt, .md, .csv)</span>
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
              <label htmlFor="rag-doc-name" className="block text-xs font-semibold text-navy mb-1">
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
                className="w-full px-3 py-2 text-xs border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-eztech"
              />
            </div>

            <fieldset className="space-y-1.5">
              <legend className="text-xs font-semibold text-navy">
                Phân bổ cho Trợ lý AI <span aria-hidden="true">*</span>
              </legend>
              <div className="grid grid-cols-2 gap-2 pt-1">
                {(['sale', 'ke_toan', 'quy_trinh', 'chung'] as const).map((cat) => (
                  <div key={cat} className="flex items-center gap-2 bg-slate-50 px-2.5 py-1.5 rounded-lg border border-slate-200">
                    <input
                      id={`cat-radio-${cat}`}
                      type="radio"
                      name="category"
                      value={cat}
                      checked={docCategory === cat}
                      onChange={() => setDocCategory(cat)}
                      className="accent-navy"
                    />
                    <label htmlFor={`cat-radio-${cat}`} className="text-xs text-navy font-medium cursor-pointer">
                      {CATEGORY_LABELS[cat]}
                    </label>
                  </div>
                ))}
              </div>
            </fieldset>

            <div>
              <label htmlFor="rag-doc-content" className="block text-xs font-semibold text-navy mb-1">
                Nội dung tài liệu (Hệ thống tự động cắt đoạn & nhúng Vector 768 chiều) <span aria-hidden="true">*</span>
              </label>
              <textarea
                id="rag-doc-content"
                name="content"
                required
                rows={6}
                value={docContent}
                onChange={(e) => setDocContent(e.target.value)}
                placeholder="Dán nội dung kịch bản sale, thông tin khóa học, học phí hoặc quy trình vào đây..."
                className="w-full px-3 py-2 text-xs border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-eztech"
              />
            </div>

            <div className="flex items-center justify-between pt-1">
              <button
                type="button"
                onClick={handleSeedDocs}
                disabled={ingesting}
                className="px-3 py-2 rounded-lg text-xs font-semibold border border-slate-200 text-slate-600 hover:bg-slate-50 cursor-pointer"
              >
                Khôi phục tài liệu mẫu EzTech
              </button>
              <button
                type="submit"
                disabled={ingesting}
                className="px-4 py-2 rounded-lg text-xs font-semibold gradient-brand text-white shadow-xs disabled:opacity-50 cursor-pointer flex items-center gap-1.5"
              >
                {ingesting ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : <Plus className="w-3.5 h-3.5" />}
                <span>{ingesting ? 'Đang tạo Vector...' : 'Lưu & Nhúng Vector'}</span>
              </button>
            </div>
          </form>

          {/* Danh sách tài liệu hiện có */}
          <div className="bg-white rounded-2xl border border-slate-200/80 shadow-card p-4 flex flex-col">
            <h4 className="text-xs font-bold text-navy uppercase tracking-wider mb-3 flex items-center gap-1.5">
              <Database className="w-4 h-4 text-eztech" />
              <span>Kho Tài Liệu Đã Nhúng ({documents.length})</span>
            </h4>
            <div className="flex-1 overflow-y-auto max-h-[360px] space-y-2.5 pr-1">
              {documents.length === 0 ? (
                <p className="text-xs text-slate-400 py-8 text-center">
                  Chưa có tài liệu nào. Hãy bấm &ldquo;Khôi phục tài liệu mẫu EzTech&rdquo; hoặc thêm mới ở bên trái.
                </p>
              ) : (
                documents.map((doc) => (
                  <div
                    key={doc.doc_id}
                    className="p-3 rounded-xl border border-slate-200/90 bg-slate-50/60 flex items-start justify-between gap-3"
                  >
                    <div className="space-y-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="text-xs font-bold text-navy">{doc.doc_name}</span>
                        <span className="px-2 py-0.5 text-[10px] font-semibold rounded bg-eztech-light text-eztech">
                          {CATEGORY_LABELS[doc.category] || doc.category}
                        </span>
                        <span className="text-[10px] text-slate-400">
                          {doc.chunk_count} đoạn • {doc.has_embedding ? 'Vector 768d' : 'Keyword'}
                        </span>
                      </div>
                      <p className="text-[11px] text-slate-500 line-clamp-2">{doc.preview}</p>
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

      {/* Khung Chat chính với AI đã chọn */}
      <div
        role="tabpanel"
        aria-labelledby={`tab-ai-${selectedAssistantId}`}
        className="bg-white rounded-2xl border border-slate-200/80 shadow-card flex flex-col h-[620px]"
      >
        {/* Header của AI đang chọn */}
        <div className="px-5 py-3.5 border-b border-slate-100 flex flex-wrap items-center justify-between gap-2 bg-slate-50/50 rounded-t-2xl">
          <div>
            <div className="flex items-center gap-2">
              <Sparkles className="w-4 h-4 text-eztech" />
              <span className="text-sm font-bold text-navy">{currentAssistant.name}</span>
              <span className="text-[11px] px-2 py-0.5 rounded-full bg-eztech-light text-eztech font-semibold">
                {currentAssistant.badge}
              </span>
            </div>
            <p className="text-xs text-slate-500 mt-0.5">{currentAssistant.description}</p>
          </div>
          {currentTurns.length > 0 && (
            <button
              type="button"
              onClick={() => setChatHistories((prev) => ({ ...prev, [selectedAssistantId]: [] }))}
              className="text-xs text-slate-500 hover:text-rose-600 font-medium px-2.5 py-1 rounded-lg hover:bg-rose-50 cursor-pointer"
            >
              Xóa hội thoại
            </button>
          )}
        </div>

        {/* Lịch sử tin nhắn */}
        <div className="flex-1 overflow-y-auto p-5 space-y-4">
          {currentTurns.length === 0 ? (
            <div className="max-w-2xl mx-auto py-8 text-center space-y-4">
              <div className="w-12 h-12 rounded-2xl bg-eztech-light text-eztech flex items-center justify-center mx-auto">
                <Bot className="w-6 h-6" />
              </div>
              <div className="space-y-1">
                <h4 className="text-sm font-bold text-navy">
                  Bắt đầu hỏi đáp cùng {currentAssistant.name}
                </h4>
                <p className="text-xs text-slate-500">
                  Trợ lý tự động kết hợp tài liệu nội bộ (RAG) và dữ liệu thời gian thực trên hệ thống EzTech.
                </p>
              </div>
              {currentAssistant.sample_questions.length > 0 && (
                <div className="flex flex-wrap items-center justify-center gap-2 pt-2">
                  {currentAssistant.sample_questions.map((sq, idx) => (
                    <button
                      key={idx}
                      type="button"
                      onClick={() => setQuestion(sq)}
                      className="text-left px-3.5 py-2 rounded-xl border border-slate-200 hover:border-eztech bg-slate-50/70 hover:bg-eztech-light/40 text-xs text-navy transition-colors cursor-pointer"
                    >
                      “{sq}”
                    </button>
                  ))}
                </div>
              )}
            </div>
          ) : (
            currentTurns.map((turn, idx) => (
              <div
                key={idx}
                className={`flex ${turn.role === 'user' ? 'justify-end' : 'justify-start'}`}
              >
                <div
                  className={`max-w-[85%] rounded-2xl px-4 py-3 text-xs leading-relaxed space-y-2 ${
                    turn.role === 'user'
                      ? 'bg-navy text-white'
                      : 'bg-slate-50 border border-slate-200/90 text-navy'
                  }`}
                >
                  {turn.role === 'user' ? (
                    <div className="whitespace-pre-wrap">{turn.content}</div>
                  ) : (
                    <FormattedAnswer content={turn.content} />
                  )}
                </div>
              </div>
            ))
          )}

          {chatLoading && (
            <div className="flex justify-start" role="status">
              <div className="bg-slate-50 border border-slate-200 rounded-2xl px-4 py-3 text-xs text-slate-500 flex items-center gap-2">
                <RefreshCw className="w-3.5 h-3.5 animate-spin text-eztech" />
                <span>{currentAssistant.name} đang tra cứu kho RAG & dữ liệu hệ thống...</span>
              </div>
            </div>
          )}
          <div ref={chatEndRef} />
        </div>

        {/* Form nhập câu hỏi (IME-safe Enter submit) */}
        <form
          ref={chatFormRef}
          onSubmit={handleSendChat}
          className="p-3.5 border-t border-slate-200/80 bg-white rounded-b-2xl flex items-end gap-2.5"
        >
          <div className="flex-1">
            <label htmlFor="ai-chat-input" className="block text-[11px] font-semibold text-slate-500 mb-1">
              Câu hỏi cho {currentAssistant.name} (Nhấn Enter để gửi, Shift + Enter để xuống dòng)
            </label>
            <textarea
              ref={chatInputRef}
              id="ai-chat-input"
              name="question"
              rows={2}
              required
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              onKeyDown={handleChatTextareaKeyDown}
              placeholder={`Nhập câu hỏi cho ${currentAssistant.name} (có thể nhập SĐT khách để tra cứu trực tiếp)...`}
              className="w-full min-h-[56px] max-h-[260px] overflow-y-auto px-3.5 py-2 text-xs border border-slate-300 rounded-xl focus:outline-none focus:ring-2 focus:ring-eztech text-navy"
            />
          </div>
          <button
            type="submit"
            disabled={chatLoading}
            className="px-4 py-2.5 rounded-xl gradient-brand text-white text-xs font-semibold shadow-sm hover:opacity-95 disabled:opacity-50 flex items-center gap-1.5 cursor-pointer shrink-0"
          >
            <Send className="w-3.5 h-3.5" />
            <span>Gửi câu hỏi</span>
          </button>
        </form>
      </div>
    </div>
  );
};
