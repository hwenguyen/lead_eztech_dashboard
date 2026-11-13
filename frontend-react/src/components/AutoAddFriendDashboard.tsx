import React, { useState, useEffect, useRef, useMemo } from 'react';
import {
  UserPlus,
  Upload,
  Play,
  Square,
  ShieldCheck,
  Tag,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  RefreshCw,
  Trash2,
  Key,
  History,
  Download,
  Check,
  Plus,
  Database,
  Copy,
  X
} from 'lucide-react';
import {
  fetchAddFriendConfig,
  fetchPancakeStateRaw,
  savePancakeStateJson,
  deletePancakeState,
  fetchLeadsWithPhonesForAddFriend,
  startAddFriendCampaign,
  fetchActiveAddFriendTask,
  fetchAddFriendStatus,
  stopAddFriendCampaign,
  fetchAddFriendHistory,
  type AddFriendConfigResponse,
  type RateLimitSettings,
  type AddFriendTaskStatus,
  type AddFriendHistoryItem
} from '../services/api';

const ACTIVE_TASK_STORAGE_KEY = 'addfriend_active_task_id';

const DEFAULT_PAGES = [
  'Eztech Consultant',
  'Eztech Phân Tích Dữ Liệu',
  'Hiền Minh Eztech',
  'Tuấn Anh Data',
  'Ann'
];

interface ParsedPhone {
  raw: string;
  phone: string;
  valid: boolean;
  duplicate: boolean;
}

function parsePhonesClient(rawText: string): ParsedPhone[] {
  const tokens = rawText
    .split(/[\r\n,;|\t]+/)
    .map((s) => s.trim())
    .filter(Boolean);

  const seen = new Set<string>();
  const result: ParsedPhone[] = [];

  for (const token of tokens) {
    // Bỏ qua dòng tiêu đề nếu có
    if (/^(sđt|sdt|phone|số điện thoại)$/i.test(token)) continue;

    let digits = token.replace(/\D/g, '');
    if (!digits) continue;

    if (digits.startsWith('84') && digits.length >= 10) {
      digits = '0' + digits.slice(2);
    } else if (digits.length === 9 && /^[35789]/.test(digits)) {
      digits = '0' + digits;
    }

    const valid = /^0[35789]\d{8}$/.test(digits);
    const duplicate = valid && seen.has(digits);
    if (valid && !duplicate) {
      seen.add(digits);
    }

    result.push({
      raw: token,
      phone: digits,
      valid,
      duplicate
    });
  }

  return result;
}

export const AutoAddFriendDashboard: React.FC = () => {
  const [subTab, setSubTab] = useState<'workspace' | 'history'>('workspace');
  const [config, setConfig] = useState<AddFriendConfigResponse | null>(null);

  // Modal Phiên Pancake (pancake_state.json)
  const [showStateModal, setShowStateModal] = useState(false);
  const [stateJsonInput, setStateJsonInput] = useState('');
  const [savingState, setSavingState] = useState(false);
  const [loadingRawState, setLoadingRawState] = useState(false);
  const [copiedState, setCopiedState] = useState(false);
  const [stateFeedback, setStateFeedback] = useState<{ type: 'success' | 'error'; text: string } | null>(null);

  // 1. Danh sách SĐT & Bộ lọc lấy từ DB
  const [rawPhoneText, setRawPhoneText] = useState('');
  const [phoneError, setPhoneError] = useState<string | null>(null);
  const [loadingLeads, setLoadingLeads] = useState(false);
  const [filterEmployee, setFilterEmployee] = useState('');
  const [filterSourcePage, setFilterSourcePage] = useState('');
  const [filterLeadTag, setFilterLeadTag] = useState('');
  const [excludeAddedTag, setExcludeAddedTag] = useState(true);
  const [leadMetaMap, setLeadMetaMap] = useState<
    Record<string, { name: string; source: string; nhu_cau: string }>
  >({});
  const fileInputRef = useRef<HTMLInputElement>(null);

  // 2. Page, Tin nhắn chào & Tag
  const [selectedPage, setSelectedPage] = useState('Eztech Consultant');
  const [selectedTemplateKey, setSelectedTemplateKey] = useState('default');
  const [messageTemplate, setMessageTemplate] = useState(
    'Chào bạn, mình là {page}. Mình xin phép kết bạn để trao đổi chi tiết hơn về dịch vụ bên mình nhé ạ!'
  );
  const [sendInboxMessage, setSendInboxMessage] = useState(true);
  const [selectedTags, setSelectedTags] = useState<string[]>([]);
  const [customTagInput, setCustomTagInput] = useState('');
  const [customTagsByPage, setCustomTagsByPage] = useState<Record<string, string[]>>({});

  // 3. Rate Limit
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
  const [dryRun, setDryRun] = useState(false);

  // 4. Trạng thái chạy
  const [activeTaskId, setActiveTaskId] = useState<string | null>(null);
  const [taskStatus, setTaskStatus] = useState<AddFriendTaskStatus | null>(null);
  const [starting, setStarting] = useState(false);
  const [banner, setBanner] = useState<{ type: 'error' | 'success' | 'info'; text: string } | null>(null);

  // Lịch sử
  const [historyItems, setHistoryItems] = useState<AddFriendHistoryItem[]>([]);
  const [loadingHistory, setLoadingHistory] = useState(false);

  // Phân tích SĐT tức thì
  const parsedList = useMemo(() => parsePhonesClient(rawPhoneText), [rawPhoneText]);
  const validPhones = useMemo(
    () => parsedList.filter((p) => p.valid && !p.duplicate).map((p) => p.phone),
    [parsedList]
  );
  const duplicateCount = useMemo(() => parsedList.filter((p) => p.duplicate).length, [parsedList]);
  const invalidCount = useMemo(() => parsedList.filter((p) => !p.valid).length, [parsedList]);

  useEffect(() => {
    fetchAddFriendConfig()
      .then((data) => setConfig(data))
      .catch(() => {});

    fetchActiveAddFriendTask()
      .then((res) => {
        if (res.active) {
          setTaskStatus(res.active);
          if (res.active.is_running) {
            setActiveTaskId(res.active.task_id);
            localStorage.setItem(ACTIVE_TASK_STORAGE_KEY, res.active.task_id);
          } else {
            localStorage.removeItem(ACTIVE_TASK_STORAGE_KEY);
          }
          return;
        }
        const savedId = localStorage.getItem(ACTIVE_TASK_STORAGE_KEY);
        if (savedId) setActiveTaskId(savedId);
      })
      .catch(() => {
        const savedId = localStorage.getItem(ACTIVE_TASK_STORAGE_KEY);
        if (savedId) setActiveTaskId(savedId);
      });
  }, []);

  useEffect(() => {
    if (!activeTaskId) return;
    let cancelled = false;
    let timer: ReturnType<typeof setInterval> | null = null;
    const poll = async () => {
      try {
        const st = await fetchAddFriendStatus(activeTaskId);
        if (cancelled) return;
        setTaskStatus(st);
        if (!st.is_running) {
          if (timer) clearInterval(timer);
          localStorage.removeItem(ACTIVE_TASK_STORAGE_KEY);
          setActiveTaskId(null);
        }
      } catch (err: any) {
        if (cancelled) return;
        if (err?.response?.status === 404) {
          if (timer) clearInterval(timer);
          localStorage.removeItem(ACTIVE_TASK_STORAGE_KEY);
          setActiveTaskId(null);
        }
      }
    };
    poll();
    timer = setInterval(poll, 1500);
    return () => {
      cancelled = true;
      if (timer) clearInterval(timer);
    };
  }, [activeTaskId]);

  const loadHistory = async () => {
    setLoadingHistory(true);
    try {
      const res = await fetchAddFriendHistory(100);
      setHistoryItems(res.items || []);
    } finally {
      setLoadingHistory(false);
    }
  };

  useEffect(() => {
    if (subTab === 'history') loadHistory();
  }, [subTab]);

  const handleApplyPreset = (preset: 'fast' | 'recommended' | 'ultra') => {
    if (preset === 'fast') {
      setRateLimit((p) => ({ ...p, preset, delay_min: 5, delay_max: 10, batch_size: 15, batch_pause_sec: 30 }));
    } else if (preset === 'recommended') {
      setRateLimit((p) => ({ ...p, preset, delay_min: 8, delay_max: 16, batch_size: 10, batch_pause_sec: 45 }));
    } else {
      setRateLimit((p) => ({ ...p, preset, delay_min: 18, delay_max: 30, batch_size: 8, batch_pause_sec: 90 }));
    }
  };

  const handleFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (ev) => {
      const text = String(ev.target?.result || '');
      // Chỉ giữ cột đầu tiên nếu là file CSV nhiều cột
      const onlyPhones = text
        .split(/\r?\n/)
        .map((line) => line.split(/[\t,;]/)[0]?.trim())
        .filter(Boolean)
        .join('\n');
      setRawPhoneText(onlyPhones);
      setPhoneError(null);
    };
    reader.readAsText(file, 'utf-8');
    e.target.value = '';
  };

  const handlePullLeadsPhones = async (channel: 'all' | 'tiktok') => {
    setLoadingLeads(true);
    setBanner(null);
    try {
      const res = await fetchLeadsWithPhonesForAddFriend({
        sourceChannel: channel,
        employee: filterEmployee || undefined,
        sourcePage: filterSourcePage || undefined,
        tag: filterLeadTag || undefined,
        excludeAddedTag,
        limit: 50
      });
      if (!res.items || res.count === 0) {
        setBanner({ type: 'info', text: 'Không tìm thấy SĐT phù hợp bộ lọc (hoặc đã có tag Đã add / đã chạy).' });
        return;
      }
      const nextMeta: Record<string, { name: string; source: string; nhu_cau: string }> = {};
      for (const it of res.items) {
        nextMeta[it.phone] = { name: it.name, source: it.source, nhu_cau: it.nhu_cau };
      }
      setLeadMetaMap(nextMeta);
      setRawPhoneText(res.items.map((it) => it.phone).join('\n'));
      setPhoneError(null);
      setBanner({ type: 'success', text: `Đã nạp ${res.count} số điện thoại từ DB.` });
    } catch {
      setBanner({ type: 'error', text: 'Không thể tải SĐT từ hệ thống.' });
    } finally {
      setLoadingLeads(false);
    }
  };

  const handleRemovePhone = (phoneToRemove: string) => {
    const remaining = validPhones.filter((p) => p !== phoneToRemove);
    setRawPhoneText(remaining.join('\n'));
  };

  const handleKeepCleanOnly = () => {
    setRawPhoneText(validPhones.join('\n'));
  };

  const handleSelectPage = (pg: string) => {
    setSelectedPage(pg);
    const nextPageTags = [
      ...(config?.tags_by_page?.[pg] || []),
      ...(customTagsByPage[pg] || [])
    ];
    const nextLower = new Set(nextPageTags.map((t) => t.toLowerCase()));
    setSelectedTags((prev) => prev.filter((t) => nextLower.has(t.toLowerCase())));
  };

  const handleToggleTag = (tag: string) => {
    setSelectedTags((prev) => (prev.includes(tag) ? prev.filter((t) => t !== tag) : [...prev, tag]));
  };

  const handleAddCustomTag = () => {
    const clean = customTagInput.trim();
    if (!clean) return;
    setCustomTagsByPage((prev) => {
      const existing = prev[selectedPage] || [];
      if (existing.includes(clean)) return prev;
      return { ...prev, [selectedPage]: [...existing, clean] };
    });
    if (!selectedTags.includes(clean)) setSelectedTags((prev) => [...prev, clean]);
    setCustomTagInput('');
  };

  const handleOpenStateModal = async () => {
    setShowStateModal(true);
    setStateFeedback(null);
    setCopiedState(false);
    if (!stateJsonInput.trim()) {
      setLoadingRawState(true);
      try {
        const res = await fetchPancakeStateRaw();
        if (res.state_json) setStateJsonInput(res.state_json);
      } catch {
        // ignore
      } finally {
        setLoadingRawState(false);
      }
    }
  };

  const handleSavePancakeState = async () => {
    if (!stateJsonInput.trim()) {
      setStateFeedback({ type: 'error', text: 'Vui lòng dán JSON pancake_state.json.' });
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
      }, 900);
    } catch (err: any) {
      setStateFeedback({
        type: 'error',
        text: err?.response?.data?.detail || 'JSON không hợp lệ.'
      });
    } finally {
      setSavingState(false);
    }
  };

  const handleDeletePancakeState = async () => {
    if (!window.confirm('Xóa phiên đăng nhập Pancake khỏi Database?')) return;
    setSavingState(true);
    try {
      const res = await deletePancakeState();
      setConfig((prev) => (prev ? { ...prev, state_info: res.state_info } : prev));
      setStateJsonInput('');
      setStateFeedback({ type: 'success', text: res.message });
    } finally {
      setSavingState(false);
    }
  };

  const handleStart = async () => {
    setBanner(null);
    if (validPhones.length === 0) {
      setPhoneError('Vui lòng nhập ít nhất 1 số điện thoại hợp lệ.');
      return;
    }
    if (!dryRun && !config?.state_info?.has_state) {
      handleOpenStateModal();
      setBanner({ type: 'error', text: 'Vui lòng lưu phiên Pancake (pancake_state.json) trước khi chạy thật.' });
      return;
    }

    // Nếu người dùng đã gõ tag vào ô nhập nhưng chưa bấm nút '+', tự động gộp vào danh sách tag
    const pendingTag = customTagInput.trim();
    const tagsToSend = pendingTag && !selectedTags.includes(pendingTag)
      ? [...selectedTags, pendingTag]
      : selectedTags;
    if (pendingTag) {
      setCustomTagsByPage((prev) => {
        const existing = prev[selectedPage] || [];
        return existing.includes(pendingTag) ? prev : { ...prev, [selectedPage]: [...existing, pendingTag] };
      });
      setSelectedTags(tagsToSend);
      setCustomTagInput('');
    }

    setStarting(true);
    setTaskStatus(null);
    try {
      const res = await startAddFriendCampaign({
        campaign_name: `ketban_${new Date().toISOString().slice(0, 10).replace(/-/g, '')}`,
        page_name: selectedPage,
        items: validPhones.map((phone) => {
          const meta = leadMetaMap[phone];
          return {
            phone,
            name: meta?.name || '',
            source: meta?.source || '',
            nhu_cau: meta?.nhu_cau || ''
          };
        }),
        message_template: messageTemplate,
        inbox_message_template: messageTemplate,
        use_source_template: false,
        send_inbox_message: sendInboxMessage,
        add_note: false,
        note_template: '',
        tags: tagsToSend,
        rate_limit: rateLimit,
        dry_run: dryRun
      });
      localStorage.setItem(ACTIVE_TASK_STORAGE_KEY, res.task_id);
      setActiveTaskId(res.task_id);
    } catch (err: any) {
      setBanner({
        type: 'error',
        text: err?.response?.data?.detail || 'Không thể bắt đầu chiến dịch.'
      });
    } finally {
      setStarting(false);
    }
  };

  const handleExportLogsCsv = () => {
    if (!taskStatus?.logs.length) return;
    const rows = taskStatus.logs.map((l) => [
      l.index,
      `"'${l.phone}"`,
      `"${l.page_name}"`,
      l.status,
      `"${(l.detail || '').replace(/"/g, '""')}"`,
      l.time
    ]);
    const csv = '\uFEFFSTT,SĐT,Page,Trạng thái,Chi tiết,Thời gian\n' + rows.map((r) => r.join(',')).join('\n');
    const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8;' }));
    const a = document.createElement('a');
    a.href = url;
    a.download = `ket_ban_${taskStatus.campaign_name}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const availableTags = useMemo(() => {
    const pageTags = config?.tags_by_page?.[selectedPage] || [];
    const customForPage = customTagsByPage[selectedPage] || [];
    return Array.from(new Set([...pageTags, ...customForPage]));
  }, [config, selectedPage, customTagsByPage]);

  const pagesList = config?.pages?.map((p) => p.name) || DEFAULT_PAGES;
  const renderedPreview = messageTemplate.replace(/\{page\}/g, selectedPage);

  return (
    <div className="space-y-5 max-w-6xl mx-auto">
      {/* HEADER GỌN GÀNG */}
      <div className="bg-white rounded-2xl border border-slate-200/80 shadow-xs px-5 py-4 flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-emerald-600 text-white flex items-center justify-center shrink-0">
            <UserPlus className="w-5 h-5" />
          </div>
          <div>
            <h2 className="text-base font-bold text-slate-900">Kết Bạn Zalo Tự Động</h2>
            <p className="text-xs text-slate-500">Dán danh sách SĐT • Chọn Page • Tự động kết bạn & gắn Tag</p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={handleOpenStateModal}
            className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-semibold border transition-colors cursor-pointer ${
              config?.state_info?.has_state
                ? 'bg-emerald-50 text-emerald-800 border-emerald-200 hover:bg-emerald-100'
                : 'bg-amber-50 text-amber-800 border-amber-300 hover:bg-amber-100'
            }`}
          >
            <Key className="w-3.5 h-3.5" />
            {config?.state_info?.has_state ? 'Phiên Pancake: Đã kết nối' : 'Cài đặt Phiên Pancake'}
          </button>

          <div className="inline-flex rounded-xl bg-slate-100 p-1 border border-slate-200">
            <button
              type="button"
              onClick={() => setSubTab('workspace')}
              className={`px-3 py-1 rounded-lg text-xs font-semibold transition-all cursor-pointer ${
                subTab === 'workspace' ? 'bg-white text-slate-900 shadow-xs' : 'text-slate-600 hover:text-slate-900'
              }`}
            >
              Kết Bạn
            </button>
            <button
              type="button"
              onClick={() => setSubTab('history')}
              className={`inline-flex items-center gap-1 px-3 py-1 rounded-lg text-xs font-semibold transition-all cursor-pointer ${
                subTab === 'history' ? 'bg-white text-slate-900 shadow-xs' : 'text-slate-600 hover:text-slate-900'
              }`}
            >
              <History className="w-3.5 h-3.5" />
              Lịch Sử
            </button>
          </div>
        </div>
      </div>

      {banner && (
        <div
          className={`flex items-center justify-between px-4 py-2.5 rounded-xl border text-xs font-medium ${
            banner.type === 'error'
              ? 'bg-rose-50 border-rose-200 text-rose-800'
              : banner.type === 'success'
              ? 'bg-emerald-50 border-emerald-200 text-emerald-800'
              : 'bg-blue-50 border-blue-200 text-blue-800'
          }`}
        >
          <span>{banner.text}</span>
          <button type="button" onClick={() => setBanner(null)} aria-label="Đóng thông báo">
            <X className="w-4 h-4" />
          </button>
        </div>
      )}

      {subTab === 'workspace' ? (
        <>
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-5">
            {/* CỘT TRÁI (5 cols): NHẬP SỐ ĐIỆN THOẠI (CHỈ SĐT) */}
            <div className="lg:col-span-5 bg-white rounded-2xl border border-slate-200/80 shadow-xs p-5 flex flex-col justify-between space-y-4">
              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <label htmlFor="phone-list-input" className="text-sm font-bold text-slate-900">
                    1. Danh Sách Số Điện Thoại
                  </label>
                  <div className="flex items-center gap-1.5">
                    <input
                      ref={fileInputRef}
                      type="file"
                      accept=".txt,.csv"
                      onChange={handleFileUpload}
                      className="hidden"
                    />
                    <button
                      type="button"
                      onClick={() => fileInputRef.current?.click()}
                      className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg text-xs font-semibold bg-slate-100 hover:bg-slate-200 text-slate-700 cursor-pointer"
                    >
                      <Upload className="w-3.5 h-3.5" />
                      File
                    </button>
                    <button
                      type="button"
                      disabled={loadingLeads}
                      onClick={() => handlePullLeadsPhones('tiktok')}
                      className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg text-xs font-semibold bg-indigo-50 hover:bg-indigo-100 text-indigo-700 cursor-pointer disabled:opacity-50"
                    >
                      <Database className="w-3.5 h-3.5" />
                      SĐT TikTok
                    </button>
                    <button
                      type="button"
                      disabled={loadingLeads}
                      onClick={() => handlePullLeadsPhones('all')}
                      className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg text-xs font-semibold bg-emerald-50 hover:bg-emerald-100 text-emerald-700 cursor-pointer disabled:opacity-50"
                    >
                      {loadingLeads ? 'Đang lấy...' : 'Lấy SĐT'}
                    </button>
                  </div>
                </div>

                {/* Bộ lọc lấy SĐT từ DB */}
                <div className="rounded-xl border border-slate-200 bg-slate-50/80 p-2.5 space-y-2">
                  <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
                    <select
                      aria-label="Lọc theo Nhân viên"
                      value={filterEmployee}
                      onChange={(e) => setFilterEmployee(e.target.value)}
                      className="w-full rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-xs text-slate-700 outline-none focus:border-emerald-500"
                    >
                      <option value="">Tất cả Nhân viên</option>
                      <option value="__unassigned__">Chưa phân công</option>
                      {(config?.lead_filters?.employees || []).map((emp) => (
                        <option key={emp} value={emp}>
                          {emp}
                        </option>
                      ))}
                    </select>

                    <select
                      aria-label="Lọc theo Page Nguồn"
                      value={filterSourcePage}
                      onChange={(e) => setFilterSourcePage(e.target.value)}
                      className="w-full rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-xs text-slate-700 outline-none focus:border-emerald-500"
                    >
                      <option value="">Tất cả Page nguồn</option>
                      {(config?.lead_filters?.source_pages || []).map((pg) => (
                        <option key={pg} value={pg}>
                          {pg}
                        </option>
                      ))}
                    </select>

                    <select
                      aria-label="Lọc theo Tag"
                      value={filterLeadTag}
                      onChange={(e) => setFilterLeadTag(e.target.value)}
                      className="w-full rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-xs text-slate-700 outline-none focus:border-emerald-500"
                    >
                      <option value="">Tất cả Tag</option>
                      <option value="__no_tag__">Chưa có tag</option>
                      {(config?.lead_filters?.lead_tags || []).map((t) => (
                        <option key={t} value={t}>
                          {t}
                        </option>
                      ))}
                    </select>
                  </div>

                  <div className="flex items-center justify-between gap-2">
                    <label className="inline-flex items-center gap-1.5 text-xs text-slate-700 cursor-pointer select-none">
                      <input
                        type="checkbox"
                        checked={excludeAddedTag}
                        onChange={(e) => setExcludeAddedTag(e.target.checked)}
                        className="w-3.5 h-3.5 accent-emerald-600 rounded"
                      />
                      <span>Chỉ lấy số chưa có tag &quot;Đã add&quot;</span>
                    </label>
                    <button
                      type="button"
                      disabled={loadingLeads}
                      onClick={() => handlePullLeadsPhones('all')}
                      className="text-[11px] font-semibold text-emerald-700 hover:underline cursor-pointer disabled:opacity-50"
                    >
                      Áp dụng &amp; Tải danh sách
                    </button>
                  </div>
                </div>

                <textarea
                  id="phone-list-input"
                  rows={9}
                  value={rawPhoneText}
                  spellCheck={false}
                  autoCorrect="off"
                  onChange={(e) => {
                    setRawPhoneText(e.target.value);
                    if (phoneError) setPhoneError(null);
                  }}
                  onBlur={() => {
                    if (rawPhoneText.trim() && validPhones.length === 0) {
                      setPhoneError('Không tìm thấy số điện thoại hợp lệ (10 số).');
                    }
                  }}
                  placeholder={'Dán danh sách SĐT (mỗi dòng 1 số):\n0987654321\n0912345678\n84905112233'}
                  className="w-full rounded-xl border border-slate-300 bg-slate-50/60 px-3.5 py-2.5 text-sm font-mono text-slate-800 focus:bg-white focus:border-emerald-500 focus:ring-2 focus:ring-emerald-500/15 outline-none transition-all"
                />

                {phoneError && <p className="text-xs text-rose-600 font-medium">{phoneError}</p>}

                {/* Thống kê SĐT gọn */}
                <div className="flex items-center justify-between flex-wrap gap-2 pt-1">
                  <div className="flex items-center gap-2 text-xs">
                    <span className="px-2.5 py-1 rounded-lg bg-emerald-50 text-emerald-700 font-bold border border-emerald-200 tabular-nums">
                      Hợp lệ: {validPhones.length} số
                    </span>
                    {duplicateCount > 0 && (
                      <span className="px-2 py-1 rounded-lg bg-amber-50 text-amber-700 font-medium tabular-nums">
                        Trùng: {duplicateCount}
                      </span>
                    )}
                    {invalidCount > 0 && (
                      <span className="px-2 py-1 rounded-lg bg-rose-50 text-rose-700 font-medium tabular-nums">
                        Sai số: {invalidCount}
                      </span>
                    )}
                  </div>

                  <div className="flex items-center gap-2">
                    {(duplicateCount > 0 || invalidCount > 0) && validPhones.length > 0 && (
                      <button
                        type="button"
                        onClick={handleKeepCleanOnly}
                        className="text-xs font-semibold text-emerald-700 hover:underline cursor-pointer"
                      >
                        Lọc sạch số lỗi/trùng
                      </button>
                    )}
                    {rawPhoneText && (
                      <button
                        type="button"
                        onClick={() => setRawPhoneText('')}
                        className="text-xs font-medium text-slate-400 hover:text-rose-600 cursor-pointer"
                      >
                        Xóa hết
                      </button>
                    )}
                  </div>
                </div>
              </div>

              {/* Danh sách chip SĐT đã chuẩn hóa */}
              {validPhones.length > 0 && (
                <div className="pt-3 border-t border-slate-100">
                  <div className="text-[11px] font-medium text-slate-400 mb-2">
                    SĐT sẽ kết bạn (đã tự đổi 84 → 0):
                  </div>
                  <div className="flex flex-wrap gap-1.5 max-h-36 overflow-y-auto pr-1">
                    {validPhones.slice(0, 60).map((phone) => (
                      <span
                        key={phone}
                        className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg bg-slate-100 text-slate-800 text-xs font-mono font-semibold tabular-nums"
                      >
                        {phone}
                        <button
                          type="button"
                          onClick={() => handleRemovePhone(phone)}
                          className="text-slate-400 hover:text-rose-600 cursor-pointer"
                          aria-label={`Xóa số ${phone}`}
                        >
                          <X className="w-3 h-3" />
                        </button>
                      </span>
                    ))}
                    {validPhones.length > 60 && (
                      <span className="px-2 py-1 text-xs text-slate-500">
                        +{validPhones.length - 60} số khác
                      </span>
                    )}
                  </div>
                </div>
              )}
            </div>

            {/* CỘT PHẢI (7 cols): PAGE + TIN NHẮN + TAG + CHỐNG CHẶN */}
            <div className="lg:col-span-7 space-y-5">
              {/* BƯỚC 2: CHỌN PAGE & TIN NHẮN CHÀO */}
              <div className="bg-white rounded-2xl border border-slate-200/80 shadow-xs p-5 space-y-4">
                <div>
                  <span className="block text-sm font-bold text-slate-900 mb-2.5">
                    2. Chọn Page Zalo
                  </span>
                  <div className="flex flex-wrap gap-2">
                    {pagesList.map((pg) => {
                      const active = selectedPage === pg;
                      return (
                        <button
                          key={pg}
                          type="button"
                          onClick={() => handleSelectPage(pg)}
                          className={`inline-flex items-center gap-1.5 px-3.5 py-2 rounded-xl text-xs font-bold border transition-all cursor-pointer ${
                            active
                              ? 'bg-emerald-600 text-white border-emerald-600 shadow-xs'
                              : 'bg-slate-50 text-slate-700 border-slate-200 hover:bg-slate-100'
                          }`}
                        >
                          {active && <Check className="w-3.5 h-3.5" />}
                          <span>{pg}</span>
                        </button>
                      );
                    })}
                  </div>
                </div>

                {/* Tin nhắn chào */}
                <div className="space-y-2 pt-2 border-t border-slate-100">
                  <div className="flex items-center justify-between gap-2">
                    <label htmlFor="greeting-msg" className="text-sm font-bold text-slate-900">
                      3. Lời Chào Kết Bạn
                    </label>
                    <select
                      id="greeting-preset-select"
                      aria-label="Chọn mẫu lời chào"
                      value={selectedTemplateKey}
                      onChange={(e) => {
                        const key = e.target.value;
                        setSelectedTemplateKey(key);
                        const found = config?.templates.find((t) => t.key === key);
                        if (found) setMessageTemplate(found.message);
                      }}
                      className="rounded-lg border border-slate-200 bg-slate-50 px-2.5 py-1 text-xs text-slate-700 outline-none focus:border-emerald-500"
                    >
                      {(config?.templates || [
                        { key: 'default', label: 'Mẫu mặc định', source_key: 'default', message: messageTemplate }
                      ]).map((t) => (
                        <option key={t.key} value={t.key}>
                          {t.label}
                        </option>
                      ))}
                    </select>
                  </div>

                  <textarea
                    id="greeting-msg"
                    rows={2}
                    value={messageTemplate}
                    onChange={(e) => setMessageTemplate(e.target.value)}
                    className="w-full rounded-xl border border-slate-300 px-3 py-2 text-xs text-slate-800 focus:border-emerald-500 outline-none"
                  />

                  <div className="flex items-center justify-between text-[11px] text-slate-500">
                    <label className="inline-flex items-center gap-1.5 cursor-pointer text-slate-700 font-medium">
                      <input
                        type="checkbox"
                        checked={sendInboxMessage}
                        onChange={(e) => setSendInboxMessage(e.target.checked)}
                        className="rounded border-slate-300 text-emerald-600 focus:ring-emerald-500"
                      />
                      <span>Gửi cả vào khung chat sau khi bấm Kết bạn</span>
                    </label>
                    <span className={`tabular-nums ${renderedPreview.length > 150 ? 'text-amber-600 font-semibold' : ''}`}>
                      {renderedPreview.length}/150 ký tự
                    </span>
                  </div>
                </div>

                {/* Gắn Tag */}
                <div className="space-y-2 pt-2 border-t border-slate-100">
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-sm font-bold text-slate-900">
                      4. Gắn Tag{' '}
                      <span className="text-xs font-medium text-indigo-600">({selectedPage})</span>
                    </span>
                    <div className="flex items-center gap-1.5">
                      <label htmlFor="custom-tag" className="sr-only">
                        Tag mới
                      </label>
                      <input
                        id="custom-tag"
                        type="text"
                        value={customTagInput}
                        onChange={(e) => setCustomTagInput(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter') {
                            e.preventDefault();
                            handleAddCustomTag();
                          }
                        }}
                        placeholder="Thêm tag..."
                        className="w-28 rounded-lg border border-slate-200 px-2.5 py-1 text-xs outline-none focus:border-indigo-500"
                      />
                      <button
                        type="button"
                        onClick={handleAddCustomTag}
                        className="p-1 rounded-lg bg-slate-100 hover:bg-slate-200 text-slate-700 cursor-pointer"
                        aria-label="Thêm tag"
                      >
                        <Plus className="w-3.5 h-3.5" />
                      </button>
                    </div>
                  </div>

                  {availableTags.length > 0 ? (
                    <div className="flex flex-wrap gap-1.5">
                      {availableTags.map((tag) => {
                        const active = selectedTags.includes(tag);
                        return (
                          <button
                            key={tag}
                            type="button"
                            onClick={() => handleToggleTag(tag)}
                            className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-lg text-xs font-semibold border transition-all cursor-pointer ${
                              active
                                ? 'bg-indigo-600 text-white border-indigo-600'
                                : 'bg-slate-50 text-slate-600 border-slate-200 hover:bg-slate-100'
                            }`}
                          >
                            <Tag className="w-3 h-3" />
                            <span>{tag}</span>
                          </button>
                        );
                      })}
                    </div>
                  ) : (
                    <p className="text-xs text-slate-400">
                      Chưa tải được tag từ Pancake cho Page &quot;{selectedPage}&quot;. Hãy cấu hình phiên Pancake hoặc nhập tên tag ở trên.
                    </p>
                  )}
                </div>
              </div>

              {/* BƯỚC 5: CHỐNG CHẶN RATE LIMIT & NÚT CHẠY */}
              <div className="bg-white rounded-2xl border border-slate-200/80 shadow-xs p-5 space-y-4">
                <div className="flex items-center justify-between">
                  <span className="text-sm font-bold text-slate-900 flex items-center gap-1.5">
                    <ShieldCheck className="w-4 h-4 text-emerald-600" />
                    5. Tốc Độ & Chống Chặn Rate Limit
                  </span>
                  <div className="inline-flex rounded-lg bg-slate-100 p-0.5 border border-slate-200 text-xs">
                    {[
                      { id: 'fast' as const, label: 'Nhanh' },
                      { id: 'recommended' as const, label: 'An toàn' },
                      { id: 'ultra' as const, label: 'Chậm' }
                    ].map((p) => (
                      <button
                        key={p.id}
                        type="button"
                        onClick={() => handleApplyPreset(p.id)}
                        className={`px-2.5 py-1 rounded-md font-semibold transition-all cursor-pointer ${
                          rateLimit.preset === p.id ? 'bg-white text-emerald-700 shadow-xs' : 'text-slate-600'
                        }`}
                      >
                        {p.label}
                      </button>
                    ))}
                  </div>
                </div>

                <div className="grid grid-cols-3 gap-3">
                  <div>
                    <label htmlFor="rl-min" className="block text-[11px] font-medium text-slate-500 mb-1">
                      Nghỉ mỗi số (giây)
                    </label>
                    <div className="flex items-center gap-1.5">
                      <input
                        id="rl-min"
                        type="number"
                        inputMode="numeric"
                        min={1}
                        value={rateLimit.delay_min}
                        onChange={(e) =>
                          setRateLimit((p) => ({ ...p, preset: 'custom', delay_min: Math.max(1, Number(e.target.value) || 1) }))
                        }
                        className="w-full rounded-lg border border-slate-300 px-2.5 py-1.5 text-xs font-bold text-center tabular-nums"
                      />
                      <span className="text-slate-400">–</span>
                      <input
                        id="rl-max"
                        aria-label="Nghỉ tối đa giữa 2 số"
                        type="number"
                        inputMode="numeric"
                        min={2}
                        value={rateLimit.delay_max}
                        onChange={(e) =>
                          setRateLimit((p) => ({
                            ...p,
                            preset: 'custom',
                            delay_max: Math.max(p.delay_min, Number(e.target.value) || 10)
                          }))
                        }
                        className="w-full rounded-lg border border-slate-300 px-2.5 py-1.5 text-xs font-bold text-center tabular-nums"
                      />
                    </div>
                  </div>

                  <div>
                    <label htmlFor="rl-batch" className="block text-[11px] font-medium text-slate-500 mb-1">
                      Nghỉ {rateLimit.batch_pause_sec}s sau mỗi (số)
                    </label>
                    <input
                      id="rl-batch"
                      type="number"
                      inputMode="numeric"
                      min={1}
                      value={rateLimit.batch_size}
                      onChange={(e) =>
                        setRateLimit((p) => ({ ...p, preset: 'custom', batch_size: Math.max(1, Number(e.target.value) || 10) }))
                      }
                      className="w-full rounded-lg border border-slate-300 px-2.5 py-1.5 text-xs font-bold text-center tabular-nums"
                    />
                  </div>

                  <div>
                    <label htmlFor="rl-limit" className="block text-[11px] font-medium text-slate-500 mb-1">
                      Giới hạn tối đa (số)
                    </label>
                    <input
                      id="rl-limit"
                      type="number"
                      inputMode="numeric"
                      min={1}
                      max={500}
                      value={rateLimit.daily_limit}
                      onChange={(e) =>
                        setRateLimit((p) => ({ ...p, daily_limit: Math.max(1, Number(e.target.value) || 50) }))
                      }
                      className="w-full rounded-lg border border-slate-300 px-2.5 py-1.5 text-xs font-bold text-center tabular-nums"
                    />
                  </div>
                </div>

                {/* Chạy thử + Nút Bắt Đầu */}
                <div className="flex items-center justify-between gap-3 pt-2 border-t border-slate-100">
                  <label className="inline-flex items-center gap-2 text-xs font-medium text-slate-700 cursor-pointer shrink-0">
                    <input
                      type="checkbox"
                      checked={dryRun}
                      onChange={(e) => setDryRun(e.target.checked)}
                      className="rounded border-slate-300 text-amber-600 focus:ring-amber-500"
                    />
                    <span>Chạy thử (Dry-run)</span>
                  </label>

                  <button
                    type="button"
                    disabled={starting || Boolean(taskStatus?.is_running) || validPhones.length === 0}
                    onClick={handleStart}
                    className={`flex-1 py-2.5 px-4 rounded-xl text-xs font-bold text-white shadow-sm flex items-center justify-center gap-2 transition-all cursor-pointer disabled:opacity-50 ${
                      dryRun ? 'bg-amber-600 hover:bg-amber-700' : 'bg-emerald-600 hover:bg-emerald-700'
                    }`}
                  >
                    <Play className="w-4 h-4" />
                    {starting
                      ? 'Đang khởi tạo...'
                      : dryRun
                      ? `Chạy Thử (${validPhones.length} SĐT)`
                      : `Bắt Đầu Kết Bạn (${validPhones.length} SĐT)`}
                  </button>
                </div>
              </div>
            </div>
          </div>

          {/* TIẾN TRÌNH ĐANG CHẠY */}
          {taskStatus && (
            <div className="bg-white rounded-2xl border border-emerald-200 shadow-xs p-5 space-y-4">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="flex items-center gap-2.5">
                  <span
                    className={`w-2.5 h-2.5 rounded-full ${
                      taskStatus.is_running ? 'bg-emerald-500 animate-ping' : 'bg-slate-400'
                    }`}
                  />
                  <div>
                    <h3 id="live-logs-heading" className="text-sm font-bold text-slate-900">
                      Tiến Trình ({taskStatus.page_name})
                    </h3>
                    <p className="text-xs text-emerald-700 font-medium">{taskStatus.current_action}</p>
                  </div>
                </div>

                <div className="flex items-center gap-2">
                  {taskStatus.logs.length > 0 && (
                    <button
                      type="button"
                      onClick={handleExportLogsCsv}
                      className="inline-flex items-center gap-1 px-3 py-1.5 rounded-xl bg-slate-100 hover:bg-slate-200 text-slate-700 text-xs font-semibold cursor-pointer"
                    >
                      <Download className="w-3.5 h-3.5" />
                      Tải CSV
                    </button>
                  )}
                  {taskStatus.is_running && (
                    <button
                      type="button"
                      onClick={() => activeTaskId && stopAddFriendCampaign(activeTaskId)}
                      className="inline-flex items-center gap-1 px-3 py-1.5 rounded-xl bg-rose-600 hover:bg-rose-700 text-white text-xs font-bold cursor-pointer"
                    >
                      <Square className="w-3.5 h-3.5" />
                      Dừng
                    </button>
                  )}
                </div>
              </div>

              <div className="w-full h-2 bg-slate-100 rounded-full overflow-hidden">
                <div
                  className="h-full bg-emerald-600 transition-all duration-300"
                  style={{
                    width: `${
                      taskStatus.total > 0 ? Math.min(100, Math.round((taskStatus.processed / taskStatus.total) * 100)) : 0
                    }%`
                  }}
                />
              </div>

              <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3 text-center">
                <div className="p-2.5 rounded-xl bg-slate-50 border border-slate-200/70">
                  <div className="text-[11px] text-slate-500">Đã chạy</div>
                  <div className="text-sm font-bold text-slate-900 tabular-nums">
                    {taskStatus.processed}/{taskStatus.total}
                  </div>
                </div>
                <div className="p-2.5 rounded-xl bg-emerald-50 border border-emerald-200">
                  <div className="text-[11px] text-emerald-700">Đã gửi kết bạn</div>
                  <div className="text-sm font-bold text-emerald-800 tabular-nums">{taskStatus.added_count}</div>
                </div>
                <div className="p-2.5 rounded-xl bg-sky-50 border border-sky-200">
                  <div className="text-[11px] text-sky-700">Đã là bạn bè</div>
                  <div className="text-sm font-bold text-sky-800 tabular-nums">
                    {taskStatus.already_friend_count ?? 0}
                  </div>
                </div>
                <div className="p-2.5 rounded-xl bg-orange-50 border border-orange-200">
                  <div className="text-[11px] text-orange-700">Thiếu bước</div>
                  <div className="text-sm font-bold text-orange-800 tabular-nums">
                    {taskStatus.partial_count ?? 0}
                  </div>
                </div>
                <div className="p-2.5 rounded-xl bg-amber-50 border border-amber-200">
                  <div className="text-[11px] text-amber-700">Không có Zalo</div>
                  <div className="text-sm font-bold text-amber-800 tabular-nums">{taskStatus.not_found_count}</div>
                </div>
                <div className="p-2.5 rounded-xl bg-rose-50 border border-rose-200">
                  <div className="text-[11px] text-rose-700">Lỗi</div>
                  <div className="text-sm font-bold text-rose-800 tabular-nums">{taskStatus.failed_count}</div>
                </div>
              </div>

              {taskStatus.logs.length > 0 && (
                <div
                  className="overflow-x-auto max-h-64 border border-slate-200 rounded-xl"
                  tabIndex={0}
                  role="region"
                  aria-labelledby="live-logs-heading"
                >
                  <table className="w-full text-left border-collapse text-xs">
                    <thead className="sticky top-0 z-10 bg-slate-100 text-slate-700 border-b border-slate-200">
                      <tr>
                        <th className="py-2 px-3 font-semibold w-12">#</th>
                        <th className="py-2 px-3 font-semibold">Số điện thoại</th>
                        <th className="py-2 px-3 font-semibold">Trạng thái</th>
                        <th className="py-2 px-3 font-semibold">Chi tiết</th>
                        <th className="py-2 px-3 font-semibold text-right">Giờ</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100">
                      {taskStatus.logs.map((log) => (
                        <tr key={`${log.index}-${log.phone}`} className="hover:bg-slate-50">
                          <td className="py-2 px-3 tabular-nums text-slate-400">{log.index}</td>
                          <td className="py-2 px-3 font-mono font-bold text-slate-900 tabular-nums">{log.phone}</td>
                          <td className="py-2 px-3">
                            {log.status === 'ADDED' || log.status === 'DRY_RUN' ? (
                              <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-semibold bg-emerald-50 text-emerald-700">
                                <CheckCircle2 className="w-3 h-3" />
                                {log.status === 'DRY_RUN' ? 'Chạy thử' : 'Đã gửi kết bạn'}
                              </span>
                            ) : log.status === 'ALREADY_FRIEND' ? (
                              <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-semibold bg-sky-50 text-sky-700">
                                <CheckCircle2 className="w-3 h-3" />
                                Đã là bạn bè
                              </span>
                            ) : log.status === 'PARTIAL' ? (
                              <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-semibold bg-orange-50 text-orange-700">
                                <AlertTriangle className="w-3 h-3" />
                                Thiếu bước
                              </span>
                            ) : log.status === 'NOT_FOUND' ? (
                              <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-semibold bg-amber-50 text-amber-700">
                                Không có Zalo
                              </span>
                            ) : (
                              <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-semibold bg-rose-50 text-rose-700">
                                <XCircle className="w-3 h-3" />
                                {log.status}
                              </span>
                            )}
                          </td>
                          <td className="py-2 px-3 text-slate-600 max-w-md break-words">{log.detail}</td>
                          <td className="py-2 px-3 tabular-nums text-slate-400 text-right">{log.time}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}
        </>
      ) : (
        /* TAB LỊCH SỬ GỌN GÀNG */
        <div className="bg-white rounded-2xl border border-slate-200/80 shadow-xs p-5 space-y-4">
          <div className="flex items-center justify-between">
            <h3 id="history-heading" className="text-sm font-bold text-slate-900">
              Lịch Sử Kết Bạn
            </h3>
            <button
              type="button"
              onClick={loadHistory}
              disabled={loadingHistory}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-slate-100 hover:bg-slate-200 text-slate-700 text-xs font-semibold cursor-pointer"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${loadingHistory ? 'animate-spin' : ''}`} />
              Làm mới
            </button>
          </div>

          <div
            className="overflow-x-auto max-h-[500px] border border-slate-200 rounded-xl"
            tabIndex={0}
            role="region"
            aria-labelledby="history-heading"
          >
            <table className="w-full text-left border-collapse text-xs">
              <thead className="sticky top-0 z-10 bg-slate-100 text-slate-700 border-b border-slate-200">
                <tr>
                  <th className="py-2.5 px-3 font-semibold">Thời gian</th>
                  <th className="py-2.5 px-3 font-semibold">Số điện thoại</th>
                  <th className="py-2.5 px-3 font-semibold">Page Zalo</th>
                  <th className="py-2.5 px-3 font-semibold">Lời chào</th>
                  <th className="py-2.5 px-3 font-semibold">Trạng thái</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {historyItems.length === 0 ? (
                  <tr>
                    <td colSpan={5} className="py-8 text-center text-slate-400">
                      {loadingHistory ? 'Đang tải...' : 'Chưa có lịch sử kết bạn.'}
                    </td>
                  </tr>
                ) : (
                  historyItems.map((h) => (
                    <tr key={h.id} className="hover:bg-slate-50">
                      <td className="py-2 px-3 tabular-nums text-slate-500 whitespace-nowrap">{h.sent_at}</td>
                      <td className="py-2 px-3 font-mono font-bold text-slate-900 tabular-nums">{h.phone}</td>
                      <td className="py-2 px-3 text-emerald-700 font-semibold">{h.page_name}</td>
                      <td className="py-2 px-3 text-slate-600 max-w-xs truncate">{h.message}</td>
                      <td className="py-2 px-3">
                        <span
                          className={`inline-flex px-2 py-0.5 rounded-full text-[11px] font-semibold ${
                            h.status === 'SENT' || h.status === 'ADDED'
                              ? 'bg-emerald-50 text-emerald-700'
                              : h.status === 'DRY_RUN'
                              ? 'bg-amber-50 text-amber-700'
                              : 'bg-rose-50 text-rose-700'
                          }`}
                        >
                          {h.status === 'SENT' ? 'Đã kết bạn' : h.status}
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

      {/* MODAL PHIÊN PANCAKE GỌN */}
      {showStateModal && (
        <div className="fixed inset-0 z-50 bg-slate-900/50 backdrop-blur-xs flex items-center justify-center p-4">
          <div className="bg-white rounded-2xl max-w-lg w-full p-5 shadow-xl border border-slate-200 space-y-4">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-bold text-slate-900 flex items-center gap-2">
                <Database className="w-4 h-4 text-emerald-600" />
                Phiên Đăng Nhập Pancake (pancake_state.json)
              </h3>
              <button
                type="button"
                onClick={() => setShowStateModal(false)}
                className="text-slate-400 hover:text-slate-700"
                aria-label="Đóng"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            {config?.state_info?.has_state ? (
              <div className="p-3 rounded-xl bg-emerald-50 border border-emerald-200 text-xs flex items-center justify-between gap-2">
                <div className="text-emerald-900 font-medium">
                  Đã lưu trong DB ({config.state_info.cookies_count} cookies)
                </div>
                <div className="flex items-center gap-1.5">
                  <button
                    type="button"
                    onClick={async () => {
                      if (!stateJsonInput.trim()) return;
                      await navigator.clipboard.writeText(stateJsonInput);
                      setCopiedState(true);
                      setTimeout(() => setCopiedState(false), 1500);
                    }}
                    className="inline-flex items-center gap-1 px-2 py-1 rounded-lg bg-white border border-emerald-300 text-emerald-800 text-[11px] font-semibold cursor-pointer"
                  >
                    <Copy className="w-3 h-3" />
                    {copiedState ? 'Đã chép' : 'Chép'}
                  </button>
                  <button
                    type="button"
                    onClick={handleDeletePancakeState}
                    className="inline-flex items-center gap-1 px-2 py-1 rounded-lg bg-rose-50 border border-rose-200 text-rose-700 text-[11px] font-semibold cursor-pointer"
                  >
                    <Trash2 className="w-3 h-3" />
                    Xóa
                  </button>
                </div>
              </div>
            ) : (
              <div className="p-2.5 rounded-xl bg-amber-50 border border-amber-200 text-xs text-amber-800 flex items-center gap-2">
                <AlertTriangle className="w-4 h-4 shrink-0 text-amber-600" />
                <span>Chưa có phiên đăng nhập. Hãy dán JSON hoặc chọn file bên dưới.</span>
              </div>
            )}

            <div>
              <div className="flex items-center justify-between mb-1.5">
                <label htmlFor="state-json-box" className="text-xs font-semibold text-slate-700">
                  Nội dung JSON
                </label>
                <label className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg bg-slate-100 hover:bg-slate-200 text-slate-700 text-xs font-semibold cursor-pointer">
                  <Upload className="w-3.5 h-3.5" />
                  Chọn file .json
                  <input
                    type="file"
                    accept=".json"
                    onChange={(e) => {
                      const file = e.target.files?.[0];
                      if (!file) return;
                      const reader = new FileReader();
                      reader.onload = (ev) => setStateJsonInput(String(ev.target?.result || ''));
                      reader.readAsText(file, 'utf-8');
                      e.target.value = '';
                    }}
                    className="hidden"
                  />
                </label>
              </div>
              <textarea
                id="state-json-box"
                rows={6}
                value={stateJsonInput}
                spellCheck={false}
                autoCorrect="off"
                onChange={(e) => setStateJsonInput(e.target.value)}
                placeholder='{"cookies": [...], "origins": [...]}'
                className="w-full rounded-xl border border-slate-300 bg-slate-50 p-3 text-xs font-mono text-slate-800 outline-none focus:bg-white focus:border-emerald-500"
              />
              {loadingRawState && <p className="text-[11px] text-slate-400 mt-1">Đang tải...</p>}
            </div>

            {stateFeedback && (
              <div
                className={`p-2.5 rounded-xl text-xs font-medium ${
                  stateFeedback.type === 'success' ? 'bg-emerald-50 text-emerald-800' : 'bg-rose-50 text-rose-800'
                }`}
              >
                {stateFeedback.text}
              </div>
            )}

            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setShowStateModal(false)}
                className="px-3.5 py-2 rounded-xl border border-slate-200 text-xs font-semibold text-slate-600 cursor-pointer"
              >
                Đóng
              </button>
              <button
                type="button"
                disabled={savingState}
                onClick={handleSavePancakeState}
                className="px-4 py-2 rounded-xl bg-emerald-600 hover:bg-emerald-700 text-white text-xs font-bold cursor-pointer disabled:opacity-50"
              >
                {savingState ? 'Đang lưu...' : 'Lưu vào Database'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
