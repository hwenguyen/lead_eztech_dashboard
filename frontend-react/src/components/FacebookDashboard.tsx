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
  Megaphone,
  Copy,
  Check,
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
  post: '#1E5BD6',     // EzTech Blue
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

  // Bộ lọc và copy bảng Ads
  const [searchAd, setSearchAd] = useState('');
  const [adLimit, setAdLimit] = useState(10);
  const [copiedAdId, setCopiedAdId] = useState<string | null>(null);

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
        color: FORMAT_COLORS[type] || '#1E5BD6',
      }));
  }, [data?.post_type_stats]);

  // Chuẩn bị dữ liệu cơ cấu nguồn Lead & SĐT (Ads vs Post vs Organic)
  const channelLeadData = useMemo(() => {
    const adsLeads = data?.summary.ads_leads || 0;
    const postLeads = data?.summary.post_leads || 0;
    const organicLeads = data?.summary.organic_leads || 0;
    if (adsLeads + postLeads + organicLeads === 0) return [];
    return [
      { name: 'Quảng cáo (Ads)', value: adsLeads, color: '#7C3AED' },       // Purple
      { name: 'Bài viết (Post)', value: postLeads, color: '#1E5BD6' },      // EzTech Blue
      { name: 'Tự nhiên (Organic)', value: organicLeads, color: '#10B981' }, // Emerald Green
    ];
  }, [data?.summary.ads_leads, data?.summary.post_leads, data?.summary.organic_leads]);

  // Lọc danh sách Top Ads
  const filteredAds = useMemo(() => {
    if (!data?.top_ads) return [];
    let list = [...data.top_ads];
    if (searchAd.trim()) {
      const q = searchAd.toLowerCase().trim();
      list = list.filter(a =>
        a.ad_id.toLowerCase().includes(q) ||
        (a.post_id && a.post_id.toLowerCase().includes(q)) ||
        (a.post_message && a.post_message.toLowerCase().includes(q))
      );
    }
    return list;
  }, [data?.top_ads, searchAd]);

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

  // Tính toán tỷ trọng phần trăm 3 nguồn (Ads vs Post vs Organic)
  const totalChannelLeads = (summary?.ads_leads || 0) + (summary?.post_leads || 0) + (summary?.organic_leads || 0);
  const adsLeadPct = totalChannelLeads > 0 ? Math.round(((summary?.ads_leads || 0) / totalChannelLeads) * 100) : 0;
  const postLeadPct = totalChannelLeads > 0 ? Math.round(((summary?.post_leads || 0) / totalChannelLeads) * 100) : 0;
  const organicLeadPct = totalChannelLeads > 0 ? Math.max(0, 100 - adsLeadPct - postLeadPct) : 0;

  const totalChannelPhones = (summary?.ads_phones || 0) + (summary?.post_phones || 0) + (summary?.organic_phones || 0);
  const adsPhonePct = totalChannelPhones > 0 ? Math.round(((summary?.ads_phones || 0) / totalChannelPhones) * 100) : 0;
  const postPhonePct = totalChannelPhones > 0 ? Math.round(((summary?.post_phones || 0) / totalChannelPhones) * 100) : 0;
  const organicPhonePct = totalChannelPhones > 0 ? Math.max(0, 100 - adsPhonePct - postPhonePct) : 0;

  return (
    <div className="space-y-5 animate-in fade-in duration-300">
      {/* 1. Header & Bộ lọc thiết kế chuẩn mực */}
      <div className="bg-white rounded-2xl border border-slate-200/90 shadow-xs overflow-hidden">
        {/* Top Header: Tiêu đề & Thời gian cập nhật */}
        <div className="px-5 py-4 flex flex-col md:flex-row md:items-center md:justify-between gap-3 border-b border-slate-100 bg-linear-to-r from-blue-50/40 via-white to-slate-50/30">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-eztech text-white flex items-center justify-center shadow-md shadow-blue-500/20 shrink-0">
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
            <div className="w-7 h-7 rounded-lg bg-blue-50 text-eztech flex items-center justify-center">
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
              <ThumbsUp className="w-3 h-3 text-eztech" /> {data?.reaction_breakdown?.like || 0}
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
                <span className="w-2.5 h-2.5 rounded-full bg-eztech" />
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
                    <stop offset="5%" stopColor="#1E5BD6" stopOpacity={0.25} />
                    <stop offset="95%" stopColor="#1E5BD6" stopOpacity={0.0} />
                  </linearGradient>
                  <linearGradient id="fbCommentGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#0A1F44" stopOpacity={0.2} />
                    <stop offset="95%" stopColor="#0A1F44" stopOpacity={0.0} />
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
                  stroke="#1E5BD6"
                  strokeWidth={2}
                  fill="url(#fbReactionGrad)"
                />
                <Area
                  type="monotone"
                  dataKey="comments"
                  name="Bình luận"
                  stroke="#0A1F44"
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
              <span className="text-[11px] font-semibold text-slate-600 mb-1">Cảm xúc</span>
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
              <span className="text-[11px] font-semibold text-slate-600 mb-1">Định dạng</span>
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
            <span>Bài tương tác nhiều nhất:</span>
            <span className="font-semibold text-navy font-mono">
              {data?.top_posts?.[0]?.reactions_total || 0} reactions
            </span>
          </div>
        </div>
      </div>

      {/* 4. PHÂN TÍCH NGUỒN LEAD: QUẢNG CÁO (ADS) VS BÀI VIẾT VS TỰ NHIÊN */}
      <div className="space-y-3.5">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <h3 className="text-[15px] font-bold text-navy tracking-tight">Phân tích Nguồn Lead Facebook</h3>
            <span className="text-[11px] font-semibold bg-purple-50 text-purple-700 border border-purple-200 px-2 py-0.5 rounded-md">
              Ads • Post • Organic
            </span>
          </div>
          <span className="text-xs text-slate-400">Bóc tách chuẩn xác hiệu quả từng nguồn</span>
        </div>

        {/* 3 Thẻ KPI Tóm tắt Nguồn Lead */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3.5">
          {/* KPI 1: Lead từ Quảng cáo (Facebook Ads) - Tím Indigo */}
          <div className="bg-white rounded-xl border border-purple-200/90 p-4 shadow-card hover:shadow-card-hover transition-all relative overflow-hidden">
            <div className="absolute top-0 right-0 w-24 h-24 bg-purple-50 rounded-bl-full -z-0 pointer-events-none" />
            <div className="relative z-10">
              <div className="flex items-center justify-between text-slate-500 mb-1.5">
                <span className="text-xs font-bold text-purple-900 flex items-center gap-1.5">
                  <span className="w-2 h-2 rounded-full bg-purple-600" />
                  Từ Quảng cáo (Facebook Ads)
                </span>
                <div className="w-6 h-6 rounded-md bg-purple-100 text-purple-700 flex items-center justify-center">
                  <Megaphone className="w-3.5 h-3.5" />
                </div>
              </div>
              <div className="text-2xl font-bold font-mono text-navy">
                {loading ? '...' : (summary?.ads_leads || 0).toLocaleString()} <span className="text-xs font-normal text-slate-400">khách ({adsLeadPct}%)</span>
              </div>
              <div className="mt-2.5 pt-2 border-t border-purple-100 flex items-center justify-between text-xs text-slate-500 font-mono">
                <span className="text-emerald-600 font-semibold flex items-center gap-1">
                  <PhoneCall className="w-3 h-3" /> {summary?.ads_phones || 0} SĐT ({adsPhonePct}%)
                </span>
                <span className="text-purple-700 font-bold bg-purple-50 border border-purple-200 px-1.5 py-0.5 rounded text-[11px]">
                  {summary?.ads_phone_rate || 0}% có số
                </span>
              </div>
            </div>
          </div>

          {/* KPI 2: Lead từ Bài viết (Post / Comment) - Chuẩn màu EzTech Blue */}
          <div className="bg-white rounded-xl border border-slate-200/80 p-4 shadow-card hover:shadow-card-hover transition-all">
            <div className="flex items-center justify-between text-slate-500 mb-1.5">
              <span className="text-xs font-semibold text-navy flex items-center gap-1.5">
                <span className="w-2 h-2 rounded-full bg-eztech" />
                Từ Bài viết (Post / Comment)
              </span>
              <div className="w-6 h-6 rounded-md bg-blue-50 text-eztech flex items-center justify-center">
                <FileText className="w-3.5 h-3.5" />
              </div>
            </div>
            <div className="text-2xl font-bold font-mono text-navy">
              {loading ? '...' : (summary?.post_leads || 0).toLocaleString()} <span className="text-xs font-normal text-slate-400">khách ({postLeadPct}%)</span>
            </div>
            <div className="mt-2.5 pt-2 border-t border-slate-100 flex items-center justify-between text-xs text-slate-500 font-mono">
              <span className="text-emerald-600 font-semibold flex items-center gap-1">
                <PhoneCall className="w-3 h-3" /> {summary?.post_phones || 0} SĐT ({postPhonePct}%)
              </span>
              <span className="text-eztech font-bold bg-blue-50 px-1.5 py-0.5 rounded text-[11px]">
                {summary?.post_phone_rate || 0}% có số
              </span>
            </div>
          </div>

          {/* KPI 3: Lead Tự nhiên (Organic Inbox) - Xanh Ngọc Emerald */}
          <div className="bg-white rounded-xl border border-slate-200/80 p-4 shadow-card hover:shadow-card-hover transition-all">
            <div className="flex items-center justify-between text-slate-500 mb-1.5">
              <span className="text-xs font-semibold text-navy flex items-center gap-1.5">
                <span className="w-2 h-2 rounded-full bg-emerald-500" />
                Tự nhiên (Organic Inbox)
              </span>
              <div className="w-6 h-6 rounded-md bg-emerald-50 text-emerald-700 flex items-center justify-center">
                <Inbox className="w-3.5 h-3.5" />
              </div>
            </div>
            <div className="text-2xl font-bold font-mono text-navy">
              {loading ? '...' : (summary?.organic_leads || 0).toLocaleString()} <span className="text-xs font-normal text-slate-400">leads ({organicLeadPct}%)</span>
            </div>
            <div className="mt-2.5 pt-2 border-t border-slate-100 flex items-center justify-between text-xs text-slate-500 font-mono">
              <span className="text-emerald-600 font-semibold flex items-center gap-1">
                <PhoneCall className="w-3 h-3" /> {summary?.organic_phones || 0} SĐT ({organicPhonePct}%)
              </span>
              <span className="text-emerald-700 font-bold bg-emerald-50 px-1.5 py-0.5 rounded text-[11px]">
                {summary?.organic_phone_rate || 0}% có số
              </span>
            </div>
          </div>
        </div>

        {/* 2 Biểu đồ chuyên sâu Phân tích 3 Nguồn */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {/* Chart 1: Cơ cấu Nguồn Lead & Bảng đối soát 3 nguồn */}
          <div className="bg-white rounded-xl border border-slate-200/80 p-5 shadow-card flex flex-col justify-between">
            <div>
              <div className="flex items-center justify-between mb-3">
                <h4 className="text-sm font-bold text-navy">Cơ cấu Nguồn & Chuyển đổi</h4>
                <div className="flex items-center gap-2 text-[11px] font-medium text-slate-500">
                  <span className="flex items-center gap-1">
                    <span className="w-2 h-2 rounded-full bg-purple-600" />
                    Ads
                  </span>
                  <span className="flex items-center gap-1">
                    <span className="w-2 h-2 rounded-full bg-eztech" />
                    Post
                  </span>
                  <span className="flex items-center gap-1">
                    <span className="w-2 h-2 rounded-full bg-emerald-500" />
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

            {/* Bảng so sánh 3 nguồn trực tiếp gọn gàng */}
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
                    <td className="py-2 font-sans font-medium text-purple-900 flex items-center gap-1.5">
                      <span className="w-2 h-2 rounded-full bg-purple-600" />
                      Quảng cáo (Facebook Ads)
                    </td>
                    <td className="py-2 text-right text-slate-700">{(summary?.ads_leads || 0).toLocaleString()}</td>
                    <td className="py-2 text-right text-emerald-600 font-bold">{summary?.ads_phones || 0}</td>
                    <td className="py-2 text-right text-purple-700 font-bold">{summary?.ads_phone_rate || 0}%</td>
                  </tr>
                  <tr>
                    <td className="py-2 font-sans font-medium text-navy flex items-center gap-1.5">
                      <span className="w-2 h-2 rounded-full bg-eztech" />
                      Bài viết (Post / Comment)
                    </td>
                    <td className="py-2 text-right text-slate-700">{(summary?.post_leads || 0).toLocaleString()}</td>
                    <td className="py-2 text-right text-emerald-600 font-bold">{summary?.post_phones || 0}</td>
                    <td className="py-2 text-right text-eztech font-bold">{summary?.post_phone_rate || 0}%</td>
                  </tr>
                  <tr>
                    <td className="py-2 font-sans font-medium text-navy flex items-center gap-1.5">
                      <span className="w-2 h-2 rounded-full bg-emerald-500" />
                      Tự nhiên (Organic Inbox)
                    </td>
                    <td className="py-2 text-right text-slate-700">{(summary?.organic_leads || 0).toLocaleString()}</td>
                    <td className="py-2 text-right text-emerald-600 font-bold">{summary?.organic_phones || 0}</td>
                    <td className="py-2 text-right text-emerald-700 font-bold">{summary?.organic_phone_rate || 0}%</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>

          {/* Chart 2: Biểu đồ cột Xu hướng Lead theo ngày (Ads vs Post vs Organic) */}
          <div className="bg-white rounded-xl border border-slate-200/80 p-5 shadow-card flex flex-col justify-between">
            <div>
              <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
                <h4 className="text-sm font-bold text-navy">Xu hướng Lead theo ngày</h4>
                <div className="flex items-center gap-3 text-[11px] font-medium text-slate-500">
                  <span className="flex items-center gap-1.5">
                    <span className="w-2.5 h-2.5 rounded-xs bg-purple-600" />
                    Lead từ Ads
                  </span>
                  <span className="flex items-center gap-1.5">
                    <span className="w-2.5 h-2.5 rounded-xs bg-eztech" />
                    Lead từ Post
                  </span>
                  <span className="flex items-center gap-1.5">
                    <span className="w-2.5 h-2.5 rounded-xs bg-emerald-500" />
                    Organic Inbox
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
                      dataKey="ads_leads"
                      name="Lead từ Ads"
                      fill="#7C3AED"
                      stackId="channel"
                      radius={[0, 0, 0, 0]}
                    />
                    <Bar
                      dataKey="post_leads"
                      name="Lead từ Post"
                      fill="#1E5BD6"
                      stackId="channel"
                      radius={[0, 0, 0, 0]}
                    />
                    <Bar
                      dataKey="organic_leads"
                      name="Lead Organic"
                      fill="#10B981"
                      stackId="channel"
                      radius={[3, 3, 0, 0]}
                    />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>

            <div className="pt-2.5 border-t border-slate-100 flex items-center justify-between text-xs text-slate-500">
              <span>Tổng tương tác bài viết:</span>
              <span className="font-semibold text-eztech font-mono">
                {(summary?.total_comments || 0).toLocaleString()} bình luận
              </span>
            </div>
          </div>
        </div>
      </div>

      {/* 5. Bảng Hiệu quả Quảng cáo Facebook (Facebook Ads Performance) */}
      <div className="bg-white rounded-xl border border-slate-200/80 shadow-card overflow-hidden">
        <div className="p-4 sm:p-5 border-b border-slate-100 flex flex-col md:flex-row md:items-center md:justify-between gap-3 bg-linear-to-r from-purple-50/40 via-white to-slate-50/30">
          <div>
            <div className="flex items-center gap-2">
              <div className="w-7 h-7 rounded-lg bg-purple-100 text-purple-700 flex items-center justify-center">
                <Megaphone className="w-4 h-4" />
              </div>
              <h3 className="text-[15px] font-bold text-navy">Hiệu quả Chiến dịch / Mẫu Ads Facebook</h3>
              <span className="px-2 py-0.5 rounded-md text-[11px] font-mono font-bold bg-purple-50 text-purple-700 border border-purple-200">
                {filteredAds.length} mẫu Ads
              </span>
            </div>
            <p className="text-xs text-slate-500 mt-1">
              Thống kê lượng khách (Leads), SĐT thu được, tỷ lệ có số (CR %) và Học viên chốt theo từng Mẫu Ads
            </p>
          </div>

          <div className="flex items-center gap-2.5">
            <div className="relative">
              <Search className="w-3.5 h-3.5 text-slate-400 absolute left-2.5 top-2.5" />
              <input
                type="text"
                placeholder="Tìm mã Ad ID / bài viết..."
                value={searchAd}
                onChange={e => setSearchAd(e.target.value)}
                className="pl-8 pr-3 py-1.5 bg-white border border-slate-200 rounded-lg text-xs text-navy placeholder:text-slate-400 focus:outline-hidden focus:ring-1 focus:ring-purple-500 w-52 sm:w-64"
              />
            </div>
          </div>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-xs text-left">
            <thead>
              <tr className="bg-slate-50/70 border-b border-slate-100 text-slate-500 font-semibold text-[11px] uppercase tracking-wider">
                <th className="py-3 px-4">Mã Quảng cáo (Ad ID)</th>
                <th className="py-3 px-4">Bài viết / Creative đính kèm</th>
                <th className="py-3 px-4 text-right">Lead từ Ads</th>
                <th className="py-3 px-4 text-right">SĐT thu được</th>
                <th className="py-3 px-4 text-right">Tỷ lệ ra số</th>
                <th className="py-3 px-4 text-right">Học viên chốt</th>
                <th className="py-3 px-4 text-center">Thao tác</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {filteredAds.length === 0 ? (
                <tr>
                  <td colSpan={7} className="py-8 text-center text-slate-400">
                    Chưa phát hiện mẫu quảng cáo nào có tương tác trong khoảng thời gian đã chọn
                  </td>
                </tr>
              ) : (
                filteredAds.slice(0, adLimit).map(ad => (
                  <tr key={ad.ad_id} className="hover:bg-purple-50/30 transition-colors">
                    <td className="py-3 px-4 font-mono font-semibold text-purple-700">
                      <div className="flex items-center gap-1.5">
                        <span className="bg-purple-50 border border-purple-200 px-2 py-0.5 rounded text-[11px]">
                          {ad.ad_id}
                        </span>
                      </div>
                    </td>
                    <td className="py-3 px-4 max-w-[320px]">
                      {(() => {
                        const cleanMsg = ad.post_message && !['.', '..', '...', 'ib', 'inbox'].includes(ad.post_message.trim().toLowerCase())
                          ? ad.post_message.trim()
                          : null;
                        const label = cleanMsg || (ad.post_id ? `Bài viết Facebook (${ad.post_id})` : 'Quảng cáo trực tiếp Inbox');

                        return ad.post_url ? (
                          <a
                            href={ad.post_url}
                            target="_blank"
                            rel="noreferrer"
                            className="font-medium text-navy hover:text-eztech line-clamp-2 transition-colors flex items-center gap-1 group"
                            title={cleanMsg || 'Xem bài viết Facebook gốc'}
                          >
                            <span className="truncate group-hover:underline">{label}</span>
                            <ExternalLink className="w-3 h-3 shrink-0 text-slate-400 group-hover:text-eztech" />
                          </a>
                        ) : (
                          <span className="text-slate-500 font-medium truncate block" title={label}>
                            {label}
                          </span>
                        );
                      })()}
                    </td>
                    <td className="py-3 px-4 text-right font-mono font-bold text-navy text-[13px]">
                      {ad.lead_count.toLocaleString()}
                    </td>
                    <td className="py-3 px-4 text-right font-mono font-bold text-emerald-600 text-[13px]">
                      {ad.phone_count.toLocaleString()}
                    </td>
                    <td className="py-3 px-4 text-right font-mono">
                      <span className="inline-block bg-purple-50 text-purple-700 border border-purple-200 px-2 py-0.5 rounded font-bold text-[11px]">
                        {ad.phone_rate}%
                      </span>
                    </td>
                    <td className="py-3 px-4 text-right font-mono">
                      {ad.deal_count > 0 ? (
                        <span className="inline-block bg-amber-50 text-amber-700 border border-amber-200 px-2 py-0.5 rounded font-bold text-[11px]">
                          {ad.deal_count} học viên
                        </span>
                      ) : (
                        <span className="text-slate-300">-</span>
                      )}
                    </td>
                    <td className="py-3 px-4 text-center">
                      <button
                        onClick={() => {
                          navigator.clipboard.writeText(ad.ad_id);
                          setCopiedAdId(ad.ad_id);
                          setTimeout(() => setCopiedAdId(null), 1500);
                        }}
                        className="inline-flex items-center gap-1 px-2 py-1 bg-slate-100 hover:bg-slate-200 text-slate-700 rounded text-[11px] font-medium transition-colors cursor-pointer"
                        title="Copy Ad ID"
                      >
                        {copiedAdId === ad.ad_id ? (
                          <>
                            <Check className="w-3 h-3 text-emerald-600" />
                            <span className="text-emerald-600 font-semibold">Đã copy</span>
                          </>
                        ) : (
                          <>
                            <Copy className="w-3 h-3 text-slate-400" />
                            <span>Copy ID</span>
                          </>
                        )}
                      </button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>

        {filteredAds.length > adLimit && (
          <div className="p-3 bg-slate-50/50 border-t border-slate-100 text-center">
            <button
              onClick={() => setAdLimit(prev => prev + 20)}
              className="text-xs font-semibold text-purple-700 hover:text-purple-800 transition-colors cursor-pointer"
            >
              Xem thêm {filteredAds.length - adLimit} mẫu Ads khác...
            </button>
          </div>
        )}
      </div>

      {/* 5. Bảng Top Bài viết Facebook Hiệu quả nhất */}
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
                      return <FileText className="w-3.5 h-3.5 text-eztech" />;
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

                    {/* Cột Link Facebook */}
                    <td className="px-5 py-3.5 text-center whitespace-nowrap">
                      {post.post_url ? (
                        <a
                          href={post.post_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="inline-flex items-center gap-1 text-[11px] font-semibold text-eztech hover:text-eztech-hover bg-blue-50/80 hover:bg-blue-100/80 px-2 py-1 rounded-md border border-blue-200/80 transition-colors"
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
    </div>
  );
}
