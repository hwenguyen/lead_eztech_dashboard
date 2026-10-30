import React, { useState, useEffect, useRef, useMemo } from 'react';
import {
  Send,
  Bot,
  Filter,
  History,
  Users,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  Play,
  Square,
  Eye,
  RefreshCw,
  ExternalLink,
  Info,
  ShieldAlert,
  ShieldCheck,
  Trash2,
  RotateCcw,
  Check,
  Key,
  Search,
  ChevronDown,
  X
} from 'lucide-react';
import {
  fetchBroadcastOptions,
  previewBroadcast,
  startBroadcast,
  fetchBroadcastStatus,
  stopBroadcast,
  fetchBroadcastHistory,
  fetchTokenStatus,
  saveTokenConfig,
  clearFailedBroadcastLogs,
  type BroadcastOptions,
  type BroadcastRecipientItem,
  type BroadcastCampaignSummary,
  type BroadcastHistoryItem,
  type BroadcastStatusResponse,
  type TokenStatusResponse
} from '../services/api';

export const BulkMessengerDashboard: React.FC = () => {
  // Navigation sub-tabs
  const [subTab, setSubTab] = useState<'compose' | 'history'>('compose');

  // Options & Token Status from Backend
  const [options, setOptions] = useState<BroadcastOptions | null>(null);
  const [loadingOptions, setLoadingOptions] = useState(false);
  const [tokenStatus, setTokenStatus] = useState<TokenStatusResponse | null>(null);
  const [showTokenModal, setShowTokenModal] = useState(false);
  const [tokenInput, setTokenInput] = useState('');
  const [pagesJsonInput, setPagesJsonInput] = useState('');
  const [savingToken, setSavingToken] = useState(false);

  // Settings & Filters Form State
  const [campaignName, setCampaignName] = useState(
    `campaign_${new Date().toISOString().slice(0, 10).replace(/-/g, '')}`
  );
  const [pageId, setPageId] = useState<string>('all');
  const [nameFilter, setNameFilter] = useState<string>('');
  const [employee, setEmployee] = useState<string>('all');
  const [gender, setGender] = useState<string>('all');
  const [selectedTags, setSelectedTags] = useState<string[]>([]);
  const [isTagDropdownOpen, setIsTagDropdownOpen] = useState<boolean>(false);
  const [tagSearchQuery, setTagSearchQuery] = useState<string>('');
  const tagDropdownRef = useRef<HTMLDivElement>(null);
  const [excludeStudents, setExcludeStudents] = useState<boolean>(true);
  const [timeFilter, setTimeFilter] = useState<string>('all'); // Default 'all' so filters don't hide existing leads
  const [phoneFilter, setPhoneFilter] = useState<string>('all');
  const [limit, setLimit] = useState<number>(50);
  const [delay, setDelay] = useState<number>(1.5);
  const [dryRun, setDryRun] = useState<boolean>(true);
  const [excludeAlreadySent, setExcludeAlreadySent] = useState<boolean>(true);

  // Zalo Personal Anti-Ban & Rate Limit Protection State
  const [zaloProtection, setZaloProtection] = useState<boolean>(true);
  const [zaloPreset, setZaloPreset] = useState<'fast' | 'recommended' | 'ultra'>('recommended');
  const [zaloMinDelay, setZaloMinDelay] = useState<number>(8);
  const [zaloMaxDelay, setZaloMaxDelay] = useState<number>(15);
  const [zaloBatchSize, setZaloBatchSize] = useState<number>(10);
  const [zaloBatchPause, setZaloBatchPause] = useState<number>(45);
  const [enableSpintax, setEnableSpintax] = useState<boolean>(true);
  const [maxConsecutiveErrors, setMaxConsecutiveErrors] = useState<number>(5);

  // Message Content & Template
  const [template, setTemplate] = useState<string>(
    '{Chào|Xin chào|Dạ chào} {gender_title} {name}, bên em gửi {gender_title_lower} thông tin ưu đãi mới nhất từ hệ thống ạ!'
  );
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Preview State & Custom Recipient Management
  const [originalRecipients, setOriginalRecipients] = useState<BroadcastRecipientItem[]>([]);
  const [previewRecipients, setPreviewRecipients] = useState<BroadcastRecipientItem[]>([]);
  const [selectedConvIds, setSelectedConvIds] = useState<Set<string>>(new Set());
  const [isCustomListApplied, setIsCustomListApplied] = useState<boolean>(false);
  const [totalMatching, setTotalMatching] = useState<number>(0);
  const [loadingPreview, setLoadingPreview] = useState<boolean>(false);
  const [hasPreviewed, setHasPreviewed] = useState<boolean>(false);

  // Active Broadcast Execution State
  const [activeTaskId, setActiveTaskId] = useState<string | null>(null);
  const [taskStatus, setTaskStatus] = useState<BroadcastStatusResponse | null>(null);
  const [isStarting, setIsStarting] = useState<boolean>(false);
  const [showConfirmModal, setShowConfirmModal] = useState<boolean>(false);

  // History State
  const [campaignSummaries, setCampaignSummaries] = useState<BroadcastCampaignSummary[]>([]);
  const [historyLogs, setHistoryLogs] = useState<BroadcastHistoryItem[]>([]);
  const [selectedHistoryCampaign, setSelectedHistoryCampaign] = useState<string>('all');
  const [loadingHistory, setLoadingHistory] = useState<boolean>(false);

  // Áp dụng preset tốc độ Zalo cá nhân
  const handleSelectZaloPreset = (preset: 'fast' | 'recommended' | 'ultra') => {
    setZaloPreset(preset);
    if (preset === 'fast') {
      setZaloMinDelay(5);
      setZaloMaxDelay(10);
      setZaloBatchSize(12);
      setZaloBatchPause(30);
    } else if (preset === 'recommended') {
      setZaloMinDelay(8);
      setZaloMaxDelay(15);
      setZaloBatchSize(10);
      setZaloBatchPause(45);
    } else {
      setZaloMinDelay(15);
      setZaloMaxDelay(28);
      setZaloBatchSize(8);
      setZaloBatchPause(65);
    }
  };

  // Xóa 1 khách khỏi danh sách xem trước
  const handleRemoveSingleRecipient = (convId: string) => {
    setPreviewRecipients((prev) => prev.filter((r) => r.conversation_id !== convId));
    setSelectedConvIds((prev) => {
      const next = new Set(prev);
      next.delete(convId);
      return next;
    });
    setIsCustomListApplied(false);
  };

  // Chọn / bỏ chọn 1 khách bằng checkbox
  const handleToggleSelectRecipient = (convId: string) => {
    setSelectedConvIds((prev) => {
      const next = new Set(prev);
      if (next.has(convId)) {
        next.delete(convId);
      } else {
        next.add(convId);
      }
      return next;
    });
  };

  // Chọn tất cả / Bỏ chọn tất cả
  const handleToggleSelectAll = () => {
    if (selectedConvIds.size === previewRecipients.length && previewRecipients.length > 0) {
      setSelectedConvIds(new Set());
    } else {
      setSelectedConvIds(new Set(previewRecipients.map((r) => r.conversation_id)));
    }
  };

  // Xóa hàng loạt các khách đã chọn
  const handleRemoveSelectedRecipients = () => {
    if (selectedConvIds.size === 0) return;
    setPreviewRecipients((prev) => prev.filter((r) => !selectedConvIds.has(r.conversation_id)));
    setSelectedConvIds(new Set());
    setIsCustomListApplied(false);
  };

  // Áp dụng danh sách custom
  const handleApplyCustomList = () => {
    if (previewRecipients.length === 0) {
      alert('Danh sách đang trống, không thể áp dụng.');
      return;
    }
    setIsCustomListApplied(true);
  };

  // Khôi phục danh sách gốc ban đầu
  const handleRestoreOriginalRecipients = () => {
    setPreviewRecipients([...originalRecipients]);
    setSelectedConvIds(new Set());
    setIsCustomListApplied(false);
  };

  // 1. Tải danh sách Options & Token Status
  const loadOptions = async (targetPageId?: string, forceRefresh: boolean = false) => {
    setLoadingOptions(true);
    try {
      const pageToFetch = typeof targetPageId === 'string' ? targetPageId : undefined;
      const [optData, tokData] = await Promise.all([
        fetchBroadcastOptions(pageToFetch, forceRefresh),
        fetchTokenStatus().catch(() => null)
      ]);
      setOptions(optData);
      if (tokData) setTokenStatus(tokData);
    } catch (err) {
      console.error('Lỗi tải broadcast options:', err);
    } finally {
      setLoadingOptions(false);
    }
  };

  // Danh sách Thẻ phân loại (Tags) được lọc CHỈ trả về các thẻ thuộc Tên Kênh đang chọn
  const availableTags = useMemo(() => {
    if (!options) return [];
    if (options.tags_by_page) {
      if (options.tags_by_page[pageId]) {
        return options.tags_by_page[pageId];
      }
      const matchedKey = Object.keys(options.tags_by_page).find(
        (k) => k.toLowerCase() === pageId.toLowerCase()
      );
      if (matchedKey && options.tags_by_page[matchedKey]) {
        return options.tags_by_page[matchedKey];
      }
    }
    if (pageId === 'all') {
      return options.tags_by_page?.all || options.tags || [];
    }
    return options.tags || [];
  }, [options, pageId]);

  // Danh sách Nhân viên phụ trách được lọc theo Tên Kênh đang chọn
  const availableEmployees = useMemo(() => {
    if (!options) return [];
    if (options.employees_by_page) {
      if (options.employees_by_page[pageId]) {
        return options.employees_by_page[pageId];
      }
      const matchedKey = Object.keys(options.employees_by_page).find(
        (k) => k.toLowerCase() === pageId.toLowerCase()
      );
      if (matchedKey && options.employees_by_page[matchedKey]) {
        return options.employees_by_page[matchedKey];
      }
    }
    if (pageId === 'all') {
      return options.employees_by_page?.all || options.employees || [];
    }
    return options.employees || [];
  }, [options, pageId]);

  // Đóng dropdown thẻ khi click ra ngoài
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (tagDropdownRef.current && !tagDropdownRef.current.contains(event.target as Node)) {
        setIsTagDropdownOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const toggleTag = (tagName: string) => {
    setSelectedTags((prev) =>
      prev.includes(tagName) ? prev.filter((t) => t !== tagName) : [...prev, tagName]
    );
  };

  const clearTags = () => {
    setSelectedTags([]);
  };

  const filteredAvailableTags = useMemo(() => {
    if (!tagSearchQuery.trim()) return availableTags;
    const q = tagSearchQuery.trim().toLowerCase();
    return availableTags.filter((t) => t.toLowerCase().includes(q));
  }, [availableTags, tagSearchQuery]);

  // Xử lý khi thay đổi Tên Kênh (tự động reset tag/nhân viên nếu không thuộc kênh mới)
  const handlePageChange = (newPageId: string) => {
    setPageId(newPageId);
    if (selectedTags.length > 0) {
      const nextTags = options?.tags_by_page?.[newPageId] || [];
      if (nextTags.length > 0) {
        const validTags = selectedTags.filter((t) => t === 'no_tag' || nextTags.includes(t));
        setSelectedTags(validTags);
      }
    }
    if (employee !== 'all') {
      const nextEmps = options?.employees_by_page?.[newPageId] || [];
      if (nextEmps.length > 0 && !nextEmps.includes(employee)) {
        setEmployee('all');
      }
    }
  };

  // Tự động kiểm tra và reset tag nếu không còn thuộc kênh đang chọn
  useEffect(() => {
    if (selectedTags.length > 0 && availableTags.length > 0) {
      const validTags = selectedTags.filter((t) => t === 'no_tag' || availableTags.includes(t));
      if (validTags.length !== selectedTags.length) {
        setSelectedTags(validTags);
      }
    }
  }, [availableTags, selectedTags]);

  // Tự động kiểm tra và reset nhân viên nếu không còn thuộc kênh đang chọn
  useEffect(() => {
    if (employee !== 'all') {
      if (availableEmployees.length > 0 && !availableEmployees.includes(employee)) {
        setEmployee('all');
      }
    }
  }, [availableEmployees, employee]);

  // 2. Tải lịch sử
  const loadHistory = async (camp?: string) => {
    setLoadingHistory(true);
    try {
      const data = await fetchBroadcastHistory(camp, 150);
      setCampaignSummaries(data.campaigns);
      setHistoryLogs(data.logs);
    } catch (err) {
      console.error('Lỗi tải lịch sử broadcast:', err);
    } finally {
      setLoadingHistory(false);
    }
  };

  useEffect(() => {
    loadOptions();
    loadHistory();
  }, []);

  // Polling tiến độ nếu có task đang chạy
  useEffect(() => {
    if (!activeTaskId) return;

    const interval = setInterval(async () => {
      try {
        const res = await fetchBroadcastStatus(activeTaskId);
        setTaskStatus(res);
        if (!res.is_running) {
          clearInterval(interval);
          loadHistory();
        }
      } catch (err) {
        console.error('Lỗi kiểm tra tiến độ:', err);
      }
    }, 1200);

    return () => clearInterval(interval);
  }, [activeTaskId]);

  // Lưu cấu hình Token Pancake
  const handleSaveTokenConfig = async () => {
    if (!tokenInput.trim() && !pagesJsonInput.trim()) {
      alert('Vui lòng nhập Pancake Token hoặc cấu hình JSON.');
      return;
    }
    setSavingToken(true);
    try {
      const res = await saveTokenConfig(tokenInput.trim(), pagesJsonInput.trim());
      setTokenStatus(res.token_status);
      setTokenInput('');
      setPagesJsonInput('');
      setShowTokenModal(false);
      alert(res.message);
    } catch (err: any) {
      alert('Lỗi lưu Token: ' + (err.response?.data?.detail || err.message));
    } finally {
      setSavingToken(false);
    }
  };

  // Xóa các bản ghi lỗi FAILED cũ
  const handleClearFailedLogs = async () => {
    if (!window.confirm('Bạn có muốn xóa toàn bộ các bản ghi lỗi (FAILED) để làm sạch lịch sử và gửi lại không?')) {
      return;
    }
    try {
      const res = await clearFailedBroadcastLogs(selectedHistoryCampaign);
      alert(res.message);
      loadHistory(selectedHistoryCampaign);
    } catch (err: any) {
      alert('Không thể xóa log lỗi: ' + (err.response?.data?.detail || err.message));
    }
  };

  // Chèn biến nhanh vào con trỏ chuột trong Textarea
  const insertVariable = (varName: string) => {
    if (!textareaRef.current) return;
    const el = textareaRef.current;
    const start = el.selectionStart;
    const end = el.selectionEnd;
    const text = el.value;
    const newText = text.substring(0, start) + varName + text.substring(end);
    setTemplate(newText);
    setTimeout(() => {
      el.focus();
      el.setSelectionRange(start + varName.length, start + varName.length);
    }, 50);
  };

  // Gọi xem trước danh sách (Preview)
  const handlePreview = async () => {
    setLoadingPreview(true);
    try {
      const res = await previewBroadcast({
        page_id: pageId,
        name_filter: nameFilter,
        employee: employee,
        gender: gender,
        tag: selectedTags.length === 1 ? selectedTags[0] : (selectedTags.length > 1 ? selectedTags.join(',') : 'all'),
        tags: selectedTags,
        time_filter: timeFilter,
        phone_filter: phoneFilter,
        limit: limit,
        template: template,
        exclude_already_sent: excludeAlreadySent,
        exclude_students: excludeStudents,
        campaign_name: campaignName
      });
      setOriginalRecipients(res.recipients);
      setPreviewRecipients(res.recipients);
      setSelectedConvIds(new Set());
      setIsCustomListApplied(false);
      setTotalMatching(res.total_matching);
      setHasPreviewed(true);
    } catch (err) {
      console.error('Lỗi xem trước:', err);
      alert('Không thể xem trước danh sách. Vui lòng kiểm tra lại kết nối backend.');
    } finally {
      setLoadingPreview(false);
    }
  };

  // Bắt đầu gửi tin
  const handleStartBroadcast = async () => {
    setShowConfirmModal(false);
    setIsStarting(true);
    try {
      const isCustomMode =
        isCustomListApplied ||
        (hasPreviewed && previewRecipients.length > 0 && previewRecipients.length !== originalRecipients.length);
      const targetConvIds =
        isCustomMode || (hasPreviewed && previewRecipients.length > 0)
          ? previewRecipients.map((r) => r.conversation_id)
          : undefined;

      const res = await startBroadcast({
        campaign_name: campaignName,
        template: template,
        page_id: pageId,
        name_filter: nameFilter,
        employee: employee,
        gender: gender,
        tag: selectedTags.length === 1 ? selectedTags[0] : (selectedTags.length > 1 ? selectedTags.join(',') : 'all'),
        tags: selectedTags,
        time_filter: timeFilter,
        phone_filter: phoneFilter,
        limit: targetConvIds ? targetConvIds.length : limit,
        delay: delay,
        dry_run: dryRun,
        exclude_already_sent: excludeAlreadySent,
        exclude_students: excludeStudents,
        target_conversation_ids: targetConvIds,
        zalo_protection: zaloProtection,
        zalo_min_delay: zaloMinDelay,
        zalo_max_delay: zaloMaxDelay,
        zalo_batch_size: zaloBatchSize,
        zalo_batch_pause: zaloBatchPause,
        enable_spintax: enableSpintax,
        max_consecutive_errors: maxConsecutiveErrors
      });
      setActiveTaskId(res.task_id);
    } catch (err: any) {
      console.error('Lỗi khởi động broadcast:', err);
      const errDetail = err.response?.data?.detail || 'Không thể bắt đầu gửi tin';
      alert('Lỗi: ' + errDetail);
      if (String(errDetail).toLowerCase().includes('token')) {
        setShowTokenModal(true);
      }
    } finally {
      setIsStarting(false);
    }
  };

  // Dừng gửi khẩn cấp
  const handleStopBroadcast = async () => {
    if (!activeTaskId) return;
    if (!window.confirm('Bạn có chắc chắn muốn dừng tác vụ gửi tin này không?')) return;
    try {
      await stopBroadcast(activeTaskId);
    } catch (err) {
      console.error('Lỗi dừng broadcast:', err);
    }
  };

  // Kiểm tra xem lựa chọn hiện tại có bao gồm kênh Zalo cá nhân hay không
  const hasZaloInSelection =
    pageId === 'all' ||
    pageId === 'all_zalo' ||
    (options?.zalo_pages || []).includes(pageId) ||
    previewRecipients.some((r) => r.is_zalo);

  // Tính mẫu hiển thị xem trước trực tiếp (Live Preview)
  const sampleRecipient = previewRecipients[0] || {
    name: 'Nguyễn Văn An',
    gender: 'male',
    gender_title: 'Anh',
    phone_number: '0987654321',
    page_id: pageId !== 'all' && pageId !== 'all_zalo' && pageId !== 'all_source' ? pageId : 'Eztech Phân Tích Dữ Liệu'
  };

  const sampleRenderedText = template
    .replace(/\{([^{}]*\|[^{}]*)\}/g, (_, group) => group.split('|')[0])
    .replace(/\{name\}/g, sampleRecipient.name || 'anh/chị')
    .replace(/\{gender_title\}/g, sampleRecipient.gender_title || 'Anh')
    .replace(
      /\{gender_title_lower\}/g,
      sampleRecipient.gender === 'male' ? 'anh' : sampleRecipient.gender === 'female' ? 'chị' : 'anh/chị'
    )
    .replace(/\{phone\}/g, sampleRecipient.phone_number || '0987654321')
    .replace(/\{page_id\}/g, sampleRecipient.page_id || 'Page')
    .replace(/\{customer_id\}/g, 'cust_101')
    .replace(/\{staff\}/g, 'Chăm sóc khách hàng');

  return (
    <div className="space-y-6">
      {/* Top Banner Navigation */}
      <div className="bg-white rounded-2xl border border-[#E5E7EB] p-5 shadow-sm flex flex-col lg:flex-row items-start lg:items-center justify-between gap-4">
        <div className="flex items-center gap-3.5">
          <div className="w-11 h-11 rounded-xl bg-gradient-to-tr from-indigo-600 to-blue-500 flex items-center justify-center text-white shadow-md shadow-indigo-100 flex-shrink-0">
            <Bot className="w-6 h-6" />
          </div>
          <div>
            <div className="flex items-center gap-2 flex-wrap">
              <h2 className="text-lg font-bold text-navy">Bot Gửi Tin Nhắn Hàng Loạt</h2>
              <span className="px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider bg-indigo-50 text-indigo-700 border border-indigo-200 rounded-full">
                Pancake API v1
              </span>
              {tokenStatus?.has_token ? (
                <span className="px-2.5 py-0.5 text-[10px] font-bold bg-emerald-50 text-emerald-700 border border-emerald-200 rounded-full flex items-center gap-1">
                  <CheckCircle2 className="w-3 h-3" /> Đã kết nối Token Pancake
                </span>
              ) : (
                <button
                  type="button"
                  onClick={() => setShowTokenModal(true)}
                  className="px-2.5 py-0.5 text-[10px] font-bold bg-amber-50 text-amber-800 border border-amber-300 rounded-full flex items-center gap-1 hover:bg-amber-100 transition-colors"
                >
                  <AlertTriangle className="w-3 h-3 text-amber-600" /> Chưa có Token gửi thật (Bấm để cài)
                </button>
              )}
            </div>
            <p className="text-xs text-[#4B5563] mt-0.5">
              Lọc khách chuẩn xác theo Kênh / Tag / SĐT / Thời gian tương tác, tích hợp chống Rate Limit & bảo vệ Zalo cá nhân.
            </p>
          </div>
        </div>

        {/* Right Actions & Sub-tab Switcher */}
        <div className="flex items-center gap-2.5 w-full lg:w-auto justify-end flex-wrap">
          <button
            type="button"
            onClick={() => setShowTokenModal(true)}
            className={`px-3.5 py-2 rounded-xl text-xs font-semibold flex items-center gap-1.5 border transition-all ${
              tokenStatus?.has_token
                ? 'bg-gray-50 hover:bg-gray-100 text-gray-700 border-gray-200'
                : 'bg-amber-500 hover:bg-amber-600 text-white border-amber-500 shadow-sm'
            }`}
          >
            <Key className="w-3.5 h-3.5" />
            <span>Cấu hình Token</span>
          </button>

          <div className="flex items-center gap-1 bg-gray-100 p-1 rounded-xl">
            <button
              onClick={() => setSubTab('compose')}
              className={`flex items-center justify-center gap-1.5 px-3.5 py-1.5 rounded-lg text-xs font-semibold transition-all ${
                subTab === 'compose' ? 'bg-white text-navy shadow-sm' : 'text-gray-500 hover:text-navy'
              }`}
            >
              <Filter className="w-3.5 h-3.5" />
              <span>Thiết lập & Gửi tin</span>
            </button>

            <button
              onClick={() => {
                setSubTab('history');
                loadHistory(selectedHistoryCampaign);
              }}
              className={`flex items-center justify-center gap-1.5 px-3.5 py-1.5 rounded-lg text-xs font-semibold transition-all ${
                subTab === 'history' ? 'bg-white text-navy shadow-sm' : 'text-gray-500 hover:text-navy'
              }`}
            >
              <History className="w-3.5 h-3.5" />
              <span>Lịch sử chạy Bot</span>
            </button>
          </div>
        </div>
      </div>

      {/* ========================================================================= */}
      {/* THANH TIẾN TRÌNH REAL-TIME NẾU CÓ TÁC VỤ ĐANG CHẠY */}
      {/* ========================================================================= */}
      {taskStatus && (
        <div
          className={`rounded-2xl border p-5 shadow-sm transition-all ${
            taskStatus.is_running
              ? 'bg-indigo-50/60 border-indigo-200'
              : taskStatus.failed > 0 && taskStatus.success === 0
              ? 'bg-rose-50/50 border-rose-200'
              : 'bg-emerald-50/50 border-emerald-200'
          }`}
        >
          <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 mb-3">
            <div className="flex items-center gap-3">
              {taskStatus.is_running ? (
                <RefreshCw className="w-5 h-5 text-indigo-600 animate-spin flex-shrink-0" />
              ) : taskStatus.failed > 0 && taskStatus.success === 0 ? (
                <XCircle className="w-5 h-5 text-rose-600 flex-shrink-0" />
              ) : (
                <CheckCircle2 className="w-5 h-5 text-emerald-600 flex-shrink-0" />
              )}
              <div>
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="text-sm font-bold text-navy">
                    Chiến dịch: {taskStatus.campaign_name}
                  </span>
                  <span
                    className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase ${
                      taskStatus.dry_run
                        ? 'bg-blue-100 text-blue-700'
                        : 'bg-red-100 text-red-700'
                    }`}
                  >
                    {taskStatus.dry_run ? 'Mô phỏng (Dry-Run)' : 'Gửi Thật (Live)'}
                  </span>
                </div>
                <p className="text-xs text-gray-600 mt-0.5">
                  {taskStatus.is_running
                    ? taskStatus.current_recipient || 'Đang xử lý...'
                    : `Đã kết thúc lúc ${taskStatus.finished_at}`}
                </p>
              </div>
            </div>

            <div className="flex items-center gap-4 text-xs">
              <div className="text-center">
                <span className="text-gray-500 block">Tiến độ</span>
                <span className="font-bold text-navy">
                  {taskStatus.processed} / {taskStatus.total}
                </span>
              </div>
              <div className="text-center">
                <span className="text-gray-500 block">Thành công</span>
                <span className="font-bold text-emerald-600">{taskStatus.success}</span>
              </div>
              <div className="text-center">
                <span className="text-gray-500 block">Thất bại</span>
                <span className="font-bold text-red-600">{taskStatus.failed}</span>
              </div>

              {taskStatus.is_running && (
                <button
                  onClick={handleStopBroadcast}
                  className="px-3 py-1.5 bg-red-600 hover:bg-red-700 text-white rounded-lg font-semibold flex items-center gap-1.5 shadow-sm transition-colors"
                >
                  <Square className="w-3.5 h-3.5" />
                  <span>Dừng khẩn cấp</span>
                </button>
              )}
            </div>
          </div>

          {/* Progress Bar */}
          <div className="w-full bg-gray-200 h-2.5 rounded-full overflow-hidden">
            <div
              className={`h-full transition-all duration-300 ${
                taskStatus.dry_run ? 'bg-blue-600' : 'bg-emerald-600'
              }`}
              style={{
                width: `${
                  taskStatus.total > 0
                    ? Math.min(100, Math.round((taskStatus.processed / taskStatus.total) * 100))
                    : 0
                }%`
              }}
            />
          </div>

          {/* Danh sách log vừa chạy */}
          {taskStatus.logs && taskStatus.logs.length > 0 && (
            <div className="mt-3 max-h-44 overflow-y-auto bg-white/90 rounded-xl p-2.5 border border-gray-200 text-[11px] font-mono space-y-1">
              {taskStatus.logs
                .slice()
                .reverse()
                .map((lg, i) => (
                  <div key={i} className="flex items-start justify-between py-1 border-b border-gray-100 last:border-0 gap-2">
                    <span className="text-gray-700">
                      [{lg.time}] #{lg.index} - <strong>{lg.customer_name}</strong> ({lg.phone_number}) -{' '}
                      <span className="text-indigo-600">{lg.page_id}</span>
                    </span>
                    <span
                      className={`font-bold flex-shrink-0 ${
                        lg.status === 'SENT'
                          ? 'text-emerald-600'
                          : lg.status === 'DRY_RUN'
                          ? 'text-blue-600'
                          : 'text-red-600'
                      }`}
                    >
                      {lg.status} {lg.error_message ? `(${lg.error_message})` : ''}
                    </span>
                  </div>
                ))}
            </div>
          )}
        </div>
      )}

      {/* ========================================================================= */}
      {/* SUB-TAB 1: THIẾT LẬP SETTINGS, BỘ LỌC & SOẠN TIN NHẮN */}
      {/* ========================================================================= */}
      {subTab === 'compose' && (
        <div className="space-y-6">
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
            {/* CỘT TRÁI: BỘ LỌC CHI TIẾT & CHỐNG RATE LIMIT ZALO (7 Cột) */}
            <div className="lg:col-span-7 space-y-5">
              {/* KHỐI 1: BỘ LỌC KHÁCH HÀNG */}
              <div className="bg-white rounded-2xl border border-[#E5E7EB] p-5 shadow-sm space-y-4">
                <div className="flex items-center justify-between border-b border-gray-100 pb-3">
                  <div className="flex items-center gap-2">
                    <Filter className="w-4 h-4 text-indigo-600" />
                    <h3 className="text-sm font-bold text-navy">
                      1. Bộ lọc khách hàng chính xác
                    </h3>
                  </div>
                  <button
                    onClick={() => loadOptions(undefined, true)}
                    disabled={loadingOptions}
                    className="text-xs text-blue-600 hover:text-blue-800 flex items-center gap-1"
                  >
                    <RefreshCw className={`w-3 h-3 ${loadingOptions ? 'animate-spin' : ''}`} />
                    <span>Làm mới bộ lọc</span>
                  </button>
                </div>

                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3.5">
                  {/* 1. Tên chiến dịch */}
                  <div>
                    <label className="block text-xs font-semibold text-gray-700 mb-1">
                      Tên chiến dịch (Lưu lịch sử & chống gửi trùng)
                    </label>
                    <input
                      type="text"
                      value={campaignName}
                      onChange={(e) => setCampaignName(e.target.value)}
                      placeholder="VD: chao_uu_dai_thang_10"
                      className="w-full px-3 py-2 bg-gray-50 border border-gray-300 rounded-lg text-xs focus:bg-white focus:ring-2 focus:ring-indigo-500 focus:outline-none transition-all font-mono"
                    />
                  </div>

                  {/* 2. Lọc theo Kênh (Tách rõ Zalo cá nhân & Fanpage nguồn) */}
                  <div>
                    <label className="block text-xs font-semibold text-gray-700 mb-1">
                      Tên Kênh (Fanpage / Zalo cá nhân)
                    </label>
                    <select
                      value={pageId}
                      onChange={(e) => handlePageChange(e.target.value)}
                      className="w-full px-3 py-2 bg-gray-50 border border-gray-300 rounded-lg text-xs focus:bg-white focus:ring-2 focus:ring-indigo-500 focus:outline-none transition-all font-medium"
                    >
                      <option value="all">Tất cả các kênh (Fanpage + Zalo)</option>
                      <option value="all_zalo">Tất cả kênh Zalo cá nhân (3 kênh)</option>
                      <option value="all_source">Tất cả kênh Nguồn Lead (FB & TikTok)</option>
                      {options?.zalo_pages && options.zalo_pages.length > 0 && (
                        <optgroup label="Kênh Zalo Cá Nhân">
                          {options.zalo_pages.map((p) => (
                            <option key={p} value={p}>
                              {p}
                            </option>
                          ))}
                        </optgroup>
                      )}
                      {options?.source_pages && options.source_pages.length > 0 && (
                        <optgroup label="Kênh Nguồn Lead (Facebook / TikTok)">
                          {options.source_pages.map((p) => (
                            <option key={p} value={p}>
                              {p}
                            </option>
                          ))}
                        </optgroup>
                      )}
                    </select>
                  </div>

                  {/* 3. Lọc theo Nhân viên phụ trách */}
                  <div>
                    <div className="flex items-center justify-between mb-1">
                      <label className="block text-xs font-semibold text-gray-700">
                        Nhân viên phụ trách (Sale)
                      </label>
                      {pageId !== 'all' && (
                        <span className="text-[10px] font-medium text-slate-500">
                          {availableEmployees.length} nhân viên
                        </span>
                      )}
                    </div>
                    <select
                      value={employee}
                      onChange={(e) => setEmployee(e.target.value)}
                      className="w-full px-3 py-2 bg-gray-50 border border-gray-300 rounded-lg text-xs focus:bg-white focus:ring-2 focus:ring-indigo-500 focus:outline-none transition-all"
                    >
                      <option value="all">Tất cả nhân viên ({availableEmployees.length})</option>
                      {availableEmployees.map((emp) => (
                        <option key={emp} value={emp}>
                          {emp}
                        </option>
                      ))}
                    </select>
                  </div>

                  {/* 4. Lọc theo Thẻ (Tags - Hỗ trợ chọn nhiều Tag để dễ lọc) */}
                  <div className="relative" ref={tagDropdownRef}>
                    <div className="flex items-center justify-between mb-1">
                      <label className="block text-xs font-semibold text-gray-700">
                        Thẻ phân loại (Tags)
                      </label>
                      <div className="flex items-center gap-1.5">
                        {selectedTags.length > 0 && (
                          <button
                            type="button"
                            onClick={clearTags}
                            className="text-[10px] text-red-500 hover:text-red-700 font-medium"
                          >
                            Bỏ chọn tất cả
                          </button>
                        )}
                        {pageId !== 'all' && (
                          <span className="text-[10px] font-medium text-indigo-600 bg-indigo-50 px-1.5 py-0.5 rounded">
                            Chỉ thẻ thuộc kênh ({availableTags.length})
                          </span>
                        )}
                      </div>
                    </div>

                    <button
                      type="button"
                      onClick={() => setIsTagDropdownOpen(!isTagDropdownOpen)}
                      className={`w-full px-3 py-2 bg-gray-50 border rounded-lg text-xs focus:bg-white focus:ring-2 focus:ring-indigo-500 focus:outline-none transition-all font-medium text-left flex items-center justify-between gap-2 ${
                        selectedTags.length > 0 ? 'border-indigo-400 ring-1 ring-indigo-200 bg-indigo-50/20' : 'border-gray-300'
                      }`}
                    >
                      <div className="flex-1 truncate">
                        {selectedTags.length === 0 ? (
                          <span className="text-gray-600 font-normal">
                            {pageId !== 'all'
                              ? `Tất cả thẻ thuộc kênh (${availableTags.length})`
                              : `Tất cả thẻ (${availableTags.length})`}
                          </span>
                        ) : (
                          <div className="flex items-center gap-1.5 truncate">
                            <span className="font-semibold text-indigo-700 bg-indigo-100 px-1.5 py-0.5 rounded text-[11px] whitespace-nowrap">
                              {selectedTags.length} thẻ đã chọn
                            </span>
                            <span className="text-gray-600 text-[11px] truncate">
                              {selectedTags.map((t) => (t === 'no_tag' ? 'Chưa gắn thẻ' : t)).join(', ')}
                            </span>
                          </div>
                        )}
                      </div>
                      <ChevronDown
                        className={`w-3.5 h-3.5 text-gray-400 flex-shrink-0 transition-transform ${
                          isTagDropdownOpen ? 'rotate-180' : ''
                        }`}
                      />
                    </button>

                    {/* Popover Dropdown Panel */}
                    {isTagDropdownOpen && (
                      <div className="absolute z-30 mt-1 w-full bg-white border border-gray-200 rounded-xl shadow-xl p-2.5 space-y-2">
                        {/* Search box */}
                        <div className="relative">
                          <input
                            type="text"
                            value={tagSearchQuery}
                            onChange={(e) => setTagSearchQuery(e.target.value)}
                            placeholder="Tìm nhanh thẻ..."
                            className="w-full pl-7 pr-7 py-1.5 text-xs bg-gray-50 border border-gray-200 rounded-lg focus:bg-white focus:ring-1 focus:ring-indigo-500 focus:outline-none"
                            autoFocus
                          />
                          <Search className="w-3.5 h-3.5 text-gray-400 absolute left-2 top-2" />
                          {tagSearchQuery && (
                            <button
                              type="button"
                              onClick={() => setTagSearchQuery('')}
                              className="absolute right-2 top-1.5 text-gray-400 hover:text-gray-600 text-xs"
                            >
                              <X className="w-3.5 h-3.5" />
                            </button>
                          )}
                        </div>

                        {/* Quick action bar */}
                        <div className="flex items-center justify-between text-[11px] px-1 text-gray-500 border-b border-gray-100 pb-1.5">
                          <button
                            type="button"
                            onClick={clearTags}
                            className={`hover:text-indigo-600 ${
                              selectedTags.length === 0 ? 'text-indigo-600 font-bold' : ''
                            }`}
                          >
                            Tất cả thẻ (bỏ lọc)
                          </button>
                          {selectedTags.length > 0 && (
                            <span className="text-indigo-600 font-semibold">
                              Đã chọn {selectedTags.length} thẻ
                            </span>
                          )}
                        </div>

                        {/* Tag list */}
                        <div className="max-h-56 overflow-y-auto space-y-0.5 pr-1">
                          {/* Option: no_tag */}
                          {(!tagSearchQuery ||
                            'chưa gắn thẻ không có tag'.includes(tagSearchQuery.toLowerCase())) && (
                            <label
                              className={`flex items-center gap-2 px-2 py-1.5 rounded-lg text-xs cursor-pointer transition-colors ${
                                selectedTags.includes('no_tag')
                                  ? 'bg-indigo-50 text-indigo-700 font-semibold'
                                  : 'hover:bg-gray-50 text-gray-700'
                              }`}
                            >
                              <input
                                type="checkbox"
                                checked={selectedTags.includes('no_tag')}
                                onChange={() => toggleTag('no_tag')}
                                className="rounded text-indigo-600 focus:ring-indigo-500 w-3.5 h-3.5"
                              />
                              <span>Chưa gắn thẻ (Không có tag)</span>
                            </label>
                          )}

                          {/* Available tags */}
                          {filteredAvailableTags.length === 0 ? (
                            <div className="text-center py-3 text-xs text-gray-400">
                              Không tìm thấy thẻ nào khớp từ khóa
                            </div>
                          ) : (
                            filteredAvailableTags.map((t) => {
                              const isChecked = selectedTags.includes(t);
                              return (
                                <label
                                  key={t}
                                  className={`flex items-center gap-2 px-2 py-1.5 rounded-lg text-xs cursor-pointer transition-colors ${
                                    isChecked
                                      ? 'bg-indigo-50 text-indigo-700 font-semibold'
                                      : 'hover:bg-gray-50 text-gray-700'
                                  }`}
                                >
                                  <input
                                    type="checkbox"
                                    checked={isChecked}
                                    onChange={() => toggleTag(t)}
                                    className="rounded text-indigo-600 focus:ring-indigo-500 w-3.5 h-3.5"
                                  />
                                  <span className="flex-1 truncate">{t}</span>
                                </label>
                              );
                            })
                          )}
                        </div>
                      </div>
                    )}

                    {/* Selected Tags Chips */}
                    {selectedTags.length > 0 && (
                      <div className="flex flex-wrap gap-1 mt-1.5 max-h-16 overflow-y-auto">
                        {selectedTags.map((t) => (
                          <span
                            key={t}
                            className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] bg-indigo-50 text-indigo-700 border border-indigo-200 font-medium"
                          >
                            <span className="truncate max-w-[120px]">{t === 'no_tag' ? 'Chưa gắn thẻ' : t}</span>
                            <button
                              type="button"
                              onClick={() => toggleTag(t)}
                              className="hover:text-red-600 font-bold ml-0.5 text-xs leading-none"
                            >
                              &times;
                            </button>
                          </span>
                        ))}
                      </div>
                    )}
                  </div>

                  {/* 5. Thời gian tương tác gần nhất */}
                  <div>
                    <label className="block text-xs font-semibold text-gray-700 mb-1">
                      Thời gian tương tác cuối
                    </label>
                    <select
                      value={timeFilter}
                      onChange={(e) => setTimeFilter(e.target.value)}
                      className="w-full px-3 py-2 bg-gray-50 border border-gray-300 rounded-lg text-xs focus:bg-white focus:ring-2 focus:ring-indigo-500 focus:outline-none transition-all"
                    >
                      <option value="all">Tất cả thời gian (Mặc định - Lấy đầy đủ nhất)</option>
                      <optgroup label="Khách cần chăm sóc lại (Theo mốc Remind)">
                        <option value="remind_1_3">1 – 3 ngày chưa tương tác lại (Remind)</option>
                        <option value="remind_4_7">4 – 7 ngày chưa tương tác lại (Remind)</option>
                        <option value="remind_over_7">Trên 7 ngày chưa tương tác lại (Remind - Khách cũ)</option>
                      </optgroup>
                      <optgroup label="Khách mới tương tác gần đây">
                        <option value="today">Hôm nay (Vừa tương tác trong ngày)</option>
                        <option value="1">Trong 24 giờ qua (An toàn 24h Facebook)</option>
                        <option value="3">Trong 3 ngày qua</option>
                        <option value="7">Trong 7 ngày qua</option>
                        <option value="30">Trong 30 ngày qua</option>
                        <option value="60">Trong 60 ngày qua</option>
                      </optgroup>
                    </select>
                  </div>

                  {/* 6. Lọc Số điện thoại */}
                  <div>
                    <label className="block text-xs font-semibold text-gray-700 mb-1">
                      Tình trạng Số điện thoại
                    </label>
                    <select
                      value={phoneFilter}
                      onChange={(e) => setPhoneFilter(e.target.value)}
                      className="w-full px-3 py-2 bg-gray-50 border border-gray-300 rounded-lg text-xs focus:bg-white focus:ring-2 focus:ring-indigo-500 focus:outline-none transition-all"
                    >
                      <option value="all">Tất cả (Có hoặc chưa có SĐT)</option>
                      <option value="has_phone">Chỉ khách đã có SĐT (hoặc tag Đã add)</option>
                      <option value="no_phone">Chỉ khách chưa có SĐT</option>
                    </select>
                  </div>

                  {/* 7. Lọc theo Giới tính */}
                  <div>
                    <label className="block text-xs font-semibold text-gray-700 mb-1">
                      Giới tính (Tự nhận diện từ tên Tiếng Việt)
                    </label>
                    <select
                      value={gender}
                      onChange={(e) => setGender(e.target.value)}
                      className="w-full px-3 py-2 bg-gray-50 border border-gray-300 rounded-lg text-xs focus:bg-white focus:ring-2 focus:ring-indigo-500 focus:outline-none transition-all"
                    >
                      <option value="all">Tất cả giới tính</option>
                      <option value="female">Nữ (Xưng hô: Chị)</option>
                      <option value="male">Nam (Xưng hô: Anh)</option>
                      <option value="unknown">Chưa rõ (Xưng hô: Anh/Chị)</option>
                    </select>
                  </div>

                  {/* 8. Tìm kiếm theo Tên khách / SĐT */}
                  <div>
                    <label className="block text-xs font-semibold text-gray-700 mb-1">
                      Tìm theo Tên khách hoặc SĐT
                    </label>
                    <input
                      type="text"
                      value={nameFilter}
                      onChange={(e) => setNameFilter(e.target.value)}
                      placeholder="Nhập tên (có/không dấu) hoặc SĐT..."
                      className="w-full px-3 py-2 bg-gray-50 border border-gray-300 rounded-lg text-xs focus:bg-white focus:ring-2 focus:ring-indigo-500 focus:outline-none transition-all"
                    />
                  </div>

                  {/* 9. Giới hạn số lượng */}
                  <div>
                    <label className="block text-xs font-semibold text-gray-700 mb-1">
                      Số lượng lấy tối đa
                    </label>
                    <select
                      value={limit}
                      onChange={(e) => setLimit(Number(e.target.value))}
                      className="w-full px-3 py-2 bg-gray-50 border border-gray-300 rounded-lg text-xs focus:bg-white focus:ring-2 focus:ring-indigo-500 focus:outline-none transition-all"
                    >
                      <option value={10}>10 khách</option>
                      <option value={20}>20 khách</option>
                      <option value={30}>30 khách</option>
                      <option value={50}>50 khách</option>
                      <option value={100}>100 khách</option>
                      <option value={200}>200 khách</option>
                      <option value={500}>500 khách</option>
                      <option value={1000}>1.000 khách</option>
                      <option value={999999}>Tất cả khách khớp lọc (Không giới hạn)</option>
                    </select>
                  </div>

                  {/* 10. Tốc độ gửi cho Fanpage thường */}
                  <div>
                    <label className="block text-xs font-semibold text-gray-700 mb-1 flex items-center justify-between">
                      <span>Nghỉ giữa 2 tin Fanpage (giây)</span>
                      <span className="text-[10px] text-gray-500">FB/TikTok &le; 5 req/s</span>
                    </label>
                    <input
                      type="number"
                      step="0.2"
                      min="0.5"
                      max="10.0"
                      value={delay}
                      onChange={(e) => setDelay(Number(e.target.value))}
                      className="w-full px-3 py-2 bg-gray-50 border border-gray-300 rounded-lg text-xs focus:bg-white focus:ring-2 focus:ring-indigo-500 focus:outline-none transition-all"
                    />
                  </div>
                </div>

                {/* Tùy chọn an toàn & lọc tự động */}
                <div className="pt-2 border-t border-gray-100 flex flex-wrap items-center gap-y-2 gap-x-6">
                  <label className="flex items-center gap-2 cursor-pointer select-none">
                    <input
                      type="checkbox"
                      checked={excludeAlreadySent}
                      onChange={(e) => setExcludeAlreadySent(e.target.checked)}
                      className="rounded text-indigo-600 focus:ring-indigo-500 w-4 h-4"
                    />
                    <span className="text-xs text-gray-700 font-medium">
                      Không gửi lặp lại cho khách đã nhận thành công chiến dịch này (Anti-Spam)
                    </span>
                  </label>

                  <label className="flex items-center gap-2 cursor-pointer select-none">
                    <input
                      type="checkbox"
                      checked={excludeStudents}
                      onChange={(e) => setExcludeStudents(e.target.checked)}
                      className="rounded text-indigo-600 focus:ring-indigo-500 w-4 h-4"
                    />
                    <span className="text-xs text-gray-700 font-medium flex items-center gap-1.5">
                      <span>Bỏ qua tag <strong className="text-indigo-700 font-semibold">"Đã là học viên"</strong></span>
                      <span className="text-[10px] bg-emerald-100 text-emerald-800 font-semibold px-1.5 py-0.5 rounded-full">
                        Auto chọn
                      </span>
                    </span>
                  </label>
                </div>
              </div>

              {/* KHỐI 2: CƠ CHẾ HẠN CHẾ RATE LIMIT & BẢO VỆ ZALO CÁ NHÂN */}
              <div
                className={`rounded-2xl border p-5 shadow-sm space-y-4 transition-all ${
                  zaloProtection
                    ? 'bg-gradient-to-br from-emerald-50/70 via-white to-teal-50/40 border-emerald-200'
                    : 'bg-white border-gray-200'
                }`}
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="flex items-center gap-2.5">
                    <div className="w-9 h-9 rounded-xl bg-emerald-600 text-white flex items-center justify-center shadow-sm flex-shrink-0">
                      <ShieldCheck className="w-5 h-5" />
                    </div>
                    <div>
                      <div className="flex items-center gap-2">
                        <h3 className="text-sm font-bold text-navy">
                          2. Chống Rate Limit &amp; Bảo Vệ Nick Zalo Cá Nhân
                        </h3>
                        {hasZaloInSelection && (
                          <span className="px-2 py-0.5 text-[10px] font-bold bg-emerald-100 text-emerald-800 rounded-full">
                            Đang áp dụng cho Zalo
                          </span>
                        )}
                      </div>
                      <p className="text-[11px] text-gray-600">
                        Giãn cách ngẫu nhiên + nghỉ giải lao theo chặng + đảo từ Spintax để Zalo không chặn gửi tin hoặc khóa tài khoản.
                      </p>
                    </div>
                  </div>

                  <button
                    type="button"
                    onClick={() => setZaloProtection(!zaloProtection)}
                    className={`relative inline-flex h-6 w-11 flex-shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out ${
                      zaloProtection ? 'bg-emerald-600' : 'bg-gray-300'
                    }`}
                  >
                    <span
                      className={`pointer-events-none inline-block h-5 w-5 transform rounded-full bg-white shadow transition duration-200 ease-in-out ${
                        zaloProtection ? 'translate-x-5' : 'translate-x-0'
                      }`}
                    />
                  </button>
                </div>

                {zaloProtection && (
                  <div className="space-y-3.5 pt-2 border-t border-emerald-100">
                    {/* Chọn mức độ bảo vệ nhanh */}
                    <div>
                      <span className="block text-[11px] font-semibold text-gray-700 mb-1.5">
                        Chế độ giãn cách Zalo cá nhân:
                      </span>
                      <div className="grid grid-cols-3 gap-2">
                        {[
                          {
                            id: 'fast',
                            title: 'Nhanh vừa',
                            desc: 'Nghỉ 5-10s/tin, giải lao 30s mỗi 12 tin (<15 khách)'
                          },
                          {
                            id: 'recommended',
                            title: 'Khuyến nghị (An toàn)',
                            desc: 'Nghỉ 8-15s/tin, giải lao 45s mỗi 10 tin'
                          },
                          {
                            id: 'ultra',
                            title: 'Siêu an toàn',
                            desc: 'Nghỉ 15-28s/tin, giải lao 65s mỗi 8 tin (Số lượng lớn)'
                          }
                        ].map((p) => (
                          <button
                            key={p.id}
                            type="button"
                            onClick={() => handleSelectZaloPreset(p.id as any)}
                            className={`p-2.5 rounded-xl border text-left transition-all ${
                              zaloPreset === p.id
                                ? 'bg-emerald-600 text-white border-emerald-600 shadow-sm'
                                : 'bg-white hover:bg-emerald-50/50 text-gray-700 border-gray-200'
                            }`}
                          >
                            <div className="text-xs font-bold">{p.title}</div>
                            <div
                              className={`text-[10px] mt-0.5 leading-tight ${
                                zaloPreset === p.id ? 'text-emerald-50' : 'text-gray-500'
                              }`}
                            >
                              {p.desc}
                            </div>
                          </button>
                        ))}
                      </div>
                    </div>

                    {/* Thông số chi tiết */}
                    <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5">
                      <div>
                        <label className="block text-[11px] font-semibold text-gray-700 mb-1">
                          Nghỉ tối thiểu (s)
                        </label>
                        <input
                          type="number"
                          min={2}
                          max={60}
                          value={zaloMinDelay}
                          onChange={(e) => setZaloMinDelay(Number(e.target.value))}
                          className="w-full px-2.5 py-1.5 bg-white border border-gray-300 rounded-lg text-xs"
                        />
                      </div>
                      <div>
                        <label className="block text-[11px] font-semibold text-gray-700 mb-1">
                          Nghỉ tối đa (s)
                        </label>
                        <input
                          type="number"
                          min={3}
                          max={120}
                          value={zaloMaxDelay}
                          onChange={(e) => setZaloMaxDelay(Number(e.target.value))}
                          className="w-full px-2.5 py-1.5 bg-white border border-gray-300 rounded-lg text-xs"
                        />
                      </div>
                      <div>
                        <label className="block text-[11px] font-semibold text-gray-700 mb-1">
                          Mỗi chặng (số tin)
                        </label>
                        <input
                          type="number"
                          min={3}
                          max={50}
                          value={zaloBatchSize}
                          onChange={(e) => setZaloBatchSize(Number(e.target.value))}
                          className="w-full px-2.5 py-1.5 bg-white border border-gray-300 rounded-lg text-xs"
                        />
                      </div>
                      <div>
                        <label className="block text-[11px] font-semibold text-gray-700 mb-1">
                          Nghỉ giữa chặng (s)
                        </label>
                        <input
                          type="number"
                          min={10}
                          max={300}
                          value={zaloBatchPause}
                          onChange={(e) => setZaloBatchPause(Number(e.target.value))}
                          className="w-full px-2.5 py-1.5 bg-white border border-gray-300 rounded-lg text-xs"
                        />
                      </div>
                    </div>

                    <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 pt-1">
                      <label className="flex items-center gap-2 cursor-pointer">
                        <input
                          type="checkbox"
                          checked={enableSpintax}
                          onChange={(e) => setEnableSpintax(e.target.checked)}
                          className="rounded text-emerald-600 focus:ring-emerald-500 w-3.5 h-3.5"
                        />
                        <span className="text-[11px] text-gray-700 font-medium">
                          Bật Spintax <code className="bg-white px-1 rounded border">{'{Chào|Xin chào}'}</code> &amp; biến thiên chữ ký tin nhắn chống Zalo quét trùng lặp
                        </span>
                      </label>

                      <div className="flex items-center gap-1.5 text-[11px] text-gray-600">
                        <span>Ngắt bảo vệ nếu lỗi liên tiếp:</span>
                        <input
                          type="number"
                          min={2}
                          max={20}
                          value={maxConsecutiveErrors}
                          onChange={(e) => setMaxConsecutiveErrors(Number(e.target.value))}
                          className="w-12 px-1.5 py-0.5 bg-white border border-gray-300 rounded text-xs text-center font-bold"
                        />
                        <span>lần</span>
                      </div>
                    </div>
                  </div>
                )}
              </div>
            </div>

            {/* CỘT PHẢI: SOẠN NỘI DUNG, CHẾ ĐỘ GỬI & LIVE PREVIEW (5 Cột) */}
            <div className="lg:col-span-5 space-y-5">
              <div className="bg-white rounded-2xl border border-[#E5E7EB] p-5 shadow-sm space-y-4">
                <div className="flex items-center justify-between">
                  <h3 className="text-sm font-bold text-navy flex items-center gap-2">
                    <Send className="w-4 h-4 text-indigo-600" />
                    3. Soạn nội dung tin nhắn
                  </h3>
                  <span className="text-[11px] text-gray-400 font-mono">
                    {template.length} ký tự
                  </span>
                </div>

                {/* Danh sách biến động & Spintax chèn nhanh */}
                <div>
                  <p className="text-[11px] font-semibold text-gray-600 mb-1.5">
                    Chèn biến cá nhân hóa &amp; Spintax chống spam:
                  </p>
                  <div className="flex flex-wrap gap-1.5">
                    {[
                      { tag: '{gender_title}', label: 'Anh/Chị' },
                      { tag: '{name}', label: 'Tên khách' },
                      { tag: '{gender_title_lower}', label: 'anh/chị' },
                      { tag: '{phone}', label: 'SĐT' },
                      { tag: '{page_id}', label: 'Tên Kênh' },
                      { tag: '{staff}', label: 'Nhân viên' },
                      { tag: '{Chào|Xin chào|Dạ chào}', label: 'Spintax Chào' },
                      { tag: '{ạ|nhé ạ|nha}', label: 'Spintax Cuối câu' }
                    ].map((b) => (
                      <button
                        key={b.tag}
                        type="button"
                        onClick={() => insertVariable(b.tag)}
                        className="px-2 py-0.5 bg-gray-100 hover:bg-indigo-50 hover:text-indigo-700 text-gray-700 rounded text-[11px] font-mono border border-gray-200 transition-colors"
                      >
                        +{b.label}
                      </button>
                    ))}
                  </div>
                </div>

                <textarea
                  ref={textareaRef}
                  rows={5}
                  value={template}
                  onChange={(e) => setTemplate(e.target.value)}
                  placeholder="Nhập nội dung tin nhắn gửi khách..."
                  className="w-full px-3 py-2 bg-gray-50 border border-gray-300 rounded-xl text-xs focus:bg-white focus:ring-2 focus:ring-indigo-500 focus:outline-none transition-all leading-relaxed"
                />

                {/* Khung mô phỏng Live Preview */}
                <div className="bg-gradient-to-b from-gray-50 to-gray-100 border border-gray-200 rounded-xl p-3.5 space-y-2">
                  <div className="flex items-center justify-between text-[11px] text-gray-500">
                    <span className="flex items-center gap-1 font-semibold text-navy">
                      <Eye className="w-3.5 h-3.5 text-blue-500" />
                      Xem trước hiển thị thực tế:
                    </span>
                    <span className="text-[10px] bg-white px-2 py-0.5 rounded border border-gray-200">
                      Mẫu: {sampleRecipient.name} ({sampleRecipient.gender === 'female' ? 'Nữ' : 'Nam'})
                    </span>
                  </div>

                  <div className="bg-white p-3 rounded-lg border border-gray-200 shadow-sm">
                    <p className="text-xs text-gray-800 whitespace-pre-wrap leading-relaxed">
                      {sampleRenderedText}
                    </p>
                  </div>
                </div>

                {/* Toggle Chế độ Dry-run / Gửi thật */}
                <div
                  className={`p-3 rounded-xl border flex items-center justify-between ${
                    dryRun ? 'bg-blue-50/50 border-blue-200' : 'bg-red-50/60 border-red-200'
                  }`}
                >
                  <div className="flex items-center gap-2.5">
                    {dryRun ? (
                      <Info className="w-4 h-4 text-blue-600 flex-shrink-0" />
                    ) : (
                      <ShieldAlert className="w-4 h-4 text-red-600 flex-shrink-0" />
                    )}
                    <div>
                      <p className={`text-xs font-bold ${dryRun ? 'text-blue-900' : 'text-red-900'}`}>
                        {dryRun ? 'Chế độ Mô phỏng an toàn (DRY-RUN)' : 'CHẾ ĐỘ GỬI THẬT (LIVE)'}
                      </p>
                      <p className="text-[11px] text-gray-600">
                        {dryRun
                          ? 'Chỉ chạy thử nghiệm và ghi log, không gửi tin thật đến khách.'
                          : 'Gửi tin nhắn trực tiếp đến Zalo / Fanpage của khách qua Pancake API.'}
                      </p>
                    </div>
                  </div>

                  <button
                    type="button"
                    onClick={() => setDryRun(!dryRun)}
                    className={`relative inline-flex h-6 w-11 flex-shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none ${
                      dryRun ? 'bg-blue-600' : 'bg-red-600'
                    }`}
                  >
                    <span
                      className={`pointer-events-none inline-block h-5 w-5 transform rounded-full bg-white shadow ring-0 transition duration-200 ease-in-out ${
                        dryRun ? 'translate-x-0' : 'translate-x-5'
                      }`}
                    />
                  </button>
                </div>

                {/* Nút Hành động */}
                <div className="pt-1 flex items-center gap-3">
                  <button
                    type="button"
                    onClick={handlePreview}
                    disabled={loadingPreview}
                    className="flex-1 px-4 py-2.5 bg-indigo-50 hover:bg-indigo-100 text-indigo-900 rounded-xl text-xs font-bold flex items-center justify-center gap-2 transition-all border border-indigo-200"
                  >
                    {loadingPreview ? (
                      <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                    ) : (
                      <Eye className="w-3.5 h-3.5 text-indigo-600" />
                    )}
                    <span>Xem trước khách ({limit})</span>
                  </button>

                  <button
                    type="button"
                    onClick={() => setShowConfirmModal(true)}
                    disabled={isStarting || (taskStatus?.is_running ?? false)}
                    className={`flex-1 px-4 py-2.5 rounded-xl text-xs font-bold text-white flex items-center justify-center gap-2 shadow-sm transition-all ${
                      dryRun
                        ? 'bg-blue-600 hover:bg-blue-700'
                        : 'bg-red-600 hover:bg-red-700'
                    }`}
                  >
                    <Play className="w-3.5 h-3.5" />
                    <span>{dryRun ? 'Chạy Mô Phỏng' : 'Bắt Đầu Gửi Thật'}</span>
                  </button>
                </div>
              </div>
            </div>
          </div>

          {/* BẢNG XEM TRƯỚC DANH SÁCH (PREVIEW TABLE) */}
          {hasPreviewed && (
            <div className="bg-white rounded-2xl border border-[#E5E7EB] p-5 shadow-sm space-y-4">
              <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3">
                <div>
                  <h3 className="text-sm font-bold text-navy flex items-center gap-2 flex-wrap">
                    <Users className="w-4 h-4 text-indigo-600" />
                    <span>
                      Danh sách người nhận ({previewRecipients.length} hiển thị / Tổng {totalMatching} khách khớp lọc)
                    </span>
                    {isCustomListApplied ? (
                      <span className="px-2 py-0.5 text-[10px] font-bold bg-emerald-50 text-emerald-700 border border-emerald-300 rounded-full flex items-center gap-1">
                        <Check className="w-3 h-3 text-emerald-600" /> Danh sách custom đã áp dụng
                      </span>
                    ) : previewRecipients.length !== originalRecipients.length ? (
                      <span className="px-2 py-0.5 text-[10px] font-bold bg-amber-50 text-amber-700 border border-amber-300 rounded-full">
                        Đã loại {originalRecipients.length - previewRecipients.length} khách (Chưa bấm Áp dụng)
                      </span>
                    ) : null}
                  </h3>
                  <p className="text-xs text-[#4B5563] mt-0.5">
                    Tick chọn và bấm &quot;Xóa&quot; hoặc bấm biểu tượng thùng rác ở từng dòng để loại trừ khách không muốn gửi, sau đó bấm &quot;Áp dụng&quot; để tạo danh sách custom.
                  </p>
                </div>

                {/* Toolbar các nút tùy biến danh sách */}
                <div className="flex items-center gap-2 flex-wrap self-end sm:self-auto">
                  {selectedConvIds.size > 0 && (
                    <button
                      type="button"
                      onClick={handleRemoveSelectedRecipients}
                      className="px-3 py-1.5 bg-rose-50 hover:bg-rose-100 text-rose-700 border border-rose-200 rounded-xl text-xs font-semibold flex items-center gap-1.5 transition-colors shadow-sm"
                      title="Xóa các khách đang tick chọn khỏi danh sách gửi"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                      <span>Xóa {selectedConvIds.size} khách</span>
                    </button>
                  )}

                  <button
                    type="button"
                    onClick={handleApplyCustomList}
                    className={`px-3.5 py-1.5 rounded-xl text-xs font-bold flex items-center gap-1.5 shadow-sm transition-all ${
                      isCustomListApplied
                        ? 'bg-emerald-600 text-white hover:bg-emerald-700'
                        : 'bg-indigo-600 hover:bg-indigo-700 text-white'
                    }`}
                    title="Khóa và áp dụng danh sách khách hàng này cho lần gửi bot"
                  >
                    <Check className="w-3.5 h-3.5" />
                    <span>
                      {isCustomListApplied
                        ? `Đã Áp Dụng (${previewRecipients.length} khách)`
                        : `Áp Dụng Danh Sách Custom (${previewRecipients.length})`}
                    </span>
                  </button>

                  {previewRecipients.length !== originalRecipients.length && (
                    <button
                      type="button"
                      onClick={handleRestoreOriginalRecipients}
                      className="px-3 py-1.5 bg-gray-100 hover:bg-gray-200 text-gray-700 rounded-xl text-xs font-semibold flex items-center gap-1.5 transition-colors border border-gray-200"
                      title="Khôi phục lại toàn bộ danh sách ban đầu từ bộ lọc"
                    >
                      <RotateCcw className="w-3.5 h-3.5 text-gray-500" />
                      <span>Khôi phục gốc ({originalRecipients.length})</span>
                    </button>
                  )}
                </div>
              </div>

              {/* Banner thông báo khi danh sách custom được áp dụng */}
              {isCustomListApplied && (
                <div className="bg-emerald-50 border border-emerald-200 rounded-xl p-3 flex flex-col sm:flex-row sm:items-center justify-between gap-2 text-xs text-emerald-900">
                  <div className="flex items-center gap-2">
                    <CheckCircle2 className="w-4 h-4 text-emerald-600 flex-shrink-0" />
                    <span>
                      <strong>Đã áp dụng danh sách custom ({previewRecipients.length} khách):</strong> Hệ thống sẽ gửi tin nhắn đến chính xác {previewRecipients.length} khách hàng này (Đã loại trừ{' '}
                      {originalRecipients.length - previewRecipients.length} khách khỏi danh sách gốc).
                    </span>
                  </div>
                  <button
                    type="button"
                    onClick={() => setShowConfirmModal(true)}
                    className={`px-3 py-1.5 rounded-lg text-xs font-bold text-white flex items-center justify-center gap-1.5 shadow-sm transition-all flex-shrink-0 ${
                      dryRun ? 'bg-blue-600 hover:bg-blue-700' : 'bg-red-600 hover:bg-red-700'
                    }`}
                  >
                    <Play className="w-3 h-3" />
                    <span>
                      {dryRun
                        ? `Mô phỏng ${previewRecipients.length} khách`
                        : `Gửi thật ${previewRecipients.length} khách`}
                    </span>
                  </button>
                </div>
              )}

              {previewRecipients.length === 0 ? (
                <div className="text-center py-10 bg-gray-50 rounded-xl">
                  <AlertTriangle className="w-8 h-8 text-amber-500 mx-auto mb-2" />
                  <p className="text-xs text-gray-600 font-semibold">
                    {originalRecipients.length > 0
                      ? 'Bạn đã xóa hết tất cả khách hàng trong danh sách xem trước.'
                      : 'Không tìm thấy khách hàng nào khớp với các điều kiện lọc trên.'}
                  </p>
                  {originalRecipients.length > 0 ? (
                    <button
                      type="button"
                      onClick={handleRestoreOriginalRecipients}
                      className="mt-3 px-3 py-1.5 bg-indigo-50 hover:bg-indigo-100 text-indigo-700 rounded-lg text-xs font-semibold inline-flex items-center gap-1.5 transition-colors"
                    >
                      <RotateCcw className="w-3.5 h-3.5" />
                      <span>Khôi phục lại {originalRecipients.length} khách ban đầu</span>
                    </button>
                  ) : (
                    <p className="text-[11px] text-gray-400 mt-1">
                      Hãy thử chọn &quot;Mọi thời gian&quot;, chọn &quot;Tất cả các kênh&quot; hoặc bỏ bớt điều kiện lọc.
                    </p>
                  )}
                </div>
              ) : (
                <div className="overflow-x-auto border border-gray-200 rounded-xl">
                  <table className="w-full text-left text-xs">
                    <thead className="bg-gray-50 text-gray-600 border-b border-gray-200">
                      <tr>
                        <th className="py-2.5 px-3 text-center w-10">
                          <input
                            type="checkbox"
                            checked={
                              previewRecipients.length > 0 &&
                              selectedConvIds.size === previewRecipients.length
                            }
                            onChange={handleToggleSelectAll}
                            className="rounded text-indigo-600 focus:ring-indigo-500 w-3.5 h-3.5 cursor-pointer"
                            title="Chọn tất cả / Bỏ chọn tất cả"
                          />
                        </th>
                        <th className="py-2.5 px-2 font-semibold text-center w-12">STT</th>
                        <th className="py-2.5 px-3 font-semibold">Khách hàng</th>
                        <th className="py-2.5 px-3 font-semibold">Giới tính</th>
                        <th className="py-2.5 px-3 font-semibold">Kênh / Page</th>
                        <th className="py-2.5 px-3 font-semibold">Tags &amp; Sale</th>
                        <th className="py-2.5 px-3 font-semibold">Liên hệ cuối</th>
                        <th className="py-2.5 px-3 font-semibold">Nội dung tin nhắn gửi đi</th>
                        <th className="py-2.5 px-3 font-semibold text-center">Pancake</th>
                        <th className="py-2.5 px-3 font-semibold text-center w-14">Xóa</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-100">
                      {previewRecipients.map((r, idx) => {
                        const isSelected = selectedConvIds.has(r.conversation_id);
                        return (
                          <tr
                            key={r.conversation_id}
                            className={`transition-colors ${
                              isSelected ? 'bg-indigo-50/50' : 'hover:bg-blue-50/30'
                            }`}
                          >
                            <td className="py-2 px-3 text-center">
                              <input
                                type="checkbox"
                                checked={isSelected}
                                onChange={() => handleToggleSelectRecipient(r.conversation_id)}
                                className="rounded text-indigo-600 focus:ring-indigo-500 w-3.5 h-3.5 cursor-pointer"
                              />
                            </td>
                            <td className="py-2 px-2 text-gray-400 font-mono text-center">
                              {idx + 1}
                            </td>
                            <td className="py-2 px-3">
                              <span className="font-semibold text-navy">{r.name}</span>
                              {r.phone_number ? (
                                <span className="block text-[11px] text-emerald-700 font-mono">
                                  {r.phone_number}
                                </span>
                              ) : (
                                <span className="block text-[10px] text-gray-400">Chưa có SĐT</span>
                              )}
                            </td>
                            <td className="py-2 px-3">
                              <span
                                className={`px-2 py-0.5 rounded text-[10px] font-semibold ${
                                  r.gender === 'female'
                                    ? 'bg-pink-100 text-pink-700'
                                    : r.gender === 'male'
                                    ? 'bg-blue-100 text-blue-700'
                                    : 'bg-gray-100 text-gray-600'
                                }`}
                              >
                                {r.gender === 'female'
                                  ? 'Nữ (Chị)'
                                  : r.gender === 'male'
                                  ? 'Nam (Anh)'
                                  : 'Chưa rõ'}
                              </span>
                            </td>
                            <td className="py-2 px-3">
                              <div className="flex items-center gap-1.5">
                                <span
                                  className={`px-1.5 py-0.5 rounded text-[9px] font-bold uppercase ${
                                    r.is_zalo
                                      ? 'bg-teal-100 text-teal-800'
                                      : 'bg-indigo-50 text-indigo-700'
                                  }`}
                                >
                                  {r.is_zalo ? 'Zalo' : 'Page'}
                                </span>
                                <span className="text-gray-700 font-medium">{r.page_id}</span>
                              </div>
                            </td>
                            <td className="py-2 px-3">
                              <span className="px-2 py-0.5 bg-gray-100 text-gray-700 rounded text-[10px] block w-fit">
                                {r.status_tag || 'Chưa gắn tag'}
                              </span>
                              {r.assigned_users && (
                                <span className="text-[10px] text-gray-400 block mt-0.5">
                                  NV: {r.assigned_users}
                                </span>
                              )}
                            </td>
                            <td className="py-2 px-3 text-[11px] text-gray-600">
                              {r.days_since_contact !== undefined ? (
                                <span className="font-semibold text-navy">
                                  {r.days_since_contact === 0
                                    ? 'Hôm nay'
                                    : `${r.days_since_contact} ngày trước`}
                                </span>
                              ) : null}
                              {r.last_contacted_at && (
                                <span className="block text-[10px] text-gray-400 font-mono">
                                  {r.last_contacted_at}
                                </span>
                              )}
                            </td>
                            <td
                              className="py-2 px-3 text-gray-800 max-w-xs truncate"
                              title={r.rendered_message}
                            >
                              {r.rendered_message}
                            </td>
                            <td className="py-2 px-3 text-center">
                              {r.pancake_url ? (
                                <a
                                  href={r.pancake_url}
                                  target="_blank"
                                  rel="noreferrer"
                                  className="inline-flex items-center gap-1 text-[11px] text-blue-600 hover:text-blue-800"
                                >
                                  <span>Mở</span>
                                  <ExternalLink className="w-3 h-3" />
                                </a>
                              ) : (
                                <span className="text-gray-300">-</span>
                              )}
                            </td>
                            <td className="py-2 px-3 text-center">
                              <button
                                type="button"
                                onClick={() => handleRemoveSingleRecipient(r.conversation_id)}
                                className="p-1.5 text-gray-400 hover:text-rose-600 hover:bg-rose-50 rounded-lg transition-colors"
                                title="Xóa khách này khỏi danh sách gửi"
                              >
                                <Trash2 className="w-3.5 h-3.5" />
                              </button>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* ========================================================================= */}
      {/* SUB-TAB 2: LỊCH SỬ TỪNG LẦN CHẠY BOT */}
      {/* ========================================================================= */}
      {subTab === 'history' && (
        <div className="space-y-6">
          {/* BẢNG 1: TỔNG HỢP CÁC CHIẾN DỊCH ĐÃ CHẠY */}
          <div className="bg-white rounded-2xl border border-[#E5E7EB] p-5 shadow-sm space-y-4">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
              <div>
                <h3 className="text-sm font-bold text-navy flex items-center gap-2">
                  <History className="w-4 h-4 text-blue-600" />
                  Danh sách chiến dịch đã chạy
                </h3>
                <p className="text-xs text-[#4B5563]">
                  Thống kê kết quả gửi tin theo từng chiến dịch (Tổng số tin, Thành công, Thất bại, Mô phỏng).
                </p>
              </div>
              <div className="flex items-center gap-2">
                <button
                  onClick={handleClearFailedLogs}
                  className="px-3 py-1.5 text-xs text-rose-700 bg-rose-50 hover:bg-rose-100 border border-rose-200 rounded-lg flex items-center gap-1.5 transition-colors font-semibold"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                  <span>Xóa các log lỗi (FAILED)</span>
                </button>
                <button
                  onClick={() => loadHistory(selectedHistoryCampaign)}
                  className="px-3 py-1.5 text-xs text-blue-600 bg-blue-50 hover:bg-blue-100 rounded-lg flex items-center gap-1.5 transition-colors font-semibold"
                >
                  <RefreshCw className={`w-3 h-3 ${loadingHistory ? 'animate-spin' : ''}`} />
                  <span>Làm mới</span>
                </button>
              </div>
            </div>

            {campaignSummaries.length === 0 ? (
              <div className="text-center py-8 bg-gray-50 rounded-xl text-xs text-gray-500">
                Chưa có dữ liệu chiến dịch nào trong lịch sử bot_auto_replies.
              </div>
            ) : (
              <div className="overflow-x-auto border border-gray-200 rounded-xl">
                <table className="w-full text-left text-xs">
                  <thead className="bg-gray-50 text-gray-600 border-b border-gray-200">
                    <tr>
                      <th className="py-2.5 px-3 font-semibold">Tên chiến dịch</th>
                      <th className="py-2.5 px-3 font-semibold">Kênh / Page</th>
                      <th className="py-2.5 px-3 font-semibold text-center">Tổng số tin</th>
                      <th className="py-2.5 px-3 font-semibold text-center">Thành công</th>
                      <th className="py-2.5 px-3 font-semibold text-center">Thất bại</th>
                      <th className="py-2.5 px-3 font-semibold text-center">Mô phỏng (Dry-run)</th>
                      <th className="py-2.5 px-3 font-semibold">Lần gửi cuối</th>
                      <th className="py-2.5 px-3 font-semibold text-center">Trạng thái</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100">
                    {campaignSummaries.map((camp) => (
                      <tr
                        key={camp.campaign_name + camp.page_id}
                        onClick={() => {
                          setSelectedHistoryCampaign(camp.campaign_name);
                          loadHistory(camp.campaign_name);
                        }}
                        className={`cursor-pointer transition-colors ${
                          selectedHistoryCampaign === camp.campaign_name
                            ? 'bg-blue-50/50'
                            : 'hover:bg-gray-50'
                        }`}
                      >
                        <td className="py-2.5 px-3 font-semibold text-navy font-mono">
                          {camp.campaign_name}
                        </td>
                        <td className="py-2.5 px-3 text-gray-600">{camp.page_id || 'Tất cả'}</td>
                        <td className="py-2.5 px-3 text-center font-bold text-gray-800">
                          {camp.total_messages}
                        </td>
                        <td className="py-2.5 px-3 text-center font-bold text-emerald-600">
                          {camp.success_count}
                        </td>
                        <td className="py-2.5 px-3 text-center font-bold text-red-600">
                          {camp.failed_count}
                        </td>
                        <td className="py-2.5 px-3 text-center font-bold text-blue-600">
                          {camp.dry_run_count}
                        </td>
                        <td className="py-2.5 px-3 text-gray-500 font-mono text-[11px]">
                          {camp.last_sent_at}
                        </td>
                        <td className="py-2.5 px-3 text-center">
                          <span
                            className={`px-2 py-0.5 rounded-full text-[10px] font-bold ${
                              camp.status === 'COMPLETED'
                                ? 'bg-emerald-100 text-emerald-700'
                                : camp.status === 'DRY_RUN'
                                ? 'bg-blue-100 text-blue-700'
                                : camp.status === 'FAILED'
                                ? 'bg-red-100 text-red-700'
                                : 'bg-amber-100 text-amber-700'
                            }`}
                          >
                            {camp.status}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {/* BẢNG 2: CHI TIẾT LOG TỪNG TIN NHẮN ĐÃ GỬI */}
          <div className="bg-white rounded-2xl border border-[#E5E7EB] p-5 shadow-sm space-y-4">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
              <div>
                <h3 className="text-sm font-bold text-navy">
                  Chi tiết lịch sử từng tin nhắn
                </h3>
                <p className="text-xs text-[#4B5563]">
                  Đang lọc theo chiến dịch:{' '}
                  <span className="font-mono font-semibold text-indigo-600">
                    {selectedHistoryCampaign === 'all' ? 'Tất cả chiến dịch' : selectedHistoryCampaign}
                  </span>
                </p>
              </div>

              {selectedHistoryCampaign !== 'all' && (
                <button
                  onClick={() => {
                    setSelectedHistoryCampaign('all');
                    loadHistory('all');
                  }}
                  className="text-xs text-gray-600 hover:text-navy underline"
                >
                  Xem tất cả chiến dịch
                </button>
              )}
            </div>

            {historyLogs.length === 0 ? (
              <div className="text-center py-8 bg-gray-50 rounded-xl text-xs text-gray-500">
                Không có bản ghi lịch sử nào.
              </div>
            ) : (
              <div className="overflow-x-auto border border-gray-200 rounded-xl">
                <table className="w-full text-left text-xs">
                  <thead className="bg-gray-50 text-gray-600 border-b border-gray-200">
                    <tr>
                      <th className="py-2.5 px-3 font-semibold">Thời gian</th>
                      <th className="py-2.5 px-3 font-semibold">Chiến dịch</th>
                      <th className="py-2.5 px-3 font-semibold">Khách hàng</th>
                      <th className="py-2.5 px-3 font-semibold">Kênh</th>
                      <th className="py-2.5 px-3 font-semibold">Nội dung đã gửi</th>
                      <th className="py-2.5 px-3 font-semibold text-center">Trạng thái</th>
                      <th className="py-2.5 px-3 font-semibold text-center">Hội thoại</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100">
                    {historyLogs.map((log) => (
                      <tr key={log.id} className="hover:bg-gray-50 transition-colors">
                        <td className="py-2 px-3 text-gray-500 font-mono text-[11px] whitespace-nowrap">
                          {log.sent_at}
                        </td>
                        <td className="py-2 px-3 font-mono font-medium text-navy">
                          {log.campaign_name}
                        </td>
                        <td className="py-2 px-3">
                          <span className="font-semibold text-gray-800">{log.customer_name}</span>
                          {log.phone_number && (
                            <span className="block text-[10px] text-gray-500">{log.phone_number}</span>
                          )}
                        </td>
                        <td className="py-2 px-3 text-gray-600">{log.page_id}</td>
                        <td className="py-2 px-3 text-gray-700 max-w-md">
                          <div className="truncate" title={log.message}>
                            {log.message}
                          </div>
                          {log.error_message && (
                            <div className="text-[10px] text-rose-600 font-mono mt-0.5">
                              Lỗi: {log.error_message}
                            </div>
                          )}
                        </td>
                        <td className="py-2 px-3 text-center">
                          <span
                            className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                              log.status === 'SENT'
                                ? 'bg-emerald-100 text-emerald-700'
                                : log.status === 'DRY_RUN'
                                ? 'bg-blue-100 text-blue-700'
                                : 'bg-red-100 text-red-700'
                            }`}
                          >
                            {log.status}
                          </span>
                        </td>
                        <td className="py-2 px-3 text-center">
                          {log.pancake_url ? (
                            <a
                              href={log.pancake_url}
                              target="_blank"
                              rel="noreferrer"
                              className="text-blue-600 hover:text-blue-800 inline-flex items-center gap-1 text-[11px]"
                            >
                              <span>Mở</span>
                              <ExternalLink className="w-3 h-3" />
                            </a>
                          ) : (
                            <span className="text-gray-300">-</span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      )}

      {/* ========================================================================= */}
      {/* MODAL CẤU HÌNH TOKEN PANCAKE */}
      {/* ========================================================================= */}
      {showTokenModal && (
        <div className="fixed inset-0 z-50 bg-black/50 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-white rounded-2xl max-w-lg w-full p-6 shadow-2xl border border-gray-200 space-y-4 max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between border-b border-gray-100 pb-3">
              <div className="flex items-center gap-2.5">
                <div className="w-9 h-9 rounded-xl bg-amber-100 text-amber-700 flex items-center justify-center">
                  <Key className="w-5 h-5" />
                </div>
                <div>
                  <h3 className="text-base font-bold text-navy">Cấu hình Pancake API Token</h3>
                  <p className="text-xs text-gray-500">
                    Lưu trữ an toàn trong Database để gửi tin nhắn thật từ Web
                  </p>
                </div>
              </div>
              <button
                type="button"
                onClick={() => setShowTokenModal(false)}
                className="text-gray-400 hover:text-gray-600 text-sm font-bold"
              >
                ✕
              </button>
            </div>

            {/* Trạng thái các kênh hiện tại */}
            {tokenStatus && (
              <div className="bg-gray-50 rounded-xl p-3 border border-gray-200 space-y-1.5">
                <p className="text-[11px] font-bold text-gray-700 mb-1">
                  Trạng thái Token theo từng kênh hiện tại:
                </p>
                <div className="grid grid-cols-1 gap-1 max-h-36 overflow-y-auto">
                  {tokenStatus.channels.map((ch) => (
                    <div
                      key={ch.page_name}
                      className="flex items-center justify-between text-[11px] bg-white px-2.5 py-1.5 rounded border border-gray-100"
                    >
                      <span className="font-medium text-navy">
                        <span className="text-[10px] font-semibold text-gray-500 mr-1.5">[{ch.is_zalo ? 'Zalo' : 'Nguồn'}]</span>
                        {ch.page_name}{' '}
                        <span className="text-[10px] text-gray-400 font-mono">
                          ({ch.api_page_id})
                        </span>
                      </span>
                      {ch.has_token ? (
                        <span className="text-emerald-600 font-bold text-[10px]">
                          ✓ Đã có ({ch.masked_token})
                        </span>
                      ) : (
                        <span className="text-rose-600 font-semibold text-[10px]">
                          ✗ Chưa có Token
                        </span>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}

            <div className="space-y-3">
              <div>
                <label className="block text-xs font-semibold text-gray-700 mb-1">
                  Cách 1: Nhập Pancake Token chung (User Access Token hoặc Page Access Token)
                </label>
                <input
                  type="password"
                  value={tokenInput}
                  onChange={(e) => setTokenInput(e.target.value)}
                  placeholder="Dán PANCAKE_API_TOKEN của bạn vào đây..."
                  className="w-full px-3 py-2 bg-gray-50 border border-gray-300 rounded-xl text-xs font-mono focus:bg-white focus:ring-2 focus:ring-indigo-500 focus:outline-none"
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-gray-700 mb-1">
                  Cách 2 (Tùy chọn): Dán cấu hình JSON nhiều Page (PANCAKE_PAGES_JSON)
                </label>
                <textarea
                  rows={3}
                  value={pagesJsonInput}
                  onChange={(e) => setPagesJsonInput(e.target.value)}
                  placeholder='VD: {"pzl_629476615535063343": "token_1", "514400205095512": "token_2"}'
                  className="w-full px-3 py-2 bg-gray-50 border border-gray-300 rounded-xl text-xs font-mono focus:bg-white focus:ring-2 focus:ring-indigo-500 focus:outline-none"
                />
              </div>
            </div>

            <div className="flex items-center justify-end gap-2.5 pt-2">
              <button
                type="button"
                onClick={() => setShowTokenModal(false)}
                className="px-4 py-2 bg-gray-100 hover:bg-gray-200 text-gray-700 rounded-xl text-xs font-semibold"
              >
                Đóng
              </button>
              <button
                type="button"
                onClick={handleSaveTokenConfig}
                disabled={savingToken}
                className="px-4 py-2 bg-indigo-600 hover:bg-indigo-700 text-white rounded-xl text-xs font-bold shadow-sm"
              >
                {savingToken ? 'Đang lưu...' : 'Lưu Token vào Hệ thống'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ========================================================================= */}
      {/* MODAL XÁC NHẬN AN TOÀN TRƯỚC KHI BẮT ĐẦU */}
      {/* ========================================================================= */}
      {showConfirmModal && (
        <div className="fixed inset-0 z-50 bg-black/50 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-white rounded-2xl max-w-md w-full p-6 shadow-2xl border border-gray-200 space-y-4">
            <div className="flex items-center gap-3">
              <div
                className={`w-10 h-10 rounded-full flex items-center justify-center ${
                  dryRun ? 'bg-blue-100 text-blue-600' : 'bg-red-100 text-red-600'
                }`}
              >
                {dryRun ? <Play className="w-5 h-5" /> : <ShieldAlert className="w-5 h-5" />}
              </div>
              <div>
                <h3 className="text-base font-bold text-navy">
                  {dryRun ? 'Xác nhận Chạy Mô Phỏng (Dry-run)' : 'CẢNH BÁO: XÁC NHẬN GỬI THẬT'}
                </h3>
                <p className="text-xs text-gray-500">
                  Chiến dịch: <span className="font-mono font-semibold">{campaignName}</span>
                </p>
              </div>
            </div>

            <div className="bg-gray-50 p-3.5 rounded-xl text-xs space-y-2 border border-gray-200">
              <div className="flex justify-between">
                <span className="text-gray-500">Kênh gửi:</span>
                <span className="font-semibold text-gray-800">
                  {pageId === 'all'
                    ? 'Tất cả các kênh'
                    : pageId === 'all_zalo'
                    ? 'Tất cả kênh Zalo cá nhân'
                    : pageId === 'all_source'
                    ? 'Tất cả kênh Nguồn Lead'
                    : pageId}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-500">Đối tượng gửi:</span>
                <span className="font-semibold text-gray-800">
                  {isCustomListApplied ||
                  (hasPreviewed &&
                    previewRecipients.length > 0 &&
                    previewRecipients.length !== originalRecipients.length)
                    ? `Danh sách Custom (${previewRecipients.length} khách đã chọn)`
                    : `${hasPreviewed ? previewRecipients.length : limit} khách hàng`}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-500">Bảo vệ Zalo cá nhân:</span>
                <span className="font-semibold text-emerald-700">
                  {zaloProtection
                    ? `Bật (Nghỉ ${zaloMinDelay}-${zaloMaxDelay}s, giải lao ${zaloBatchPause}s mỗi ${zaloBatchSize} tin)`
                    : `Tắt (${delay}s/tin)`}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-500">Chế độ:</span>
                <span className={`font-bold ${dryRun ? 'text-blue-600' : 'text-red-600'}`}>
                  {dryRun ? 'Mô phỏng (Không gọi API thật)' : 'GỬI THẬT ĐẾN KHÁCH HÀNG'}
                </span>
              </div>
            </div>

            <div className="flex items-center justify-end gap-3 pt-2">
              <button
                type="button"
                onClick={() => setShowConfirmModal(false)}
                className="px-4 py-2 bg-gray-100 hover:bg-gray-200 text-gray-700 rounded-xl text-xs font-semibold transition-colors"
              >
                Hủy bỏ
              </button>
              <button
                type="button"
                onClick={handleStartBroadcast}
                className={`px-5 py-2 text-white rounded-xl text-xs font-bold shadow-sm transition-all ${
                  dryRun ? 'bg-blue-600 hover:bg-blue-700' : 'bg-red-600 hover:bg-red-700'
                }`}
              >
                {dryRun ? 'Bắt đầu mô phỏng' : 'Tôi đồng ý gửi thật'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
