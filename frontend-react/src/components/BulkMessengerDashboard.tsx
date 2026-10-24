import React, { useState, useEffect, useRef } from 'react';
import {
  Send,
  Bot,
  Filter,
  History,
  Settings,
  Users,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  Play,
  Square,
  Eye,
  RefreshCw,
  ExternalLink,
  Clock,
  Sparkles,
  Info,
  ShieldAlert
} from 'lucide-react';
import {
  fetchBroadcastOptions,
  previewBroadcast,
  startBroadcast,
  fetchBroadcastStatus,
  stopBroadcast,
  fetchBroadcastHistory,
  type BroadcastOptions,
  type BroadcastRecipientItem,
  type BroadcastCampaignSummary,
  type BroadcastHistoryItem,
  type BroadcastStatusResponse
} from '../services/api';

export const BulkMessengerDashboard: React.FC = () => {
  // Navigation sub-tabs
  const [subTab, setSubTab] = useState<'compose' | 'history'>('compose');

  // Options from Backend
  const [options, setOptions] = useState<BroadcastOptions | null>(null);
  const [loadingOptions, setLoadingOptions] = useState(false);

  // Settings & Filters Form State
  const [campaignName, setCampaignName] = useState(`campaign_${new Date().toISOString().slice(0, 10).replace(/-/g, '')}`);
  const [pageId, setPageId] = useState<string>('all');
  const [nameFilter, setNameFilter] = useState<string>('');
  const [employee, setEmployee] = useState<string>('all');
  const [gender, setGender] = useState<string>('all');
  const [tag, setTag] = useState<string>('all');
  const [daysAgo, setDaysAgo] = useState<number | undefined>(1); // Default 1 day for FB 24h compliance
  const [limit, setLimit] = useState<number>(20);
  const [delay, setDelay] = useState<number>(1.2);
  const [dryRun, setDryRun] = useState<boolean>(true);
  const [excludeAlreadySent, setExcludeAlreadySent] = useState<boolean>(true);

  // Message Content & Template
  const [template, setTemplate] = useState<string>(
    'Chào {gender_title} {name}, bên em gửi {gender_title_lower} thông tin ưu đãi mới nhất từ hệ thống ạ!'
  );
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Preview State
  const [previewRecipients, setPreviewRecipients] = useState<BroadcastRecipientItem[]>([]);
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

  // 1. Tải danh sách Options (Kênh, Nhân viên, Tags, Giới tính)
  const loadOptions = async () => {
    setLoadingOptions(true);
    try {
      const data = await fetchBroadcastOptions();
      setOptions(data);
    } catch (err) {
      console.error('Lỗi tải broadcast options:', err);
    } finally {
      setLoadingOptions(false);
    }
  };

  // 2. Tải lịch sử
  const loadHistory = async (camp?: string) => {
    setLoadingHistory(true);
    try {
      const data = await fetchBroadcastHistory(camp, 100);
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
          loadHistory(); // Reload lịch sử khi hoàn thành
        }
      } catch (err) {
        console.error('Lỗi kiểm tra tiến độ:', err);
      }
    }, 1500);

    return () => clearInterval(interval);
  }, [activeTaskId]);

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
        tag: tag,
        days_ago: daysAgo,
        limit: limit,
        template: template,
        exclude_already_sent: excludeAlreadySent,
        campaign_name: campaignName
      });
      setPreviewRecipients(res.recipients);
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
      const res = await startBroadcast({
        campaign_name: campaignName,
        template: template,
        page_id: pageId,
        name_filter: nameFilter,
        employee: employee,
        gender: gender,
        tag: tag,
        days_ago: daysAgo,
        limit: limit,
        delay: delay,
        dry_run: dryRun,
        exclude_already_sent: excludeAlreadySent
      });
      setActiveTaskId(res.task_id);
    } catch (err: any) {
      console.error('Lỗi khởi động broadcast:', err);
      alert('Lỗi: ' + (err.response?.data?.detail || 'Không thể bắt đầu gửi tin'));
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
      alert('Đã gửi yêu cầu dừng tác vụ.');
    } catch (err) {
      console.error('Lỗi dừng broadcast:', err);
    }
  };

  // Tính mẫu hiển thị xem trước trực tiếp (Live Preview)
  const sampleRecipient = previewRecipients[0] || {
    name: 'Nguyễn Văn An',
    gender: 'male',
    gender_title: 'Anh',
    phone_number: '0987654321',
    page_id: pageId !== 'all' ? pageId : 'EzTech Official'
  };

  const sampleRenderedText = template
    .replace('{name}', sampleRecipient.name || 'anh/chị')
    .replace('{gender_title}', sampleRecipient.gender_title || 'Anh')
    .replace('{gender_title_lower}', sampleRecipient.gender === 'male' ? 'anh' : sampleRecipient.gender === 'female' ? 'chị' : 'anh/chị')
    .replace('{phone}', sampleRecipient.phone_number || '0987654321')
    .replace('{page_id}', sampleRecipient.page_id || 'Page')
    .replace('{customer_id}', 'cust_101')
    .replace('{staff}', 'Chăm sóc khách hàng');

  return (
    <div className="space-y-6">
      {/* Top Banner Navigation */}
      <div className="bg-white rounded-2xl border border-[#E5E7EB] p-5 shadow-sm flex flex-col md:flex-row items-start md:items-center justify-between gap-4">
        <div className="flex items-center gap-3.5">
          <div className="w-11 h-11 rounded-xl bg-gradient-to-tr from-indigo-600 to-blue-500 flex items-center justify-center text-white shadow-md shadow-indigo-100">
            <Bot className="w-6 h-6" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-lg font-bold text-navy">Bot Gửi Tin Nhắn Tự Động</h2>
              <span className="px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider bg-indigo-50 text-indigo-700 border border-indigo-200 rounded-full">
                Pancake API v1
              </span>
            </div>
            <p className="text-xs text-[#4B5563] mt-0.5">
              Gửi tin nhắn hàng loạt theo bộ lọc lead thông minh, chống spam và kiểm soát an toàn tốc độ gửi.
            </p>
          </div>
        </div>

        {/* Sub-tab Switcher */}
        <div className="flex items-center gap-1 bg-gray-100 p-1 rounded-xl w-full md:w-auto">
          <button
            onClick={() => setSubTab('compose')}
            className={`flex-1 md:flex-none flex items-center justify-center gap-2 px-4 py-2 rounded-lg text-xs font-semibold transition-all ${
              subTab === 'compose'
                ? 'bg-white text-navy shadow-sm'
                : 'text-[#4B5563] hover:text-navy hover:bg-white/50'
            }`}
          >
            <Settings className="w-3.5 h-3.5 text-indigo-600" />
            <span>Cấu hình & Gửi tin</span>
          </button>
          <button
            onClick={() => {
              setSubTab('history');
              loadHistory(selectedHistoryCampaign);
            }}
            className={`flex-1 md:flex-none flex items-center justify-center gap-2 px-4 py-2 rounded-lg text-xs font-semibold transition-all ${
              subTab === 'history'
                ? 'bg-white text-navy shadow-sm'
                : 'text-[#4B5563] hover:text-navy hover:bg-white/50'
            }`}
          >
            <History className="w-3.5 h-3.5 text-blue-600" />
            <span>Lịch sử từng lần chạy</span>
            {campaignSummaries.length > 0 && (
              <span className="px-1.5 py-0.2 bg-blue-100 text-blue-700 rounded-full text-[10px]">
                {campaignSummaries.length}
              </span>
            )}
          </button>
        </div>
      </div>

      {/* Progress Notification Banner (nếu có task đang chạy) */}
      {taskStatus && taskStatus.is_running && (
        <div className="bg-gradient-to-r from-blue-50 to-indigo-50 border border-blue-200 rounded-2xl p-4 shadow-sm animate-pulse">
          <div className="flex items-center justify-between gap-4">
            <div className="flex items-center gap-3">
              <div className="w-3 h-3 rounded-full bg-blue-600 animate-ping" />
              <div>
                <h4 className="text-sm font-bold text-navy flex items-center gap-2">
                  Đang chạy chiến dịch: <span className="text-blue-600 font-mono">{taskStatus.campaign_name}</span>
                  {taskStatus.dry_run && (
                    <span className="px-2 py-0.5 bg-amber-100 text-amber-800 rounded text-xs font-medium">Mô phỏng</span>
                  )}
                </h4>
                <p className="text-xs text-[#4B5563] mt-0.5">
                  Đang xử lý: {taskStatus.processed}/{taskStatus.total} tin (Thành công: {taskStatus.success}, Thất bại: {taskStatus.failed})
                  {taskStatus.current_recipient && ` — Đang gửi: ${taskStatus.current_recipient}`}
                </p>
              </div>
            </div>
            <button
              onClick={handleStopBroadcast}
              className="px-3 py-1.5 bg-red-600 hover:bg-red-700 text-white rounded-lg text-xs font-semibold flex items-center gap-1.5 shadow-sm transition-colors"
            >
              <Square className="w-3.5 h-3.5" />
              Dừng khẩn cấp
            </button>
          </div>
          {/* Progress Bar */}
          <div className="w-full bg-blue-200 rounded-full h-2 mt-3 overflow-hidden">
            <div
              className="bg-blue-600 h-2 rounded-full transition-all duration-300"
              style={{ width: `${taskStatus.total > 0 ? (taskStatus.processed / taskStatus.total) * 100 : 0}%` }}
            />
          </div>
        </div>
      )}

      {/* ========================================================================= */}
      {/* SUB-TAB 1: CẤU HÌNH & GỬI TIN */}
      {/* ========================================================================= */}
      {subTab === 'compose' && (
        <div className="space-y-6">
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
            {/* CỘT TRÁI: BỘ LỌC CHI TIẾT (7 Cột) */}
            <div className="lg:col-span-7 bg-white rounded-2xl border border-[#E5E7EB] p-5 shadow-sm space-y-5">
              <div className="flex items-center justify-between pb-3 border-b border-gray-100">
                <div className="flex items-center gap-2">
                  <Filter className="w-4 h-4 text-indigo-600" />
                  <h3 className="text-sm font-bold text-navy">Bộ lọc khách hàng mục tiêu & Cài đặt</h3>
                </div>
                <button
                  onClick={loadOptions}
                  className="text-xs text-blue-600 hover:text-blue-800 flex items-center gap-1"
                  title="Làm mới danh sách filter"
                >
                  <RefreshCw className={`w-3 h-3 ${loadingOptions ? 'animate-spin' : ''}`} />
                  Làm mới
                </button>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                {/* 1. Tên chiến dịch */}
                <div className="sm:col-span-2">
                  <label className="block text-xs font-semibold text-gray-700 mb-1">
                    Tên chiến dịch (Campaign ID) <span className="text-red-500">*</span>
                  </label>
                  <input
                    type="text"
                    value={campaignName}
                    onChange={(e) => setCampaignName(e.target.value)}
                    placeholder="vd: uu_dai_hoc_vien_t10"
                    className="w-full px-3 py-2 bg-gray-50 border border-gray-300 rounded-lg text-xs font-mono focus:bg-white focus:ring-2 focus:ring-indigo-500 focus:outline-none transition-all"
                  />
                  <p className="text-[11px] text-gray-500 mt-1">
                    Dùng để quản lý lịch sử và ngăn ngừa gửi tin nhắn trùng lặp tới cùng 1 khách hàng.
                  </p>
                </div>

                {/* 2. Tên Kênh / Fanpage */}
                <div>
                  <label className="block text-xs font-semibold text-gray-700 mb-1">
                    Kênh / Fanpage Pancake
                  </label>
                  <select
                    value={pageId}
                    onChange={(e) => setPageId(e.target.value)}
                    className="w-full px-3 py-2 bg-gray-50 border border-gray-300 rounded-lg text-xs focus:bg-white focus:ring-2 focus:ring-indigo-500 focus:outline-none transition-all"
                  >
                    <option value="all">Tất cả kênh / Fanpage</option>
                    {options?.pages.map((p) => (
                      <option key={p} value={p}>
                        {p}
                      </option>
                    ))}
                  </select>
                </div>

                {/* 3. Nhân viên phụ trách */}
                <div>
                  <label className="block text-xs font-semibold text-gray-700 mb-1">
                    Nhân viên phụ trách
                  </label>
                  <select
                    value={employee}
                    onChange={(e) => setEmployee(e.target.value)}
                    className="w-full px-3 py-2 bg-gray-50 border border-gray-300 rounded-lg text-xs focus:bg-white focus:ring-2 focus:ring-indigo-500 focus:outline-none transition-all"
                  >
                    <option value="all">Tất cả nhân viên</option>
                    {options?.employees.map((emp) => (
                      <option key={emp} value={emp}>
                        {emp}
                      </option>
                    ))}
                  </select>
                </div>

                {/* 4. Giới tính */}
                <div>
                  <label className="block text-xs font-semibold text-gray-700 mb-1 flex items-center gap-1">
                    <Sparkles className="w-3 h-3 text-amber-500" />
                    Lọc theo Giới tính
                  </label>
                  <select
                    value={gender}
                    onChange={(e) => setGender(e.target.value)}
                    className="w-full px-3 py-2 bg-gray-50 border border-gray-300 rounded-lg text-xs focus:bg-white focus:ring-2 focus:ring-indigo-500 focus:outline-none transition-all"
                  >
                    {options?.gender_options.map((g) => (
                      <option key={g.id} value={g.id}>
                        {g.label}
                      </option>
                    ))}
                  </select>
                </div>

                {/* 5. Thẻ Tags trạng thái */}
                <div>
                  <label className="block text-xs font-semibold text-gray-700 mb-1">
                    Lọc theo Thẻ (Tags)
                  </label>
                  <select
                    value={tag}
                    onChange={(e) => setTag(e.target.value)}
                    className="w-full px-3 py-2 bg-gray-50 border border-gray-300 rounded-lg text-xs focus:bg-white focus:ring-2 focus:ring-indigo-500 focus:outline-none transition-all"
                  >
                    <option value="all">Tất cả các thẻ tags</option>
                    {options?.tags.map((t) => (
                      <option key={t} value={t}>
                        {t}
                      </option>
                    ))}
                  </select>
                </div>

                {/* 6. Lọc theo Tên khách hàng */}
                <div>
                  <label className="block text-xs font-semibold text-gray-700 mb-1">
                    Tìm kiếm theo Tên khách
                  </label>
                  <input
                    type="text"
                    value={nameFilter}
                    onChange={(e) => setNameFilter(e.target.value)}
                    placeholder="vd: Nguyễn, Mai, Hương..."
                    className="w-full px-3 py-2 bg-gray-50 border border-gray-300 rounded-lg text-xs focus:bg-white focus:ring-2 focus:ring-indigo-500 focus:outline-none transition-all"
                  />
                </div>

                {/* 7. Khoảng thời gian tương tác gần nhất */}
                <div>
                  <label className="block text-xs font-semibold text-gray-700 mb-1 flex items-center justify-between">
                    <span>Thời gian tương tác</span>
                    <span className="text-[10px] text-blue-600 font-medium">Chính sách FB 24h</span>
                  </label>
                  <select
                    value={daysAgo ?? 'all'}
                    onChange={(e) => setDaysAgo(e.target.value === 'all' ? undefined : Number(e.target.value))}
                    className="w-full px-3 py-2 bg-gray-50 border border-gray-300 rounded-lg text-xs focus:bg-white focus:ring-2 focus:ring-indigo-500 focus:outline-none transition-all"
                  >
                    <option value={1}>Trong 24 giờ qua (Khuyên dùng cho Facebook)</option>
                    <option value={3}>Trong 3 ngày qua</option>
                    <option value={7}>Trong 7 ngày qua (Hỗ trợ Private Reply)</option>
                    <option value={30}>Trong 30 ngày qua</option>
                    <option value="all">Tất cả thời gian</option>
                  </select>
                </div>

                {/* 8. Giới hạn số lượng & Tốc độ gửi */}
                <div>
                  <label className="block text-xs font-semibold text-gray-700 mb-1">
                    Số lượng gửi tối đa
                  </label>
                  <select
                    value={limit}
                    onChange={(e) => setLimit(Number(e.target.value))}
                    className="w-full px-3 py-2 bg-gray-50 border border-gray-300 rounded-lg text-xs focus:bg-white focus:ring-2 focus:ring-indigo-500 focus:outline-none transition-all"
                  >
                    <option value={10}>10 tin</option>
                    <option value={20}>20 tin</option>
                    <option value={50}>50 tin</option>
                    <option value={100}>100 tin</option>
                    <option value={200}>200 tin</option>
                  </select>
                </div>

                <div>
                  <label className="block text-xs font-semibold text-gray-700 mb-1 flex items-center justify-between">
                    <span>Nghỉ giữa 2 tin (giây)</span>
                    <span className="text-[10px] text-gray-500">Rate Limit: &le; 5 req/s</span>
                  </label>
                  <input
                    type="number"
                    step="0.1"
                    min="0.5"
                    max="5.0"
                    value={delay}
                    onChange={(e) => setDelay(Number(e.target.value))}
                    className="w-full px-3 py-2 bg-gray-50 border border-gray-300 rounded-lg text-xs focus:bg-white focus:ring-2 focus:ring-indigo-500 focus:outline-none transition-all"
                  />
                </div>
              </div>

              {/* Tùy chọn an toàn */}
              <div className="pt-3 border-t border-gray-100 space-y-3">
                <label className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={excludeAlreadySent}
                    onChange={(e) => setExcludeAlreadySent(e.target.checked)}
                    className="rounded text-indigo-600 focus:ring-indigo-500 w-4 h-4"
                  />
                  <span className="text-xs text-gray-700 font-medium">
                    Không gửi lặp lại cho khách đã từng nhận chiến dịch này (Anti-Spam)
                  </span>
                </label>

                {/* Toggle Chế độ Dry-run */}
                <div className={`p-3 rounded-xl border flex items-center justify-between ${
                  dryRun ? 'bg-blue-50/50 border-blue-200' : 'bg-red-50/50 border-red-200'
                }`}>
                  <div className="flex items-center gap-2.5">
                    {dryRun ? (
                      <Info className="w-4 h-4 text-blue-600" />
                    ) : (
                      <ShieldAlert className="w-4 h-4 text-red-600" />
                    )}
                    <div>
                      <p className={`text-xs font-bold ${dryRun ? 'text-blue-900' : 'text-red-900'}`}>
                        {dryRun ? 'Chế độ Mô phỏng an toàn (DRY-RUN)' : 'CẢNH BÁO: CHẾ ĐỘ GỬI THẬT (LIVE)'}
                      </p>
                      <p className="text-[11px] text-gray-600">
                        {dryRun
                          ? 'Mô phỏng gửi và ghi log thử nghiệm, không gửi tin nhắn thật đến khách.'
                          : 'Tin nhắn sẽ được gửi trực tiếp đến Facebook/Zalo của khách hàng qua Pancake.'}
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
              </div>
            </div>

            {/* CỘT PHẢI: SOẠN NỘI DUNG & LIVE PREVIEW (5 Cột) */}
            <div className="lg:col-span-5 space-y-5">
              {/* Soạn nội dung tin nhắn */}
              <div className="bg-white rounded-2xl border border-[#E5E7EB] p-5 shadow-sm space-y-3">
                <div className="flex items-center justify-between">
                  <h3 className="text-sm font-bold text-navy flex items-center gap-2">
                    <Send className="w-4 h-4 text-indigo-600" />
                    Nội dung tin nhắn
                  </h3>
                  <span className="text-[11px] text-gray-400 font-mono">
                    {template.length} ký tự
                  </span>
                </div>

                {/* Danh sách biến động chèn nhanh */}
                <div>
                  <p className="text-[11px] font-semibold text-gray-600 mb-1.5">Chèn biến động:</p>
                  <div className="flex flex-wrap gap-1.5">
                    {[
                      { tag: '{gender_title}', label: 'Anh/Chị' },
                      { tag: '{name}', label: 'Tên khách' },
                      { tag: '{gender_title_lower}', label: 'anh/chị' },
                      { tag: '{phone}', label: 'SĐT' },
                      { tag: '{page_id}', label: 'Tên Kênh' },
                      { tag: '{staff}', label: 'Nhân viên' }
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
                      Mẫu cho: {sampleRecipient.name} ({sampleRecipient.gender === 'female' ? 'Nữ' : 'Nam'})
                    </span>
                  </div>

                  <div className="bg-white p-3 rounded-lg border border-gray-200 shadow-sm">
                    <p className="text-xs text-gray-800 whitespace-pre-wrap leading-relaxed">
                      {sampleRenderedText}
                    </p>
                  </div>
                </div>

                {/* Nút Hành động */}
                <div className="pt-2 flex items-center gap-3">
                  <button
                    type="button"
                    onClick={handlePreview}
                    disabled={loadingPreview}
                    className="flex-1 px-4 py-2.5 bg-gray-100 hover:bg-gray-200 text-navy rounded-xl text-xs font-semibold flex items-center justify-center gap-2 transition-all border border-gray-300"
                  >
                    {loadingPreview ? (
                      <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                    ) : (
                      <Eye className="w-3.5 h-3.5 text-gray-600" />
                    )}
                    <span>Xem trước ({limit} khách)</span>
                  </button>

                  <button
                    type="button"
                    onClick={() => setShowConfirmModal(true)}
                    disabled={isStarting || (taskStatus?.is_running ?? false)}
                    className={`flex-1 px-4 py-2.5 rounded-xl text-xs font-bold text-white flex items-center justify-center gap-2 shadow-sm transition-all ${
                      dryRun
                        ? 'bg-blue-600 hover:bg-blue-700'
                        : 'bg-red-600 hover:bg-red-700 animate-pulse'
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
              <div className="flex items-center justify-between">
                <div>
                  <h3 className="text-sm font-bold text-navy flex items-center gap-2">
                    <Users className="w-4 h-4 text-indigo-600" />
                    Danh sách người nhận thỏa mãn ({previewRecipients.length}/{totalMatching} khách hàng)
                  </h3>
                  <p className="text-xs text-[#4B5563]">
                    Kiểm tra nội dung tin nhắn cá nhân hóa trước khi chạy chiến dịch.
                  </p>
                </div>
              </div>

              {previewRecipients.length === 0 ? (
                <div className="text-center py-10 bg-gray-50 rounded-xl">
                  <AlertTriangle className="w-8 h-8 text-amber-500 mx-auto mb-2" />
                  <p className="text-xs text-gray-600 font-semibold">
                    Không tìm thấy khách hàng nào khớp với các điều kiện lọc trên.
                  </p>
                  <p className="text-[11px] text-gray-400 mt-1">
                    Hãy thử nới lỏng bộ lọc: mở rộng thời gian, chọn Tất cả kênh hoặc bỏ bớt thẻ tags.
                  </p>
                </div>
              ) : (
                <div className="overflow-x-auto border border-gray-200 rounded-xl">
                  <table className="w-full text-left text-xs">
                    <thead className="bg-gray-50 text-gray-600 border-b border-gray-200">
                      <tr>
                        <th className="py-2.5 px-3 font-semibold">STT</th>
                        <th className="py-2.5 px-3 font-semibold">Khách hàng</th>
                        <th className="py-2.5 px-3 font-semibold">Giới tính</th>
                        <th className="py-2.5 px-3 font-semibold">Kênh / Page</th>
                        <th className="py-2.5 px-3 font-semibold">Tags</th>
                        <th className="py-2.5 px-3 font-semibold">Nội dung tin nhắn gửi đi</th>
                        <th className="py-2.5 px-3 font-semibold text-center">Hội thoại</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-100">
                      {previewRecipients.map((r, idx) => (
                        <tr key={r.conversation_id} className="hover:bg-blue-50/30 transition-colors">
                          <td className="py-2 px-3 text-gray-400 font-mono">{idx + 1}</td>
                          <td className="py-2 px-3">
                            <span className="font-semibold text-navy">{r.name}</span>
                            {r.phone_number && (
                              <span className="block text-[11px] text-gray-500">{r.phone_number}</span>
                            )}
                          </td>
                          <td className="py-2 px-3">
                            <span className={`px-2 py-0.5 rounded text-[10px] font-semibold ${
                              r.gender === 'female'
                                ? 'bg-pink-100 text-pink-700'
                                : r.gender === 'male'
                                ? 'bg-blue-100 text-blue-700'
                                : 'bg-gray-100 text-gray-600'
                            }`}>
                              {r.gender === 'female' ? 'Nữ (Chị)' : r.gender === 'male' ? 'Nam (Anh)' : 'Chưa rõ'}
                            </span>
                          </td>
                          <td className="py-2 px-3 text-gray-600">{r.page_id}</td>
                          <td className="py-2 px-3">
                            <span className="px-2 py-0.5 bg-gray-100 text-gray-700 rounded text-[10px]">
                              {r.status_tag || 'Chưa gắn tag'}
                            </span>
                          </td>
                          <td className="py-2 px-3 text-gray-800 max-w-md truncate" title={r.rendered_message}>
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
                        </tr>
                      ))}
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
            <div className="flex items-center justify-between">
              <div>
                <h3 className="text-sm font-bold text-navy flex items-center gap-2">
                  <History className="w-4 h-4 text-blue-600" />
                  Danh sách chiến dịch đã chạy
                </h3>
                <p className="text-xs text-[#4B5563]">
                  Thống kê kết quả gửi tin theo từng chiến dịch (Tổng số tin, Thành công, Thất bại, Mô phỏng).
                </p>
              </div>
              <button
                onClick={() => loadHistory(selectedHistoryCampaign)}
                className="px-3 py-1.5 text-xs text-blue-600 bg-blue-50 hover:bg-blue-100 rounded-lg flex items-center gap-1.5 transition-colors"
              >
                <RefreshCw className={`w-3 h-3 ${loadingHistory ? 'animate-spin' : ''}`} />
                Làm mới
              </button>
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
                          selectedHistoryCampaign === camp.campaign_name ? 'bg-blue-50/50' : 'hover:bg-gray-50'
                        }`}
                      >
                        <td className="py-2.5 px-3 font-semibold text-navy font-mono">
                          {camp.campaign_name}
                        </td>
                        <td className="py-2.5 px-3 text-gray-600">{camp.page_id || 'Tất cả'}</td>
                        <td className="py-2.5 px-3 text-center font-bold text-gray-800">{camp.total_messages}</td>
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
                          {camp.last_sent_at || 'N/A'}
                        </td>
                        <td className="py-2.5 px-3 text-center">
                          <span className={`px-2 py-0.5 rounded text-[10px] font-semibold ${
                            camp.status === 'Hoàn thành'
                              ? 'bg-emerald-100 text-emerald-800'
                              : camp.status === 'Mô phỏng (Dry-run)'
                              ? 'bg-blue-100 text-blue-800'
                              : 'bg-red-100 text-red-800'
                          }`}>
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

          {/* BẢNG 2: CHI TIẾT TỪNG TIN NHẮN ĐÃ GỬI (LOGS) */}
          <div className="bg-white rounded-2xl border border-[#E5E7EB] p-5 shadow-sm space-y-4">
            <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3">
              <div>
                <h3 className="text-sm font-bold text-navy flex items-center gap-2">
                  <Clock className="w-4 h-4 text-indigo-600" />
                  Chi tiết từng tin nhắn (Lịch sử gửi bot)
                </h3>
                <p className="text-xs text-[#4B5563]">
                  Xem nội dung tin nhắn, thời gian và phản hồi từ Pancake API cho từng hội thoại.
                </p>
              </div>

              {/* Lọc theo chiến dịch */}
              <div className="flex items-center gap-2">
                <span className="text-xs text-gray-500 font-medium">Chiến dịch:</span>
                <select
                  value={selectedHistoryCampaign}
                  onChange={(e) => {
                    setSelectedHistoryCampaign(e.target.value);
                    loadHistory(e.target.value);
                  }}
                  className="px-2.5 py-1.5 bg-gray-50 border border-gray-300 rounded-lg text-xs font-mono focus:outline-none"
                >
                  <option value="all">Tất cả chiến dịch</option>
                  {campaignSummaries.map((c) => (
                    <option key={c.campaign_name} value={c.campaign_name}>
                      {c.campaign_name}
                    </option>
                  ))}
                </select>
              </div>
            </div>

            {historyLogs.length === 0 ? (
              <div className="text-center py-8 bg-gray-50 rounded-xl text-xs text-gray-500">
                Không tìm thấy bản ghi log nào thỏa mãn.
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
                      <th className="py-2.5 px-3 font-semibold text-center">Kết quả</th>
                      <th className="py-2.5 px-3 font-semibold">Lỗi chi tiết</th>
                      <th className="py-2.5 px-3 font-semibold text-center">Hội thoại</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100">
                    {historyLogs.map((log) => (
                      <tr key={log.id} className="hover:bg-gray-50/50 transition-colors">
                        <td className="py-2 px-3 text-gray-500 font-mono text-[11px] whitespace-nowrap">
                          {log.sent_at}
                        </td>
                        <td className="py-2 px-3 font-mono text-navy font-medium">
                          {log.campaign_name}
                        </td>
                        <td className="py-2 px-3">
                          <span className="font-semibold text-navy">{log.customer_name || 'Khách'}</span>
                          {log.phone_number && (
                            <span className="block text-[10px] text-gray-400 font-mono">{log.phone_number}</span>
                          )}
                        </td>
                        <td className="py-2 px-3 text-gray-600">{log.page_id}</td>
                        <td className="py-2 px-3 text-gray-800 max-w-xs truncate" title={log.message}>
                          {log.message}
                        </td>
                        <td className="py-2 px-3 text-center">
                          {log.status === 'SENT' ? (
                            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-bold bg-emerald-100 text-emerald-800">
                              <CheckCircle2 className="w-3 h-3 text-emerald-600" />
                              SENT
                            </span>
                          ) : log.status === 'DRY_RUN' ? (
                            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-bold bg-blue-100 text-blue-800">
                              DRY_RUN
                            </span>
                          ) : (
                            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-bold bg-red-100 text-red-800">
                              <XCircle className="w-3 h-3 text-red-600" />
                              FAILED
                            </span>
                          )}
                        </td>
                        <td className="py-2 px-3 text-red-600 text-[11px] max-w-xs truncate" title={log.error_message || ''}>
                          {log.error_message || <span className="text-gray-300">-</span>}
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

      {/* MODAL XÁC NHẬN AN TOÀN TRƯỚC KHI BẮT ĐẦU */}
      {showConfirmModal && (
        <div className="fixed inset-0 z-50 bg-black/50 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-white rounded-2xl max-w-md w-full p-6 shadow-2xl border border-gray-200 space-y-4">
            <div className="flex items-center gap-3">
              <div className={`w-10 h-10 rounded-full flex items-center justify-center ${
                dryRun ? 'bg-blue-100 text-blue-600' : 'bg-red-100 text-red-600'
              }`}>
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
                <span className="font-semibold text-gray-800">{pageId === 'all' ? 'Tất cả kênh' : pageId}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-500">Giới hạn số lượng:</span>
                <span className="font-semibold text-gray-800">{limit} khách hàng</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-500">Tốc độ gửi:</span>
                <span className="font-semibold text-gray-800">{delay} giây/tin (An toàn &le; 5 req/s)</span>
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
