import { useState, useEffect, useMemo } from 'react';
import { format, subDays, startOfMonth } from 'date-fns';
import {
  MessageSquare,
  ThumbsUp,
  Users,
  PhoneCall,
  Award,
  ExternalLink,
  Calendar,
  RefreshCw,
  Search,
  Video,
  Radio,
  Inbox,
  TrendingUp,
} from 'lucide-react';
import {
  ResponsiveContainer,
  AreaChart,
  Area,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  PieChart,
  Pie,
  Cell,
} from 'recharts';
import {
  fetchTikTokMetrics,
  clearClientApiCache,
  fetchTikTokPages,
  type FacebookMetricsResponse,
  type TikTokPageItem,
} from '../services/api';

const CHANNEL_COLORS: Record<string, string> = {
  'Anh Kế toán làm Data (TikTok)': '#1E5BD6',
  'Hành trang cho kế toán': '#00B4D8',
  'Chị Kế Toán GenZ': '#F5B400',
  'Anh kế toán Daily': '#10B981',
};

// SVG Icon TikTok chuẩn
export function TikTokIcon({ className = 'w-5 h-5' }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="currentColor">
      <path d="M19.59 6.69a4.83 4.83 0 0 1-3.77-4.25V2h-3.45v13.67a2.89 2.89 0 0 1-5.2 1.74 2.89 2.89 0 0 1 2.31-4.64c.298-.002.595.042.88.13V9.4a6.33 6.33 0 0 0-1-.08A6.34 6.34 0 0 0 3 15.66a6.34 6.34 0 0 0 10.82 4.46 6.3 6.3 0 0 0 1.86-4.46V8.7a8.18 8.18 0 0 0 4.91 1.63V6.88a4.85 4.85 0 0 1-1-.19z" />
    </svg>
  );
}

export function TikTokDashboard() {
  // Bộ lọc thời gian mặc định 30 ngày gần nhất
  const [startDate, setStartDate] = useState(() => format(subDays(new Date(), 30), 'yyyy-MM-dd'));
  const [endDate, setEndDate] = useState(() => format(new Date(), 'yyyy-MM-dd'));
  const [activePreset, setActivePreset] = useState<number | 'month' | 'custom'>(30);
  const [pageId, setPageId] = useState('');
  const [pagesList, setPagesList] = useState<TikTokPageItem[]>([]);

  // Dữ liệu chỉ số
  const [data, setData] = useState<FacebookMetricsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastRefreshed, setLastRefreshed] = useState<Date | null>(null);

  // Bộ lọc bảng video
  const [searchPost, setSearchPost] = useState('');
  const [sortBy, setSortBy] = useState<'leads' | 'phones' | 'deals' | 'comments' | 'reactions' | 'date'>('leads');
  const [postLimit, setPostLimit] = useState(15);

  // Load danh sách Kênh TikTok
  useEffect(() => {
    fetchTikTokPages()
      .then(pages => setPagesList(pages))
      .catch(err => console.error('Error fetching TikTok pages:', err));
  }, []);

  // Load dữ liệu metrics
  const loadMetrics = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetchTikTokMetrics(startDate, endDate, pageId || undefined);
      setData(res);
      setLastRefreshed(new Date());
    } catch (err: any) {
      console.error('Lỗi khi tải dữ liệu TikTok metrics:', err);
      setError(err?.response?.data?.detail || err?.message || 'Có lỗi xảy ra khi tải dữ liệu TikTok');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadMetrics();
  }, [startDate, endDate, pageId]);

  // Bộ chọn ngày nhanh
  const handlePreset = (preset: 7 | 14 | 30 | 'month') => {
    setActivePreset(preset);
    const end = new Date();
    setEndDate(format(end, 'yyyy-MM-dd'));
    if (preset === 'month') {
      setStartDate(format(startOfMonth(end), 'yyyy-MM-dd'));
    } else {
      setStartDate(format(subDays(end, preset), 'yyyy-MM-dd'));
    }
  };

  // Chuẩn bị dữ liệu phân bổ theo Kênh TikTok
  const channelPieData = useMemo(() => {
    if (!data?.top_posts) return [];
    const countByChannel: Record<string, number> = {};
    for (const p of data.top_posts) {
      const cName = p.page_name || 'Khác';
      countByChannel[cName] = (countByChannel[cName] || 0) + 1;
    }
    return Object.entries(countByChannel).map(([name, count]) => ({
      name,
      value: count,
      color: CHANNEL_COLORS[name] || '#1E5BD6',
    }));
  }, [data?.top_posts]);

  // Chuẩn bị dữ liệu cơ cấu nguồn Lead (Video vs Organic)
  const channelLeadData = useMemo(() => {
    const postLeads = data?.summary.post_leads || 0;
    const organicLeads = data?.summary.organic_leads || 0;
    if (postLeads + organicLeads === 0) return [];
    return [
      { name: 'Từ Video (TikTok)', value: postLeads, color: '#1E5BD6' },   // EzTech Blue
      { name: 'Tự nhiên (Organic)', value: organicLeads, color: '#F5B400' }, // EzTech Gold
    ];
  }, [data?.summary.post_leads, data?.summary.organic_leads]);

  // Lọc và sắp xếp bảng Top video
  const filteredPosts = useMemo(() => {
    if (!data?.top_posts) return [];
    let list = [...data.top_posts];

    if (searchPost.trim()) {
      const q = searchPost.toLowerCase().trim();
      list = list.filter(p =>
        (p.message && p.message.toLowerCase().includes(q)) ||
        p.post_id.includes(q)
      );
    }

    list.sort((a, b) => {
      if (sortBy === 'leads') {
        return (b.lead_count || 0) - (a.lead_count || 0);
      }
      if (sortBy === 'phones') {
        return (b.phone_count || 0) - (a.phone_count || 0);
      }
      if (sortBy === 'deals') {
        return (b.deal_count || 0) - (a.deal_count || 0);
      }
      if (sortBy === 'comments') {
        return (b.comment_count || 0) - (a.comment_count || 0);
      }
      if (sortBy === 'reactions') {
        return (b.reactions_total || 0) - (a.reactions_total || 0);
      }
      // date
      return new Date(b.inserted_at || 0).getTime() - new Date(a.inserted_at || 0).getTime();
    });

    return list;
  }, [data?.top_posts, searchPost, sortBy]);

  const summary = data?.summary;

  // Tính toán tỷ trọng phần trăm nguồn
  const totalChannelLeads = (summary?.post_leads || 0) + (summary?.organic_leads || 0);
  const postLeadPct = totalChannelLeads > 0 ? Math.round(((summary?.post_leads || 0) / totalChannelLeads) * 100) : 0;
  const organicLeadPct = totalChannelLeads > 0 ? 100 - postLeadPct : 0;

  const totalChannelPhones = (summary?.post_phones || 0) + (summary?.organic_phones || 0);
  const postPhonePct = totalChannelPhones > 0 ? Math.round(((summary?.post_phones || 0) / totalChannelPhones) * 100) : 0;
  const organicPhonePct = totalChannelPhones > 0 ? 100 - postPhonePct : 0;

  return (
    <div className="space-y-5 animate-in fade-in duration-300">
      {/* 1. Header & Bộ lọc thiết kế chuẩn mực */}
      <div className="bg-white rounded-2xl border border-slate-200/90 shadow-xs overflow-hidden">
        {/* Top Header: Tiêu đề & Thời gian cập nhật */}
        <div className="px-5 py-4 flex flex-col md:flex-row md:items-center md:justify-between gap-3 border-b border-slate-100 bg-linear-to-r from-slate-900/5 via-white to-blue-50/20">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-slate-900 text-white flex items-center justify-center shadow-md shadow-slate-900/20 shrink-0">
              <TikTokIcon className="w-5 h-5" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h2 className="text-lg font-bold text-navy tracking-tight">TikTok Analytics</h2>
                <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-slate-100 text-slate-800 border border-slate-300 uppercase">
                  Video Performance
                </span>
              </div>
              <p className="text-xs text-slate-500 mt-0.5">
                Hiệu quả Video, tương tác, Lead Organic & Video, SĐT thu được và Deal chốt từ TikTok
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2.5 self-start md:self-auto">
            {lastRefreshed && (
              <span className="text-[11px] font-mono text-slate-400 tabular-nums">
                Cập nhật: {format(lastRefreshed, 'HH:mm:ss')}
              </span>
            )}
            <button
              onClick={() => { clearClientApiCache(); loadMetrics(); }}
              disabled={loading}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-slate-200 bg-white hover:bg-slate-50 text-navy text-xs font-semibold shadow-2xs hover:border-slate-300 disabled:opacity-50 transition-all cursor-pointer"
              title="Làm mới dữ liệu"
            >
              <RefreshCw className={`w-3.5 h-3.5 text-eztech ${loading ? 'animate-spin' : ''}`} />
              <span>Làm mới</span>
            </button>
          </div>
        </div>

        {/* Filter Toolbar: Phân bổ hợp lý, rõ ràng */}
        <div className="px-5 py-3.5 bg-slate-50/50 flex flex-wrap items-center justify-between gap-3">
          {/* Nhóm bộ lọc thời gian */}
          <div className="flex flex-wrap items-center gap-2.5">
            {/* Segmented Preset Buttons */}
            <div className="inline-flex rounded-lg border border-slate-200/90 bg-white p-0.5 text-xs shadow-2xs">
              <button
                onClick={() => handlePreset(7)}
                className={`px-3 py-1.5 rounded-md font-medium transition-all cursor-pointer ${
                  activePreset === 7
                    ? 'bg-navy text-white shadow-xs font-semibold'
                    : 'text-slate-600 hover:text-navy hover:bg-slate-100/70'
                }`}
              >
                7 ngày
              </button>
              <button
                onClick={() => handlePreset(14)}
                className={`px-3 py-1.5 rounded-md font-medium transition-all cursor-pointer ${
                  activePreset === 14
                    ? 'bg-navy text-white shadow-xs font-semibold'
                    : 'text-slate-600 hover:text-navy hover:bg-slate-100/70'
                }`}
              >
                14 ngày
              </button>
              <button
                onClick={() => handlePreset(30)}
                className={`px-3 py-1.5 rounded-md font-medium transition-all cursor-pointer ${
                  activePreset === 30
                    ? 'bg-navy text-white shadow-xs font-semibold'
                    : 'text-slate-600 hover:text-navy hover:bg-slate-100/70'
                }`}
              >
                30 ngày
              </button>
              <button
                onClick={() => handlePreset('month')}
                className={`px-3 py-1.5 rounded-md font-medium transition-all cursor-pointer ${
                  activePreset === 'month'
                    ? 'bg-navy text-white shadow-xs font-semibold'
                    : 'text-slate-600 hover:text-navy hover:bg-slate-100/70'
                }`}
              >
                Tháng này
              </button>
            </div>

            {/* Custom Date Inputs */}
            <div className="inline-flex items-center gap-1.5 bg-white border border-slate-200/90 px-3 py-1.5 rounded-lg text-xs shadow-2xs">
              <Calendar className="w-3.5 h-3.5 text-slate-400 shrink-0" />
              <input
                type="date"
                value={startDate}
                onChange={e => {
                  setStartDate(e.target.value);
                  setActivePreset('custom');
                }}
                className="border-none bg-transparent text-navy text-xs focus:outline-hidden font-medium cursor-pointer"
              />
              <span className="text-slate-400 font-medium">→</span>
              <input
                type="date"
                value={endDate}
                onChange={e => {
                  setEndDate(e.target.value);
                  setActivePreset('custom');
                }}
                className="border-none bg-transparent text-navy text-xs focus:outline-hidden font-medium cursor-pointer"
              />
            </div>
          </div>

          {/* Chọn Kênh TikTok với độ rộng thoải mái */}
          <div className="flex items-center gap-2">
            <span className="text-xs font-medium text-slate-500 whitespace-nowrap hidden sm:inline">Kênh:</span>
            <select
              value={pageId}
              onChange={e => setPageId(e.target.value)}
              className="bg-white border border-slate-200/90 text-xs rounded-lg px-3 py-1.5 text-navy font-semibold focus:ring-1 focus:ring-eztech focus:outline-hidden shadow-2xs min-w-[220px] max-w-[320px] cursor-pointer"
            >
              <option value="">Tất cả Kênh TikTok</option>
              {pagesList.map(p => (
                <option key={p.id} value={p.name}>
                  {p.name}
                </option>
              ))}
            </select>
          </div>
        </div>
      </div>

      {/* Thông báo lỗi nếu API gặp sự cố */}
      {error && (
        <div className="bg-rose-50 border border-rose-200 text-rose-700 px-4 py-3 rounded-xl text-xs flex items-center justify-between shadow-2xs">
          <div className="flex items-center gap-2">
            <span className="font-bold">Lỗi tải dữ liệu:</span>
            <span>{error}</span>
          </div>
          <button
            onClick={loadMetrics}
            className="px-3 py-1 bg-white hover:bg-rose-100 text-rose-700 font-semibold rounded-md border border-rose-300 transition-colors cursor-pointer"
          >
            Thử lại
          </button>
        </div>
      )}

      {/* 2. Hàng 5 Thẻ KPI Tóm tắt Toàn kênh */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-3.5">
        {/* Card 1: Video xuất bản */}
        <div className="bg-white rounded-xl border border-slate-200/80 p-4 shadow-card hover:shadow-card-hover transition-all">
          <div className="flex items-center justify-between text-slate-500 mb-2">
            <span className="text-xs font-medium">Video xuất bản</span>
            <div className="w-7 h-7 rounded-lg bg-slate-100 text-slate-800 flex items-center justify-center">
              <Video className="w-4 h-4" />
            </div>
          </div>
          <div className="text-2xl font-bold font-mono text-navy">
            {loading ? '...' : (summary?.total_posts || 0).toLocaleString()}
          </div>
          <div className="mt-2 pt-2 border-t border-slate-100 flex items-center justify-between text-[11px] text-slate-500">
            <span>TB/Video:</span>
            <span className="font-mono font-semibold text-navy">
              {summary?.avg_comments_per_post || 0} bình luận
            </span>
          </div>
        </div>

        {/* Card 2: Lượt Thích / Tim */}
        <div className="bg-white rounded-xl border border-slate-200/80 p-4 shadow-card hover:shadow-card-hover transition-all">
          <div className="flex items-center justify-between text-slate-500 mb-2">
            <span className="text-xs font-medium">Tổng Lượt Thích</span>
            <div className="w-7 h-7 rounded-lg bg-rose-50 text-rose-500 flex items-center justify-center">
              <ThumbsUp className="w-4 h-4" />
            </div>
          </div>
          <div className="text-2xl font-bold font-mono text-navy">
            {loading ? '...' : (summary?.total_reactions || 0).toLocaleString()}
          </div>
          <div className="mt-2 pt-2 border-t border-slate-100 flex items-center justify-between text-[11px] text-slate-500">
            <span>Chia sẻ:</span>
            <span className="font-mono font-semibold text-navy">
              {summary?.total_shares || 0} lượt
            </span>
          </div>
        </div>

        {/* Card 3: Bình luận */}
        <div className="bg-white rounded-xl border border-slate-200/80 p-4 shadow-card hover:shadow-card-hover transition-all">
          <div className="flex items-center justify-between text-slate-500 mb-2">
            <span className="text-xs font-medium">Bình luận thu về</span>
            <div className="w-7 h-7 rounded-lg bg-eztech-light text-eztech flex items-center justify-center">
              <MessageSquare className="w-4 h-4" />
            </div>
          </div>
          <div className="text-2xl font-bold font-mono text-navy">
            {loading ? '...' : (summary?.total_comments || 0).toLocaleString()}
          </div>
          <div className="mt-2 pt-2 border-t border-slate-100 flex items-center justify-between text-[11px] text-slate-500">
            <span>SĐT từ bình luận:</span>
            <span className="font-mono font-semibold text-emerald-600">
              {summary?.comment_phones || 0} SĐT
            </span>
          </div>
        </div>

        {/* Card 4: SĐT thu được / Lead */}
        <div className="bg-white rounded-xl border border-slate-200/80 p-4 shadow-card hover:shadow-card-hover transition-all">
          <div className="flex items-center justify-between text-slate-500 mb-2">
            <span className="text-xs font-medium">SĐT thu được / Lead</span>
            <div className="w-7 h-7 rounded-lg bg-emerald-50 text-emerald-600 flex items-center justify-center">
              <PhoneCall className="w-4 h-4" />
            </div>
          </div>
          <div className="text-2xl font-bold font-mono text-navy flex items-baseline gap-1.5">
            <span>{loading ? '...' : (summary?.phone_leads || 0).toLocaleString()}</span>
            <span className="text-xs font-normal text-slate-400">/ {summary?.total_leads || 0} leads</span>
          </div>
          <div className="mt-2 pt-2 border-t border-slate-100 flex items-center justify-between text-[11px] text-slate-500">
            <span>Tỷ lệ có số:</span>
            <span className="font-mono font-bold text-emerald-600">
              {summary?.phone_conversion_rate || 0}%
            </span>
          </div>
        </div>

        {/* Card 5: Học viên chốt (Deal Win) */}
        <div className="bg-white rounded-xl border border-slate-200/80 p-4 shadow-card hover:shadow-card-hover transition-all col-span-2 sm:col-span-1">
          <div className="flex items-center justify-between text-slate-500 mb-2">
            <span className="text-xs font-medium">Học viên chốt (Deal Win)</span>
            <div className="w-7 h-7 rounded-lg bg-gold-light text-gold-dark flex items-center justify-center">
              <Award className="w-4 h-4" />
            </div>
          </div>
          <div className="text-2xl font-bold font-mono text-navy">
            {loading ? '...' : (summary?.deal_wins || 0).toLocaleString()}
          </div>
          <div className="mt-2 pt-2 border-t border-slate-100 flex items-center justify-between text-[11px] text-slate-500">
            <span>Tỷ lệ chốt/SĐT:</span>
            <span className="font-mono font-bold text-gold-dark">
              {summary?.deal_conversion_rate || 0}%
            </span>
          </div>
        </div>
      </div>

      {/* 3. Hàng Biểu đồ: Xu hướng (AreaChart) + Phân bổ Kênh TikTok */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Cột trái: Xu hướng Hoạt động TikTok theo ngày */}
        <div className="lg:col-span-2 bg-white rounded-xl border border-slate-200/80 p-5 shadow-card">
          <div className="flex flex-wrap items-center justify-between gap-2 mb-4">
            <div>
              <h3 className="text-[15px] font-semibold text-navy tracking-tight">Xu hướng hoạt động TikTok</h3>
              <p className="text-xs text-slate-500 mt-0.5">Biến động Bình luận, Lead và SĐT thu được theo ngày</p>
            </div>
            <div className="flex items-center gap-3 text-[11px] font-medium text-slate-500">
              <span className="flex items-center gap-1.5">
                <span className="w-2.5 h-2.5 rounded-full bg-navy" />
                Bình luận
              </span>
              <span className="flex items-center gap-1.5">
                <span className="w-2.5 h-2.5 rounded-full bg-eztech" />
                Lead TikTok
              </span>
              <span className="flex items-center gap-1.5">
                <span className="w-2.5 h-2.5 rounded-full bg-emerald-500" />
                SĐT thu được
              </span>
            </div>
          </div>

          <div className="h-[280px] w-full">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={data?.trend || []} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                <defs>
                  <linearGradient id="ttCommentGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#0A1F44" stopOpacity={0.25} />
                    <stop offset="95%" stopColor="#0A1F44" stopOpacity={0.0} />
                  </linearGradient>
                  <linearGradient id="ttLeadGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#1E5BD6" stopOpacity={0.25} />
                    <stop offset="95%" stopColor="#1E5BD6" stopOpacity={0.0} />
                  </linearGradient>
                  <linearGradient id="ttPhoneGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#10B981" stopOpacity={0.3} />
                    <stop offset="95%" stopColor="#10B981" stopOpacity={0.0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" vertical={false} />
                <XAxis
                  dataKey="date"
                  tick={{ fontSize: 11, fill: '#94a3b8' }}
                  tickFormatter={d => {
                    const parts = d.split('-');
                    return parts.length === 3 ? `${parts[2]}/${parts[1]}` : d;
                  }}
                  axisLine={{ stroke: '#e2e8f0' }}
                  tickLine={false}
                />
                <YAxis
                  tick={{ fontSize: 11, fill: '#94a3b8' }}
                  axisLine={false}
                  tickLine={false}
                  allowDecimals={false}
                />
                <Tooltip
                  content={({ active, payload, label }) => {
                    if (active && payload && payload.length) {
                      return (
                        <div className="bg-white/95 backdrop-blur-md border border-slate-200/90 rounded-xl shadow-lg p-3 text-xs">
                          <p className="font-mono font-semibold text-navy mb-2 pb-1.5 border-b border-slate-100">
                            Ngày {label}
                          </p>
                          <div className="space-y-1.5">
                            {payload.map((p: any) => (
                              <div key={p.name} className="flex items-center justify-between gap-4">
                                <span className="flex items-center gap-1.5 text-slate-500">
                                  <span className="w-2 h-2 rounded-full" style={{ backgroundColor: p.color }} />
                                  {p.name}:
                                </span>
                                <span className="font-mono font-bold text-navy tabular-nums">{p.value}</span>
                              </div>
                            ))}
                          </div>
                        </div>
                      );
                    }
                    return null;
                  }}
                />
                <Area
                  type="monotone"
                  dataKey="comments"
                  name="Bình luận"
                  stroke="#0A1F44"
                  strokeWidth={2}
                  fill="url(#ttCommentGrad)"
                />
                <Area
                  type="monotone"
                  dataKey="leads"
                  name="Lead TikTok"
                  stroke="#1E5BD6"
                  strokeWidth={2}
                  fill="url(#ttLeadGrad)"
                />
                <Area
                  type="monotone"
                  dataKey="phones"
                  name="SĐT thu được"
                  stroke="#10B981"
                  strokeWidth={2}
                  fill="url(#ttPhoneGrad)"
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Cột phải: Phân bổ Video theo Kênh */}
        <div className="bg-white rounded-xl border border-slate-200/80 p-5 shadow-card flex flex-col justify-between">
          <div>
            <h3 className="text-[15px] font-semibold text-navy tracking-tight">Phân bổ Kênh TikTok</h3>
            <p className="text-xs text-slate-500 mt-0.5">Số lượng video đã đăng tải theo từng kênh</p>
          </div>

          <div className="my-4 flex flex-col items-center">
            <div className="h-40 w-full">
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie
                    data={channelPieData}
                    dataKey="value"
                    nameKey="name"
                    innerRadius={36}
                    outerRadius={60}
                    paddingAngle={3}
                  >
                    {channelPieData.map(entry => (
                      <Cell key={entry.name} fill={entry.color} />
                    ))}
                  </Pie>
                  <Tooltip />
                </PieChart>
              </ResponsiveContainer>
            </div>
            <div className="flex flex-wrap justify-center gap-2 mt-2 text-[10px] text-slate-500">
              {channelPieData.map(c => (
                <span key={c.name} className="flex items-center gap-1 font-medium">
                  <span className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: c.color }} />
                  {c.name}: {c.value}
                </span>
              ))}
            </div>
          </div>

          <div className="pt-3 border-t border-slate-100 flex items-center justify-between text-xs text-slate-500">
            <span>Video nhiều bình luận nhất:</span>
            <span className="font-semibold text-navy font-mono">
              {data?.top_posts?.[0]?.comment_count || 0} bình luận
            </span>
          </div>
        </div>
      </div>

      {/* 4. PHÂN TÍCH NGUỒN LEAD: VIDEO VS ORGANIC */}
      <div className="space-y-3.5">
        <div className="flex items-center justify-between">
          <h3 className="text-[15px] font-bold text-navy tracking-tight">Nguồn Lead: Video vs Organic</h3>
          <span className="text-xs text-slate-400">So sánh hiệu quả thu hút & chuyển đổi SĐT</span>
        </div>

        {/* 3 Thẻ KPI Tóm tắt Nguồn Lead */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3.5">
          {/* KPI 1: Lead từ Video - EzTech Blue */}
          <div className="bg-white rounded-xl border border-slate-200/80 p-4 shadow-card hover:shadow-card-hover transition-all">
            <div className="flex items-center justify-between text-slate-500 mb-1.5">
              <span className="text-xs font-semibold text-navy flex items-center gap-1.5">
                <span className="w-2 h-2 rounded-full bg-eztech" />
                Từ Video (TikTok)
              </span>
              <div className="w-6 h-6 rounded-md bg-blue-50 text-eztech flex items-center justify-center">
                <Video className="w-3.5 h-3.5" />
              </div>
            </div>
            <div className="text-2xl font-bold font-mono text-navy">
              {loading ? '...' : (summary?.post_leads || 0).toLocaleString()} <span className="text-xs font-normal text-slate-400">khách</span>
            </div>
            <div className="mt-2.5 pt-2 border-t border-slate-100 flex items-center justify-between text-xs text-slate-500 font-mono">
              <span className="text-emerald-600 font-semibold flex items-center gap-1">
                <PhoneCall className="w-3 h-3" /> {summary?.post_phones || 0} SĐT
              </span>
              <span className="text-eztech font-bold bg-blue-50 px-1.5 py-0.5 rounded text-[11px]">
                {summary?.post_phone_rate || 0}% có số
              </span>
            </div>
          </div>

          {/* KPI 2: Lead Tự nhiên (Organic) - EzTech Gold */}
          <div className="bg-white rounded-xl border border-slate-200/80 p-4 shadow-card hover:shadow-card-hover transition-all">
            <div className="flex items-center justify-between text-slate-500 mb-1.5">
              <span className="text-xs font-semibold text-navy flex items-center gap-1.5">
                <span className="w-2 h-2 rounded-full bg-gold" />
                Tự nhiên (Organic Inbox)
              </span>
              <div className="w-6 h-6 rounded-md bg-gold-light text-gold-dark flex items-center justify-center">
                <Inbox className="w-3.5 h-3.5" />
              </div>
            </div>
            <div className="text-2xl font-bold font-mono text-navy">
              {loading ? '...' : (summary?.organic_leads || 0).toLocaleString()} <span className="text-xs font-normal text-slate-400">leads</span>
            </div>
            <div className="mt-2.5 pt-2 border-t border-slate-100 flex items-center justify-between text-xs text-slate-500 font-mono">
              <span className="text-emerald-600 font-semibold flex items-center gap-1">
                <PhoneCall className="w-3 h-3" /> {summary?.organic_phones || 0} SĐT
              </span>
              <span className="text-gold-dark font-bold bg-gold-light px-1.5 py-0.5 rounded text-[11px]">
                {summary?.organic_phone_rate || 0}% có số
              </span>
            </div>
          </div>

          {/* KPI 3: Cơ cấu đóng góp Kênh */}
          <div className="bg-white rounded-xl border border-slate-200/80 p-4 shadow-card hover:shadow-card-hover transition-all">
            <div className="flex items-center justify-between text-slate-500 mb-1.5">
              <span className="text-xs font-semibold text-navy">Tỷ trọng nguồn</span>
              <div className="w-6 h-6 rounded-md bg-slate-100 text-slate-600 flex items-center justify-center">
                <TrendingUp className="w-3.5 h-3.5" />
              </div>
            </div>
            <div className="text-xl font-bold font-mono text-navy flex items-baseline gap-1.5">
              <span className="text-gold-dark">{organicLeadPct}% Organic</span>
              <span className="text-slate-300">•</span>
              <span className="text-eztech">{postLeadPct}% Video</span>
            </div>
            <div className="mt-2.5 pt-2 border-t border-slate-100 flex items-center justify-between text-xs text-slate-500 font-mono">
              <span>Đóng góp SĐT:</span>
              <span className="font-semibold text-navy">
                {organicPhonePct}% Inbox • {postPhonePct}% Video
              </span>
            </div>
          </div>
        </div>

        {/* 2 Biểu đồ chuyên sâu Phân tích Video vs Organic */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {/* Chart 1: Cơ cấu Nguồn Lead & Bảng đối soát gọn */}
          <div className="bg-white rounded-xl border border-slate-200/80 p-5 shadow-card flex flex-col justify-between">
            <div>
              <div className="flex items-center justify-between mb-3">
                <h4 className="text-sm font-bold text-navy">Cơ cấu Nguồn & Chuyển đổi</h4>
                <div className="flex items-center gap-2 text-[11px] font-medium text-slate-500">
                  <span className="flex items-center gap-1">
                    <span className="w-2 h-2 rounded-full bg-eztech" />
                    Video
                  </span>
                  <span className="flex items-center gap-1">
                    <span className="w-2 h-2 rounded-full bg-gold" />
                    Organic
                  </span>
                </div>
              </div>

              {/* Donut Chart tinh gọn */}
              <div className="h-36 w-full my-2">
                <ResponsiveContainer width="100%" height="100%">
                  <PieChart>
                    <Pie
                      data={channelLeadData}
                      dataKey="value"
                      nameKey="name"
                      innerRadius={36}
                      outerRadius={56}
                      paddingAngle={3}
                    >
                      {channelLeadData.map(entry => (
                        <Cell key={entry.name} fill={entry.color} />
                      ))}
                    </Pie>
                    <Tooltip />
                  </PieChart>
                </ResponsiveContainer>
              </div>
            </div>

            {/* Bảng so sánh chỉ số trực tiếp gọn gàng */}
            <div className="pt-3 border-t border-slate-100">
              <table className="w-full text-xs text-left">
                <thead>
                  <tr className="text-slate-400 text-[10px] uppercase font-semibold border-b border-slate-100">
                    <th className="pb-1.5">Nguồn</th>
                    <th className="pb-1.5 text-right">Khách</th>
                    <th className="pb-1.5 text-right">SĐT</th>
                    <th className="pb-1.5 text-right">Tỷ lệ số</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-50 font-mono text-[11px]">
                  <tr>
                    <td className="py-2 font-sans font-medium text-navy flex items-center gap-1.5">
                      <span className="w-2 h-2 rounded-full bg-eztech" />
                      Từ Video
                    </td>
                    <td className="py-2 text-right text-slate-700">{(summary?.post_leads || 0).toLocaleString()}</td>
                    <td className="py-2 text-right text-emerald-600 font-bold">{summary?.post_phones || 0}</td>
                    <td className="py-2 text-right text-eztech font-bold">{summary?.post_phone_rate || 0}%</td>
                  </tr>
                  <tr>
                    <td className="py-2 font-sans font-medium text-navy flex items-center gap-1.5">
                      <span className="w-2 h-2 rounded-full bg-gold" />
                      Tự nhiên (Organic)
                    </td>
                    <td className="py-2 text-right text-slate-700">{(summary?.organic_leads || 0).toLocaleString()}</td>
                    <td className="py-2 text-right text-emerald-600 font-bold">{summary?.organic_phones || 0}</td>
                    <td className="py-2 text-right text-gold-dark font-bold">{summary?.organic_phone_rate || 0}%</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>

          {/* Chart 2: Biểu đồ cột Xu hướng Lead theo ngày (Video vs Organic) */}
          <div className="bg-white rounded-xl border border-slate-200/80 p-5 shadow-card flex flex-col justify-between">
            <div>
              <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
                <h4 className="text-sm font-bold text-navy">Xu hướng Lead theo ngày</h4>
                <div className="flex items-center gap-3 text-[11px] font-medium text-slate-500">
                  <span className="flex items-center gap-1.5">
                    <span className="w-2.5 h-2.5 rounded-xs bg-gold" />
                    Organic Inbox
                  </span>
                  <span className="flex items-center gap-1.5">
                    <span className="w-2.5 h-2.5 rounded-xs bg-eztech" />
                    Lead từ Video
                  </span>
                </div>
              </div>

              <div className="h-[220px] w-full">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={data?.trend || []} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" vertical={false} />
                    <XAxis
                      dataKey="date"
                      tick={{ fontSize: 10, fill: '#94a3b8' }}
                      tickFormatter={d => {
                        const parts = d.split('-');
                        return parts.length === 3 ? `${parts[2]}/${parts[1]}` : d;
                      }}
                      axisLine={{ stroke: '#e2e8f0' }}
                      tickLine={false}
                    />
                    <YAxis
                      tick={{ fontSize: 10, fill: '#94a3b8' }}
                      axisLine={false}
                      tickLine={false}
                      allowDecimals={false}
                    />
                    <Tooltip
                      content={({ active, payload, label }) => {
                        if (active && payload && payload.length) {
                          return (
                            <div className="bg-white/95 backdrop-blur-md border border-slate-200/90 rounded-xl shadow-lg p-3 text-xs">
                              <p className="font-mono font-semibold text-navy mb-1.5 pb-1 border-b border-slate-100">
                                Ngày {label}
                              </p>
                              <div className="space-y-1">
                                {payload.map((p: any) => (
                                  <div key={p.dataKey} className="flex items-center justify-between gap-4">
                                    <span className="flex items-center gap-1.5 text-slate-500">
                                      <span className="w-2 h-2 rounded-full" style={{ backgroundColor: p.color }} />
                                      {p.name}:
                                    </span>
                                    <span className="font-mono font-bold text-navy tabular-nums">{p.value}</span>
                                  </div>
                                ))}
                              </div>
                            </div>
                          );
                        }
                        return null;
                      }}
                    />
                    <Bar
                      dataKey="organic_leads"
                      name="Lead Organic"
                      fill="#F5B400"
                      stackId="channel"
                      radius={[0, 0, 0, 0]}
                    />
                    <Bar
                      dataKey="post_leads"
                      name="Lead từ Video"
                      fill="#1E5BD6"
                      stackId="channel"
                      radius={[3, 3, 0, 0]}
                    />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>

            <div className="pt-2.5 border-t border-slate-100 flex items-center justify-between text-xs text-slate-500">
              <span>Tổng tương tác video TikTok:</span>
              <span className="font-semibold text-eztech font-mono">
                {(summary?.total_comments || 0).toLocaleString()} bình luận
              </span>
            </div>
          </div>
        </div>
      </div>

      {/* 5. Bảng Top Video TikTok Hiệu quả nhất */}
      <div className="bg-white rounded-xl border border-slate-200/80 shadow-card overflow-hidden">
        {/* Bảng Header & Bộ lọc video */}
        <div className="p-4 sm:p-5 border-b border-slate-100 flex flex-col md:flex-row md:items-center md:justify-between gap-3 bg-slate-50/40">
          <div>
            <div className="flex items-center gap-2">
              <h3 className="text-[15px] font-bold text-navy">Top Video TikTok Hiệu quả nhất</h3>
              <span className="px-2 py-0.5 rounded-md text-[11px] font-mono font-medium bg-slate-200/80 text-slate-700">
                {filteredPosts.length} video
              </span>
            </div>
            <p className="text-xs text-slate-500 mt-0.5">
              Xếp hạng video TikTok theo Lead thu về, SĐT, bình luận và học viên chốt
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-2.5">
            {/* Search Input */}
            <div className="relative">
              <Search className="w-3.5 h-3.5 text-slate-400 absolute left-2.5 top-2.5" />
              <input
                type="text"
                placeholder="Tìm nội dung / ID..."
                value={searchPost}
                onChange={e => setSearchPost(e.target.value)}
                className="pl-8 pr-3 py-1.5 bg-white border border-slate-200 rounded-lg text-xs text-navy placeholder:text-slate-400 focus:outline-hidden focus:ring-1 focus:ring-eztech w-44 sm:w-52"
              />
            </div>

            {/* Sort Dropdown hỗ trợ sắp xếp theo Leads, SĐT, Deal Win, Comments */}
            <select
              value={sortBy}
              onChange={e => setSortBy(e.target.value as any)}
              className="bg-white border border-slate-200 rounded-lg text-xs px-2.5 py-1.5 text-navy font-medium focus:outline-hidden cursor-pointer"
            >
              <option value="leads">Xếp theo: Lead thu về (Nhiều nhất)</option>
              <option value="phones">Xếp theo: SĐT thu được (Nhiều nhất)</option>
              <option value="deals">Xếp theo: Học viên chốt (Nhiều nhất)</option>
              <option value="comments">Xếp theo: Bình luận (Nhiều nhất)</option>
              <option value="reactions">Xếp theo: Lượt thích (Nhiều nhất)</option>
              <option value="date">Xếp theo: Mới nhất</option>
            </select>
          </div>
        </div>

        {/* Bảng dữ liệu: Đầy đủ Lead thu về, SĐT, Deal win */}
        <div className="overflow-x-auto">
          <table className="w-full text-left text-[13px]">
            <thead>
              <tr className="bg-slate-50/70 border-b border-slate-100 text-[11px] font-semibold text-slate-500 uppercase tracking-wider">
                <th className="px-5 py-3.5">Video & Nội dung</th>
                <th className="px-4 py-3.5">Kênh</th>
                <th className="px-4 py-3.5 text-right">Lượt thích</th>
                <th className="px-4 py-3.5 text-right">Bình luận</th>
                <th className="px-4 py-3.5 text-right">Lead thu về</th>
                <th className="px-4 py-3.5 text-right">SĐT thu được</th>
                <th className="px-4 py-3.5 text-right">Học viên (Deal)</th>
                <th className="px-5 py-3.5 text-center">Liên kết</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {filteredPosts.slice(0, postLimit).map((post, idx) => {
                return (
                  <tr key={post.post_id} className="hover:bg-slate-50/70 transition-colors">
                    {/* Cột Nội dung */}
                    <td className="px-5 py-3.5 max-w-md">
                      <div className="flex items-start gap-2.5">
                        <span className="w-5 h-5 rounded-md bg-slate-100 text-slate-500 font-mono text-[10px] font-bold flex items-center justify-center shrink-0 mt-0.5">
                          #{idx + 1}
                        </span>
                        <div className="min-w-0">
                          <p className="text-xs font-medium text-navy line-clamp-2 leading-relaxed">
                            {post.message || <span className="text-slate-400 italic">Video TikTok không có mô tả</span>}
                          </p>
                          <div className="flex items-center gap-2 mt-1 text-[11px] text-slate-400 font-mono">
                            <span>{post.inserted_at || '—'}</span>
                          </div>
                        </div>
                      </div>
                    </td>

                    {/* Cột Kênh */}
                    <td className="px-4 py-3.5 whitespace-nowrap">
                      <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-md text-[11px] font-medium bg-slate-50 text-slate-700 border border-slate-200">
                        {post.type === 'livestream' ? (
                          <Radio className="w-3.5 h-3.5 text-rose-600 animate-pulse" />
                        ) : (
                          <Video className="w-3.5 h-3.5 text-slate-600" />
                        )}
                        <span className="truncate max-w-[140px]">{post.page_name}</span>
                      </span>
                    </td>

                    {/* Cột Lượt thích */}
                    <td className="px-4 py-3.5 text-right whitespace-nowrap">
                      <div className="font-mono font-bold text-navy text-xs">
                        {(post.reactions_total || 0).toLocaleString()}
                      </div>
                    </td>

                    {/* Cột Bình luận */}
                    <td className="px-4 py-3.5 text-right whitespace-nowrap">
                      <span className="font-mono font-semibold text-navy text-xs">
                        {(post.comment_count || 0).toLocaleString()}
                      </span>
                    </td>

                    {/* Cột Lead thu về */}
                    <td className="px-4 py-3.5 text-right whitespace-nowrap">
                      {post.lead_count > 0 ? (
                        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-xs font-mono font-bold bg-blue-50 text-eztech border border-blue-200">
                          <Users className="w-3 h-3 text-eztech" />
                          {post.lead_count}
                        </span>
                      ) : (
                        <span className="text-slate-300 font-mono text-xs">—</span>
                      )}
                    </td>

                    {/* Cột SĐT thu được */}
                    <td className="px-4 py-3.5 text-right whitespace-nowrap">
                      {post.phone_count > 0 ? (
                        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-xs font-mono font-bold bg-emerald-50 text-emerald-700 border border-emerald-200">
                          <PhoneCall className="w-3 h-3 text-emerald-600" />
                          {post.phone_count}
                        </span>
                      ) : (
                        <span className="text-slate-300 font-mono text-xs">—</span>
                      )}
                    </td>

                    {/* Cột Deal Win */}
                    <td className="px-4 py-3.5 text-right whitespace-nowrap">
                      {post.deal_count > 0 ? (
                        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-xs font-mono font-bold bg-gold-light text-gold-dark border border-gold-border">
                          <Award className="w-3 h-3 text-gold-dark" />
                          {post.deal_count}
                        </span>
                      ) : (
                        <span className="text-slate-300 font-mono text-xs">—</span>
                      )}
                    </td>

                    {/* Cột Link TikTok */}
                    <td className="px-5 py-3.5 text-center whitespace-nowrap">
                      {post.post_url ? (
                        <a
                          href={post.post_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="inline-flex items-center gap-1 text-[11px] font-semibold text-slate-800 hover:text-black bg-slate-100 hover:bg-slate-200 px-2 py-1 rounded-md border border-slate-300 transition-colors"
                          title={`Xem video: ${post.post_id}`}
                        >
                          <TikTokIcon className="w-3 h-3" />
                          <span>Xem Video</span>
                          <ExternalLink className="w-2.5 h-2.5" />
                        </a>
                      ) : (
                        <span className="text-slate-300 text-xs">—</span>
                      )}
                    </td>
                  </tr>
                );
              })}

              {filteredPosts.length === 0 && (
                <tr>
                  <td colSpan={8} className="px-6 py-12 text-center text-slate-400 text-xs">
                    Không tìm thấy video TikTok nào phù hợp trong khoảng thời gian này
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        {/* Nút Xem thêm video */}
        {filteredPosts.length > postLimit && (
          <div className="p-3 bg-slate-50/60 border-t border-slate-100 text-center">
            <button
              onClick={() => setPostLimit(prev => prev + 20)}
              className="px-4 py-1.5 rounded-lg text-xs font-semibold text-navy bg-white hover:bg-slate-50 border border-slate-200 shadow-xs transition-colors cursor-pointer"
            >
              Xem thêm video ({filteredPosts.length - postLimit} video còn lại)
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
