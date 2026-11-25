import React, { useState, useEffect, useCallback, useRef } from 'react';
import { format, subDays, startOfMonth } from 'date-fns';
import {
  Award,
  Filter,
  RefreshCw,
  Search,
  ChevronLeft,
  ChevronRight,
  Eye,
  Pencil,
  Save,
  ShieldCheck,
  X,
  Phone,
  Mail,
  Calendar,
  MapPin,
  Briefcase,
  FileText,
  TrendingUp,
  PhoneCall,
  Users
} from 'lucide-react';
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip as RechartsTooltip,
  ResponsiveContainer,
  BarChart,
  Bar,
  Cell
} from 'recharts';
import {
  fetchDealWinSummary,
  fetchDealWinList,
  fetchDealWinOptions,
  clearClientApiCache,
  fetchDealWinDetail,
  updateDealWinItem,
  syncDealsWithLeads,
  isAbortError,
  getStoredAuth,
  type DealWinItem,
  type DealWinUpdatePayload,
  type DealWinSummary,
  type DealWinOptions
} from '../services/api';
import { getTabDataScope } from '../config/permissions';
import { safeFormatDate } from '../utils/format';
import { showAppToast } from '../utils/toast';
import { ErrorBanner } from './ErrorBanner';
import { AccessibleModal } from './AccessibleModal';

export function DealWinDashboard() {
  const authUser = getStoredAuth()?.user || null;
  const isPersonalScope = getTabDataScope(authUser, 'deals') === 'personal';
  const personalEmployeeName = (authUser?.full_name || authUser?.username || '').trim();

  // Preset dates: default to 30 days
  const [startDate, setStartDate] = useState(() => format(subDays(new Date(), 30), 'yyyy-MM-dd'));
  const [endDate, setEndDate] = useState(() => format(new Date(), 'yyyy-MM-dd'));
  const [datePreset, setDatePreset] = useState<'7d' | '30d' | 'month' | 'all' | 'custom'>('30d');

  // Filters (auto chọn lọc 'Tất cả form đăng ký')
  const [onlyStudent, setOnlyStudent] = useState<boolean>(false);
  const [selectedSale, setSelectedSale] = useState(() => (isPersonalScope ? personalEmployeeName : ''));
  const [selectedPage, setSelectedPage] = useState('');
  const [selectedSource, setSelectedSource] = useState('');
  const [searchQuery, setSearchQuery] = useState('');
  const [activeSearch, setActiveSearch] = useState('');

  useEffect(() => {
    if (isPersonalScope && personalEmployeeName && selectedSale !== personalEmployeeName) {
      setSelectedSale(personalEmployeeName);
    }
  }, [isPersonalScope, personalEmployeeName, selectedSale]);

  // Dropdown options
  const [options, setOptions] = useState<DealWinOptions>({ sales_persons: [], pages: [], sources: [] });

  // Distinct single sales persons list (giữ tên chứa 'data' như 'Tuấn Anh data', chỉ loại tag rác)
  const salesPersonsList = React.useMemo(() => {
    const set = new Set<string>();
    const junk = ['chưa phân công', 'bỏ qua', 'chưa đóng tiền', 'không học', 'học t7', 'đóng trc'];
    (options.sales_persons || []).forEach(sp => {
      if (sp) {
        sp.split(',').forEach(name => {
          const trimmed = name.trim();
          const low = trimmed.toLowerCase();
          if (trimmed && low !== 'data' && !junk.some(j => low.includes(j))) {
            set.add(trimmed);
          }
        });
      }
    });
    return Array.from(set).sort((a, b) => a.localeCompare(b, 'vi'));
  }, [options.sales_persons]);

  // Data states
  const [summary, setSummary] = useState<DealWinSummary | null>(null);
  const [deals, setDeals] = useState<DealWinItem[]>([]);
  const [totalDeals, setTotalDeals] = useState(0);
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const pageSize = 20;

  // Loading, error & status
  const [loadingSummary, setLoadingSummary] = useState(false);
  const [loadingList, setLoadingList] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [syncingPancake, setSyncingPancake] = useState(false);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  // Modal detail & edit
  const [detailModal, setDetailModal] = useState<DealWinItem | null>(null);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [editModal, setEditModal] = useState<DealWinItem | null>(null);
  const [editForm, setEditForm] = useState<DealWinUpdatePayload>({});
  const [savingEdit, setSavingEdit] = useState(false);

  const summaryAbortRef = useRef<AbortController | null>(null);
  const listAbortRef = useRef<AbortController | null>(null);
  const detailReqIdRef = useRef<number | null>(null);

  // Load dropdown options when onlyStudent changes & reset stale selections
  useEffect(() => {
    const controller = new AbortController();
    fetchDealWinOptions(onlyStudent, { signal: controller.signal })
      .then((res) => {
        if (controller.signal.aborted) return;
        setOptions(res);
        if (selectedPage && res.pages && !res.pages.includes(selectedPage)) setSelectedPage('');
        if (selectedSource && res.sources && !res.sources.includes(selectedSource)) setSelectedSource('');
      })
      .catch((err) => {
        if (!isAbortError(err)) console.error('Error fetching deal options:', err);
      });
    return () => controller.abort();
  }, [onlyStudent]);

  // Quick date presets
  const handleDatePreset = (preset: '7d' | '30d' | 'month' | 'all') => {
    setDatePreset(preset);
    const today = new Date();
    if (preset === '7d') {
      setStartDate(format(subDays(today, 7), 'yyyy-MM-dd'));
      setEndDate(format(today, 'yyyy-MM-dd'));
    } else if (preset === '30d') {
      setStartDate(format(subDays(today, 30), 'yyyy-MM-dd'));
      setEndDate(format(today, 'yyyy-MM-dd'));
    } else if (preset === 'month') {
      setStartDate(format(startOfMonth(today), 'yyyy-MM-dd'));
      setEndDate(format(today, 'yyyy-MM-dd'));
    } else if (preset === 'all') {
      setStartDate('');
      setEndDate(format(today, 'yyyy-MM-dd'));
    }
  };

  // Fetch summary & aggregations (KHÔNG phụ thuộc activeSearch để tránh flash KPI khi tìm kiếm)
  const loadSummaryData = useCallback(async (skipCache: boolean = false) => {
    if (startDate && endDate && startDate > endDate) {
      setErrorMsg('Ngày bắt đầu không được lớn hơn ngày kết thúc.');
      return;
    }
    summaryAbortRef.current?.abort();
    const controller = new AbortController();
    summaryAbortRef.current = controller;

    setLoadingSummary(true);
    setErrorMsg(null);
    try {
      const res = await fetchDealWinSummary(
        startDate || undefined,
        endDate || undefined,
        selectedSale || undefined,
        onlyStudent,
        selectedPage || undefined,
        selectedSource || undefined,
        { signal: controller.signal, skipCache }
      );
      if (controller.signal.aborted) return;
      setSummary(res);
      setLastUpdated(new Date());
    } catch (err) {
      if (isAbortError(err)) return;
      console.error('Error fetching deal summary:', err);
      setErrorMsg('Không thể tải thống kê Deal Win. Vui lòng thử lại.');
    } finally {
      if (summaryAbortRef.current === controller) {
        setLoadingSummary(false);
      }
    }
  }, [startDate, endDate, selectedSale, onlyStudent, selectedPage, selectedSource]);

  // Fetch paginated table rows
  const loadListData = useCallback(async (targetPage: number = 1, skipCache: boolean = false) => {
    if (startDate && endDate && startDate > endDate) return;
    listAbortRef.current?.abort();
    const controller = new AbortController();
    listAbortRef.current = controller;

    setLoadingList(true);
    try {
      const res = await fetchDealWinList(
        targetPage,
        pageSize,
        startDate || undefined,
        endDate || undefined,
        selectedSale || undefined,
        activeSearch || undefined,
        onlyStudent,
        selectedPage || undefined,
        selectedSource || undefined,
        { signal: controller.signal, skipCache }
      );
      if (controller.signal.aborted) return;
      setDeals(res.data);
      setTotalDeals(res.total);
      setTotalPages(Math.max(1, res.total_pages));
      setPage(res.page);
    } catch (err) {
      if (isAbortError(err)) return;
      console.error('Error fetching deal list:', err);
      setErrorMsg('Không thể tải danh sách học viên Deal Win. Vui lòng thử lại.');
    } finally {
      if (listAbortRef.current === controller) {
        setLoadingList(false);
      }
    }
  }, [startDate, endDate, selectedSale, activeSearch, onlyStudent, selectedPage, selectedSource]);

  // Tách 2 effect: Summary chỉ reload khi bộ lọc chính đổi; List reload thêm khi activeSearch đổi
  useEffect(() => {
    loadSummaryData(false);
    return () => { summaryAbortRef.current?.abort(); };
  }, [loadSummaryData]);

  useEffect(() => {
    loadListData(1, false);
    return () => { listAbortRef.current?.abort(); };
  }, [loadListData]);

  const handleSyncPancake = async () => {
    setSyncingPancake(true);
    try {
      const res = await syncDealsWithLeads();
      showAppToast(res.message || 'Đồng bộ Pancake thành công!', 'success');
      clearClientApiCache('/deals/');
      const [opt] = await Promise.all([
        fetchDealWinOptions(onlyStudent, { skipCache: true }).catch(() => null),
        loadSummaryData(true),
        loadListData(1, true),
      ]);
      if (opt) setOptions(opt);
    } catch (err) {
      console.error('Error syncing with Pancake:', err);
      showAppToast('Lỗi đồng bộ với Pancake! Vui lòng thử lại.', 'error');
    } finally {
      setSyncingPancake(false);
    }
  };

  const handleSearchSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setActiveSearch(searchQuery.trim());
  };

  const handleOpenDetail = async (deal: DealWinItem) => {
    detailReqIdRef.current = deal.id;
    setDetailModal(deal);
    setLoadingDetail(true);
    try {
      const full = await fetchDealWinDetail(deal.id);
      if (detailReqIdRef.current === deal.id) {
        setDetailModal(full);
      }
    } catch (err) {
      console.error('Error fetching deal detail:', err);
      if (detailReqIdRef.current === deal.id) {
        showAppToast('Không thể tải thêm thông tin chi tiết học viên.', 'error');
      }
    } finally {
      if (detailReqIdRef.current === deal.id) {
        setLoadingDetail(false);
      }
    }
  };

  const closeDetailModal = () => {
    detailReqIdRef.current = null;
    setDetailModal(null);
    setLoadingDetail(false);
  };

  const handleOpenEdit = (deal: DealWinItem) => {
    setEditModal(deal);
    setEditForm({
      full_name: deal.full_name || '',
      phone_number: deal.phone_number || '',
      email: deal.email || '',
      birth_year: deal.birth_year || '',
      address: deal.address || '',
      industry: deal.industry || '',
      job_title: deal.job_title || '',
      expectation: deal.expectation || '',
      care_by: deal.care_by || 'Chưa phân công',
      page_id: deal.page_id || '',
      source_page: deal.source_page || 'Other/ Web',
      is_student: Boolean(deal.is_student),
      lead_tag: deal.lead_tag || '',
    });
  };

  const closeEditModal = () => {
    if (savingEdit) return;
    setEditModal(null);
    setEditForm({});
  };

  const handleSaveEdit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!editModal) return;
    setSavingEdit(true);
    try {
      const updated = await updateDealWinItem(editModal.id, editForm);
      setDeals((prev) => prev.map((d) => (d.id === updated.id ? { ...d, ...updated } : d)));
      if (detailModal && detailModal.id === updated.id) {
        setDetailModal(updated);
      }
      showAppToast('Đã lưu chỉnh sửa học viên vào database (ETL sẽ giữ nguyên bản ghi này).', 'success');
      setEditModal(null);
      setEditForm({});
      // Cập nhật lại options & summary nền
      fetchDealWinOptions(onlyStudent, { skipCache: true }).then(setOptions).catch(() => {});
      loadSummaryData(true);
    } catch (err: any) {
      console.error('Error saving deal edit:', err);
      showAppToast(err?.response?.data?.detail || 'Không thể lưu chỉnh sửa. Vui lòng thử lại.', 'error');
    } finally {
      setSavingEdit(false);
    }
  };

  const handleRefresh = () => {
    clearClientApiCache('/deals/');
    loadSummaryData(true);
    loadListData(page, true);
  };

  const total = summary?.total_deals || 0;

  // Format Top Sales for Bar Chart (memoized so typing in search doesn't re-sort)
  const topSalesData = React.useMemo(
    () =>
      Object.entries(summary?.sales_person_stats || {})
        .map(([name, count]) => ({ name, count }))
        .sort((a, b) => b.count - a.count)
        .slice(0, 8),
    [summary?.sales_person_stats]
  );

  const topSalesCount = React.useMemo(() => {
    if (summary?.top_sales_person && summary?.sales_person_stats) {
      const direct = summary.sales_person_stats[summary.top_sales_person];
      if (typeof direct === 'number') return direct;
    }
    return topSalesData[0]?.count ?? 0;
  }, [summary?.top_sales_person, summary?.sales_person_stats, topSalesData]);

  const BAR_COLORS = ['#1E5BD6', '#10B981', '#F59E0B', '#8B5CF6', '#EC4899', '#06B6D4', '#64748B', '#3B82F6'];

  return (
    <div className="space-y-6">
      {/* FILTER BAR */}
      <div className="bg-white rounded-2xl border border-[#E5E7EB] shadow-sm p-5">
        <div className="flex flex-wrap items-center justify-between gap-4 mb-4">
          <div className="flex items-center gap-2">
            <Filter className="w-4 h-4 text-[#1E5BD6]" />
            <span className="text-sm font-semibold text-navy">Bộ lọc Deal Win</span>
          </div>

          {/* Quick Date Presets */}
          <div className="flex items-center gap-1.5 bg-gray-100 p-1 rounded-xl text-xs">
            <button
              onClick={() => handleDatePreset('7d')}
              className={`px-3 py-1 rounded-lg font-medium transition-all ${
                datePreset === '7d' ? 'bg-white text-navy shadow-sm' : 'text-[#4B5563] hover:text-navy'
              }`}
            >
              7 ngày qua
            </button>
            <button
              onClick={() => handleDatePreset('30d')}
              className={`px-3 py-1 rounded-lg font-medium transition-all ${
                datePreset === '30d' ? 'bg-white text-navy shadow-sm' : 'text-[#4B5563] hover:text-navy'
              }`}
            >
              30 ngày qua
            </button>
            <button
              onClick={() => handleDatePreset('month')}
              className={`px-3 py-1 rounded-lg font-medium transition-all ${
                datePreset === 'month' ? 'bg-white text-navy shadow-sm' : 'text-[#4B5563] hover:text-navy'
              }`}
            >
              Tháng này
            </button>
            <button
              onClick={() => handleDatePreset('all')}
              className={`px-3 py-1 rounded-lg font-medium transition-all ${
                datePreset === 'all' ? 'bg-white text-navy shadow-sm' : 'text-[#4B5563] hover:text-navy'
              }`}
            >
              Toàn bộ
            </button>
          </div>
        </div>

        <div className="flex flex-wrap gap-3 items-end">
          {/* Custom Date Range */}
          <div className="flex flex-col gap-1">
            <label className="text-xs font-medium text-[#4B5563]">Từ ngày</label>
            <input
              type="date"
              value={startDate}
              onChange={e => {
                setStartDate(e.target.value);
                setDatePreset('custom');
              }}
              className="px-3 py-2 border border-[#E5E7EB] rounded-xl text-sm bg-white focus:outline-none focus:ring-2 focus:ring-[#1E5BD6]/20 focus:border-[#1E5BD6] transition-all text-[#111827]"
            />
          </div>

          <div className="flex flex-col gap-1">
            <label className="text-xs font-medium text-[#4B5563]">Đến ngày</label>
            <input
              type="date"
              value={endDate}
              onChange={e => {
                setEndDate(e.target.value);
                setDatePreset('custom');
              }}
              className="px-3 py-2 border border-[#E5E7EB] rounded-xl text-sm bg-white focus:outline-none focus:ring-2 focus:ring-[#1E5BD6]/20 focus:border-[#1E5BD6] transition-all text-[#111827]"
            />
          </div>

          <div className="h-9 w-px bg-[#E5E7EB] mx-1 hidden sm:block" />

          {/* Phân loại Học viên */}
          <div className="flex flex-col gap-1 min-w-[190px]">
            <label className="text-xs font-medium text-[#4B5563]">Phân loại Học viên</label>
            <select
              value={onlyStudent ? 'student' : 'all'}
              onChange={e => setOnlyStudent(e.target.value === 'student')}
              className="px-3 py-2 border border-[#E5E7EB] rounded-xl text-sm bg-white focus:outline-none focus:ring-2 focus:ring-[#1E5BD6]/20 focus:border-[#1E5BD6] transition-all text-[#111827] cursor-pointer font-medium"
            >
              <option value="student">✓ Có tag 'Đã là học viên'</option>
              <option value="all">Tất cả form đăng ký</option>
            </select>
          </div>

          {/* Sale Filter */}
          <div className="flex flex-col gap-1 min-w-[170px]">
            <label className="text-xs font-medium text-[#4B5563]">Nhân viên Sale</label>
            {isPersonalScope ? (
              <div className="px-3 py-2 border border-[#E5E7EB] bg-slate-50 rounded-xl text-sm text-[#111827] font-semibold truncate" title="Chỉ xem dữ liệu cá nhân">
                {personalEmployeeName}
              </div>
            ) : (
              <select
                value={selectedSale}
                onChange={e => setSelectedSale(e.target.value)}
                className="px-3 py-2 border border-[#E5E7EB] rounded-xl text-sm bg-white focus:outline-none focus:ring-2 focus:ring-[#1E5BD6]/20 focus:border-[#1E5BD6] transition-all text-[#111827] cursor-pointer font-medium"
              >
                <option value="">Tất cả Sale ({salesPersonsList.length})</option>
                {salesPersonsList.map(sp => (
                  <option key={sp} value={sp}>{sp}</option>
                ))}
              </select>
            )}
          </div>

          {/* Page Filter (Zalo Chăm Sóc) */}
          <div className="flex flex-col gap-1 min-w-[180px]">
            <label className="text-xs font-medium text-[#4B5563]">Page Zalo CS</label>
            <select
              value={selectedPage}
              onChange={e => setSelectedPage(e.target.value)}
              className="px-3 py-2 border border-[#E5E7EB] rounded-xl text-sm bg-white focus:outline-none focus:ring-2 focus:ring-[#1E5BD6]/20 focus:border-[#1E5BD6] transition-all text-[#111827] cursor-pointer font-medium"
            >
              <option value="">Tất cả Page ({(options.pages || []).length})</option>
              {(options.pages || []).map(pg => (
                <option key={pg} value={pg}>{pg}</option>
              ))}
            </select>
          </div>

          {/* Source Filter */}
          <div className="flex flex-col gap-1 min-w-[180px]">
            <label className="text-xs font-medium text-[#4B5563]">Nguồn</label>
            <select
              value={selectedSource}
              onChange={e => setSelectedSource(e.target.value)}
              className="px-3 py-2 border border-[#E5E7EB] rounded-xl text-sm bg-white focus:outline-none focus:ring-2 focus:ring-[#1E5BD6]/20 focus:border-[#1E5BD6] transition-all text-[#111827] cursor-pointer font-medium"
            >
              <option value="">Tất cả Nguồn ({(options.sources || []).length})</option>
              {(options.sources || []).map(src => (
                <option key={src} value={src}>{src}</option>
              ))}
            </select>
          </div>

          {/* Search Bar */}
          <form onSubmit={handleSearchSubmit} className="flex flex-col gap-1 flex-1 min-w-[240px]">
            <label htmlFor="dealwin-search" className="text-xs font-medium text-[#4B5563]">Tìm kiếm nhanh</label>
            <div className="flex items-center gap-1.5">
              <div className="relative flex-1">
                <input
                  id="dealwin-search"
                  type="search"
                  placeholder="Tên, SĐT, Email, Note... (Enter để tìm)"
                  value={searchQuery}
                  onChange={e => {
                    const v = e.target.value;
                    setSearchQuery(v);
                    if (!v.trim() && activeSearch) setActiveSearch('');
                  }}
                  className="w-full pl-9 pr-8 py-2 border border-[#E5E7EB] rounded-xl text-sm bg-white focus:outline-none focus:ring-2 focus:ring-[#1E5BD6]/20 focus:border-[#1E5BD6] transition-all text-[#111827]"
                />
                <Search className="w-4 h-4 text-gray-400 absolute left-3 top-2.5" aria-hidden="true" />
                {searchQuery && (
                  <button
                    type="button"
                    aria-label="Xóa từ khóa tìm kiếm"
                    onClick={() => {
                      setSearchQuery('');
                      setActiveSearch('');
                    }}
                    className="absolute right-2.5 top-2.5 text-gray-400 hover:text-gray-600 cursor-pointer"
                  >
                    <X className="w-4 h-4" aria-hidden="true" />
                  </button>
                )}
              </div>
              <button
                type="submit"
                className="px-3 py-2 rounded-xl text-xs font-semibold bg-eztech hover:bg-eztech-hover text-white transition-colors cursor-pointer shrink-0"
              >
                Tìm
              </button>
            </div>
          </form>

          {/* Action Buttons & Timestamp */}
          <div className="flex items-center gap-2 shrink-0">
            {lastUpdated && (
              <span className="text-xs text-gray-400 hidden xl:inline">
                Cập nhật: {format(lastUpdated, 'HH:mm:ss')}
              </span>
            )}
            {!isPersonalScope && (
              <button
                type="button"
                onClick={handleSyncPancake}
                disabled={syncingPancake || loadingSummary || loadingList}
                className="flex items-center gap-1.5 px-3 py-2 text-xs font-semibold text-emerald-700 bg-emerald-50 hover:bg-emerald-100 rounded-xl transition-colors disabled:opacity-50 border border-emerald-200 cursor-pointer"
                title="Đồng bộ tag 'Đã là học viên' và nhân viên chăm sóc từ Pancake"
              >
                <RefreshCw className={`w-3.5 h-3.5 ${syncingPancake ? 'animate-spin' : ''}`} aria-hidden="true" />
                <span>{syncingPancake ? 'Đang đồng bộ...' : 'Đồng bộ Pancake'}</span>
              </button>
            )}
            <button
              type="button"
              onClick={handleRefresh}
              disabled={loadingSummary || loadingList}
              className="flex items-center gap-1.5 px-3.5 py-2 text-xs font-semibold text-brand-600 bg-brand-50 hover:bg-brand-100 border border-brand-200/80 rounded-xl transition-colors disabled:opacity-50 cursor-pointer"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${loadingSummary || loadingList ? 'animate-spin' : ''}`} aria-hidden="true" />
              <span>Làm mới</span>
            </button>
          </div>
        </div>
      </div>

      <ErrorBanner message={errorMsg} onRetry={handleRefresh} />

      {/* KPI METRICS ROW */}
      <div className="ez-kpi-grid grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-5">
        {/* Card 1: Total Deals */}
        <div className="bg-white rounded-2xl border border-[#E5E7EB] p-5 shadow-sm hover:shadow-md transition-all flex flex-col justify-between">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-[#4B5563]">Tổng Học Viên Chốt</span>
            <div className="w-10 h-10 rounded-xl bg-brand-100 text-brand-600 flex items-center justify-center">
              <Award className="w-5 h-5" aria-hidden="true" />
            </div>
          </div>
          <div className="mt-4">
            <div className="text-3xl font-bold text-navy tracking-tight font-mono">
              {loadingSummary ? '...' : total.toLocaleString('vi-VN')}
            </div>
          </div>
        </div>

        {/* Card 2: Conversion Rate (Tỷ lệ Convert: Deal Win / SĐT) */}
        <div className="bg-white rounded-2xl border border-emerald-200/90 p-5 shadow-sm hover:shadow-md transition-all flex flex-col justify-between relative overflow-hidden">
          <div className="absolute top-0 right-0 w-24 h-24 bg-emerald-50 rounded-bl-full z-0 pointer-events-none" />
          <div className="relative z-10 flex items-center justify-between">
            <span className="text-xs font-bold text-emerald-800">Tỷ Lệ Convert (Chốt / SĐT)</span>
            <div className="w-10 h-10 rounded-xl bg-emerald-100 text-emerald-700 flex items-center justify-center shadow-sm">
              <TrendingUp className="w-5 h-5" aria-hidden="true" />
            </div>
          </div>
          <div className="mt-4 relative z-10">
            <div className="text-3xl font-bold text-emerald-600 tracking-tight font-mono">
              {loadingSummary ? '...' : `${summary?.conversion_rate || 0}%`}
            </div>
            <p className="text-xs font-semibold text-emerald-700 mt-1 font-mono">
              {total.toLocaleString('vi-VN')} deal / {(summary?.total_phones || 0).toLocaleString('vi-VN')} SĐT thu về
            </p>
          </div>
        </div>

        {/* Card 3: Total Phones in Period */}
        <div className="bg-white rounded-2xl border border-[#E5E7EB] p-5 shadow-sm hover:shadow-md transition-all flex flex-col justify-between">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-[#4B5563]">SĐT Thu Về Trong Kỳ</span>
            <div className="w-10 h-10 rounded-xl bg-purple-100 text-purple-600 flex items-center justify-center">
              <PhoneCall className="w-5 h-5" aria-hidden="true" />
            </div>
          </div>
          <div className="mt-4">
            <div className="text-3xl font-bold text-navy tracking-tight font-mono">
              {loadingSummary ? '...' : (summary?.total_phones || 0).toLocaleString('vi-VN')}
            </div>
          </div>
        </div>

        {/* Card 4: Top Sales */}
        <div className="bg-white rounded-2xl border border-[#E5E7EB] p-5 shadow-sm hover:shadow-md transition-all flex flex-col justify-between">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-[#4B5563]">Top Nhân Viên Chốt</span>
            <div className="w-10 h-10 rounded-xl bg-amber-100 text-amber-600 flex items-center justify-center">
              <Users className="w-5 h-5" aria-hidden="true" />
            </div>
          </div>
          <div className="mt-4">
            <div className="text-2xl font-bold text-navy tracking-tight truncate" title={summary?.top_sales_person || 'Chưa có'}>
              {loadingSummary ? '...' : (summary?.top_sales_person || 'Chưa có')}
            </div>
            <p className="text-xs font-medium text-amber-600 mt-1">
              {topSalesCount > 0 ? `${topSalesCount} deal chốt thành công` : 'Đóng góp nhiều Deal Win nhất'}
            </p>
          </div>
        </div>
      </div>

      {/* CHARTS SECTION */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Trend Area Chart (2/3 width) */}
        <div className="lg:col-span-2 bg-white rounded-2xl border border-[#E5E7EB] p-6 shadow-sm">
          <div className="mb-6">
            <h3 className="text-base font-semibold text-navy">Xu hướng Deal Win theo ngày</h3>
          </div>

          <ResponsiveContainer width="100%" height={260}>
            <AreaChart
              data={summary?.daily_trend || []}
              margin={{ top: 10, right: 10, left: -20, bottom: 0 }}
            >
              <defs>
                <linearGradient id="colorDealTrend" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#1E5BD6" stopOpacity={0.25} />
                  <stop offset="95%" stopColor="#1E5BD6" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="var(--ez-chart-grid)" />
              <XAxis
                dataKey="date"
                tickFormatter={str => {
                  if (!str) return '';
                  const parts = str.split('-');
                  return parts.length >= 3 ? `${parts[2]}/${parts[1]}` : str;
                }}
                tick={{ fontSize: 11, fill: 'var(--ez-chart-axis)' }}
                axisLine={false}
                tickLine={false}
              />
              <YAxis
                allowDecimals={false}
                tick={{ fontSize: 11, fill: 'var(--ez-chart-axis)' }}
                axisLine={false}
                tickLine={false}
              />
              <RechartsTooltip
                content={({ active, payload, label }) => {
                  if (active && payload && payload.length) {
                    return (
                      <div className="bg-white border border-[#E5E7EB] rounded-xl shadow-lg p-3 text-xs">
                        <p className="font-semibold text-gray-700 mb-1">{label}</p>
                        <div className="flex items-center gap-2">
                          <span className="w-2.5 h-2.5 rounded-full bg-[#1E5BD6]" />
                          <span className="text-[#4B5563]">Học viên chốt:</span>
                          <span className="font-bold text-navy">{payload[0].value}</span>
                        </div>
                      </div>
                    );
                  }
                  return null;
                }}
              />
              <Area
                type="monotone"
                dataKey="count"
                name="Học viên"
                stroke="#1E5BD6"
                strokeWidth={2.5}
                fillOpacity={1}
                fill="url(#colorDealTrend)"
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>

        {/* Top Sales Bar Chart (1/3 width) */}
        <div className="bg-white rounded-2xl border border-[#E5E7EB] p-6 shadow-sm flex flex-col justify-between">
          <div className="mb-4">
            <h3 className="text-base font-semibold text-navy">Top Sales chốt Deal</h3>
          </div>

          {topSalesData.length > 0 ? (
            <ResponsiveContainer width="100%" height={240}>
              <BarChart
                layout="vertical"
                data={topSalesData}
                margin={{ top: 0, right: 20, left: 20, bottom: 0 }}
              >
                <CartesianGrid strokeDasharray="3 3" horizontal={false} stroke="var(--ez-chart-grid)" />
                <XAxis type="number" allowDecimals={false} tick={{ fontSize: 10, fill: 'var(--ez-chart-axis)' }} axisLine={false} tickLine={false} />
                <YAxis
                  dataKey="name"
                  type="category"
                  tick={{ fontSize: 11, fill: 'var(--ez-text)', fontWeight: 500 }}
                  axisLine={false}
                  tickLine={false}
                  width={90}
                />
                <RechartsTooltip
                  content={({ active, payload }) => {
                    if (active && payload && payload.length) {
                      const data = payload[0].payload;
                      return (
                        <div className="bg-white border border-[#E5E7EB] rounded-xl shadow-lg p-2.5 text-xs">
                          <p className="font-bold text-navy">{data.name}</p>
                          <p className="text-[#4B5563] mt-0.5">Số học viên: <span className="font-bold text-blue-600">{data.count}</span></p>
                        </div>
                      );
                    }
                    return null;
                  }}
                />
                <Bar dataKey="count" radius={[0, 6, 6, 0]}>
                  {topSalesData.map((_, index) => (
                    <Cell key={`cell-${index}`} fill={BAR_COLORS[index % BAR_COLORS.length]} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <div className="h-[240px] flex items-center justify-center text-xs text-gray-400">
              Chưa có dữ liệu Sale trong kỳ
            </div>
          )}
        </div>
      </div>

      {/* DATA TABLE */}
      <div className="bg-white rounded-2xl border border-[#E5E7EB] shadow-sm overflow-hidden flex flex-col">
        <div className="px-6 py-4 border-b border-[#E5E7EB] flex flex-wrap items-center justify-between gap-4">
          <div>
            <h3 className="text-base font-semibold text-navy">Danh sách Học viên Chốt (Deal Win)</h3>
            <p className="text-xs text-[#4B5563] mt-0.5">
              Tìm thấy <span className="font-bold text-navy">{totalDeals}</span> học viên
              {activeSearch && ` (theo từ khóa: "${activeSearch}")`}
            </p>
          </div>

          {/* Quick Pagination info */}
          <div className="flex items-center gap-2">
            <span className="text-xs text-[#4B5563]">
              Trang {page} / {totalPages || 1}
            </span>
            <div className="flex items-center gap-1">
              <button
                onClick={() => loadListData(page - 1)}
                disabled={page <= 1 || loadingList}
                className="p-1.5 rounded-lg border border-[#E5E7EB] hover:bg-gray-50 disabled:opacity-40 transition-colors"
                title="Trang trước"
              >
                <ChevronLeft className="w-4 h-4 text-gray-600" />
              </button>
              <button
                onClick={() => loadListData(page + 1)}
                disabled={page >= totalPages || loadingList}
                className="p-1.5 rounded-lg border border-[#E5E7EB] hover:bg-gray-50 disabled:opacity-40 transition-colors"
                title="Trang sau"
              >
                <ChevronRight className="w-4 h-4 text-gray-600" />
              </button>
            </div>
          </div>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-sm text-left">
            <thead>
              <tr className="text-xs text-[#4B5563] bg-[#F3F6FA] uppercase tracking-wide">
                <th className="px-5 py-3 font-semibold">Thời gian</th>
                <th className="px-5 py-3 font-semibold">Học Viên</th>
                <th className="px-5 py-3 font-semibold">SĐT / Email</th>
                <th className="px-5 py-3 font-semibold">Page Zalo CS</th>
                <th className="px-5 py-3 font-semibold">Nguồn</th>
                <th className="px-5 py-3 font-semibold">Sale Chăm Sóc</th>
                <th className="px-5 py-3 font-semibold text-right">Chi Tiết</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#E5E7EB]">
              {loadingList ? (
                <tr>
                  <td colSpan={7} className="px-6 py-12 text-center text-xs text-gray-500">
                    <RefreshCw className="w-5 h-5 animate-spin mx-auto mb-2 text-[#1E5BD6]" />
                    Đang tải danh sách học viên...
                  </td>
                </tr>
              ) : deals.length > 0 ? (
                deals.map(deal => {
                  return (
                    <tr key={deal.id} className="hover:bg-[#F8FAFC] transition-colors group">
                      {/* Time */}
                      <td className="px-5 py-3.5 whitespace-nowrap text-xs text-gray-500">
                        {deal.timestamp ? (
                          <>
                            <div className="font-medium text-gray-800">
                              {safeFormatDate(deal.timestamp, 'dd/MM/yyyy')}
                            </div>
                            <div className="text-[11px] text-gray-400">
                              {safeFormatDate(deal.timestamp, 'HH:mm', '')}
                            </div>
                          </>
                        ) : (
                          '—'
                        )}
                      </td>

                      {/* Student Name */}
                      <td className="px-5 py-3.5 whitespace-nowrap">
                        <div className="flex items-center gap-2.5">
                          <div className="w-8 h-8 rounded-full bg-brand-100 text-brand-600 flex items-center justify-center text-xs font-bold shrink-0">
                            {(deal.full_name || 'H').charAt(0).toUpperCase()}
                          </div>
                          <div>
                            <div className="font-semibold text-navy flex items-center gap-1.5 flex-wrap">
                              <span>{deal.full_name || 'Học viên'}</span>
                              {deal.is_student && (
                                <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-semibold bg-emerald-50 text-emerald-700 border border-emerald-200">
                                  Học viên
                                </span>
                              )}
                              {deal.is_manually_edited && (
                                <span
                                  title={deal.edited_by ? `Đã sửa bởi ${deal.edited_by} (ETL không ghi đè lại)` : 'Đã chỉnh sửa thủ công (ETL không ghi đè lại)'}
                                  className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[10px] font-semibold bg-amber-50 text-amber-700 border border-amber-200"
                                >
                                  <ShieldCheck className="w-2.5 h-2.5" aria-hidden="true" />
                                  Đã sửa
                                </span>
                              )}
                            </div>
                            {deal.birth_year && (
                              <div className="text-[11px] text-gray-400">
                                Năm sinh: {deal.birth_year}
                              </div>
                            )}
                          </div>
                        </div>
                      </td>

                      {/* Phone & Email */}
                      <td className="px-5 py-3.5 whitespace-nowrap text-xs">
                        <div className="font-medium text-navy">{deal.phone_number || '—'}</div>
                        {deal.email && (
                          <div className="text-[11px] text-gray-400 max-w-[150px] truncate" title={deal.email}>
                            {deal.email}
                          </div>
                        )}
                      </td>

                      {/* Page Zalo CS */}
                      <td className="px-5 py-3.5 whitespace-nowrap text-xs">
                        {deal.page_id ? (
                          <span className="font-medium text-brand-700 bg-brand-50 px-2 py-0.5 rounded-md border border-brand-200/60">
                            {deal.page_id}
                          </span>
                        ) : (
                          <span className="text-gray-400">—</span>
                        )}
                      </td>

                      {/* Nguồn */}
                      <td className="px-5 py-3.5 whitespace-nowrap text-xs">
                        {(() => {
                          const src = deal.source_page || 'Other/ Web';
                          const isOther = src === 'Other/ Web';
                          return (
                            <span
                              className={`font-medium px-2 py-0.5 rounded-md border ${
                                isOther
                                  ? 'text-gray-600 bg-gray-100 border-gray-200'
                                  : 'text-indigo-700 bg-indigo-50 border-indigo-200/70'
                              }`}
                            >
                              {src}
                            </span>
                          );
                        })()}
                      </td>

                      {/* Care by Sale */}
                      <td className="px-5 py-3.5 whitespace-nowrap text-xs">
                        <span className="font-semibold text-navy bg-slate-100/90 px-2 py-0.5 rounded-md border border-slate-200">
                          {deal.care_by || 'Chưa phân công'}
                        </span>
                      </td>

                      {/* Action */}
                      <td className="px-5 py-3.5 whitespace-nowrap text-right">
                        <div className="inline-flex items-center justify-end gap-1.5">
                          <button
                            type="button"
                            onClick={() => handleOpenEdit(deal)}
                            className="inline-flex items-center gap-1 text-xs font-semibold text-amber-700 hover:text-amber-900 bg-amber-50 hover:bg-amber-100 border border-amber-200/80 px-2.5 py-1 rounded-lg transition-colors cursor-pointer"
                            title="Chỉnh sửa thông tin học viên (lưu vào DB & khóa không cho ETL ghi đè)"
                          >
                            <Pencil className="w-3.5 h-3.5" aria-hidden="true" />
                            <span>Sửa</span>
                          </button>
                          <button
                            type="button"
                            onClick={() => handleOpenDetail(deal)}
                            className="inline-flex items-center gap-1 text-xs font-semibold text-brand-600 hover:text-navy bg-brand-50 hover:bg-brand-100 border border-brand-200/60 px-2.5 py-1 rounded-lg transition-colors cursor-pointer"
                          >
                            <Eye className="w-3.5 h-3.5" aria-hidden="true" />
                            <span>Xem</span>
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })
              ) : (
                <tr>
                  <td colSpan={7} className="px-6 py-12 text-center text-xs text-gray-500">
                    Không tìm thấy học viên nào phù hợp với bộ lọc hiện tại.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        {/* BOTTOM PAGINATION */}
        <div className="px-6 py-4 border-t border-[#E5E7EB] flex flex-wrap items-center justify-between gap-4 text-xs text-[#4B5563]">
          <div>
            Hiển thị{' '}
            <span className="font-semibold text-navy">
              {deals.length > 0 ? (page - 1) * pageSize + 1 : 0}
            </span>{' '}
            -{' '}
            <span className="font-semibold text-navy">
              {Math.min(page * pageSize, totalDeals)}
            </span>{' '}
            trong tổng số <span className="font-semibold text-navy">{totalDeals}</span> học viên
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={() => loadListData(page - 1, true)}
              disabled={page <= 1 || loadingList}
              className="px-3 py-1.5 rounded-lg border border-[#E5E7EB] hover:bg-gray-50 disabled:opacity-40 transition-colors font-medium"
            >
              Trang trước
            </button>
            <span className="px-2 font-semibold text-navy">
              {page} / {totalPages || 1}
            </span>
            <button
              onClick={() => loadListData(page + 1, true)}
              disabled={page >= totalPages || loadingList}
              className="px-3 py-1.5 rounded-lg border border-[#E5E7EB] hover:bg-gray-50 disabled:opacity-40 transition-colors font-medium"
            >
              Trang sau
            </button>
          </div>
        </div>
      </div>

      {/* DETAIL MODAL */}
      <AccessibleModal
        isOpen={Boolean(detailModal)}
        onClose={closeDetailModal}
        labelledBy="deal-detail-modal-title"
        overlayClassName="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50 backdrop-blur-sm"
      >
        {detailModal && (
          <div className="bg-white rounded-2xl max-w-2xl w-full max-h-[90vh] overflow-y-auto shadow-2xl border border-gray-100 flex flex-col">
            {/* Modal Header */}
            <div className="px-6 py-4 border-b border-gray-100 flex items-center justify-between sticky top-0 bg-white z-10">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-full bg-brand-100 text-brand-600 flex items-center justify-center text-sm font-bold">
                  {(detailModal.full_name || 'H').charAt(0).toUpperCase()}
                </div>
                <div>
                  <h3 id="deal-detail-modal-title" className="text-base font-bold text-navy">
                    {detailModal.full_name || 'Học viên'}
                  </h3>
                  <p className="text-xs text-gray-500">Mã dòng: {detailModal.sheet_row_id || 'N/A'}</p>
                </div>
              </div>
              <button
                type="button"
                aria-label="Đóng chi tiết học viên"
                onClick={closeDetailModal}
                className="p-1.5 rounded-lg text-gray-400 hover:text-gray-600 hover:bg-gray-100 transition-colors cursor-pointer"
              >
                <X className="w-5 h-5" aria-hidden="true" />
              </button>
            </div>

            {/* Modal Content */}
            <div className="p-6 space-y-5 text-sm">
              {loadingDetail && (
                <div className="text-center py-2 text-xs text-brand-600 flex items-center justify-center gap-2">
                  <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                  Đang tải thông tin chi tiết đầy đủ...
                </div>
              )}

              {/* Thông tin cơ bản */}
              <div>
                <h4 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2.5">
                  Thông tin liên hệ & cá nhân
                </h4>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 bg-gray-50 p-4 rounded-xl">
                  <div className="flex items-center gap-2 text-gray-700">
                    <Phone className="w-4 h-4 text-gray-400 shrink-0" />
                    <span className="font-medium text-navy">{detailModal.phone_number || 'Chưa có SĐT'}</span>
                  </div>
                  <div className="flex items-center gap-2 text-gray-700">
                    <Mail className="w-4 h-4 text-gray-400 shrink-0" />
                    <span className="truncate">{detailModal.email || 'Chưa có Email'}</span>
                  </div>
                  <div className="flex items-center gap-2 text-gray-700">
                    <Calendar className="w-4 h-4 text-gray-400 shrink-0" />
                    <span>Năm sinh: <strong>{detailModal.birth_year || '—'}</strong></span>
                  </div>
                  <div className="flex items-center gap-2 text-gray-700">
                    <MapPin className="w-4 h-4 text-gray-400 shrink-0" />
                    <span className="truncate">{detailModal.address || 'Chưa có địa chỉ'}</span>
                  </div>
                </div>
              </div>

              {/* Phụ trách & Trạng thái Pancake */}
              <div>
                <h4 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2.5">
                  Phụ trách & Trạng thái Pancake
                </h4>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 bg-gray-50 p-4 rounded-xl">
                  <div>
                    <span className="text-xs text-gray-500 block">Sale phụ trách (Care by):</span>
                    <span className="font-semibold text-navy">{detailModal.care_by || 'Chưa phân công'}</span>
                  </div>
                  <div>
                    <span className="text-xs text-gray-500 block">Page Zalo chăm sóc:</span>
                    <span className="font-semibold text-blue-700">{detailModal.page_id || '—'}</span>
                  </div>
                  <div>
                    <span className="text-xs text-gray-500 block">Nguồn (FB / TikTok / Web):</span>
                    <span className="font-semibold text-indigo-700">{detailModal.source_page || 'Other/ Web'}</span>
                  </div>
                  <div className="sm:col-span-2">
                    <span className="text-xs text-gray-500 block">Trạng thái gắn tag Pancake:</span>
                    <div className="flex items-center gap-2 mt-0.5">
                      {detailModal.is_student ? (
                        <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-semibold bg-emerald-100 text-emerald-800">
                          ✓ Đã là học viên
                        </span>
                      ) : (
                        <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-gray-100 text-gray-600">
                          Chưa có tag Học viên
                        </span>
                      )}
                      {detailModal.lead_tag && (
                        <span className="text-xs text-gray-500 truncate" title={detailModal.lead_tag}>
                          (Tags: {detailModal.lead_tag})
                        </span>
                      )}
                    </div>
                  </div>
                </div>
              </div>

              {/* Ngành nghề & Kỳ vọng */}
              <div>
                <h4 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2.5">
                  Khảo sát & Nguyện vọng
                </h4>
                <div className="space-y-3 bg-gray-50 p-4 rounded-xl">
                  <div>
                    <div className="flex items-center gap-1.5 text-xs text-gray-500 mb-1">
                      <Briefcase className="w-3.5 h-3.5" />
                      <span>Vị trí / Nghề nghiệp / Lĩnh vực:</span>
                    </div>
                    <p className="text-gray-800 font-medium">
                      {detailModal.job_title || detailModal.industry
                        ? `${detailModal.job_title || ''} ${detailModal.industry ? `(${detailModal.industry})` : ''}`
                        : 'Chưa cập nhật'}
                    </p>
                  </div>

                  <div>
                    <div className="flex items-center gap-1.5 text-xs text-gray-500 mb-1">
                      <FileText className="w-3.5 h-3.5" />
                      <span>Mục đích / Kỳ vọng tham gia khóa học:</span>
                    </div>
                    <p className="text-gray-800 bg-white p-3 rounded-lg border border-gray-200 whitespace-pre-wrap">
                      {detailModal.expectation || 'Không có ghi chú kỳ vọng.'}
                    </p>
                  </div>
                </div>
              </div>
            </div>

            {/* Modal Footer */}
            <div className="px-6 py-3 border-t border-gray-100 flex items-center justify-between gap-3 bg-gray-50 rounded-b-2xl">
              <div>
                {detailModal.is_manually_edited && (
                  <span className="inline-flex items-center gap-1 text-[11px] font-medium text-amber-700">
                    <ShieldCheck className="w-3.5 h-3.5" aria-hidden="true" />
                    Đã sửa thủ công{detailModal.edited_by ? ` bởi ${detailModal.edited_by}` : ''} — ETL giữ nguyên
                  </span>
                )}
              </div>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => {
                    const target = detailModal;
                    closeDetailModal();
                    handleOpenEdit(target);
                  }}
                  className="inline-flex items-center gap-1.5 px-4 py-2 text-xs font-semibold text-amber-800 bg-amber-50 hover:bg-amber-100 border border-amber-200 rounded-xl transition-colors cursor-pointer"
                >
                  <Pencil className="w-3.5 h-3.5" aria-hidden="true" />
                  Chỉnh sửa
                </button>
                <button
                  type="button"
                  onClick={closeDetailModal}
                  className="px-4 py-2 text-xs font-semibold text-gray-700 bg-white border border-gray-200 rounded-xl hover:bg-gray-100 transition-colors cursor-pointer"
                >
                  Đóng
                </button>
              </div>
            </div>
          </div>
        )}
      </AccessibleModal>

      {/* EDIT MODAL */}
      <AccessibleModal
        isOpen={Boolean(editModal)}
        onClose={closeEditModal}
        labelledBy="deal-edit-modal-title"
        overlayClassName="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50 backdrop-blur-sm"
      >
        {editModal && (
          <form
            onSubmit={handleSaveEdit}
            className="bg-white rounded-2xl max-w-2xl w-full max-h-[90vh] overflow-y-auto shadow-2xl border border-gray-100 flex flex-col"
          >
            {/* Header */}
            <div className="px-6 py-4 border-b border-gray-100 flex items-center justify-between sticky top-0 bg-white z-10">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-full bg-amber-50 text-amber-700 border border-amber-200 flex items-center justify-center">
                  <Pencil className="w-4 h-4" aria-hidden="true" />
                </div>
                <div>
                  <h3 id="deal-edit-modal-title" className="text-base font-bold text-navy">
                    Chỉnh sửa học viên Deal Win
                  </h3>
                  <p className="text-xs text-gray-500">
                    ID #{editModal.id}{editModal.sheet_row_id ? ` • ${editModal.sheet_row_id}` : ''}
                  </p>
                </div>
              </div>
              <button
                type="button"
                aria-label="Đóng chỉnh sửa học viên"
                onClick={closeEditModal}
                className="p-1.5 rounded-lg text-gray-400 hover:text-gray-600 hover:bg-gray-100 transition-colors cursor-pointer"
              >
                <X className="w-5 h-5" aria-hidden="true" />
              </button>
            </div>

            {/* Body */}
            <div className="p-6 space-y-4 text-sm">
              <div className="flex items-start gap-2.5 p-3 rounded-xl bg-amber-50 border border-amber-200 text-xs text-amber-800">
                <ShieldCheck className="w-4 h-4 shrink-0 mt-0.5" aria-hidden="true" />
                <span>
                  Khi lưu chỉnh sửa, bản ghi này sẽ được đánh dấu <strong>Đã chỉnh sửa thủ công</strong> vào database và quy trình ETL / đồng bộ Pancake sẽ <strong>không cào đè lại</strong> nữa.
                </span>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3.5">
                <div>
                  <label className="block text-xs font-semibold text-navy mb-1">Họ và tên</label>
                  <input
                    type="text"
                    required
                    value={editForm.full_name || ''}
                    onChange={(e) => setEditForm((f) => ({ ...f, full_name: e.target.value }))}
                    className="w-full px-3 py-2 border border-[#E5E7EB] rounded-xl text-sm bg-white focus:outline-none focus:ring-2 focus:ring-[#1E5BD6]/20 focus:border-[#1E5BD6]"
                  />
                </div>
                <div>
                  <label className="block text-xs font-semibold text-navy mb-1">Số điện thoại</label>
                  <input
                    type="text"
                    value={editForm.phone_number || ''}
                    onChange={(e) => setEditForm((f) => ({ ...f, phone_number: e.target.value }))}
                    className="w-full px-3 py-2 border border-[#E5E7EB] rounded-xl text-sm bg-white focus:outline-none focus:ring-2 focus:ring-[#1E5BD6]/20 focus:border-[#1E5BD6]"
                  />
                </div>
                <div>
                  <label className="block text-xs font-semibold text-navy mb-1">Email</label>
                  <input
                    type="text"
                    value={editForm.email || ''}
                    onChange={(e) => setEditForm((f) => ({ ...f, email: e.target.value }))}
                    className="w-full px-3 py-2 border border-[#E5E7EB] rounded-xl text-sm bg-white focus:outline-none focus:ring-2 focus:ring-[#1E5BD6]/20 focus:border-[#1E5BD6]"
                  />
                </div>
                <div>
                  <label className="block text-xs font-semibold text-navy mb-1">Năm sinh / Ngày sinh</label>
                  <input
                    type="text"
                    value={editForm.birth_year || ''}
                    onChange={(e) => setEditForm((f) => ({ ...f, birth_year: e.target.value }))}
                    className="w-full px-3 py-2 border border-[#E5E7EB] rounded-xl text-sm bg-white focus:outline-none focus:ring-2 focus:ring-[#1E5BD6]/20 focus:border-[#1E5BD6]"
                  />
                </div>
                <div className="sm:col-span-2">
                  <label className="block text-xs font-semibold text-navy mb-1">Địa chỉ (Tỉnh / Thành phố)</label>
                  <input
                    type="text"
                    value={editForm.address || ''}
                    onChange={(e) => setEditForm((f) => ({ ...f, address: e.target.value }))}
                    className="w-full px-3 py-2 border border-[#E5E7EB] rounded-xl text-sm bg-white focus:outline-none focus:ring-2 focus:ring-[#1E5BD6]/20 focus:border-[#1E5BD6]"
                  />
                </div>
                <div>
                  <label className="block text-xs font-semibold text-navy mb-1">Sale chăm sóc (Care by)</label>
                  <select
                    value={editForm.care_by || 'Chưa phân công'}
                    onChange={(e) => setEditForm((f) => ({ ...f, care_by: e.target.value }))}
                    className="w-full px-3 py-2 border border-[#E5E7EB] rounded-xl text-sm bg-white focus:outline-none focus:ring-2 focus:ring-[#1E5BD6]/20 focus:border-[#1E5BD6] cursor-pointer"
                  >
                    <option value="Chưa phân công">Chưa phân công</option>
                    {editForm.care_by &&
                      editForm.care_by !== 'Chưa phân công' &&
                      !salesPersonsList.includes(editForm.care_by) && (
                        <option value={editForm.care_by}>{editForm.care_by}</option>
                      )}
                    {salesPersonsList.map((sp) => (
                      <option key={sp} value={sp}>
                        {sp}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="block text-xs font-semibold text-navy mb-1">Page Zalo CS</label>
                  <select
                    value={editForm.page_id || ''}
                    onChange={(e) => setEditForm((f) => ({ ...f, page_id: e.target.value }))}
                    className="w-full px-3 py-2 border border-[#E5E7EB] rounded-xl text-sm bg-white focus:outline-none focus:ring-2 focus:ring-[#1E5BD6]/20 focus:border-[#1E5BD6] cursor-pointer"
                  >
                    <option value="">— Chưa xác định —</option>
                    {editForm.page_id && !(options.pages || []).includes(editForm.page_id) && (
                      <option value={editForm.page_id}>{editForm.page_id}</option>
                    )}
                    {(options.pages || []).map((pg) => (
                      <option key={pg} value={pg}>
                        {pg}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="block text-xs font-semibold text-navy mb-1">Nguồn</label>
                  <select
                    value={editForm.source_page || 'Other/ Web'}
                    onChange={(e) => setEditForm((f) => ({ ...f, source_page: e.target.value }))}
                    className="w-full px-3 py-2 border border-[#E5E7EB] rounded-xl text-sm bg-white focus:outline-none focus:ring-2 focus:ring-[#1E5BD6]/20 focus:border-[#1E5BD6] cursor-pointer"
                  >
                    {!(options.sources || []).includes('Other/ Web') && (
                      <option value="Other/ Web">Other/ Web</option>
                    )}
                    {editForm.source_page &&
                      editForm.source_page !== 'Other/ Web' &&
                      !(options.sources || []).includes(editForm.source_page) && (
                        <option value={editForm.source_page}>{editForm.source_page}</option>
                      )}
                    {(options.sources || []).map((src) => (
                      <option key={src} value={src}>
                        {src}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="block text-xs font-semibold text-navy mb-1">Tags Pancake</label>
                  <input
                    type="text"
                    value={editForm.lead_tag || ''}
                    onChange={(e) => setEditForm((f) => ({ ...f, lead_tag: e.target.value }))}
                    placeholder="VD: Đã là học viên"
                    className="w-full px-3 py-2 border border-[#E5E7EB] rounded-xl text-sm bg-white focus:outline-none focus:ring-2 focus:ring-[#1E5BD6]/20 focus:border-[#1E5BD6]"
                  />
                </div>
                <div>
                  <label className="block text-xs font-semibold text-navy mb-1">Lĩnh vực hoạt động</label>
                  <input
                    type="text"
                    value={editForm.industry || ''}
                    onChange={(e) => setEditForm((f) => ({ ...f, industry: e.target.value }))}
                    className="w-full px-3 py-2 border border-[#E5E7EB] rounded-xl text-sm bg-white focus:outline-none focus:ring-2 focus:ring-[#1E5BD6]/20 focus:border-[#1E5BD6]"
                  />
                </div>
                <div>
                  <label className="block text-xs font-semibold text-navy mb-1">Vị trí / Ngành nghề</label>
                  <input
                    type="text"
                    value={editForm.job_title || ''}
                    onChange={(e) => setEditForm((f) => ({ ...f, job_title: e.target.value }))}
                    className="w-full px-3 py-2 border border-[#E5E7EB] rounded-xl text-sm bg-white focus:outline-none focus:ring-2 focus:ring-[#1E5BD6]/20 focus:border-[#1E5BD6]"
                  />
                </div>
                <div className="sm:col-span-2">
                  <label className="inline-flex items-center gap-2 text-xs font-semibold text-navy cursor-pointer select-none">
                    <input
                      type="checkbox"
                      checked={Boolean(editForm.is_student)}
                      onChange={(e) => setEditForm((f) => ({ ...f, is_student: e.target.checked }))}
                      className="rounded border-gray-300 text-brand-600 focus:ring-brand-500"
                    />
                    <span>Đánh dấu đã là học viên (có tag &apos;Đã là học viên&apos;)</span>
                  </label>
                </div>
                <div className="sm:col-span-2">
                  <label className="block text-xs font-semibold text-navy mb-1">Mục đích / Kỳ vọng tham gia khoá học</label>
                  <textarea
                    rows={3}
                    value={editForm.expectation || ''}
                    onChange={(e) => setEditForm((f) => ({ ...f, expectation: e.target.value }))}
                    className="w-full px-3 py-2 border border-[#E5E7EB] rounded-xl text-sm bg-white focus:outline-none focus:ring-2 focus:ring-[#1E5BD6]/20 focus:border-[#1E5BD6]"
                  />
                </div>
              </div>
            </div>

            {/* Footer */}
            <div className="px-6 py-3 border-t border-gray-100 flex items-center justify-end gap-2 bg-gray-50 rounded-b-2xl">
              <button
                type="button"
                onClick={closeEditModal}
                disabled={savingEdit}
                className="px-4 py-2 text-xs font-semibold text-gray-700 bg-white border border-gray-200 rounded-xl hover:bg-gray-100 transition-colors cursor-pointer disabled:opacity-50"
              >
                Hủy
              </button>
              <button
                type="submit"
                disabled={savingEdit}
                className="inline-flex items-center gap-1.5 px-4 py-2 text-xs font-semibold text-white bg-brand-600 hover:bg-brand-700 rounded-xl shadow-xs transition-colors cursor-pointer disabled:opacity-50"
              >
                <Save className="w-3.5 h-3.5" aria-hidden="true" />
                <span>{savingEdit ? 'Đang lưu...' : 'Lưu thay đổi'}</span>
              </button>
            </div>
          </form>
        )}
      </AccessibleModal>
    </div>
  );
}
