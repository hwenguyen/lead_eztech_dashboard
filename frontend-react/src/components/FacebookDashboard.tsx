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
  Filter,
  Video,
  Image as ImageIcon,
  FileText,
  Radio,
} from 'lucide-react';
import {
  ResponsiveContainer,
  AreaChart,
  Area,
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
    try {
      const res = await fetchFacebookMetrics(startDate, endDate, pageId || undefined);
      setData(res);
      setLastRefreshed(new Date());
    } catch (err) {
      console.error('Lỗi khi tải dữ liệu Facebook metrics:', err);
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

  return (
    <div className="space-y-5 animate-in fade-in duration-300">
      {/* 1. Header & Bộ lọc thiết kế lại chuẩn mực */}
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
                Hiệu quả bài viết, tương tác, Lead, SĐT thu được và Deal chốt từ Facebook
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

        {/* Filter Toolbar: Phân bổ hợp lý, rõ ràng, không bị co ép */}
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

      {/* 2. Hàng 5 Thẻ KPI Tóm tắt */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-3.5">
        {/* Card 1: Bài viết & Đăng tải */}
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

        {/* Card 4: Lead & SĐT thu được */}
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

      {/* 5. Phân bổ Nhân viên & Tag Facebook */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Nhân viên phụ trách Lead Facebook */}
        <div className="bg-white rounded-xl border border-slate-200/80 p-5 shadow-card">
          <div className="flex items-center justify-between mb-4">
            <div>
              <h3 className="text-sm font-bold text-navy">Phân bổ Nhân viên chăm sóc Facebook</h3>
              <p className="text-xs text-slate-500 mt-0.5">Số lượng khách hàng từ Facebook được giao phụ trách</p>
            </div>
            <Users className="w-4 h-4 text-slate-400" />
          </div>

          <div className="space-y-2.5">
            {Object.entries(data?.employee_stats || {}).map(([emp, count]) => {
              const total = data?.summary.total_leads || 1;
              const pct = Math.round((count / total) * 100);
              return (
                <div key={emp} className="space-y-1">
                  <div className="flex items-center justify-between text-xs">
                    <span className="font-medium text-navy">{emp}</span>
                    <span className="font-mono text-slate-500 tabular-nums">
                      {count} ({pct}%)
                    </span>
                  </div>
                  <div className="h-1.5 w-full bg-slate-100 rounded-full overflow-hidden">
                    <div
                      className="h-full bg-eztech rounded-full transition-all duration-500"
                      style={{ width: `${Math.min(pct, 100)}%` }}
                    />
                  </div>
                </div>
              );
            })}
            {Object.keys(data?.employee_stats || {}).length === 0 && (
              <p className="text-xs text-slate-400 italic py-4 text-center">Chưa có phân bổ nhân viên</p>
            )}
          </div>
        </div>

        {/* Thống kê Thẻ / Tag từ Facebook */}
        <div className="bg-white rounded-xl border border-slate-200/80 p-5 shadow-card">
          <div className="flex items-center justify-between mb-4">
            <div>
              <h3 className="text-sm font-bold text-navy">Top Thẻ phân loại Lead Facebook</h3>
              <p className="text-xs text-slate-500 mt-0.5">Các tag gắn nhiều nhất trên khách hàng nguồn Facebook</p>
            </div>
            <Filter className="w-4 h-4 text-slate-400" />
          </div>

          <div className="flex flex-wrap gap-2">
            {Object.entries(data?.tag_stats || {}).map(([tag, count]) => (
              <span
                key={tag}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-slate-50 border border-slate-200 text-slate-700 hover:border-blue-300 hover:bg-blue-50/50 transition-colors"
              >
                <span className="w-2 h-2 rounded-full bg-blue-500" />
                <span>{tag}</span>
                <span className="font-mono font-bold text-navy bg-white px-1.5 py-0.2 rounded border border-slate-200 text-[10px]">
                  {count}
                </span>
              </span>
            ))}
            {Object.keys(data?.tag_stats || {}).length === 0 && (
              <p className="text-xs text-slate-400 italic py-4 text-center">Chưa có thẻ phân loại</p>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
