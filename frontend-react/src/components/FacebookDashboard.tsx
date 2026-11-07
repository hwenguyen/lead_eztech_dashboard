import { useState, useEffect, useMemo } from 'react';
import { format, subDays, startOfMonth } from 'date-fns';
import {
  Facebook,
  MessageSquare,
  ThumbsUp,
  Heart,
  Users,
  PhoneCall,
  Award,
  ExternalLink,
  Calendar,
  RefreshCw,
  Search,
  Video,
  Image as ImageIcon,
  FileText,
  Radio,
  Inbox,
  TrendingUp,
  Sparkles,
  Layers,
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
  fetchFacebookMetrics,
  fetchFacebookPages,
  type FacebookMetricsResponse,
  type FacebookPageItem,
} from '../services/api';

const REACTION_COLORS: Record<string, string> = {
  like: '#1877F2',     // Facebook Blue
  love: '#FA383E',     // Facebook Red/Heart
  haha: '#F7B125',     // Gold/Yellow
  care: '#F59E0B',     // Amber
  wow: '#EAB308',      // Yellow
  sad: '#64748B',      // Slate
  angry: '#EA580C',    // Orange
};

const FORMAT_COLORS: Record<string, string> = {
  post: '#0084FF',
  video: '#8B5CF6',
  photo: '#10B981',
  livestream: '#EF4444',
  text: '#64748B',
};

const FORMAT_LABELS: Record<string, string> = {
  post: 'Bài viết (Status)',
  video: 'Video',
  photo: 'Hình ảnh',
  livestream: 'Phát trực tiếp',
  text: 'Văn bản',
};

export function FacebookDashboard() {
  // Bộ lọc thời gian mặc định 30 ngày gần nhất
  const [startDate, setStartDate] = useState(() => format(subDays(new Date(), 30), 'yyyy-MM-dd'));
  const [endDate, setEndDate] = useState(() => format(new Date(), 'yyyy-MM-dd'));
  const [activePreset, setActivePreset] = useState<number | 'month' | 'custom'>(30);
  const [pageId, setPageId] = useState('');
  const [pagesList, setPagesList] = useState<FacebookPageItem[]>([]);

  // Dữ liệu chỉ số
  const [data, setData] = useState<FacebookMetricsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastRefreshed, setLastRefreshed] = useState<Date | null>(null);

  // Bộ lọc bảng bài viết
  const [searchPost, setSearchPost] = useState('');
  const [typeFilter, setTypeFilter] = useState<string>('all');
  const [sortBy, setSortBy] = useState<'leads' | 'phones' | 'deals' | 'reactions' | 'comments' | 'date'>('leads');
  const [postLimit, setPostLimit] = useState(15);

  // Load danh sách Fanpage Facebook
  useEffect(() => {
    fetchFacebookPages()
      .then(pages => setPagesList(pages))
      .catch(err => console.error('Error fetching Facebook pages:', err));
  }, []);

  // Load dữ liệu metrics
  const loadMetrics = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetchFacebookMetrics(startDate, endDate, pageId || undefined);
      setData(res);
      setLastRefreshed(new Date());
    } catch (err: any) {
      console.error('Lỗi khi tải dữ liệu Facebook metrics:', err);
      setError(err?.response?.data?.detail || err?.message || 'Có lỗi xảy ra khi tải dữ liệu Facebook');
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

  // Chuẩn bị dữ liệu biểu đồ cảm xúc Donut
  const reactionPieData = useMemo(() => {
    if (!data?.reaction_breakdown) return [];
    return Object.entries(data.reaction_breakdown)
      .filter(([_, count]) => count > 0)
      .map(([type, count]) => ({
        name: type.charAt(0).toUpperCase() + type.slice(1),
        key: type,
        value: count,
        color: REACTION_COLORS[type] || '#94A3B8',
      }));
  }, [data?.reaction_breakdown]);

  // Chuẩn bị dữ liệu định dạng bài viết
  const formatPieData = useMemo(() => {
    if (!data?.post_type_stats) return [];
    return Object.entries(data.post_type_stats)
      .filter(([_, count]) => count > 0)
      .map(([type, count]) => ({
        name: FORMAT_LABELS[type] || type,
        key: type,
        value: count,
        color: FORMAT_COLORS[type] || '#3B82F6',
      }));
  }, [data?.post_type_stats]);

  // Chuẩn bị dữ liệu cơ cấu nguồn Lead & SĐT (Post vs Organic)
  const channelLeadData = useMemo(() => {
    const postLeads = data?.summary.post_leads || 0;
    const organicLeads = data?.summary.organic_leads || 0;
    if (postLeads + organicLeads === 0) return [];
    return [
      { name: 'Từ Bài viết (Post)', value: postLeads, color: '#1877F2' },
      { name: 'Tự nhiên (Organic Inbox)', value: organicLeads, color: '#8B5CF6' },
    ];
  }, [data?.summary.post_leads, data?.summary.organic_leads]);

  const channelPhoneData = useMemo(() => {
    const postPhones = data?.summary.post_phones || 0;
    const organicPhones = data?.summary.organic_phones || 0;
    if (postPhones + organicPhones === 0) return [];
    return [
      { name: 'Từ Bài viết (Post)', value: postPhones, color: '#1877F2' },
      { name: 'Tự nhiên (Organic Inbox)', value: organicPhones, color: '#8B5CF6' },
    ];
  }, [data?.summary.post_phones, data?.summary.organic_phones]);

  // Lọc và sắp xếp bảng Top bài viết
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

    if (typeFilter !== 'all') {
      list = list.filter(p => p.type.toLowerCase() === typeFilter);
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
      if (sortBy === 'reactions') {
        return (b.reactions_total || 0) - (a.reactions_total || 0);
      }
      if (sortBy === 'comments') {
        return (b.comment_count || 0) - (a.comment_count || 0);
      }
      // date
      return new Date(b.inserted_at || 0).getTime() - new Date(a.inserted_at || 0).getTime();
    });

    return list;
  }, [data?.top_posts, searchPost, typeFilter, sortBy]);

  const summary = data?.summary;

  // Tính toán tỷ trọng phần trăm
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
        <div className="px-5 py-4 flex flex-col md:flex-row md:items-center md:justify-between gap-3 border-b border-slate-100 bg-linear-to-r from-blue-50/40 via-white to-slate-50/30">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-[#1877F2] text-white flex items-center justify-center shadow-md shadow-blue-500/20 shrink-0">
              <Facebook className="w-5 h-5 fill-white" />
            </div>
            <div>
              <h2 className="text-lg font-bold text-navy tracking-tight">Facebook Analytics</h2>
              <p className="text-xs text-slate-500 mt-0.5">
                Hiệu quả bài viết, tương tác, Lead Organic & Post, SĐT thu được và Deal chốt
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
              onClick={loadMetrics}
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

          {/* Chọn Fanpage với độ rộng thoải mái không bị cắt chữ */}
          <div className="flex items-center gap-2">
            <span className="text-xs font-medium text-slate-500 whitespace-nowrap hidden sm:inline">Trang:</span>
            <select
              value={pageId}
              onChange={e => setPageId(e.target.value)}
              className="bg-white border border-slate-200/90 text-xs rounded-lg px-3 py-1.5 text-navy font-semibold focus:ring-1 focus:ring-eztech focus:outline-hidden shadow-2xs min-w-[220px] max-w-[320px] cursor-pointer"
            >
              <option value="">Tất cả Fanpage Facebook</option>
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
        {/* Card 1: Bài viết xuất bản */}
        <div className="bg-white rounded-xl border border-slate-200/80 p-4 shadow-card hover:shadow-card-hover transition-all">
          <div className="flex items-center justify-between text-slate-500 mb-2">
            <span className="text-xs font-medium">Bài viết xuất bản</span>
            <div className="w-7 h-7 rounded-lg bg-blue-50 text-[#1877F2] flex items-center justify-center">
              <FileText className="w-4 h-4" />
            </div>
          </div>
          <div className="text-2xl font-bold font-mono text-navy">
            {loading ? '...' : (summary?.total_posts || 0).toLocaleString()}
          </div>
          <div className="mt-2 pt-2 border-t border-slate-100 flex items-center justify-between text-[11px] text-slate-500">
            <span>TB/Bài:</span>
            <span className="font-mono font-semibold text-navy">
              {summary?.avg_reactions_per_post || 0} tương tác
            </span>
          </div>
        </div>

        {/* Card 2: Lượt Cảm xúc */}
        <div className="bg-white rounded-xl border border-slate-200/80 p-4 shadow-card hover:shadow-card-hover transition-all">
          <div className="flex items-center justify-between text-slate-500 mb-2">
            <span className="text-xs font-medium">Tổng Cảm xúc (Reactions)</span>
            <div className="w-7 h-7 rounded-lg bg-rose-50 text-rose-500 flex items-center justify-center">
              <ThumbsUp className="w-4 h-4" />
            </div>
          </div>
          <div className="text-2xl font-bold font-mono text-navy">
            {loading ? '...' : (summary?.total_reactions || 0).toLocaleString()}
          </div>
          <div className="mt-2 pt-2 border-t border-slate-100 flex items-center justify-between text-[11px] text-slate-500">
            <span className="flex items-center gap-1">
              <ThumbsUp className="w-3 h-3 text-[#1877F2]" /> {data?.reaction_breakdown?.like || 0}
            </span>
            <span className="flex items-center gap-1 text-rose-500 font-semibold">
              <Heart className="w-3 h-3 fill-rose-500" /> {data?.reaction_breakdown?.love || 0}
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

      {/* 3. Hàng Biểu đồ: Xu hướng (AreaChart) + Phân bổ Cảm xúc & Nội dung */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Cột trái: Xu hướng Tương tác & Lead theo ngày */}
        <div className="lg:col-span-2 bg-white rounded-xl border border-slate-200/80 p-5 shadow-card">
          <div className="flex flex-wrap items-center justify-between gap-2 mb-4">
            <div>
              <h3 className="text-[15px] font-semibold text-navy tracking-tight">Xu hướng hoạt động Facebook</h3>
              <p className="text-xs text-slate-500 mt-0.5">Biến động Tương tác, Bình luận, Lead và SĐT thu được theo ngày</p>
            </div>
            <div className="flex items-center gap-3 text-[11px] font-medium text-slate-500">
              <span className="flex items-center gap-1.5">
                <span className="w-2.5 h-2.5 rounded-full bg-[#1877F2]" />
                Tương tác (Reactions)
              </span>
              <span className="flex items-center gap-1.5">
                <span className="w-2.5 h-2.5 rounded-full bg-navy" />
                Bình luận
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
                  <linearGradient id="fbReactionGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#1877F2" stopOpacity={0.25} />
                    <stop offset="95%" stopColor="#1877F2" stopOpacity={0.0} />
                  </linearGradient>
                  <linearGradient id="fbCommentGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#0F172A" stopOpacity={0.2} />
                    <stop offset="95%" stopColor="#0F172A" stopOpacity={0.0} />
                  </linearGradient>
                  <linearGradient id="fbPhoneGrad" x1="0" y1="0" x2="0" y2="1">
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
                  dataKey="reactions"
                  name="Tương tác"
                  stroke="#1877F2"
                  strokeWidth={2}
                  fill="url(#fbReactionGrad)"
                />
                <Area
                  type="monotone"
                  dataKey="comments"
                  name="Bình luận"
                  stroke="#0F172A"
                  strokeWidth={1.5}
                  fill="url(#fbCommentGrad)"
                />
                <Area
                  type="monotone"
                  dataKey="phones"
                  name="SĐT thu được"
                  stroke="#10B981"
                  strokeWidth={2}
                  fill="url(#fbPhoneGrad)"
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Cột phải: Phân bổ Cảm xúc & Định dạng */}
        <div className="bg-white rounded-xl border border-slate-200/80 p-5 shadow-card flex flex-col justify-between">
          <div>
            <h3 className="text-[15px] font-semibold text-navy tracking-tight">Cảm xúc & Định dạng</h3>
            <p className="text-xs text-slate-500 mt-0.5">Tỷ lệ tương tác theo cảm xúc và loại bài đăng</p>
          </div>

          <div className="grid grid-cols-2 gap-3 my-4">
            {/* Donut Cảm xúc */}
            <div className="flex flex-col items-center">
              <span className="text-[11px] font-semibold text-slate-600 mb-1">Cảm xúc (Reactions)</span>
              <div className="h-32 w-full">
                <ResponsiveContainer width="100%" height="100%">
                  <PieChart>
                    <Pie
                      data={reactionPieData}
                      dataKey="value"
                      nameKey="name"
                      innerRadius={30}
                      outerRadius={50}
                      paddingAngle={3}
                    >
                      {reactionPieData.map(entry => (
                        <Cell key={entry.name} fill={entry.color} />
                      ))}
                    </Pie>
                    <Tooltip />
                  </PieChart>
                </ResponsiveContainer>
              </div>
              <div className="flex flex-wrap justify-center gap-1.5 mt-1 text-[10px] text-slate-500">
                {reactionPieData.slice(0, 3).map(r => (
                  <span key={r.name} className="flex items-center gap-1">
                    <span className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: r.color }} />
                    {r.name}: {r.value}
                  </span>
                ))}
              </div>
            </div>

            {/* Donut Loại bài viết */}
            <div className="flex flex-col items-center">
              <span className="text-[11px] font-semibold text-slate-600 mb-1">Định dạng bài</span>
              <div className="h-32 w-full">
                <ResponsiveContainer width="100%" height="100%">
                  <PieChart>
                    <Pie
                      data={formatPieData}
                      dataKey="value"
                      nameKey="name"
                      innerRadius={30}
                      outerRadius={50}
                      paddingAngle={3}
                    >
                      {formatPieData.map(entry => (
                        <Cell key={entry.name} fill={entry.color} />
                      ))}
                    </Pie>
                    <Tooltip />
                  </PieChart>
                </ResponsiveContainer>
              </div>
              <div className="flex flex-wrap justify-center gap-1.5 mt-1 text-[10px] text-slate-500">
                {formatPieData.slice(0, 3).map(f => (
                  <span key={f.name} className="flex items-center gap-1">
                    <span className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: f.color }} />
                    {f.name}: {f.value}
                  </span>
                ))}
              </div>
            </div>
          </div>

          <div className="pt-3 border-t border-slate-100 flex items-center justify-between text-xs text-slate-500">
            <span>Bài nhiều tương tác nhất:</span>
            <span className="font-semibold text-navy font-mono">
              {data?.top_posts?.[0]?.reactions_total || 0} reactions
            </span>
          </div>
        </div>
      </div>

      {/* 4. Bảng Top Bài viết Facebook Hiệu quả nhất */}
      <div className="bg-white rounded-xl border border-slate-200/80 shadow-card overflow-hidden">
        {/* Bảng Header & Bộ lọc bài viết */}
        <div className="p-4 sm:p-5 border-b border-slate-100 flex flex-col md:flex-row md:items-center md:justify-between gap-3 bg-slate-50/40">
          <div>
            <div className="flex items-center gap-2">
              <h3 className="text-[15px] font-bold text-navy">Top Bài viết Facebook Hiệu quả nhất</h3>
              <span className="px-2 py-0.5 rounded-md text-[11px] font-mono font-medium bg-slate-200/80 text-slate-700">
                {filteredPosts.length} bài
              </span>
            </div>
            <p className="text-xs text-slate-500 mt-0.5">
              Thống kê Lead thu về, SĐT và Deal win chi tiết của từng bài viết
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

            {/* Filter Type */}
            <select
              value={typeFilter}
              onChange={e => setTypeFilter(e.target.value)}
              className="bg-white border border-slate-200 rounded-lg text-xs px-2.5 py-1.5 text-navy font-medium focus:outline-hidden cursor-pointer"
            >
              <option value="all">Tất cả định dạng</option>
              <option value="post">Bài viết (Post)</option>
              <option value="video">Video</option>
              <option value="photo">Hình ảnh</option>
              <option value="livestream">Livestream</option>
            </select>

            {/* Sort Dropdown hỗ trợ sắp xếp theo Leads, SĐT, Deal Win */}
            <select
              value={sortBy}
              onChange={e => setSortBy(e.target.value as any)}
              className="bg-white border border-slate-200 rounded-lg text-xs px-2.5 py-1.5 text-navy font-medium focus:outline-hidden cursor-pointer"
            >
              <option value="leads">Xếp theo: Lead thu về (Nhiều nhất)</option>
              <option value="phones">Xếp theo: SĐT thu được (Nhiều nhất)</option>
              <option value="deals">Xếp theo: Học viên chốt (Nhiều nhất)</option>
              <option value="reactions">Xếp theo: Cảm xúc (Nhiều nhất)</option>
              <option value="comments">Xếp theo: Bình luận (Nhiều nhất)</option>
              <option value="date">Xếp theo: Mới nhất</option>
            </select>
          </div>
        </div>

        {/* Bảng dữ liệu: Đầy đủ Lead thu về, SĐT, Deal win */}
        <div className="overflow-x-auto">
          <table className="w-full text-left text-[13px]">
            <thead>
              <tr className="bg-slate-50/70 border-b border-slate-100 text-[11px] font-semibold text-slate-500 uppercase tracking-wider">
                <th className="px-5 py-3.5">Bài viết & Nội dung</th>
                <th className="px-4 py-3.5">Định dạng</th>
                <th className="px-4 py-3.5 text-right">Cảm xúc</th>
                <th className="px-4 py-3.5 text-right">Bình luận</th>
                <th className="px-4 py-3.5 text-right">Lead thu về</th>
                <th className="px-4 py-3.5 text-right">SĐT thu được</th>
                <th className="px-4 py-3.5 text-right">Học viên (Deal)</th>
                <th className="px-5 py-3.5 text-center">Liên kết</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {filteredPosts.slice(0, postLimit).map((post, idx) => {
                const formatIcon = () => {
                  switch (post.type) {
                    case 'video':
                      return <Video className="w-3.5 h-3.5 text-purple-600" />;
                    case 'photo':
                      return <ImageIcon className="w-3.5 h-3.5 text-emerald-600" />;
                    case 'livestream':
                      return <Radio className="w-3.5 h-3.5 text-rose-600 animate-pulse" />;
                    default:
                      return <FileText className="w-3.5 h-3.5 text-blue-600" />;
                  }
                };

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
                            {post.message || <span className="text-slate-400 italic">Không có tiêu đề (Hình ảnh/Video)</span>}
                          </p>
                          <div className="flex items-center gap-2 mt-1 text-[11px] text-slate-400 font-mono">
                            <span>{post.inserted_at || '—'}</span>
                            <span>•</span>
                            <span className="truncate max-w-[150px]">{post.page_name}</span>
                          </div>
                        </div>
                      </div>
                    </td>

                    {/* Cột Định dạng */}
                    <td className="px-4 py-3.5 whitespace-nowrap">
                      <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-md text-[11px] font-medium bg-slate-50 text-slate-700 border border-slate-200">
                        {formatIcon()}
                        <span>{FORMAT_LABELS[post.type] || post.type}</span>
                      </span>
                    </td>

                    {/* Cột Cảm xúc */}
                    <td className="px-4 py-3.5 text-right whitespace-nowrap">
                      <div className="font-mono font-bold text-navy text-xs">
                        {(post.reactions_total || 0).toLocaleString()}
                      </div>
                      <div className="text-[10px] text-slate-400 font-mono flex items-center justify-end gap-1.5 mt-0.5">
                        <span>👍 {post.like_count || 0}</span>
                        {post.love_count > 0 && <span className="text-rose-500">❤️ {post.love_count}</span>}
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
                        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-xs font-mono font-bold bg-blue-50 text-blue-700 border border-blue-200">
                          <Users className="w-3 h-3 text-[#1877F2]" />
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
                        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-xs font-mono font-bold bg-amber-50 text-amber-700 border border-amber-200">
                          <Award className="w-3 h-3 text-amber-600" />
                          {post.deal_count}
                        </span>
                      ) : (
                        <span className="text-slate-300 font-mono text-xs">—</span>
                      )}
                    </td>

                    {/* Cột Link Facebook */}
                    <td className="px-5 py-3.5 text-center whitespace-nowrap">
                      {post.post_url ? (
                        <a
                          href={post.post_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="inline-flex items-center gap-1 text-[11px] font-semibold text-[#1877F2] hover:text-blue-800 bg-blue-50/80 hover:bg-blue-100/80 px-2 py-1 rounded-md border border-blue-200/80 transition-colors"
                          title={`Xem bài viết: ${post.post_id}`}
                        >
                          <Facebook className="w-3 h-3" />
                          <span>Xem FB</span>
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
                    Không tìm thấy bài viết Facebook nào phù hợp trong khoảng thời gian này
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        {/* Nút Xem thêm bài viết */}
        {filteredPosts.length > postLimit && (
          <div className="p-3 bg-slate-50/60 border-t border-slate-100 text-center">
            <button
              onClick={() => setPostLimit(prev => prev + 20)}
              className="px-4 py-1.5 rounded-lg text-xs font-semibold text-navy bg-white hover:bg-slate-50 border border-slate-200 shadow-xs transition-colors cursor-pointer"
            >
              Xem thêm bài viết ({filteredPosts.length - postLimit} bài còn lại)
            </button>
          </div>
        )}
      </div>

      {/* 5. PHÂN TÍCH CHUYÊN SÂU NGUỒN LEAD: BÀI VIẾT (POST) VS TỰ NHIÊN (ORGANIC INBOX) */}
      <div className="space-y-4">
        {/* Tiêu đề phân đoạn */}
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2 pt-2">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-lg bg-linear-to-tr from-blue-600 to-indigo-600 text-white flex items-center justify-center shadow-xs">
              <Layers className="w-4 h-4" />
            </div>
            <div>
              <h3 className="text-base font-bold text-navy tracking-tight flex items-center gap-2">
                Phân tích Nguồn Lead: Bài viết (Post) vs Tự nhiên (Organic)
                <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-indigo-50 text-indigo-700 border border-indigo-200 uppercase">
                  Hiệu quả Kênh
                </span>
              </h3>
              <p className="text-xs text-slate-500 mt-0.5">
                So sánh số lượng khách hàng tiềm năng, SĐT thu được và tỷ lệ ra số giữa kênh Bài viết và Tin nhắn trực tiếp
              </p>
            </div>
          </div>
        </div>

        {/* 3 Thẻ KPI So sánh Nguồn Lead */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3.5">
          {/* KPI 1: Lead từ Bài viết (Post) */}
          <div className="bg-white rounded-xl border border-blue-100 p-4 shadow-card hover:shadow-card-hover transition-all relative overflow-hidden">
            <div className="absolute top-0 right-0 w-24 h-24 bg-blue-500/5 rounded-full blur-xl pointer-events-none" />
            <div className="flex items-center justify-between text-slate-500 mb-2">
              <div className="flex items-center gap-1.5">
                <span className="w-2 h-2 rounded-full bg-[#1877F2]" />
                <span className="text-xs font-semibold text-navy">Từ Bài viết (Post / Ads)</span>
              </div>
              <div className="w-7 h-7 rounded-lg bg-blue-50 text-[#1877F2] flex items-center justify-center">
                <FileText className="w-4 h-4" />
              </div>
            </div>
            <div className="text-2xl font-bold font-mono text-navy">
              {loading ? '...' : (summary?.post_leads || 0).toLocaleString()} <span className="text-xs font-normal text-slate-500">khách</span>
            </div>
            <div className="mt-3 pt-2.5 border-t border-slate-100 flex items-center justify-between text-[11px] text-slate-500">
              <span className="flex items-center gap-1 text-emerald-600 font-semibold">
                <PhoneCall className="w-3 h-3" /> {summary?.post_phones || 0} SĐT thu được
              </span>
              <span className="font-mono font-bold text-blue-600 bg-blue-50 px-2 py-0.5 rounded border border-blue-200">
                Tỷ lệ có số: {summary?.post_phone_rate || 0}%
              </span>
            </div>
          </div>

          {/* KPI 2: Lead Tự nhiên (Organic Inbox) */}
          <div className="bg-white rounded-xl border border-purple-100 p-4 shadow-card hover:shadow-card-hover transition-all relative overflow-hidden">
            <div className="absolute top-0 right-0 w-24 h-24 bg-purple-500/5 rounded-full blur-xl pointer-events-none" />
            <div className="flex items-center justify-between text-slate-500 mb-2">
              <div className="flex items-center gap-1.5">
                <span className="w-2 h-2 rounded-full bg-[#8B5CF6]" />
                <span className="text-xs font-semibold text-navy">Tự nhiên (Organic Inbox)</span>
              </div>
              <div className="w-7 h-7 rounded-lg bg-purple-50 text-[#8B5CF6] flex items-center justify-center">
                <Inbox className="w-4 h-4" />
              </div>
            </div>
            <div className="text-2xl font-bold font-mono text-navy">
              {loading ? '...' : (summary?.organic_leads || 0).toLocaleString()} <span className="text-xs font-normal text-slate-500">leads</span>
            </div>
            <div className="mt-3 pt-2.5 border-t border-slate-100 flex items-center justify-between text-[11px] text-slate-500">
              <span className="flex items-center gap-1 text-emerald-600 font-semibold">
                <PhoneCall className="w-3 h-3" /> {summary?.organic_phones || 0} SĐT thu được
              </span>
              <span className="font-mono font-bold text-purple-600 bg-purple-50 px-2 py-0.5 rounded border border-purple-200">
                Tỷ lệ có số: {summary?.organic_phone_rate || 0}%
              </span>
            </div>
          </div>

          {/* KPI 3: Cơ cấu đóng góp & Deal chốt */}
          <div className="bg-white rounded-xl border border-emerald-100 p-4 shadow-card hover:shadow-card-hover transition-all relative overflow-hidden">
            <div className="absolute top-0 right-0 w-24 h-24 bg-emerald-500/5 rounded-full blur-xl pointer-events-none" />
            <div className="flex items-center justify-between text-slate-500 mb-2">
              <div className="flex items-center gap-1.5">
                <Sparkles className="w-3.5 h-3.5 text-emerald-600" />
                <span className="text-xs font-semibold text-navy">Cơ cấu đóng góp Kênh</span>
              </div>
              <div className="w-7 h-7 rounded-lg bg-emerald-50 text-emerald-600 flex items-center justify-center">
                <TrendingUp className="w-4 h-4" />
              </div>
            </div>
            <div className="text-xl font-bold font-mono text-navy flex items-baseline gap-2">
              <span className="text-purple-600">{organicLeadPct}% Organic</span>
              <span className="text-slate-300">•</span>
              <span className="text-blue-600">{postLeadPct}% Post</span>
            </div>
            <div className="mt-3 pt-2.5 border-t border-slate-100 flex items-center justify-between text-[11px] text-slate-500">
              <span>Đóng góp SĐT:</span>
              <span className="font-mono font-bold text-emerald-700">
                {organicPhonePct}% Inbox vs {postPhonePct}% Post
              </span>
            </div>
          </div>
        </div>

        {/* 2 Biểu đồ chuyên sâu Phân tích Post vs Organic */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {/* Chart 1: Cơ cấu Nguồn Lead & SĐT (Donut Charts & Bảng đối soát) */}
          <div className="bg-white rounded-xl border border-slate-200/80 p-5 shadow-card flex flex-col justify-between">
            <div>
              <div className="flex items-center justify-between">
                <div>
                  <h4 className="text-sm font-bold text-navy">Cơ cấu Nguồn Lead & Số điện thoại</h4>
                  <p className="text-xs text-slate-500 mt-0.5">Tỷ lệ đóng góp giữa Bài viết (Post) và Tin nhắn tự nhiên (Organic)</p>
                </div>
              </div>

              {/* 2 Donut Charts Song song */}
              <div className="grid grid-cols-2 gap-3 my-4">
                {/* Donut Lead */}
                <div className="flex flex-col items-center">
                  <span className="text-[11px] font-semibold text-slate-600 mb-1">Cơ cấu Khách (Leads)</span>
                  <div className="h-32 w-full">
                    <ResponsiveContainer width="100%" height="100%">
                      <PieChart>
                        <Pie
                          data={channelLeadData}
                          dataKey="value"
                          nameKey="name"
                          innerRadius={30}
                          outerRadius={50}
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
                  <div className="text-center text-[11px] font-mono text-slate-600 mt-1">
                    <span className="text-blue-600 font-bold">{postLeadPct}%</span> Post vs{' '}
                    <span className="text-purple-600 font-bold">{organicLeadPct}%</span> Organic
                  </div>
                </div>

                {/* Donut Phone */}
                <div className="flex flex-col items-center">
                  <span className="text-[11px] font-semibold text-slate-600 mb-1">Cơ cấu Số điện thoại</span>
                  <div className="h-32 w-full">
                    <ResponsiveContainer width="100%" height="100%">
                      <PieChart>
                        <Pie
                          data={channelPhoneData}
                          dataKey="value"
                          nameKey="name"
                          innerRadius={30}
                          outerRadius={50}
                          paddingAngle={3}
                        >
                          {channelPhoneData.map(entry => (
                            <Cell key={entry.name} fill={entry.color} />
                          ))}
                        </Pie>
                        <Tooltip />
                      </PieChart>
                    </ResponsiveContainer>
                  </div>
                  <div className="text-center text-[11px] font-mono text-slate-600 mt-1">
                    <span className="text-blue-600 font-bold">{postPhonePct}%</span> Post vs{' '}
                    <span className="text-purple-600 font-bold">{organicPhonePct}%</span> Organic
                  </div>
                </div>
              </div>
            </div>

            {/* Bảng so sánh chỉ số trực tiếp */}
            <div className="pt-3 border-t border-slate-100 overflow-hidden">
              <table className="w-full text-xs text-left">
                <thead>
                  <tr className="text-slate-400 text-[10px] uppercase font-semibold border-b border-slate-100">
                    <th className="pb-1.5">Nguồn</th>
                    <th className="pb-1.5 text-right">Khách / Lead</th>
                    <th className="pb-1.5 text-right">SĐT thu được</th>
                    <th className="pb-1.5 text-right">Tỷ lệ có số</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-50 font-mono text-[11px]">
                  <tr>
                    <td className="py-1.5 font-sans font-medium text-navy flex items-center gap-1.5">
                      <span className="w-2 h-2 rounded-full bg-[#1877F2]" />
                      Bài viết (Post)
                    </td>
                    <td className="py-1.5 text-right text-slate-700">{(summary?.post_leads || 0).toLocaleString()}</td>
                    <td className="py-1.5 text-right text-emerald-600 font-bold">{summary?.post_phones || 0}</td>
                    <td className="py-1.5 text-right text-blue-600 font-semibold">{summary?.post_phone_rate || 0}%</td>
                  </tr>
                  <tr>
                    <td className="py-1.5 font-sans font-medium text-navy flex items-center gap-1.5">
                      <span className="w-2 h-2 rounded-full bg-[#8B5CF6]" />
                      Tự nhiên (Organic)
                    </td>
                    <td className="py-1.5 text-right text-slate-700">{(summary?.organic_leads || 0).toLocaleString()}</td>
                    <td className="py-1.5 text-right text-emerald-600 font-bold">{summary?.organic_phones || 0}</td>
                    <td className="py-1.5 text-right text-purple-600 font-semibold">{summary?.organic_phone_rate || 0}%</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>

          {/* Chart 2: Biểu đồ cột Xu hướng Lead theo ngày: Post vs Organic */}
          <div className="bg-white rounded-xl border border-slate-200/80 p-5 shadow-card flex flex-col justify-between">
            <div>
              <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
                <div>
                  <h4 className="text-sm font-bold text-navy">Xu hướng Lead theo ngày (Post vs Organic)</h4>
                  <p className="text-xs text-slate-500 mt-0.5">Biến động lượng khách hàng mới mỗi ngày theo nguồn</p>
                </div>
                <div className="flex items-center gap-3 text-[11px] font-medium text-slate-500">
                  <span className="flex items-center gap-1.5">
                    <span className="w-2.5 h-2.5 rounded-sm bg-[#8B5CF6]" />
                    Organic Inbox
                  </span>
                  <span className="flex items-center gap-1.5">
                    <span className="w-2.5 h-2.5 rounded-sm bg-[#1877F2]" />
                    Lead từ Post
                  </span>
                </div>
              </div>

              <div className="h-[240px] w-full">
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
                      fill="#8B5CF6"
                      stackId="channel"
                      radius={[0, 0, 0, 0]}
                    />
                    <Bar
                      dataKey="post_leads"
                      name="Lead từ Post"
                      fill="#1877F2"
                      stackId="channel"
                      radius={[3, 3, 0, 0]}
                    />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>

            <div className="pt-3 border-t border-slate-100 flex items-center justify-between text-xs text-slate-500">
              <span>Tổng tương tác bài viết (Post):</span>
              <span className="font-semibold text-blue-600 font-mono">
                {(summary?.total_comments || 0).toLocaleString()} bình luận
              </span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
