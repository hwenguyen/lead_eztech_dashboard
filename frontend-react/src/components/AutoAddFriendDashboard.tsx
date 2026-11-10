import React, { useState, useEffect, useRef, useMemo } from 'react';
import {
  UserPlus,
  Upload,
  Play,
  Square,
  ShieldCheck,
  ShieldAlert,
  Tag,
  MessageSquare,
  FileSpreadsheet,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  RefreshCw,
  Trash2,
  Key,
  Sparkles,
  History,
  Download,
  Check,
  Plus,
  Info,
  Database,
  Copy,
  X
} from 'lucide-react';
import {
  fetchAddFriendConfig,
  fetchPancakeStateRaw,
  savePancakeStateJson,
  deletePancakeState,
  parseBulkPhones,
  fetchLeadsWithPhonesForAddFriend,
  startAddFriendCampaign,
  fetchAddFriendStatus,
  stopAddFriendCampaign,
  fetchAddFriendHistory,
  type AddFriendConfigResponse,
  type PhoneImportItem,
  type RateLimitSettings,
  type AddFriendTaskStatus,
  type AddFriendHistoryItem
} from '../services/api';

const SAMPLE_BULK_TEXT = `0987654321\tNguyễn Văn An\tcontact-page\tTư vấn khóa học Data Finance
84912345678\tTrần Thị Bích\tqua-tang-file-aio\tNhận bộ file AIO miễn phí
0905112233\tLê Hoàng Nam\treport:quan-tri-pl\tBáo cáo Quản trị P&L
938776655\tPhạm Minh Tuấn\tcourse:data-business\tKhóa học Data in Business
0977889900\tVũ Thị Hương\tLanding khóa AI cho Kế toán\tKhóa AI cho Kế toán`;

export const AutoAddFriendDashboard: React.FC = () => {
  // Sub-tabs: 'workspace' | 'history'
  const [subTab, setSubTab] = useState<'workspace' | 'history'>('workspace');

  // Config from Backend
  const [config, setConfig] = useState<AddFriendConfigResponse | null>(null);

  // Pancake State Modal (`pancake_state.json`)
  const [showStateModal, setShowStateModal] = useState<boolean>(false);
  const [stateJsonInput, setStateJsonInput] = useState<string>('');
  const [savingState, setSavingState] = useState<boolean>(false);
  const [loadingRawState, setLoadingRawState] = useState<boolean>(false);
  const [copiedState, setCopiedState] = useState<boolean>(false);
  const [stateFeedback, setStateFeedback] = useState<{ type: 'success' | 'error'; text: string } | null>(null);

  // Step 1: Bulk Phone Import State
  const [rawPhoneText, setRawPhoneText] = useState<string>(SAMPLE_BULK_TEXT);
  const [phoneInputError, setPhoneInputError] = useState<string | null>(null);
  const [skipSourcesInput, setSkipSourcesInput] = useState<string>('ezexcel-dung-thu, test-case-123');
  const [loadingLeadsPhones, setLoadingLeadsPhones] = useState<boolean>(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Step 2: Page, Greeting Message, Note & Tag Settings
  const [campaignName, setCampaignName] = useState<string>(
    `addfriend_${new Date().toISOString().slice(0, 10).replace(/-/g, '')}`
  );
  const [selectedPage, setSelectedPage] = useState<string>('Eztech Consultant');
  const [customPageInput, setCustomPageInput] = useState<string>('');
  const [selectedTemplateKey, setSelectedTemplateKey] = useState<string>('default');
  const [messageTemplate, setMessageTemplate] = useState<string>(
    'Chào bạn, mình là {page}. Mình xin phép kết bạn để trao đổi chi tiết hơn về dịch vụ bên mình nhé ạ!'
  );
  const [useSourceTemplate, setUseSourceTemplate] = useState<boolean>(true);
  const [sendInboxMessage, setSendInboxMessage] = useState<boolean>(true);
  const [addNote, setAddNote] = useState<boolean>(true);
  const [noteTemplate, setNoteTemplate] = useState<string>('Nguồn: {source} | Nhu cầu: {nhu_cau}');
  const [selectedTags, setSelectedTags] = useState<string[]>(['Web']);
  const [customTagInput, setCustomTagInput] = useState<string>('');
  const messageTextareaRef = useRef<HTMLTextAreaElement>(null);

  // Step 3: Anti-Rate-Limit Settings
  const [rateLimit, setRateLimit] = useState<RateLimitSettings>({
    preset: 'recommended',
    delay_min: 8,
    delay_max: 16,
    batch_size: 10,
    batch_pause_sec: 45,
    max_retries: 2,
    max_consecutive_errors: 3,
    daily_limit: 50,
    enable_spintax: true,
    exclude_already_added: true
  });
  const [dryRun, setDryRun] = useState<boolean>(true);

  // Step 4: Parsed Preview & Selection State
  const [parsedItems, setParsedItems] = useState<PhoneImportItem[]>([]);
  const [selectedPhones, setSelectedPhones] = useState<Set<string>>(new Set());
  const [parseStats, setParseStats] = useState<{
    total_lines: number;
    valid_count: number;
    invalid_count: number;
    duplicate_count: number;
    skipped_source_count: number;
    already_added_count: number;
    ready_count: number;
  } | null>(null);
  const [parsing, setParsing] = useState<boolean>(false);

  // Active Task Execution & Polling
  const [activeTaskId, setActiveTaskId] = useState<string | null>(null);
  const [taskStatus, setTaskStatus] = useState<AddFriendTaskStatus | null>(null);
  const [startingCampaign, setStartingCampaign] = useState<boolean>(false);
  const [actionBanner, setActionBanner] = useState<{ type: 'error' | 'info' | 'success'; text: string } | null>(null);

  // History State
  const [historyItems, setHistoryItems] = useState<AddFriendHistoryItem[]>([]);
  const [loadingHistory, setLoadingHistory] = useState<boolean>(false);

  const effectivePageName = useMemo(() => {
    return (customPageInput.trim() || selectedPage || 'Eztech Consultant').trim();
  }, [customPageInput, selectedPage]);

  // Load initial config
  const loadConfig = async () => {
    try {
      const data = await fetchAddFriendConfig();
      setConfig(data);
      if (data.skip_sources && data.skip_sources.length > 0) {
        setSkipSourcesInput(data.skip_sources.join(', '));
      }
    } catch (err) {
      console.error('Không thể tải cấu hình Kết bạn tự động:', err);
    }
  };

  useEffect(() => {
    loadConfig();
  }, []);

  // Auto-parse initial sample phones once config is ready
  useEffect(() => {
    if (rawPhoneText.trim()) {
      handleParsePhones();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Poll active task status
  useEffect(() => {
    if (!activeTaskId) return;
    let timer: ReturnType<typeof setInterval> | null = null;

    const poll = async () => {
      try {
        const st = await fetchAddFriendStatus(activeTaskId);
        setTaskStatus(st);
        if (!st.is_running && timer) {
          clearInterval(timer);
        }
      } catch (err) {
        console.error('Lỗi khi lấy trạng thái tiến trình kết bạn:', err);
      }
    };

    poll();
    timer = setInterval(poll, 1500);
    return () => {
      if (timer) clearInterval(timer);
    };
  }, [activeTaskId]);

  // Load history when switching to history tab
  const loadHistory = async () => {
    setLoadingHistory(true);
    try {
      const res = await fetchAddFriendHistory(150);
      setHistoryItems(res.items || []);
    } catch (err) {
      console.error('Lỗi tải lịch sử kết bạn:', err);
    } finally {
      setLoadingHistory(false);
    }
  };

  useEffect(() => {
    if (subTab === 'history') {
      loadHistory();
    }
  }, [subTab]);

  // Apply Rate Limit Preset
  const handleApplyPreset = (preset: 'fast' | 'recommended' | 'ultra') => {
    if (preset === 'fast') {
      setRateLimit((prev) => ({
        ...prev,
        preset: 'fast',
        delay_min: 5,
        delay_max: 10,
        batch_size: 15,
        batch_pause_sec: 30,
        max_retries: 2,
        max_consecutive_errors: 4
      }));
    } else if (preset === 'recommended') {
      setRateLimit((prev) => ({
        ...prev,
        preset: 'recommended',
        delay_min: 8,
        delay_max: 16,
        batch_size: 10,
        batch_pause_sec: 45,
        max_retries: 2,
        max_consecutive_errors: 3
      }));
    } else {
      setRateLimit((prev) => ({
        ...prev,
        preset: 'ultra',
        delay_min: 18,
        delay_max: 32,
        batch_size: 8,
        batch_pause_sec: 90,
        max_retries: 3,
        max_consecutive_errors: 2
      }));
    }
  };

  // Parse & normalize phones
  const handleParsePhones = async (overrideText?: string) => {
    const textToParse = overrideText !== undefined ? overrideText : rawPhoneText;
    if (!textToParse.trim()) {
      setPhoneInputError('Vui lòng nhập hoặc dán ít nhất 1 số điện thoại.');
      setParsedItems([]);
      setParseStats(null);
      return;
    }
    setPhoneInputError(null);
    setParsing(true);
    try {
      const skipList = skipSourcesInput
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean);

      const res = await parseBulkPhones({
        raw_text: textToParse,
        page_name: effectivePageName,
        message_template: messageTemplate,
        note_template: noteTemplate,
        use_source_template: useSourceTemplate,
        enable_spintax: rateLimit.enable_spintax,
        skip_sources: skipList,
        exclude_already_added: rateLimit.exclude_already_added
      });

      setParsedItems(res.items);
      setParseStats({
        total_lines: res.total_lines,
        valid_count: res.valid_count,
        invalid_count: res.invalid_count,
        duplicate_count: res.duplicate_count,
        skipped_source_count: res.skipped_source_count,
        already_added_count: res.already_added_count,
        ready_count: res.ready_count
      });

      // Mặc định chọn tất cả các dòng hợp lệ (không trùng, không thuộc nguồn skip, chưa add)
      const readySet = new Set<string>();
      res.items.forEach((item) => {
        if (item.is_valid && !item.is_duplicate && !item.is_skipped_source && !item.already_added) {
          readySet.add(item.phone);
        }
      });
      setSelectedPhones(readySet);
    } catch (err: any) {
      setActionBanner({
        type: 'error',
        text: err?.response?.data?.detail || 'Không thể phân tích danh sách số điện thoại.'
      });
    } finally {
      setParsing(false);
    }
  };

  // Upload CSV / TXT file
  const handleFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (ev) => {
      const content = String(ev.target?.result || '');
      setRawPhoneText(content);
      setPhoneInputError(null);
      handleParsePhones(content);
    };
    reader.readAsText(file, 'utf-8');
    e.target.value = '';
  };

  // Pull leads with phones from DB
  const handlePullLeadsPhones = async (channel: 'all' | 'tiktok' | 'facebook') => {
    setLoadingLeadsPhones(true);
    setActionBanner(null);
    try {
      const res = await fetchLeadsWithPhonesForAddFriend(channel, 50);
      if (!res.formatted_text || res.count === 0) {
        setActionBanner({
          type: 'info',
          text: 'Không tìm thấy SĐT mới nào chưa kết bạn trong kênh này.'
        });
        return;
      }
      setRawPhoneText(res.formatted_text);
      setPhoneInputError(null);
      await handleParsePhones(res.formatted_text);
      setActionBanner({
        type: 'success',
        text: `Đã nạp ${res.count} số điện thoại khách hàng từ hệ thống Leads!`
      });
    } catch (err: any) {
      setActionBanner({
        type: 'error',
        text: err?.response?.data?.detail || 'Không thể tải SĐT từ kho Leads.'
      });
    } finally {
      setLoadingLeadsPhones(false);
    }
  };

  // Insert placeholder into greeting message
  const handleInsertVariable = (variable: string) => {
    const el = messageTextareaRef.current;
    if (!el) {
      setMessageTemplate((prev) => `${prev} ${variable}`);
      return;
    }
    const start = el.selectionStart || 0;
    const end = el.selectionEnd || 0;
    const next = messageTemplate.slice(0, start) + variable + messageTemplate.slice(end);
    setMessageTemplate(next);
    setTimeout(() => {
      el.focus();
      el.setSelectionRange(start + variable.length, start + variable.length);
    }, 10);
  };

  // Toggle tag selection
  const handleToggleTag = (tag: string) => {
    setSelectedTags((prev) =>
      prev.includes(tag) ? prev.filter((t) => t !== tag) : [...prev, tag]
    );
  };

  // Add custom tag
  const handleAddCustomTag = () => {
    const clean = customTagInput.trim();
    if (!clean) return;
    if (!selectedTags.includes(clean)) {
      setSelectedTags((prev) => [...prev, clean]);
    }
    setCustomTagInput('');
  };

  // Toggle single phone row
  const handleToggleSelectPhone = (phone: string) => {
    setSelectedPhones((prev) => {
      const next = new Set(prev);
      if (next.has(phone)) {
        next.delete(phone);
      } else {
        next.add(phone);
      }
      return next;
    });
  };

  // Remove row from preview
  const handleRemovePreviewItem = (indexToRemove: number, phone: string) => {
    setParsedItems((prev) => prev.filter((_, idx) => idx !== indexToRemove));
    setSelectedPhones((prev) => {
      const next = new Set(prev);
      next.delete(phone);
      return next;
    });
  };

  // Mở Modal cấu hình & tự động nạp state hiện tại từ Database
  const handleOpenStateModal = async () => {
    setShowStateModal(true);
    setStateFeedback(null);
    setCopiedState(false);
    if (!stateJsonInput.trim()) {
      setLoadingRawState(true);
      try {
        const res = await fetchPancakeStateRaw();
        if (res.state_json) {
          setStateJsonInput(res.state_json);
        }
      } catch (err) {
        // ignore
      } finally {
        setLoadingRawState(false);
      }
    }
  };

  // Tải file pancake_state.json về máy tính
  const handleDownloadStateJson = () => {
    if (!stateJsonInput.trim()) return;
    const blob = new Blob([stateJsonInput], { type: 'application/json;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'pancake_state.json';
    a.click();
    URL.revokeObjectURL(url);
  };

  // Sao chép JSON vào Clipboard
  const handleCopyStateJson = async () => {
    if (!stateJsonInput.trim()) return;
    try {
      await navigator.clipboard.writeText(stateJsonInput);
      setCopiedState(true);
      setTimeout(() => setCopiedState(false), 2000);
    } catch (e) {
      // fallback
    }
  };

  // Xóa cấu hình phiên đăng nhập khỏi bảng app_configs
  const handleDeletePancakeState = async () => {
    if (!window.confirm('Bạn có chắc chắn muốn xóa phiên đăng nhập Pancake khỏi Database?')) return;
    setSavingState(true);
    setStateFeedback(null);
    try {
      const res = await deletePancakeState();
      setConfig((prev) => (prev ? { ...prev, state_info: res.state_info } : prev));
      setStateJsonInput('');
      setStateFeedback({ type: 'success', text: res.message });
    } catch (err: any) {
      setStateFeedback({
        type: 'error',
        text: err?.response?.data?.detail || 'Không thể xóa phiên đăng nhập.'
      });
    } finally {
      setSavingState(false);
    }
  };

  // Save pancake_state.json vào bảng app_configs
  const handleSavePancakeState = async () => {
    if (!stateJsonInput.trim()) {
      setStateFeedback({ type: 'error', text: 'Vui lòng dán nội dung JSON của file pancake_state.json.' });
      return;
    }
    setSavingState(true);
    setStateFeedback(null);
    try {
      const res = await savePancakeStateJson(stateJsonInput);
      setConfig((prev) => (prev ? { ...prev, state_info: res.state_info } : prev));
      setStateFeedback({ type: 'success', text: res.message });
      setTimeout(() => {
        setShowStateModal(false);
        setStateFeedback(null);
      }, 1200);
    } catch (err: any) {
      setStateFeedback({
        type: 'error',
        text: err?.response?.data?.detail || 'JSON không hợp lệ hoặc không thể lưu phiên đăng nhập.'
      });
    } finally {
      setSavingState(false);
    }
  };

  // Upload pancake_state.json file into modal
  const handleStateFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (ev) => {
      setStateJsonInput(String(ev.target?.result || ''));
      setStateFeedback(null);
    };
    reader.readAsText(file, 'utf-8');
    e.target.value = '';
  };

  // Start campaign
  const handleStartCampaign = async () => {
    setActionBanner(null);

    const targets = parsedItems
      .filter((item) => item.is_valid && !item.is_duplicate && selectedPhones.has(item.phone))
      .map((item) => ({
        phone: item.phone,
        name: item.name,
        source: item.source,
        nhu_cau: item.nhu_cau,
        custom_message: item.rendered_message,
        custom_note: item.rendered_note
      }));

    if (targets.length === 0) {
      setActionBanner({
        type: 'error',
        text: 'Chưa có số điện thoại hợp lệ nào được chọn để kết bạn. Vui lòng kiểm tra lại danh sách!'
      });
      return;
    }

    if (!dryRun && !config?.state_info?.has_state) {
      setShowStateModal(true);
      setActionBanner({
        type: 'error',
        text: 'Để chạy thật (Live), vui lòng cấu hình phiên đăng nhập pancake_state.json trước!'
      });
      return;
    }

    setStartingCampaign(true);
    try {
      const res = await startAddFriendCampaign({
        campaign_name: campaignName.trim() || `addfriend_${Date.now()}`,
        page_name: effectivePageName,
        items: targets,
        message_template: messageTemplate,
        inbox_message_template: messageTemplate,
        use_source_template: useSourceTemplate,
        send_inbox_message: sendInboxMessage,
        add_note: addNote,
        note_template: noteTemplate,
        tags: selectedTags,
        rate_limit: rateLimit,
        dry_run: dryRun
      });

      setActiveTaskId(res.task_id);
      setActionBanner({
        type: 'success',
        text: `Đã khởi chạy chiến dịch "${res.campaign_name}" cho ${res.total} số điện thoại!`
      });
    } catch (err: any) {
      setActionBanner({
        type: 'error',
        text: err?.response?.data?.detail || 'Không thể khởi động chiến dịch kết bạn tự động.'
      });
    } finally {
      setStartingCampaign(false);
    }
  };

  // Stop running campaign
  const handleStopCampaign = async () => {
    if (!activeTaskId) return;
    try {
      await stopAddFriendCampaign(activeTaskId);
    } catch (err) {
      console.error('Lỗi khi dừng chiến dịch:', err);
    }
  };

  // Export logs to CSV
  const handleExportLogsCsv = () => {
    if (!taskStatus || !taskStatus.logs.length) return;
    const headers = ['STT', 'Số điện thoại', 'Tên khách', 'Nguồn', 'Nhu cầu', 'Page Zalo', 'Trạng thái', 'Chi tiết', 'Thời gian'];
    const rows = taskStatus.logs.map((l) => [
      l.index,
      `"'${l.phone}"`,
      `"${(l.name || '').replace(/"/g, '""')}"`,
      `"${(l.source || '').replace(/"/g, '""')}"`,
      `"${(l.nhu_cau || '').replace(/"/g, '""')}"`,
      `"${(l.page_name || '').replace(/"/g, '""')}"`,
      l.status,
      `"${(l.detail || '').replace(/"/g, '""')}"`,
      l.time
    ]);
    const csvContent = '\uFEFF' + [headers.join(','), ...rows.map((r) => r.join(','))].join('\n');
    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `ket_qua_ket_ban_${taskStatus.campaign_name}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const availableTags = useMemo(() => {
    const base = config?.tags || ['Web', 'Đào tạo', 'Lead Other', 'Đã add', 'Đang tư vấn', 'Xin file'];
    const merged = Array.from(new Set([...base, ...selectedTags]));
    return merged;
  }, [config?.tags, selectedTags]);

  const charCount = messageTemplate.length;

  return (
    <div className="space-y-6">
      {/* Top Header & Mode Switcher */}
      <div className="bg-white rounded-2xl border border-slate-200/80 shadow-sm p-5">
        <div className="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-4">
          <div className="flex items-start gap-3.5">
            <div className="w-12 h-12 rounded-2xl bg-gradient-to-br from-emerald-500 to-teal-600 flex items-center justify-center text-white shadow-md shadow-emerald-600/20 shrink-0">
              <UserPlus className="w-6 h-6" />
            </div>
            <div>
              <div className="flex items-center gap-2.5 flex-wrap">
                <h2 className="text-lg font-bold text-slate-900">
                  Kết Bạn Zalo Tự Động Hàng Loạt (Auto Add Friend)
                </h2>
                <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-emerald-50 text-emerald-700 border border-emerald-200">
                  <Sparkles className="w-3.5 h-3.5" />
                  Chuẩn workflow Pancake Bot
                </span>
              </div>
              <p className="text-xs text-slate-500 mt-1">
                Import danh sách SĐT từ Excel/Sheet hoặc Kho Leads • Tự động chuẩn hóa đầu số 0/84 • Chọn Page Zalo • Cá nhân hóa lời chào, ghi chú & gắn Tag • Chống chặn Rate Limit
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2.5 flex-wrap">
            {/* Trạng thái phiên Pancake */}
            <button
              type="button"
              onClick={handleOpenStateModal}
              className={`inline-flex items-center gap-2 px-3.5 py-2 rounded-xl text-xs font-semibold border transition-all ${
                config?.state_info?.has_state
                  ? 'bg-emerald-50/80 text-emerald-800 border-emerald-200 hover:bg-emerald-100'
                  : 'bg-amber-50 text-amber-800 border-amber-300 hover:bg-amber-100'
              }`}
            >
              <Key className="w-3.5 h-3.5" />
              {config?.state_info?.has_state ? (
                <span>
                  Phiên Pancake: Đã lưu DB ({config.state_info.cookies_count} cookies)
                </span>
              ) : (
                <span>Cấu hình Phiên Pancake (app_configs)</span>
              )}
            </button>

            {/* Sub-tab buttons */}
            <div className="inline-flex rounded-xl bg-slate-100 p-1 border border-slate-200">
              <button
                type="button"
                onClick={() => setSubTab('workspace')}
                className={`inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg text-xs font-semibold transition-all ${
                  subTab === 'workspace'
                    ? 'bg-white text-emerald-700 shadow-sm'
                    : 'text-slate-600 hover:text-slate-900'
                }`}
              >
                <UserPlus className="w-3.5 h-3.5" />
                Thiết Lập & Chạy Kết Bạn
              </button>
              <button
                type="button"
                onClick={() => setSubTab('history')}
                className={`inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg text-xs font-semibold transition-all ${
                  subTab === 'history'
                    ? 'bg-white text-emerald-700 shadow-sm'
                    : 'text-slate-600 hover:text-slate-900'
                }`}
              >
                <History className="w-3.5 h-3.5" />
                Lịch Sử Kết Bạn
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* Action Banner */}
      {actionBanner && (
        <div
          className={`flex items-center justify-between gap-3 px-4 py-3 rounded-xl border text-xs font-medium ${
            actionBanner.type === 'error'
              ? 'bg-rose-50 border-rose-200 text-rose-800'
              : actionBanner.type === 'success'
              ? 'bg-emerald-50 border-emerald-200 text-emerald-800'
              : 'bg-blue-50 border-blue-200 text-blue-800'
          }`}
        >
          <div className="flex items-center gap-2">
            {actionBanner.type === 'error' ? (
              <AlertTriangle className="w-4 h-4 shrink-0 text-rose-600" />
            ) : actionBanner.type === 'success' ? (
              <CheckCircle2 className="w-4 h-4 shrink-0 text-emerald-600" />
            ) : (
              <Info className="w-4 h-4 shrink-0 text-blue-600" />
            )}
            <span>{actionBanner.text}</span>
          </div>
          <button
            type="button"
            onClick={() => setActionBanner(null)}
            className="text-slate-400 hover:text-slate-700"
            aria-label="Đóng thông báo"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      )}

      {subTab === 'workspace' ? (
        <>
          {/* Main Configuration Grid: Left (Import & Page/Message) | Right (Tags & Rate Limit) */}
          <div className="grid grid-cols-1 xl:grid-cols-12 gap-6">
            {/* LEFT COLUMN (7 cols): Step 1 (Bulk Import) + Step 2 (Page & Greeting Message) */}
            <div className="xl:col-span-7 space-y-6">
              {/* STEP 1: IMPORT HÀNG LOẠT SỐ ĐIỆN THOẠI */}
              <div className="bg-white rounded-2xl border border-slate-200/80 shadow-sm p-5 space-y-4">
                <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 pb-3">
                  <div className="flex items-center gap-2.5">
                    <span className="w-6 h-6 rounded-full bg-emerald-600 text-white text-xs font-bold flex items-center justify-center">
                      1
                    </span>
                    <div>
                      <h3 className="text-sm font-bold text-slate-900">
                        Import Hàng Loạt Số Điện Thoại
                      </h3>
                      <p className="text-[11px] text-slate-500">
                        Dán danh sách SĐT (1 số/dòng) hoặc copy các cột <code className="text-emerald-700 font-semibold">SĐT | Tên | Nguồn | Nhu cầu</code> từ Excel / Google Sheet
                      </p>
                    </div>
                  </div>

                  {/* Quick Import Toolbar */}
                  <div className="flex items-center gap-1.5 flex-wrap">
                    <input
                      ref={fileInputRef}
                      type="file"
                      accept=".csv,.txt,.tsv"
                      onChange={handleFileUpload}
                      className="hidden"
                    />
                    <button
                      type="button"
                      onClick={() => fileInputRef.current?.click()}
                      className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-semibold bg-slate-100 text-slate-700 hover:bg-slate-200 transition-colors"
                    >
                      <Upload className="w-3.5 h-3.5" />
                      Tải file CSV/TXT
                    </button>

                    <button
                      type="button"
                      disabled={loadingLeadsPhones}
                      onClick={() => handlePullLeadsPhones('tiktok')}
                      className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-semibold bg-indigo-50 text-indigo-700 hover:bg-indigo-100 border border-indigo-200 transition-colors disabled:opacity-50"
                    >
                      <Database className="w-3.5 h-3.5" />
                      Lấy SĐT từ TikTok
                    </button>

                    <button
                      type="button"
                      disabled={loadingLeadsPhones}
                      onClick={() => handlePullLeadsPhones('all')}
                      className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-semibold bg-emerald-50 text-emerald-700 hover:bg-emerald-100 border border-emerald-200 transition-colors disabled:opacity-50"
                    >
                      <FileSpreadsheet className="w-3.5 h-3.5" />
                      Lấy SĐT từ Kho Leads
                    </button>

                    <button
                      type="button"
                      onClick={() => {
                        setRawPhoneText(SAMPLE_BULK_TEXT);
                        setPhoneInputError(null);
                        handleParsePhones(SAMPLE_BULK_TEXT);
                      }}
                      className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-xs font-medium text-slate-600 hover:bg-slate-100 transition-colors"
                    >
                      Dữ liệu mẫu
                    </button>
                  </div>
                </div>

                <div>
                  <div className="flex items-center justify-between mb-1.5">
                    <label
                      htmlFor="bulk-phone-textarea"
                      className="block text-xs font-semibold text-slate-700"
                    >
                      Danh sách Số điện thoại cần kết bạn (Tự động đổi 84... → 0... và thêm số 0 bị mất từ Excel)
                    </label>
                    <button
                      type="button"
                      onClick={() => {
                        setRawPhoneText('');
                        setParsedItems([]);
                        setParseStats(null);
                      }}
                      className="text-[11px] text-rose-600 hover:underline font-medium"
                    >
                      Xóa trắng
                    </button>
                  </div>
                  <textarea
                    id="bulk-phone-textarea"
                    rows={6}
                    value={rawPhoneText}
                    spellCheck={false}
                    autoCorrect="off"
                    onChange={(e) => {
                      setRawPhoneText(e.target.value);
                      if (phoneInputError) setPhoneInputError(null);
                    }}
                    onBlur={() => {
                      if (!rawPhoneText.trim()) {
                        setPhoneInputError('Vui lòng nhập hoặc dán ít nhất 1 số điện thoại.');
                      }
                    }}
                    placeholder={`Ví dụ:\n0987654321\n84912345678\tNguyễn Thị Mai\tcontact-page\tTư vấn khóa học\n0905112233\tTrần Văn Hùng\tqua-tang-file-aio\tNhận bộ file AIO`}
                    className="w-full rounded-xl border border-slate-300 bg-slate-50/60 px-3.5 py-2.5 text-xs font-mono text-slate-800 focus:bg-white focus:border-emerald-500 focus:ring-2 focus:ring-emerald-500/20 outline-none transition-all"
                  />
                  {phoneInputError && (
                    <p className="mt-1 text-xs text-rose-600 font-medium">{phoneInputError}</p>
                  )}
                </div>

                {/* Skip Sources & Parse Action */}
                <div className="grid grid-cols-1 md:grid-cols-12 gap-3 items-end pt-1">
                  <div className="md:col-span-8">
                    <label
                      htmlFor="skip-sources-input"
                      className="block text-xs font-semibold text-slate-700 mb-1"
                    >
                      Nguồn loại trừ tự động (<code className="text-slate-500">SKIP_SOURCES</code> từ bot.py, ngăn cách bởi dấu phẩy)
                    </label>
                    <input
                      id="skip-sources-input"
                      type="text"
                      value={skipSourcesInput}
                      autoCorrect="off"
                      spellCheck={false}
                      onChange={(e) => setSkipSourcesInput(e.target.value)}
                      placeholder="ezexcel-dung-thu, test-case-123"
                      className="w-full rounded-xl border border-slate-300 px-3 py-2 text-xs text-slate-700 focus:border-emerald-500 focus:ring-2 focus:ring-emerald-500/20 outline-none"
                    />
                  </div>
                  <div className="md:col-span-4">
                    <button
                      type="button"
                      disabled={parsing}
                      onClick={() => handleParsePhones()}
                      className="w-full inline-flex items-center justify-center gap-2 px-4 py-2 rounded-xl bg-slate-900 hover:bg-slate-800 text-white text-xs font-semibold shadow-sm transition-all disabled:opacity-50"
                    >
                      <RefreshCw className={`w-3.5 h-3.5 ${parsing ? 'animate-spin' : ''}`} />
                      {parsing ? 'Đang chuẩn hóa...' : 'Phân Tích & Chuẩn Hóa SĐT'}
                    </button>
                  </div>
                </div>
              </div>

              {/* STEP 2: CHỌN PAGE ZALO & SOẠN TIN NHẮN CHÀO */}
              <div className="bg-white rounded-2xl border border-slate-200/80 shadow-sm p-5 space-y-4">
                <div className="flex items-center gap-2.5 border-b border-slate-100 pb-3">
                  <span className="w-6 h-6 rounded-full bg-emerald-600 text-white text-xs font-bold flex items-center justify-center">
                    2
                  </span>
                  <div>
                    <h3 className="text-sm font-bold text-slate-900">
                      Chọn Page Zalo & Soạn Kịch Bản Tin Nhắn Chào
                    </h3>
                    <p className="text-[11px] text-slate-500">
                      Chọn tài khoản Zalo trên Pancake để gửi kết bạn và tùy biến lời chào / tin nhắn hộp thoại
                    </p>
                  </div>
                </div>

                {/* Campaign Name & Target Page Selection */}
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div>
                    <label
                      htmlFor="addfriend-campaign-name"
                      className="block text-xs font-semibold text-slate-700 mb-1"
                    >
                      Tên chiến dịch kết bạn
                    </label>
                    <input
                      id="addfriend-campaign-name"
                      type="text"
                      value={campaignName}
                      autoCorrect="off"
                      onChange={(e) => setCampaignName(e.target.value)}
                      className="w-full rounded-xl border border-slate-300 px-3 py-2 text-xs text-slate-800 focus:border-emerald-500 focus:ring-2 focus:ring-emerald-500/20 outline-none"
                    />
                  </div>

                  <div>
                    <label
                      htmlFor="custom-page-name"
                      className="block text-xs font-semibold text-slate-700 mb-1"
                    >
                      Hoặc nhập tên Page Zalo khác trên Pancake (nếu cần)
                    </label>
                    <input
                      id="custom-page-name"
                      type="text"
                      value={customPageInput}
                      onChange={(e) => setCustomPageInput(e.target.value)}
                      placeholder="Để trống nếu chọn Page bên dưới..."
                      className="w-full rounded-xl border border-slate-300 px-3 py-2 text-xs text-slate-800 focus:border-emerald-500 focus:ring-2 focus:ring-emerald-500/20 outline-none"
                    />
                  </div>
                </div>

                {/* Quick Page Selector Pills */}
                <div>
                  <span className="block text-xs font-semibold text-slate-700 mb-2">
                    Chọn Page Zalo thực hiện kết bạn (<code className="text-emerald-700">TARGET_DASHBOARD</code>):
                  </span>
                  <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2">
                    {(config?.pages || [
                      { id: 'Eztech Consultant', name: 'Eztech Consultant', badge: 'Mặc định (bot.py)' },
                      { id: 'Eztech Phân Tích Dữ Liệu', name: 'Eztech Phân Tích Dữ Liệu', badge: 'Zalo Personal' },
                      { id: 'Hiền Minh Eztech', name: 'Hiền Minh Eztech', badge: 'Zalo Personal' },
                      { id: 'Tuấn Anh Data', name: 'Tuấn Anh Data', badge: 'Zalo Personal' },
                      { id: 'Ann', name: 'Ann', badge: 'Zalo Personal' }
                    ]).map((pg) => {
                      const isSelected = !customPageInput.trim() && selectedPage === pg.id;
                      return (
                        <button
                          key={pg.id}
                          type="button"
                          onClick={() => {
                            setSelectedPage(pg.id);
                            setCustomPageInput('');
                          }}
                          className={`flex items-center justify-between px-3 py-2.5 rounded-xl border text-left transition-all ${
                            isSelected
                              ? 'bg-emerald-50/90 border-emerald-500 text-emerald-900 ring-2 ring-emerald-500/15'
                              : 'bg-white border-slate-200 text-slate-700 hover:border-slate-300 hover:bg-slate-50'
                          }`}
                        >
                          <div className="min-w-0">
                            <div className="text-xs font-bold truncate">{pg.name}</div>
                            <div className="text-[10px] text-slate-500">{pg.badge}</div>
                          </div>
                          {isSelected && <Check className="w-4 h-4 text-emerald-600 shrink-0" />}
                        </button>
                      );
                    })}
                  </div>
                </div>

                {/* Template Preset Selector from bot.py */}
                <div className="space-y-2 pt-1">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <label
                      htmlFor="bot-template-select"
                      className="block text-xs font-semibold text-slate-700"
                    >
                      Mẫu tin nhắn chào theo nguồn (<code className="text-emerald-700">MESSAGE_TEMPLATES</code> từ bot.py)
                    </label>
                    <label className="inline-flex items-center gap-2 text-xs text-slate-700 cursor-pointer">
                      <input
                        type="checkbox"
                        checked={useSourceTemplate}
                        onChange={(e) => setUseSourceTemplate(e.target.checked)}
                        className="rounded border-slate-300 text-emerald-600 focus:ring-emerald-500"
                      />
                      <span className="font-medium">
                        Tự động đổi câu chào nếu cột Nguồn khớp mẫu
                      </span>
                    </label>
                  </div>

                  <select
                    id="bot-template-select"
                    value={selectedTemplateKey}
                    onChange={(e) => {
                      const key = e.target.value;
                      setSelectedTemplateKey(key);
                      const found = config?.templates.find((t) => t.key === key);
                      if (found) {
                        setMessageTemplate(found.message);
                      }
                    }}
                    className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-xs text-slate-800 focus:border-emerald-500 focus:ring-2 focus:ring-emerald-500/20 outline-none"
                  >
                    {(config?.templates || [
                      {
                        key: 'default',
                        label: 'Mặc định (Tư vấn chung)',
                        source_key: 'default',
                        message:
                          'Chào bạn, mình là {page}. Mình xin phép kết bạn để trao đổi chi tiết hơn về dịch vụ bên mình nhé ạ!'
                      }
                    ]).map((tpl) => (
                      <option key={tpl.key} value={tpl.key}>
                        {tpl.label}
                      </option>
                    ))}
                  </select>
                </div>

                {/* Greeting Message Composer */}
                <div>
                  <div className="flex flex-wrap items-center justify-between gap-2 mb-1.5">
                    <label
                      htmlFor="greeting-message-textarea"
                      className="block text-xs font-semibold text-slate-700"
                    >
                      Nội dung Lời mời kết bạn & Tin nhắn chào
                    </label>
                    <span
                      className={`text-[11px] font-semibold tabular-nums ${
                        charCount > 150 ? 'text-amber-600' : 'text-slate-500'
                      }`}
                    >
                      {charCount}/150 ký tự (Modal Kết bạn Zalo giới hạn 150 ký tự; tin nhắn hộp thoại không giới hạn)
                    </span>
                  </div>

                  {/* Variable Insertion Chips */}
                  <div className="flex items-center gap-1.5 flex-wrap mb-2">
                    <span className="text-[11px] text-slate-500 mr-1">Chèn biến:</span>
                    {[
                      { label: 'Tên Page {page}', val: '{page}' },
                      { label: 'Tên khách {name}', val: '{name}' },
                      { label: 'Anh/Chị {gender_title}', val: '{gender_title}' },
                      { label: 'Nguồn {source}', val: '{source}' },
                      { label: 'Nhu cầu {nhu_cau}', val: '{nhu_cau}' },
                      { label: 'Spintax {Chào|Xin chào|Dạ chào}', val: '{Chào|Xin chào|Dạ chào}' }
                    ].map((chip) => (
                      <button
                        key={chip.val}
                        type="button"
                        onClick={() => handleInsertVariable(chip.val)}
                        className="px-2 py-1 rounded-lg bg-slate-100 hover:bg-emerald-50 hover:text-emerald-700 text-slate-700 text-[11px] font-medium border border-slate-200 transition-colors"
                      >
                        + {chip.label}
                      </button>
                    ))}
                  </div>

                  <textarea
                    id="greeting-message-textarea"
                    ref={messageTextareaRef}
                    rows={3}
                    value={messageTemplate}
                    onChange={(e) => setMessageTemplate(e.target.value)}
                    className="w-full rounded-xl border border-slate-300 px-3.5 py-2.5 text-xs text-slate-800 focus:border-emerald-500 focus:ring-2 focus:ring-emerald-500/20 outline-none"
                  />
                </div>

                {/* Post-Add-Friend Actions: Inbox Message & Customer Note */}
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3 pt-1">
                  <label className="flex items-start gap-2.5 p-3 rounded-xl border border-slate-200 bg-slate-50/60 cursor-pointer hover:bg-slate-50">
                    <input
                      type="checkbox"
                      checked={sendInboxMessage}
                      onChange={(e) => setSendInboxMessage(e.target.checked)}
                      className="mt-0.5 rounded border-slate-300 text-emerald-600 focus:ring-emerald-500"
                    />
                    <div>
                      <div className="text-xs font-bold text-slate-800 flex items-center gap-1.5">
                        <MessageSquare className="w-3.5 h-3.5 text-emerald-600" />
                        Bấm &ldquo;Nhắn tin&rdquo; & gửi lời chào vào hộp thoại
                      </div>
                      <p className="text-[11px] text-slate-500 mt-0.5">
                        Sau khi gửi lời mời kết bạn, tự động mở khung chat (<code className="text-slate-600">#replyBoxComposer</code>) và gửi tin nhắn chào.
                      </p>
                    </div>
                  </label>

                  <div className="p-3 rounded-xl border border-slate-200 bg-slate-50/60 space-y-2">
                    <label className="flex items-center gap-2 cursor-pointer">
                      <input
                        type="checkbox"
                        checked={addNote}
                        onChange={(e) => setAddNote(e.target.checked)}
                        className="rounded border-slate-300 text-emerald-600 focus:ring-emerald-500"
                      />
                      <span className="text-xs font-bold text-slate-800">
                        Tự động lưu Ghi chú khách hàng trên Pancake
                      </span>
                    </label>
                    {addNote && (
                      <div>
                        <label htmlFor="note-template-input" className="sr-only">
                          Mẫu ghi chú khách hàng
                        </label>
                        <input
                          id="note-template-input"
                          type="text"
                          value={noteTemplate}
                          onChange={(e) => setNoteTemplate(e.target.value)}
                          placeholder="Nguồn: {source} | Nhu cầu: {nhu_cau}"
                          className="w-full rounded-lg border border-slate-300 bg-white px-2.5 py-1.5 text-xs text-slate-700 focus:border-emerald-500 outline-none"
                        />
                      </div>
                    )}
                  </div>
                </div>
              </div>
            </div>

            {/* RIGHT COLUMN (5 cols): Gắn Tag + Chống chặn Rate Limit */}
            <div className="xl:col-span-5 space-y-6">
              {/* GẮN THẺ TAG TỰ ĐỘNG */}
              <div className="bg-white rounded-2xl border border-slate-200/80 shadow-sm p-5 space-y-4">
                <div className="flex items-center justify-between border-b border-slate-100 pb-3">
                  <div className="flex items-center gap-2.5">
                    <div className="w-7 h-7 rounded-lg bg-indigo-50 text-indigo-600 flex items-center justify-center">
                      <Tag className="w-4 h-4" />
                    </div>
                    <div>
                      <h3 className="text-sm font-bold text-slate-900">
                        Gắn Thẻ Tag Tự Động Sau Khi Kết Bạn
                      </h3>
                      <p className="text-[11px] text-slate-500">
                        Bot tự động click gắn các thẻ Tag đã chọn trong hội thoại Pancake
                      </p>
                    </div>
                  </div>
                  <span className="text-xs font-semibold text-indigo-700 bg-indigo-50 px-2.5 py-0.5 rounded-full">
                    Đã chọn: {selectedTags.length}
                  </span>
                </div>

                {/* Tag Pills */}
                <div className="flex flex-wrap gap-1.5 max-h-36 overflow-y-auto pr-1">
                  {availableTags.map((tag) => {
                    const active = selectedTags.includes(tag);
                    return (
                      <button
                        key={tag}
                        type="button"
                        onClick={() => handleToggleTag(tag)}
                        className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-semibold border transition-all ${
                          active
                            ? 'bg-indigo-600 text-white border-indigo-600 shadow-xs'
                            : 'bg-slate-50 text-slate-700 border-slate-200 hover:bg-slate-100'
                        }`}
                      >
                        <Tag className="w-3 h-3" />
                        <span>{tag}</span>
                        {active && <Check className="w-3 h-3" />}
                      </button>
                    );
                  })}
                </div>

                {/* Add Custom Tag */}
                <div className="flex items-center gap-2 pt-1">
                  <label htmlFor="custom-tag-input" className="sr-only">
                    Thêm tên Tag tùy chỉnh
                  </label>
                  <input
                    id="custom-tag-input"
                    type="text"
                    value={customTagInput}
                    onChange={(e) => setCustomTagInput(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') {
                        e.preventDefault();
                        handleAddCustomTag();
                      }
                    }}
                    placeholder="Nhập tên Tag trên Pancake (vd: Web, Đào tạo...)"
                    className="flex-1 rounded-xl border border-slate-300 px-3 py-1.5 text-xs text-slate-800 focus:border-indigo-500 outline-none"
                  />
                  <button
                    type="button"
                    onClick={handleAddCustomTag}
                    className="inline-flex items-center gap-1 px-3 py-1.5 rounded-xl bg-indigo-50 hover:bg-indigo-100 text-indigo-700 text-xs font-semibold border border-indigo-200"
                  >
                    <Plus className="w-3.5 h-3.5" />
                    Thêm Tag
                  </button>
                </div>
              </div>

              {/* STEP 3: SETTING CHỐNG CHẶN RATE LIMIT ZALO */}
              <div className="bg-white rounded-2xl border border-slate-200/80 shadow-sm p-5 space-y-4">
                <div className="flex items-center justify-between border-b border-slate-100 pb-3">
                  <div className="flex items-center gap-2.5">
                    <span className="w-6 h-6 rounded-full bg-emerald-600 text-white text-xs font-bold flex items-center justify-center">
                      3
                    </span>
                    <div>
                      <h3 className="text-sm font-bold text-slate-900">
                        Cấu Hình Chống Chặn Rate Limit & Bảo Vệ Nick Zalo
                      </h3>
                      <p className="text-[11px] text-slate-500">
                        Giãn cách ngẫu nhiên, nghỉ giải lao theo chặng & tự ngắt khi Pancake lỗi 502/504
                      </p>
                    </div>
                  </div>
                  <ShieldCheck className="w-5 h-5 text-emerald-600 shrink-0" />
                </div>

                {/* Speed Presets */}
                <div className="grid grid-cols-3 gap-2">
                  {[
                    {
                      id: 'fast' as const,
                      title: 'Nhanh',
                      desc: '5–10s / số • Nghỉ 30s mỗi 15 số'
                    },
                    {
                      id: 'recommended' as const,
                      title: 'Khuyên dùng',
                      desc: '8–16s / số • Nghỉ 45s mỗi 10 số'
                    },
                    {
                      id: 'ultra' as const,
                      title: 'Siêu an toàn',
                      desc: '18–32s / số • Nghỉ 90s mỗi 8 số'
                    }
                  ].map((p) => {
                    const active = rateLimit.preset === p.id;
                    return (
                      <button
                        key={p.id}
                        type="button"
                        onClick={() => handleApplyPreset(p.id)}
                        className={`p-2.5 rounded-xl border text-left transition-all ${
                          active
                            ? 'bg-emerald-50 border-emerald-500 text-emerald-900 ring-2 ring-emerald-500/15'
                            : 'bg-slate-50/70 border-slate-200 text-slate-700 hover:bg-slate-100'
                        }`}
                      >
                        <div className="text-xs font-bold flex items-center justify-between">
                          <span>{p.title}</span>
                          {active && <Check className="w-3.5 h-3.5 text-emerald-600" />}
                        </div>
                        <div className="text-[10px] text-slate-500 mt-0.5">{p.desc}</div>
                      </button>
                    );
                  })}
                </div>

                {/* Detailed Rate Limit Controls */}
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label
                      htmlFor="rl-delay-min"
                      className="block text-[11px] font-semibold text-slate-700 mb-1"
                    >
                      Nghỉ tối thiểu giữa 2 SĐT (giây)
                    </label>
                    <input
                      id="rl-delay-min"
                      type="number"
                      inputMode="numeric"
                      min={1}
                      max={120}
                      value={rateLimit.delay_min}
                      onChange={(e) =>
                        setRateLimit((prev) => ({
                          ...prev,
                          preset: 'custom',
                          delay_min: Math.max(1, Number(e.target.value) || 1)
                        }))
                      }
                      className="w-full rounded-xl border border-slate-300 px-3 py-1.5 text-xs font-semibold tabular-nums text-slate-800 focus:border-emerald-500 outline-none"
                    />
                  </div>

                  <div>
                    <label
                      htmlFor="rl-delay-max"
                      className="block text-[11px] font-semibold text-slate-700 mb-1"
                    >
                      Nghỉ tối đa giữa 2 SĐT (giây)
                    </label>
                    <input
                      id="rl-delay-max"
                      type="number"
                      inputMode="numeric"
                      min={2}
                      max={300}
                      value={rateLimit.delay_max}
                      onChange={(e) =>
                        setRateLimit((prev) => ({
                          ...prev,
                          preset: 'custom',
                          delay_max: Math.max(prev.delay_min, Number(e.target.value) || 10)
                        }))
                      }
                      className="w-full rounded-xl border border-slate-300 px-3 py-1.5 text-xs font-semibold tabular-nums text-slate-800 focus:border-emerald-500 outline-none"
                    />
                  </div>

                  <div>
                    <label
                      htmlFor="rl-batch-size"
                      className="block text-[11px] font-semibold text-slate-700 mb-1"
                    >
                      Nghỉ giải lao sau mỗi (SĐT)
                    </label>
                    <input
                      id="rl-batch-size"
                      type="number"
                      inputMode="numeric"
                      min={1}
                      max={100}
                      value={rateLimit.batch_size}
                      onChange={(e) =>
                        setRateLimit((prev) => ({
                          ...prev,
                          preset: 'custom',
                          batch_size: Math.max(1, Number(e.target.value) || 10)
                        }))
                      }
                      className="w-full rounded-xl border border-slate-300 px-3 py-1.5 text-xs font-semibold tabular-nums text-slate-800 focus:border-emerald-500 outline-none"
                    />
                  </div>

                  <div>
                    <label
                      htmlFor="rl-batch-pause"
                      className="block text-[11px] font-semibold text-slate-700 mb-1"
                    >
                      Thời gian nghỉ giữa chặng (giây)
                    </label>
                    <input
                      id="rl-batch-pause"
                      type="number"
                      inputMode="numeric"
                      min={0}
                      max={900}
                      value={rateLimit.batch_pause_sec}
                      onChange={(e) =>
                        setRateLimit((prev) => ({
                          ...prev,
                          preset: 'custom',
                          batch_pause_sec: Math.max(0, Number(e.target.value) || 0)
                        }))
                      }
                      className="w-full rounded-xl border border-slate-300 px-3 py-1.5 text-xs font-semibold tabular-nums text-slate-800 focus:border-emerald-500 outline-none"
                    />
                  </div>

                  <div>
                    <label
                      htmlFor="rl-max-retries"
                      className="block text-[11px] font-semibold text-slate-700 mb-1"
                    >
                      Số lần thử lại khi lag (<code className="text-slate-500">MAX_RETRIES</code>)
                    </label>
                    <input
                      id="rl-max-retries"
                      type="number"
                      inputMode="numeric"
                      min={1}
                      max={5}
                      value={rateLimit.max_retries}
                      onChange={(e) =>
                        setRateLimit((prev) => ({
                          ...prev,
                          max_retries: Math.min(5, Math.max(1, Number(e.target.value) || 2))
                        }))
                      }
                      className="w-full rounded-xl border border-slate-300 px-3 py-1.5 text-xs font-semibold tabular-nums text-slate-800 focus:border-emerald-500 outline-none"
                    />
                  </div>

                  <div>
                    <label
                      htmlFor="rl-daily-limit"
                      className="block text-[11px] font-semibold text-slate-700 mb-1"
                    >
                      Giới hạn tối đa mỗi đợt chạy (SĐT)
                    </label>
                    <input
                      id="rl-daily-limit"
                      type="number"
                      inputMode="numeric"
                      min={1}
                      max={500}
                      value={rateLimit.daily_limit}
                      onChange={(e) =>
                        setRateLimit((prev) => ({
                          ...prev,
                          daily_limit: Math.max(1, Number(e.target.value) || 50)
                        }))
                      }
                      className="w-full rounded-xl border border-slate-300 px-3 py-1.5 text-xs font-semibold tabular-nums text-slate-800 focus:border-emerald-500 outline-none"
                    />
                  </div>
                </div>

                {/* Checkboxes: Spintax, Exclude already added, Circuit Breaker */}
                <div className="space-y-2 pt-1 border-t border-slate-100">
                  <label className="flex items-center justify-between text-xs text-slate-700 cursor-pointer">
                    <span>Xoay vòng từ ngữ Spintax chống trùng lặp nội dung</span>
                    <input
                      type="checkbox"
                      checked={rateLimit.enable_spintax}
                      onChange={(e) =>
                        setRateLimit((prev) => ({ ...prev, enable_spintax: e.target.checked }))
                      }
                      className="rounded border-slate-300 text-emerald-600 focus:ring-emerald-500"
                    />
                  </label>

                  <label className="flex items-center justify-between text-xs text-slate-700 cursor-pointer">
                    <span>Bỏ qua SĐT đã từng gửi kết bạn thành công trong lịch sử</span>
                    <input
                      type="checkbox"
                      checked={rateLimit.exclude_already_added}
                      onChange={(e) =>
                        setRateLimit((prev) => ({
                          ...prev,
                          exclude_already_added: e.target.checked
                        }))
                      }
                      className="rounded border-slate-300 text-emerald-600 focus:ring-emerald-500"
                    />
                  </label>

                  <div className="flex items-center justify-between text-xs text-slate-700">
                    <label htmlFor="rl-circuit-breaker">
                      Tự động ngắt bảo vệ (Circuit Breaker) khi lỗi liên tiếp:
                    </label>
                    <input
                      id="rl-circuit-breaker"
                      type="number"
                      inputMode="numeric"
                      min={1}
                      max={15}
                      value={rateLimit.max_consecutive_errors}
                      onChange={(e) =>
                        setRateLimit((prev) => ({
                          ...prev,
                          max_consecutive_errors: Math.max(1, Number(e.target.value) || 3)
                        }))
                      }
                      className="w-16 rounded-lg border border-slate-300 px-2 py-1 text-xs text-center font-bold tabular-nums"
                    />
                  </div>
                </div>

                {/* Dry-Run vs Live Mode Switch + Start Button */}
                <div className="pt-2 border-t border-slate-100 space-y-3">
                  <div className="grid grid-cols-2 gap-2">
                    <button
                      type="button"
                      onClick={() => setDryRun(true)}
                      className={`px-3 py-2.5 rounded-xl border text-xs font-bold flex items-center justify-center gap-1.5 transition-all ${
                        dryRun
                          ? 'bg-amber-50 border-amber-400 text-amber-900 ring-2 ring-amber-400/20'
                          : 'bg-white border-slate-200 text-slate-600 hover:bg-slate-50'
                      }`}
                    >
                      <ShieldAlert className="w-4 h-4 text-amber-600" />
                      Chạy Thử (Dry-Run)
                    </button>

                    <button
                      type="button"
                      onClick={() => setDryRun(false)}
                      className={`px-3 py-2.5 rounded-xl border text-xs font-bold flex items-center justify-center gap-1.5 transition-all ${
                        !dryRun
                          ? 'bg-emerald-600 border-emerald-600 text-white shadow-sm'
                          : 'bg-white border-slate-200 text-slate-600 hover:bg-slate-50'
                      }`}
                    >
                      <Play className="w-4 h-4" />
                      Chạy Thật (Playwright)
                    </button>
                  </div>

                  <button
                    type="button"
                    disabled={startingCampaign || Boolean(taskStatus?.is_running)}
                    onClick={handleStartCampaign}
                    className={`w-full py-3 px-4 rounded-xl text-xs font-bold text-white shadow-md flex items-center justify-center gap-2 transition-all disabled:opacity-50 ${
                      dryRun
                        ? 'bg-amber-600 hover:bg-amber-700 shadow-amber-600/20'
                        : 'bg-gradient-to-r from-emerald-600 to-teal-600 hover:from-emerald-700 hover:to-teal-700 shadow-emerald-600/25'
                    }`}
                  >
                    <UserPlus className="w-4 h-4" />
                    {startingCampaign
                      ? 'Đang khởi tạo chiến dịch...'
                      : dryRun
                      ? `Bắt Đầu Chạy Thử Nghiệm (${selectedPhones.size} SĐT đã chọn)`
                      : `Bắt Đầu Kết Bạn Tự Động Trên "${effectivePageName}" (${selectedPhones.size} SĐT)`}
                  </button>
                </div>
              </div>
            </div>
          </div>

          {/* ACTIVE CAMPAIGN PROGRESS & REAL-TIME LOGS */}
          {taskStatus && (
            <div className="bg-white rounded-2xl border border-emerald-200 shadow-sm p-5 space-y-4">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="flex items-center gap-3">
                  <div
                    className={`w-3 h-3 rounded-full ${
                      taskStatus.is_running ? 'bg-emerald-500 animate-ping' : 'bg-slate-400'
                    }`}
                  />
                  <div>
                    <div className="flex items-center gap-2">
                      <h3 className="text-sm font-bold text-slate-900">
                        Tiến Trình Chiến Dịch: {taskStatus.campaign_name}
                      </h3>
                      <span className="px-2 py-0.5 rounded-full text-[11px] font-semibold bg-slate-100 text-slate-700">
                        Page: {taskStatus.page_name}
                      </span>
                      {taskStatus.dry_run && (
                        <span className="px-2 py-0.5 rounded-full text-[11px] font-semibold bg-amber-100 text-amber-800">
                          Chế độ Chạy thử (Dry-Run)
                        </span>
                      )}
                    </div>
                    <p className="text-xs text-emerald-700 font-medium mt-0.5">
                      {taskStatus.current_action}
                    </p>
                  </div>
                </div>

                <div className="flex items-center gap-2">
                  {taskStatus.logs.length > 0 && (
                    <button
                      type="button"
                      onClick={handleExportLogsCsv}
                      className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-slate-100 hover:bg-slate-200 text-slate-700 text-xs font-semibold"
                    >
                      <Download className="w-3.5 h-3.5" />
                      Xuất CSV kết quả
                    </button>
                  )}

                  {taskStatus.is_running && (
                    <button
                      type="button"
                      onClick={handleStopCampaign}
                      className="inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded-xl bg-rose-600 hover:bg-rose-700 text-white text-xs font-bold shadow-xs"
                    >
                      <Square className="w-3.5 h-3.5" />
                      Dừng Khẩn Cấp
                    </button>
                  )}
                </div>
              </div>

              {/* Progress Bar & KPI Counters */}
              <div className="space-y-2">
                <div className="w-full h-2.5 bg-slate-100 rounded-full overflow-hidden">
                  <div
                    className="h-full bg-gradient-to-r from-emerald-500 to-teal-600 transition-all duration-300"
                    style={{
                      width: `${
                        taskStatus.total > 0
                          ? Math.min(100, Math.round((taskStatus.processed / taskStatus.total) * 100))
                          : 0
                      }%`
                    }}
                  />
                </div>

                <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 pt-1">
                  <div className="p-3 rounded-xl bg-slate-50 border border-slate-200/70">
                    <div className="text-[11px] text-slate-500">Đã xử lý / Tổng số</div>
                    <div className="text-base font-bold text-slate-900 tabular-nums mt-0.5">
                      {taskStatus.processed} / {taskStatus.total}
                    </div>
                  </div>
                  <div className="p-3 rounded-xl bg-emerald-50/70 border border-emerald-200">
                    <div className="text-[11px] text-emerald-700">Đã gửi kết bạn thành công</div>
                    <div className="text-base font-bold text-emerald-800 tabular-nums mt-0.5">
                      {taskStatus.added_count}
                    </div>
                  </div>
                  <div className="p-3 rounded-xl bg-amber-50/70 border border-amber-200">
                    <div className="text-[11px] text-amber-700">Không tìm thấy Zalo</div>
                    <div className="text-base font-bold text-amber-800 tabular-nums mt-0.5">
                      {taskStatus.not_found_count}
                    </div>
                  </div>
                  <div className="p-3 rounded-xl bg-rose-50/70 border border-rose-200">
                    <div className="text-[11px] text-rose-700">Lỗi / Timeout</div>
                    <div className="text-base font-bold text-rose-800 tabular-nums mt-0.5">
                      {taskStatus.failed_count}
                    </div>
                  </div>
                </div>
              </div>

              {/* Real-time Execution Logs Table */}
              {taskStatus.logs.length > 0 && (
                <div
                  className="overflow-x-auto max-h-72 border border-slate-200 rounded-xl"
                  tabIndex={0}
                  role="region"
                  aria-label="Nhật ký kết bạn thời gian thực"
                >
                  <table className="w-full text-left border-collapse text-xs">
                    <thead className="sticky top-0 z-10 bg-slate-100 text-slate-700 border-b border-slate-200">
                      <tr>
                        <th className="py-2.5 px-3 font-semibold">#</th>
                        <th className="py-2.5 px-3 font-semibold">SĐT</th>
                        <th className="py-2.5 px-3 font-semibold">Khách hàng</th>
                        <th className="py-2.5 px-3 font-semibold">Nguồn</th>
                        <th className="py-2.5 px-3 font-semibold">Trạng thái</th>
                        <th className="py-2.5 px-3 font-semibold">Chi tiết thực thi</th>
                        <th className="py-2.5 px-3 font-semibold">Lúc</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100">
                      {taskStatus.logs.map((log) => (
                        <tr key={`${log.index}-${log.phone}`} className="hover:bg-slate-50">
                          <td className="py-2 px-3 tabular-nums text-slate-500">{log.index}</td>
                          <td className="py-2 px-3 font-mono font-bold text-slate-900 tabular-nums">
                            {log.phone}
                          </td>
                          <td className="py-2 px-3 text-slate-800 font-medium">{log.name}</td>
                          <td className="py-2 px-3 text-slate-600">{log.source}</td>
                          <td className="py-2 px-3">
                            {log.status === 'ADDED' || log.status === 'DRY_RUN' ? (
                              <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-semibold bg-emerald-50 text-emerald-700 border border-emerald-200">
                                <CheckCircle2 className="w-3 h-3" />
                                {log.status === 'DRY_RUN' ? 'Chạy thử OK' : 'Đã kết bạn'}
                              </span>
                            ) : log.status === 'NOT_FOUND' ? (
                              <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-semibold bg-amber-50 text-amber-700 border border-amber-200">
                                Không có Zalo
                              </span>
                            ) : (
                              <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-semibold bg-rose-50 text-rose-700 border border-rose-200">
                                <XCircle className="w-3 h-3" />
                                {log.status}
                              </span>
                            )}
                          </td>
                          <td className="py-2 px-3 text-slate-600 max-w-md truncate" title={log.detail}>
                            {log.detail}
                          </td>
                          <td className="py-2 px-3 tabular-nums text-slate-400">{log.time}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}

          {/* STEP 4: BẢNG XEM TRƯỚC DANH SÁCH SĐT ĐÃ CHUẨN HÓA */}
          <div className="bg-white rounded-2xl border border-slate-200/80 shadow-sm p-5 space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <h3 id="parsed-phones-heading" className="text-sm font-bold text-slate-900">
                  Danh Sách Số Điện Thoại Đã Chuẩn Hóa & Xem Trước Lời Chào ({parsedItems.length} dòng)
                </h3>
                {parseStats && (
                  <div className="flex flex-wrap items-center gap-2 mt-1.5 text-[11px]">
                    <span className="px-2 py-0.5 rounded-md bg-emerald-50 text-emerald-700 font-semibold border border-emerald-200 tabular-nums">
                      Sẵn sàng chạy: {parseStats.ready_count}
                    </span>
                    <span className="px-2 py-0.5 rounded-md bg-slate-100 text-slate-700 font-medium tabular-nums">
                      Hợp lệ: {parseStats.valid_count}
                    </span>
                    {parseStats.duplicate_count > 0 && (
                      <span className="px-2 py-0.5 rounded-md bg-amber-50 text-amber-700 font-medium tabular-nums">
                        Trùng lặp: {parseStats.duplicate_count}
                      </span>
                    )}
                    {parseStats.skipped_source_count > 0 && (
                      <span className="px-2 py-0.5 rounded-md bg-orange-50 text-orange-700 font-medium tabular-nums">
                        Thuộc nguồn Skip: {parseStats.skipped_source_count}
                      </span>
                    )}
                    {parseStats.already_added_count > 0 && (
                      <span className="px-2 py-0.5 rounded-md bg-blue-50 text-blue-700 font-medium tabular-nums">
                        Đã kết bạn trước đó: {parseStats.already_added_count}
                      </span>
                    )}
                    {parseStats.invalid_count > 0 && (
                      <span className="px-2 py-0.5 rounded-md bg-rose-50 text-rose-700 font-medium tabular-nums">
                        Sai định dạng: {parseStats.invalid_count}
                      </span>
                    )}
                  </div>
                )}
              </div>

              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => {
                    const allValid = new Set<string>();
                    parsedItems.forEach((it) => {
                      if (it.is_valid && !it.is_duplicate) allValid.add(it.phone);
                    });
                    setSelectedPhones(allValid);
                  }}
                  className="px-2.5 py-1.5 rounded-lg text-xs font-semibold bg-slate-100 hover:bg-slate-200 text-slate-700"
                >
                  Chọn tất cả hợp lệ
                </button>
                <button
                  type="button"
                  onClick={() => setSelectedPhones(new Set())}
                  className="px-2.5 py-1.5 rounded-lg text-xs font-semibold bg-slate-100 hover:bg-slate-200 text-slate-700"
                >
                  Bỏ chọn tất cả
                </button>
              </div>
            </div>

            <div
              className="overflow-x-auto max-h-96 border border-slate-200 rounded-xl"
              tabIndex={0}
              role="region"
              aria-labelledby="parsed-phones-heading"
            >
              <table className="w-full text-left border-collapse text-xs">
                <thead className="sticky top-0 z-10 bg-slate-100 text-slate-700 border-b border-slate-200">
                  <tr>
                    <th className="py-2.5 px-3 w-10 text-center">Chọn</th>
                    <th className="py-2.5 px-3 font-semibold">SĐT Chuẩn Hóa</th>
                    <th className="py-2.5 px-3 font-semibold">Trạng Thái</th>
                    <th className="py-2.5 px-3 font-semibold">Tên Khách</th>
                    <th className="py-2.5 px-3 font-semibold">Nguồn (Source)</th>
                    <th className="py-2.5 px-3 font-semibold">Nhu Cầu</th>
                    <th className="py-2.5 px-3 font-semibold">Lời Chào Sẽ Gửi (Preview)</th>
                    <th className="py-2.5 px-3 font-semibold text-right">Xóa</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {parsedItems.length === 0 ? (
                    <tr>
                      <td colSpan={8} className="py-8 text-center text-slate-400">
                        Chưa có dữ liệu. Hãy dán danh sách SĐT ở Bước 1 và bấm &ldquo;Phân Tích & Chuẩn Hóa SĐT&rdquo;.
                      </td>
                    </tr>
                  ) : (
                    parsedItems.map((item, idx) => {
                      const checked = selectedPhones.has(item.phone);
                      const selectable = item.is_valid && !item.is_duplicate;
                      return (
                        <tr
                          key={`${idx}-${item.raw_phone}`}
                          className={`hover:bg-slate-50/80 ${
                            !item.is_valid || item.is_duplicate || item.is_skipped_source
                              ? 'bg-slate-50/40 opacity-70'
                              : ''
                          }`}
                        >
                          <td className="py-2 px-3 text-center">
                            <input
                              type="checkbox"
                              disabled={!selectable}
                              checked={checked}
                              onChange={() => handleToggleSelectPhone(item.phone)}
                              aria-label={`Chọn số điện thoại ${item.phone}`}
                              className="rounded border-slate-300 text-emerald-600 focus:ring-emerald-500 disabled:opacity-40"
                            />
                          </td>
                          <td className="py-2 px-3 font-mono font-bold text-slate-900 tabular-nums">
                            <div>{item.phone}</div>
                            {item.raw_phone !== item.phone && (
                              <div className="text-[10px] text-slate-400 font-normal">
                                Gốc: {item.raw_phone}
                              </div>
                            )}
                          </td>
                          <td className="py-2 px-3">
                            {!item.is_valid ? (
                              <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-semibold bg-rose-50 text-rose-700 border border-rose-200">
                                {item.validation_note}
                              </span>
                            ) : item.is_duplicate ? (
                              <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-semibold bg-amber-50 text-amber-700 border border-amber-200">
                                Trùng SĐT
                              </span>
                            ) : item.is_skipped_source ? (
                              <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-semibold bg-orange-50 text-orange-700 border border-orange-200">
                                Nguồn loại trừ
                              </span>
                            ) : item.already_added ? (
                              <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-semibold bg-blue-50 text-blue-700 border border-blue-200">
                                Đã kết bạn cũ
                              </span>
                            ) : (
                              <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-semibold bg-emerald-50 text-emerald-700 border border-emerald-200">
                                Sẵn sàng
                              </span>
                            )}
                          </td>
                          <td className="py-2 px-3 text-slate-800 font-medium">
                            {item.name || <span className="text-slate-400">-</span>}
                          </td>
                          <td className="py-2 px-3">
                            {item.source ? (
                              <span className="px-2 py-0.5 rounded-md bg-slate-100 text-slate-700 text-[11px] font-mono">
                                {item.source}
                              </span>
                            ) : (
                              <span className="text-slate-400">-</span>
                            )}
                          </td>
                          <td className="py-2 px-3 text-slate-600 max-w-[160px] truncate">
                            {item.nhu_cau || <span className="text-slate-400">-</span>}
                          </td>
                          <td
                            className="py-2 px-3 text-slate-600 max-w-xs truncate"
                            title={item.rendered_message}
                          >
                            {item.rendered_message}
                          </td>
                          <td className="py-2 px-3 text-right">
                            <button
                              type="button"
                              onClick={() => handleRemovePreviewItem(idx, item.phone)}
                              className="p-1 rounded-lg text-slate-400 hover:text-rose-600 hover:bg-rose-50 transition-colors"
                              aria-label={`Xóa dòng số ${item.phone}`}
                            >
                              <Trash2 className="w-3.5 h-3.5" />
                            </button>
                          </td>
                        </tr>
                      );
                    })
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </>
      ) : (
        /* SUB-TAB: LỊCH SỬ KẾT BẠN TỰ ĐỘNG */
        <div className="bg-white rounded-2xl border border-slate-200/80 shadow-sm p-5 space-y-4">
          <div className="flex items-center justify-between">
            <div>
              <h3 id="history-table-heading" className="text-sm font-bold text-slate-900">
                Lịch Sử Các Lượt Kết Bạn Tự Động Đã Thực Hiện
              </h3>
              <p className="text-xs text-slate-500">
                Lưu vết đầy đủ SĐT, Page Zalo thực hiện, lời chào đã gửi và trạng thái phản hồi từ Pancake
              </p>
            </div>
            <button
              type="button"
              onClick={loadHistory}
              disabled={loadingHistory}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-slate-100 hover:bg-slate-200 text-slate-700 text-xs font-semibold"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${loadingHistory ? 'animate-spin' : ''}`} />
              Làm mới
            </button>
          </div>

          <div
            className="overflow-x-auto max-h-[540px] border border-slate-200 rounded-xl"
            tabIndex={0}
            role="region"
            aria-labelledby="history-table-heading"
          >
            <table className="w-full text-left border-collapse text-xs">
              <thead className="sticky top-0 z-10 bg-slate-100 text-slate-700 border-b border-slate-200">
                <tr>
                  <th className="py-2.5 px-3 font-semibold">Thời gian</th>
                  <th className="py-2.5 px-3 font-semibold">Chiến dịch</th>
                  <th className="py-2.5 px-3 font-semibold">SĐT</th>
                  <th className="py-2.5 px-3 font-semibold">Page Zalo</th>
                  <th className="py-2.5 px-3 font-semibold">Thông tin & Tag</th>
                  <th className="py-2.5 px-3 font-semibold">Lời chào đã gửi</th>
                  <th className="py-2.5 px-3 font-semibold">Trạng thái</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {historyItems.length === 0 ? (
                  <tr>
                    <td colSpan={7} className="py-10 text-center text-slate-400">
                      {loadingHistory ? 'Đang tải lịch sử...' : 'Chưa có lịch sử kết bạn tự động nào.'}
                    </td>
                  </tr>
                ) : (
                  historyItems.map((h) => (
                    <tr key={h.id} className="hover:bg-slate-50">
                      <td className="py-2.5 px-3 tabular-nums text-slate-500 whitespace-nowrap">
                        {h.sent_at}
                      </td>
                      <td className="py-2.5 px-3 font-medium text-slate-800">{h.campaign_name}</td>
                      <td className="py-2.5 px-3 font-mono font-bold text-slate-900 tabular-nums">
                        {h.phone}
                      </td>
                      <td className="py-2.5 px-3 text-emerald-700 font-semibold">{h.page_name}</td>
                      <td className="py-2.5 px-3 text-slate-600 max-w-xs truncate" title={h.customer_info}>
                        {h.customer_info}
                      </td>
                      <td className="py-2.5 px-3 text-slate-600 max-w-xs truncate" title={h.message}>
                        {h.message}
                      </td>
                      <td className="py-2.5 px-3">
                        <span
                          className={`inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-semibold ${
                            h.status === 'SENT' || h.status === 'ADDED'
                              ? 'bg-emerald-50 text-emerald-700 border border-emerald-200'
                              : h.status === 'DRY_RUN'
                              ? 'bg-amber-50 text-amber-700 border border-amber-200'
                              : 'bg-rose-50 text-rose-700 border border-rose-200'
                          }`}
                          title={h.detail}
                        >
                          {h.status === 'SENT' ? 'ADDED' : h.status}
                        </span>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* MODAL CẤU HÌNH PHIÊN ĐĂNG NHẬP PANCAKE (`pancake_state.json`) */}
      {showStateModal && (
        <div className="fixed inset-0 z-50 bg-slate-900/50 backdrop-blur-xs flex items-center justify-center p-4">
          <div className="bg-white rounded-2xl max-w-xl w-full p-6 shadow-xl border border-slate-200 space-y-4">
            <div className="flex items-start justify-between gap-3">
              <div>
                <h3 className="text-base font-bold text-slate-900 flex items-center gap-2">
                  <Database className="w-4 h-4 text-emerald-600" />
                  Lưu Bền Vững pancake_state.json Vào Database (app_configs)
                </h3>
                <p className="text-xs text-slate-500 mt-1">
                  Dữ liệu được lưu trực tiếp vào bảng <code className="text-emerald-700 font-semibold">app_configs</code> trên Neon PostgreSQL, không bao giờ bị mất khi khởi động lại server hay deploy trên Render.
                </p>
              </div>
              <button
                type="button"
                onClick={() => setShowStateModal(false)}
                className="text-slate-400 hover:text-slate-700"
                aria-label="Đóng hộp thoại"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            {/* Current State Status in Database */}
            {config?.state_info?.has_state ? (
              <div className="p-3 rounded-xl bg-emerald-50/80 border border-emerald-200 text-xs space-y-2">
                <div className="flex items-center justify-between">
                  <div className="font-bold text-emerald-900 flex items-center gap-1.5">
                    <CheckCircle2 className="w-4 h-4 text-emerald-600 shrink-0" />
                    <span>Đã lưu bền vững trong bảng app_configs (Neon DB)</span>
                  </div>
                  <span className="text-[10px] bg-emerald-200 text-emerald-800 font-mono px-2 py-0.5 rounded">
                    {config.state_info.storage_key || 'PANCAKE_STORAGE_STATE'}
                  </span>
                </div>
                <div className="grid grid-cols-3 gap-2 text-[11px] text-emerald-800">
                  <div>Cookies: <span className="font-bold tabular-nums">{config.state_info.cookies_count}</span></div>
                  <div>Origins: <span className="font-bold tabular-nums">{config.state_info.origins_count}</span></div>
                  <div>Cập nhật: <span className="font-medium">{config.state_info.updated_at || 'Mới cập nhật'}</span></div>
                </div>
                <div className="flex items-center gap-2 pt-1 border-t border-emerald-200/60">
                  <button
                    type="button"
                    onClick={handleDownloadStateJson}
                    className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg bg-white border border-emerald-300 text-emerald-800 text-[11px] font-semibold hover:bg-emerald-100"
                  >
                    <Download className="w-3 h-3" />
                    Tải file pancake_state.json
                  </button>
                  <button
                    type="button"
                    onClick={handleCopyStateJson}
                    className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg bg-white border border-emerald-300 text-emerald-800 text-[11px] font-semibold hover:bg-emerald-100"
                  >
                    {copiedState ? <Check className="w-3 h-3 text-emerald-600" /> : <Copy className="w-3 h-3" />}
                    {copiedState ? 'Đã sao chép!' : 'Sao chép JSON'}
                  </button>
                  <button
                    type="button"
                    onClick={handleDeletePancakeState}
                    className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg bg-rose-50 border border-rose-200 text-rose-700 text-[11px] font-semibold hover:bg-rose-100 ml-auto"
                  >
                    <Trash2 className="w-3 h-3" />
                    Xóa phiên
                  </button>
                </div>
              </div>
            ) : (
              <div className="p-3 rounded-xl bg-amber-50 border border-amber-200 text-xs text-amber-800 flex items-start gap-2">
                <AlertTriangle className="w-4 h-4 shrink-0 text-amber-600 mt-0.5" />
                <div>
                  <div className="font-bold">Chưa có phiên đăng nhập trong bảng app_configs</div>
                  <div className="text-[11px] mt-0.5">
                    Hãy dán nội dung JSON hoặc tải file <code className="font-semibold">pancake_state.json</code> bên dưới để lưu bền vững vào Database.
                  </div>
                </div>
              </div>
            )}

            <div className="flex items-center justify-between">
              <label
                htmlFor="pancake-state-json-textarea"
                className="text-xs font-semibold text-slate-700"
              >
                Dán nội dung JSON mới hoặc tải file <code className="text-emerald-700">pancake_state.json</code>:
              </label>
              <label className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-slate-100 hover:bg-slate-200 text-slate-700 text-xs font-semibold cursor-pointer">
                <Upload className="w-3.5 h-3.5" />
                Chọn file JSON
                <input
                  type="file"
                  accept=".json"
                  onChange={handleStateFileUpload}
                  className="hidden"
                />
              </label>
            </div>

            <textarea
              id="pancake-state-json-textarea"
              rows={7}
              value={stateJsonInput}
              spellCheck={false}
              autoCorrect="off"
              onChange={(e) => setStateJsonInput(e.target.value)}
              placeholder='{"cookies": [...], "origins": [...]}'
              className="w-full rounded-xl border border-slate-300 bg-slate-50 p-3 text-xs font-mono text-slate-800 focus:bg-white focus:border-emerald-500 outline-none"
            />
            {loadingRawState && (
              <p className="text-[11px] text-slate-400">Đang tải dữ liệu JSON từ Database...</p>
            )}

            {stateFeedback && (
              <div
                className={`p-3 rounded-xl text-xs font-medium ${
                  stateFeedback.type === 'success'
                    ? 'bg-emerald-50 text-emerald-800 border border-emerald-200'
                    : 'bg-rose-50 text-rose-800 border border-rose-200'
                }`}
              >
                {stateFeedback.text}
              </div>
            )}

            <div className="flex items-center justify-end gap-2 pt-2">
              <button
                type="button"
                onClick={() => setShowStateModal(false)}
                className="px-4 py-2 rounded-xl border border-slate-200 text-xs font-semibold text-slate-600 hover:bg-slate-50"
              >
                Đóng
              </button>
              <button
                type="button"
                disabled={savingState}
                onClick={handleSavePancakeState}
                className="px-4 py-2 rounded-xl bg-emerald-600 hover:bg-emerald-700 text-white text-xs font-bold shadow-sm disabled:opacity-50 flex items-center gap-1.5"
              >
                <Database className="w-3.5 h-3.5" />
                {savingState ? 'Đang lưu vào DB...' : 'Lưu Bền Vững Vào app_configs'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
