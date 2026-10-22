import React, { useState, useEffect } from 'react';
import { format, subDays, startOfMonth } from 'date-fns';
import {
  Award,
  CreditCard,
  UserCheck,
  BookOpen,
  Filter,
  RefreshCw,
  Search,
  ChevronLeft,
  ChevronRight,
  Eye,
  X,
  Phone,
  Mail,
  Calendar,
  MapPin,
  Briefcase,
  Share2,
  FileText
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
  fetchDealWinDetail,
  type DealWinItem,
  type DealWinSummary,
  type DealWinOptions
} from '../services/api';
import { StatsPieChart } from './StatsPieChart';

export function DealWinDashboard() {
  // Preset dates: default to 30 days
  const [startDate, setStartDate] = useState(format(subDays(new Date(), 30), 'yyyy-MM-dd'));
  const [endDate, setEndDate] = useState(format(new Date(), 'yyyy-MM-dd'));
  const [datePreset, setDatePreset] = useState<'7d' | '30d' | 'month' | 'all' | 'custom'>('30d');

  // Filters
  const [selectedSale, setSelectedSale] = useState('');
  const [selectedCourse, setSelectedCourse] = useState('');
  const [searchQuery, setSearchQuery] = useState('');
  const [activeSearch, setActiveSearch] = useState('');

  // Dropdown options
  const [options, setOptions] = useState<DealWinOptions>({ sales_persons: [], products: [] });

  // Data states
  const [summary, setSummary] = useState<DealWinSummary | null>(null);
  const [deals, setDeals] = useState<DealWinItem[]>([]);
  const [totalDeals, setTotalDeals] = useState(0);
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const pageSize = 20;

  // Loading & status
  const [loadingSummary, setLoadingSummary] = useState(false);
  const [loadingList, setLoadingList] = useState(false);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  // Modal detail
  const [detailModal, setDetailModal] = useState<DealWinItem | null>(null);
  const [loadingDetail, setLoadingDetail] = useState(false);

  // Load dropdown options once on mount
  useEffect(() => {
    fetchDealWinOptions()
      .then(res => setOptions(res))
      .catch(err => console.error('Error fetching deal options:', err));
  }, []);

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
      setStartDate('2025-01-01');
      setEndDate(format(today, 'yyyy-MM-dd'));
    }
  };

  // Fetch summary & aggregations (called only when date, sale, or course changes)
  const loadSummaryData = async () => {
    setLoadingSummary(true);
    try {
      const res = await fetchDealWinSummary(
        startDate,
        endDate,
        selectedSale || undefined,
        selectedCourse || undefined
      );
      setSummary(res);
      setLastUpdated(new Date());
    } catch (err) {
      console.error('Error fetching deal summary:', err);
    } finally {
      setLoadingSummary(false);
    }
  };

  // Fetch paginated table rows (called on page change or filter/search change)
  const loadListData = async (targetPage: number = 1) => {
    setLoadingList(true);
    try {
      const res = await fetchDealWinList(
        targetPage,
        pageSize,
        startDate,
        endDate,
        selectedSale || undefined,
        selectedCourse || undefined,
        activeSearch || undefined
      );
      setDeals(res.data);
      setTotalDeals(res.total);
      setTotalPages(res.total_pages);
      setPage(res.page);
    } catch (err) {
      console.error('Error fetching deal list:', err);
    } finally {
      setLoadingList(false);
    }
  };

  // Reload when main filters change
  useEffect(() => {
    loadSummaryData();
    loadListData(1);
  }, [startDate, endDate, selectedSale, selectedCourse, activeSearch]);

  const handleSearchSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setActiveSearch(searchQuery.trim());
  };

  const handleOpenDetail = async (deal: DealWinItem) => {
    setDetailModal(deal);
    setLoadingDetail(true);
    try {
      const full = await fetchDealWinDetail(deal.id);
      setDetailModal(full);
    } catch (err) {
      console.error('Error fetching deal detail:', err);
    } finally {
      setLoadingDetail(false);
    }
  };

  const handleRefresh = () => {
    loadSummaryData();
    loadListData(page);
  };

  const total = summary?.total_deals || 0;
  const paid = summary?.paid_deals || 0;
  const paidRate = total > 0 ? ((paid / total) * 100).toFixed(1) : '0';

  // Format Top Sales for Bar Chart
  const topSalesData = Object.entries(summary?.sales_person_stats || {})
    .map(([name, count]) => ({ name, count }))
    .sort((a, b) => b.count - a.count)
    .slice(0, 8);

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

          {/* Sale Filter */}
          <div className="flex flex-col gap-1 min-w-[160px]">
            <label className="text-xs font-medium text-[#4B5563]">Nhân viên Sale</label>
            <select
              value={selectedSale}
              onChange={e => setSelectedSale(e.target.value)}
              className="px-3 py-2 border border-[#E5E7EB] rounded-xl text-sm bg-white focus:outline-none focus:ring-2 focus:ring-[#1E5BD6]/20 focus:border-[#1E5BD6] transition-all text-[#111827] cursor-pointer"
            >
              <option value="">Tất cả Sale ({options.sales_persons.length})</option>
              {options.sales_persons.map(sp => (
                <option key={sp} value={sp}>{sp}</option>
              ))}
            </select>
          </div>

          {/* Course Filter */}
          <div className="flex flex-col gap-1 min-w-[160px]">
            <label className="text-xs font-medium text-[#4B5563]">Khóa học</label>
            <select
              value={selectedCourse}
              onChange={e => setSelectedCourse(e.target.value)}
              className="px-3 py-2 border border-[#E5E7EB] rounded-xl text-sm bg-white focus:outline-none focus:ring-2 focus:ring-[#1E5BD6]/20 focus:border-[#1E5BD6] transition-all text-[#111827] cursor-pointer"
            >
              <option value="">Tất cả khóa ({options.products.length})</option>
              {options.products.map(p => (
                <option key={p} value={p}>{p}</option>
              ))}
            </select>
          </div>

          {/* Search Bar */}
          <form onSubmit={handleSearchSubmit} className="flex flex-col gap-1 flex-1 min-w-[220px]">
            <label className="text-xs font-medium text-[#4B5563]">Tìm kiếm nhanh</label>
            <div className="relative">
              <input
                type="text"
                placeholder="Tên, SĐT, Email, Note..."
                value={searchQuery}
                onChange={e => setSearchQuery(e.target.value)}
                className="w-full pl-9 pr-9 py-2 border border-[#E5E7EB] rounded-xl text-sm bg-white focus:outline-none focus:ring-2 focus:ring-[#1E5BD6]/20 focus:border-[#1E5BD6] transition-all text-[#111827]"
              />
              <Search className="w-4 h-4 text-gray-400 absolute left-3 top-2.5" />
              {searchQuery && (
                <button
                  type="button"
                  onClick={() => {
                    setSearchQuery('');
                    setActiveSearch('');
                  }}
                  className="absolute right-3 top-2.5 text-gray-400 hover:text-gray-600"
                >
                  <X className="w-4 h-4" />
                </button>
              )}
            </div>
          </form>

          {/* Refresh Button & Timestamp */}
          <div className="flex items-center gap-2 shrink-0">
            {lastUpdated && (
              <span className="text-xs text-gray-400 hidden md:inline">
                Cập nhật: {format(lastUpdated, 'HH:mm:ss')}
              </span>
            )}
            <button
              onClick={handleRefresh}
              disabled={loadingSummary || loadingList}
              className="flex items-center gap-1.5 px-3.5 py-2 text-xs font-semibold text-[#1E5BD6] bg-blue-50 hover:bg-blue-100 rounded-xl transition-colors disabled:opacity-50"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${loadingSummary || loadingList ? 'animate-spin' : ''}`} />
              <span>Làm mới</span>
            </button>
          </div>
        </div>
      </div>

      {/* KPI METRICS ROW */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-5">
        {/* Total Deals */}
        <div className="bg-white rounded-2xl border border-[#E5E7EB] p-5 shadow-sm hover:shadow-md transition-all flex flex-col justify-between">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-[#4B5563]">Tổng Học Viên Chốt</span>
            <div className="w-10 h-10 rounded-xl bg-blue-100 text-blue-600 flex items-center justify-center">
              <Award className="w-5 h-5" />
            </div>
          </div>
          <div className="mt-4">
            <div className="text-3xl font-bold text-navy tracking-tight">
              {loadingSummary ? '...' : total.toLocaleString('vi-VN')}
            </div>
            <p className="text-xs font-medium text-blue-600 mt-1">Đã chốt từ Google Form / Sheet</p>
          </div>
        </div>

        {/* Paid Status */}
        <div className="bg-white rounded-2xl border border-[#E5E7EB] p-5 shadow-sm hover:shadow-md transition-all flex flex-col justify-between">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-[#4B5563]">Đã Xác Nhận Đóng Tiền</span>
            <div className="w-10 h-10 rounded-xl bg-emerald-100 text-emerald-600 flex items-center justify-center">
              <CreditCard className="w-5 h-5" />
            </div>
          </div>
          <div className="mt-4">
            <div className="text-3xl font-bold text-navy tracking-tight">
              {loadingSummary ? '...' : paid.toLocaleString('vi-VN')}
            </div>
            <p className="text-xs font-medium text-emerald-600 mt-1">
              Tỷ lệ thanh toán: {paidRate}%
            </p>
          </div>
        </div>

        {/* Top Sales */}
        <div className="bg-white rounded-2xl border border-[#E5E7EB] p-5 shadow-sm hover:shadow-md transition-all flex flex-col justify-between">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-[#4B5563]">Top Sale Xuất Sắc</span>
            <div className="w-10 h-10 rounded-xl bg-amber-100 text-amber-600 flex items-center justify-center">
              <UserCheck className="w-5 h-5" />
            </div>
          </div>
          <div className="mt-4">
            <div className="text-2xl font-bold text-navy tracking-tight truncate">
              {loadingSummary ? '...' : summary?.top_sales_person || 'N/A'}
            </div>
            <p className="text-xs font-medium text-amber-600 mt-1">
              {summary?.top_sales_person && summary.sales_person_stats[summary.top_sales_person]
                ? `${summary.sales_person_stats[summary.top_sales_person]} học viên chốt`
                : 'Chưa có dữ liệu'}
            </p>
          </div>
        </div>

        {/* Top Course */}
        <div className="bg-white rounded-2xl border border-[#E5E7EB] p-5 shadow-sm hover:shadow-md transition-all flex flex-col justify-between">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-[#4B5563]">Khóa Học Đăng Ký Nhiều Nhất</span>
            <div className="w-10 h-10 rounded-xl bg-purple-100 text-purple-600 flex items-center justify-center">
              <BookOpen className="w-5 h-5" />
            </div>
          </div>
          <div className="mt-4">
            <div className="text-2xl font-bold text-navy tracking-tight truncate">
              {loadingSummary ? '...' : summary?.top_product || 'N/A'}
            </div>
            <p className="text-xs font-medium text-purple-600 mt-1">
              {summary?.top_product && summary.product_stats[summary.top_product]
                ? `${summary.product_stats[summary.top_product]} lượt đăng ký`
                : 'Chưa có dữ liệu'}
            </p>
          </div>
        </div>
      </div>

      {/* CHARTS SECTION */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Trend Area Chart (2/3 width) */}
        <div className="lg:col-span-2 bg-white rounded-2xl border border-[#E5E7EB] p-6 shadow-sm">
          <div className="flex items-center justify-between mb-6">
            <div>
              <h3 className="text-base font-semibold text-navy">Xu hướng Deal Win theo ngày</h3>
              <p className="text-xs text-[#4B5563] mt-0.5">Số học viên đăng ký hoàn tất theo thời gian</p>
            </div>
            <span className="text-xs font-medium text-blue-600 bg-blue-50 px-2.5 py-1 rounded-full">
              {summary?.daily_trend?.length || 0} ngày có dữ liệu
            </span>
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
              <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#F3F4F6" />
              <XAxis
                dataKey="date"
                tickFormatter={str => {
                  if (!str) return '';
                  const parts = str.split('-');
                  return parts.length >= 3 ? `${parts[2]}/${parts[1]}` : str;
                }}
                tick={{ fontSize: 11, fill: '#6B7280' }}
                axisLine={false}
                tickLine={false}
              />
              <YAxis
                allowDecimals={false}
                tick={{ fontSize: 11, fill: '#6B7280' }}
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
            <p className="text-xs text-[#4B5563] mt-0.5">Xếp hạng số học viên theo nhân viên chăm sóc</p>
          </div>

          {topSalesData.length > 0 ? (
            <ResponsiveContainer width="100%" height={240}>
              <BarChart
                layout="vertical"
                data={topSalesData}
                margin={{ top: 0, right: 20, left: 20, bottom: 0 }}
              >
                <CartesianGrid strokeDasharray="3 3" horizontal={false} stroke="#F3F4F6" />
                <XAxis type="number" allowDecimals={false} tick={{ fontSize: 10, fill: '#6B7280' }} axisLine={false} tickLine={false} />
                <YAxis
                  dataKey="name"
                  type="category"
                  tick={{ fontSize: 11, fill: '#1E293B', fontWeight: 500 }}
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

      {/* SECOND CHARTS ROW: Khóa Học & Kênh Nguồn */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <StatsPieChart
          title="Phân bổ theo Khóa học"
          subtitle="Tỷ lệ học viên đăng ký theo từng khóa đào tạo"
          stats={summary?.product_stats}
        />
        <StatsPieChart
          title="Phân bổ theo Kênh nguồn"
          subtitle="Nguồn học viên biết đến khóa đào tạo (Tiktok, Facebook, Giới thiệu...)"
          stats={summary?.source_stats}
        />
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
                <th className="px-5 py-3 font-semibold">Khóa Học</th>
                <th className="px-5 py-3 font-semibold">Đóng Tiền</th>
                <th className="px-5 py-3 font-semibold">Sale Chăm Sóc</th>
                <th className="px-5 py-3 font-semibold">Kênh Nguồn</th>
                <th className="px-5 py-3 font-semibold">Ghi Chú</th>
                <th className="px-5 py-3 font-semibold text-right">Chi Tiết</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#E5E7EB]">
              {loadingList ? (
                <tr>
                  <td colSpan={9} className="px-6 py-12 text-center text-xs text-gray-500">
                    <RefreshCw className="w-5 h-5 animate-spin mx-auto mb-2 text-[#1E5BD6]" />
                    Đang tải danh sách học viên...
                  </td>
                </tr>
              ) : deals.length > 0 ? (
                deals.map(deal => {
                  const paymentLower = (deal.payment_status || '').toLowerCase();
                  const isPaid =
                    paymentLower.includes('full') ||
                    paymentLower.includes('đã đóng') ||
                    paymentLower.includes('đã chuyển') ||
                    paymentLower.includes('đã ck');
                  const isPartial =
                    paymentLower.includes('cọc') ||
                    paymentLower.includes('thiếu') ||
                    paymentLower.includes('nộp');

                  return (
                    <tr key={deal.id} className="hover:bg-[#F8FAFC] transition-colors group">
                      {/* Time */}
                      <td className="px-5 py-3.5 whitespace-nowrap text-xs text-gray-500">
                        {deal.timestamp ? (
                          <>
                            <div className="font-medium text-gray-800">
                              {format(new Date(deal.timestamp), 'dd/MM/yyyy')}
                            </div>
                            <div className="text-[11px] text-gray-400">
                              {format(new Date(deal.timestamp), 'HH:mm')}
                            </div>
                          </>
                        ) : (
                          '—'
                        )}
                      </td>

                      {/* Student Name */}
                      <td className="px-5 py-3.5 whitespace-nowrap">
                        <div className="flex items-center gap-2.5">
                          <div className="w-8 h-8 rounded-full bg-blue-100 text-[#1E5BD6] flex items-center justify-center text-xs font-bold shrink-0">
                            {(deal.full_name || 'H').charAt(0).toUpperCase()}
                          </div>
                          <div>
                            <div className="font-semibold text-navy">
                              {deal.full_name || 'Học viên'}
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

                      {/* Course */}
                      <td className="px-5 py-3.5 whitespace-nowrap">
                        {deal.course_name ? (
                          <span className="inline-flex items-center px-2 py-0.5 rounded-md text-xs font-semibold bg-blue-50 text-blue-700 border border-blue-200">
                            {deal.course_name}
                          </span>
                        ) : (
                          <span className="text-xs text-gray-400">Chưa xác định</span>
                        )}
                      </td>

                      {/* Payment Status */}
                      <td className="px-5 py-3.5 whitespace-nowrap">
                        {deal.payment_status ? (
                          <span
                            className={`inline-flex items-center px-2 py-0.5 rounded-md text-xs font-semibold ${
                              isPaid
                                ? 'bg-emerald-50 text-emerald-700 border border-emerald-200'
                                : isPartial
                                ? 'bg-amber-50 text-amber-700 border border-amber-200'
                                : 'bg-gray-100 text-gray-700 border border-gray-200'
                            }`}
                          >
                            {deal.payment_status}
                          </span>
                        ) : (
                          <span className="text-xs text-gray-400">Chưa có</span>
                        )}
                      </td>

                      {/* Care by Sale */}
                      <td className="px-5 py-3.5 whitespace-nowrap text-xs">
                        <span className="font-medium text-gray-800">
                          {deal.care_by || 'Chưa phân công'}
                        </span>
                      </td>

                      {/* Source Channel */}
                      <td className="px-5 py-3.5 whitespace-nowrap text-xs text-gray-600">
                        {deal.source_channel || '—'}
                      </td>

                      {/* Note */}
                      <td className="px-5 py-3.5 text-xs text-gray-500 max-w-[200px] truncate" title={deal.note || ''}>
                        {deal.note || '—'}
                      </td>

                      {/* Action */}
                      <td className="px-5 py-3.5 whitespace-nowrap text-right">
                        <button
                          onClick={() => handleOpenDetail(deal)}
                          className="inline-flex items-center gap-1 text-xs font-semibold text-[#1E5BD6] hover:text-navy bg-blue-50 hover:bg-blue-100 px-2.5 py-1 rounded-lg transition-colors"
                        >
                          <Eye className="w-3.5 h-3.5" />
                          <span>Xem</span>
                        </button>
                      </td>
                    </tr>
                  );
                })
              ) : (
                <tr>
                  <td colSpan={9} className="px-6 py-12 text-center text-xs text-gray-500">
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
              onClick={() => loadListData(page - 1)}
              disabled={page <= 1 || loadingList}
              className="px-3 py-1.5 rounded-lg border border-[#E5E7EB] hover:bg-gray-50 disabled:opacity-40 transition-colors font-medium"
            >
              Trang trước
            </button>
            <span className="px-2 font-semibold text-navy">
              {page} / {totalPages || 1}
            </span>
            <button
              onClick={() => loadListData(page + 1)}
              disabled={page >= totalPages || loadingList}
              className="px-3 py-1.5 rounded-lg border border-[#E5E7EB] hover:bg-gray-50 disabled:opacity-40 transition-colors font-medium"
            >
              Trang sau
            </button>
          </div>
        </div>
      </div>

      {/* DETAIL MODAL */}
      {detailModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40 backdrop-blur-xs">
          <div className="bg-white rounded-2xl max-w-2xl w-full max-h-[90vh] overflow-y-auto shadow-2xl border border-gray-100 flex flex-col">
            {/* Modal Header */}
            <div className="px-6 py-4 border-b border-gray-100 flex items-center justify-between sticky top-0 bg-white z-10">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-full bg-blue-100 text-[#1E5BD6] flex items-center justify-center text-sm font-bold">
                  {(detailModal.full_name || 'H').charAt(0).toUpperCase()}
                </div>
                <div>
                  <h3 className="text-base font-bold text-navy">{detailModal.full_name || 'Học viên'}</h3>
                  <p className="text-xs text-gray-500">Mã dòng: {detailModal.sheet_row_id || 'N/A'}</p>
                </div>
              </div>
              <button
                onClick={() => setDetailModal(null)}
                className="p-1.5 rounded-lg text-gray-400 hover:text-gray-600 hover:bg-gray-100 transition-colors"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            {/* Modal Content */}
            <div className="p-6 space-y-5 text-sm">
              {loadingDetail && (
                <div className="text-center py-2 text-xs text-blue-600 flex items-center justify-center gap-2">
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

              {/* Thông tin khóa học */}
              <div>
                <h4 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2.5">
                  Khóa học & Thanh toán
                </h4>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 bg-gray-50 p-4 rounded-xl">
                  <div>
                    <span className="text-xs text-gray-500 block">Khóa học đăng ký:</span>
                    <span className="font-semibold text-blue-700">{detailModal.course_name || 'Chưa xác định'}</span>
                  </div>
                  <div>
                    <span className="text-xs text-gray-500 block">Tình trạng đóng tiền:</span>
                    <span className="font-semibold text-emerald-700">{detailModal.payment_status || 'Chưa ghi nhận'}</span>
                  </div>
                  <div>
                    <span className="text-xs text-gray-500 block">Sale phụ trách (Care by):</span>
                    <span className="font-semibold text-navy">{detailModal.care_by || 'Chưa phân công'}</span>
                  </div>
                  <div>
                    <span className="text-xs text-gray-500 block">Kênh biết đến:</span>
                    <span className="font-semibold text-gray-800">{detailModal.source_channel || 'Không rõ'}</span>
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

                  {detailModal.note && (
                    <div>
                      <div className="flex items-center gap-1.5 text-xs text-gray-500 mb-1">
                        <Share2 className="w-3.5 h-3.5" />
                        <span>Ghi chú bổ sung (Note):</span>
                      </div>
                      <p className="text-gray-800 bg-white p-3 rounded-lg border border-gray-200">
                        {detailModal.note}
                      </p>
                    </div>
                  )}
                </div>
              </div>
            </div>

            {/* Modal Footer */}
            <div className="px-6 py-3 border-t border-gray-100 flex justify-end bg-gray-50 rounded-b-2xl">
              <button
                onClick={() => setDetailModal(null)}
                className="px-4 py-2 text-xs font-semibold text-gray-700 bg-white border border-gray-200 rounded-xl hover:bg-gray-100 transition-colors"
              >
                Đóng
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
