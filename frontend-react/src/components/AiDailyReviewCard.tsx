import React, { useEffect, useState, useRef } from 'react';
import {
  Sparkles,
  RefreshCw,
  TrendingUp,
  Users,
  ShieldAlert,
  Target,
  Lightbulb,
  ChevronDown,
  ChevronUp,
  Clock,
  AlertCircle,
} from 'lucide-react';
import {
  fetchAiDailyReview,
  refreshAiDailyReview,
  type AiDailyReviewChannel,
  type AiDailyReviewData,
} from '../services/api';

const renderInlineBold = (text: string): React.ReactNode[] => {
  const parts = text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g);
  return parts.map((part, idx) => {
    if (part.startsWith('**') && part.endsWith('**') && part.length > 4) {
      return (
        <strong key={idx} className="font-semibold text-navy">
          {part.slice(2, -2)}
        </strong>
      );
    }
    if (part.startsWith('`') && part.endsWith('`') && part.length > 2) {
      return (
        <code key={idx} className="px-1 py-0.5 rounded bg-slate-100 text-[11px] font-mono text-navy">
          {part.slice(1, -1)}
        </code>
      );
    }
    return <React.Fragment key={idx}>{part}</React.Fragment>;
  });
};

interface AiDailyReviewCardProps {
  channel?: AiDailyReviewChannel;
}

const CHANNEL_META: Record<
  AiDailyReviewChannel,
  {
    title: string;
    busyText: string;
    refreshTitle: string;
    iconBgClass: string;
    headerGradientClass: string;
  }
> = {
  overview: {
    title: 'AI Đánh Giá Hiệu Suất & Insight Hằng Ngày',
    busyText:
      'AI đang thu thập thông số từ các Dashboard (Tổng quan, Facebook, TikTok, Remind SLA, Deal Win) và phân tích cho hôm nay...',
    refreshTitle: 'Gửi toàn bộ thông số Dashboard qua Gemini AI đánh giá lại ngay',
    iconBgClass: 'gradient-brand text-white',
    headerGradientClass: 'from-brand-50/60 via-white to-gold-light/30',
  },
  facebook: {
    title: 'AI Đánh Giá Hiệu Suất & Gợi Ý Kênh Facebook Hằng Ngày',
    busyText:
      'AI đang phân tích dữ liệu Fanpage, Top bài viết, Facebook Ads và khung giờ đăng bài 0h–23h cho hôm nay...',
    refreshTitle: 'Gửi dữ liệu kênh Facebook qua Gemini AI đánh giá & gợi ý lại ngay',
    iconBgClass: 'bg-gradient-to-br from-[#1877F2] to-indigo-600 text-white',
    headerGradientClass: 'from-blue-50/70 via-white to-indigo-50/30',
  },
  tiktok: {
    title: 'AI Đánh Giá Hiệu Suất & Gợi Ý Kênh TikTok Hằng Ngày',
    busyText:
      'AI đang phân tích dữ liệu 5 kênh TikTok, Top video, lượt xem theo khung giờ 0h–23h và tỷ lệ ra SĐT cho hôm nay...',
    refreshTitle: 'Gửi dữ liệu kênh TikTok qua Gemini AI đánh giá & gợi ý lại ngay',
    iconBgClass: 'bg-gradient-to-br from-slate-900 to-slate-700 text-white',
    headerGradientClass: 'from-slate-100/70 via-white to-blue-50/30',
  },
};

export const AiDailyReviewCard: React.FC<AiDailyReviewCardProps> = ({ channel = 'overview' }) => {
  const [review, setReview] = useState<AiDailyReviewData | null>(null);
  const [isToday, setIsToday] = useState<boolean>(false);
  const [generating, setGenerating] = useState<boolean>(false);
  const [loading, setLoading] = useState<boolean>(true);
  const [refreshing, setRefreshing] = useState<boolean>(false);
  const [errorMsg, setErrorMsg] = useState<string>('');
  const [expanded, setExpanded] = useState<boolean>(true);
  const pollTimerRef = useRef<number | null>(null);

  const meta = CHANNEL_META[channel];

  const clearPoll = () => {
    if (pollTimerRef.current !== null) {
      window.clearTimeout(pollTimerRef.current);
      pollTimerRef.current = null;
    }
  };

  const loadReview = async (pollAttempt = 0) => {
    try {
      const res = await fetchAiDailyReview(channel);
      setReview(res.review);
      setIsToday(res.is_today);
      setGenerating(res.generating);
      setErrorMsg('');

      if (res.generating && !res.is_today && pollAttempt < 15) {
        clearPoll();
        pollTimerRef.current = window.setTimeout(() => {
          loadReview(pollAttempt + 1);
        }, 3000);
      }
    } catch (err: any) {
      setErrorMsg(err?.response?.data?.detail || 'Không thể tải báo cáo AI Đánh giá lúc này.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    setLoading(true);
    loadReview(0);
    return () => clearPoll();
  }, [channel]);

  const handleManualRefresh = async () => {
    clearPoll();
    setRefreshing(true);
    setErrorMsg('');
    try {
      const res = await refreshAiDailyReview(channel);
      setReview(res.review);
      setIsToday(res.is_today);
      setGenerating(false);
      setExpanded(true);
    } catch (err: any) {
      setErrorMsg(err?.response?.data?.detail || 'Lỗi khi chạy AI Đánh giá. Vui lòng thử lại sau ít giây.');
    } finally {
      setRefreshing(false);
    }
  };

  const isBusy = refreshing || generating;

  return (
    <section className="bg-white rounded-2xl border border-slate-200/80 shadow-card overflow-hidden">
      {/* Header */}
      <div className={`px-5 py-3.5 border-b border-slate-100 flex flex-wrap items-center justify-between gap-3 bg-gradient-to-r ${meta.headerGradientClass}`}>
        <div className="flex items-center gap-3 min-w-0">
          <div className={`w-9 h-9 rounded-xl ${meta.iconBgClass} flex items-center justify-center shadow-sm shrink-0`}>
            <Sparkles className="w-4 h-4 text-gold-400" />
          </div>
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="text-sm font-bold text-navy tracking-tight">
                {meta.title}
              </h3>
              {isBusy && (
                <span className="inline-flex items-center gap-1 text-[11px] font-medium text-brand-600">
                  <RefreshCw className="w-3 h-3 animate-spin" />
                  Đang tổng hợp thông số &amp; phân tích...
                </span>
              )}
            </div>
            <div className="flex flex-wrap items-center gap-2 text-[11px] text-slate-500 mt-0.5">
              <span className="inline-flex items-center gap-1">
                <Clock className="w-3 h-3 text-slate-400" />
                {review ? `Cập nhật ${review.generated_at}` : 'Tự động cập nhật mỗi ngày'}
              </span>
              {review?.period_label && (
                <span className="text-slate-400">• {review.period_label}</span>
              )}
              {review && !isToday && !isBusy && (
                <span className="text-amber-600 font-medium">(Bản ngày {review.date})</span>
              )}
            </div>
          </div>
        </div>

        <div className="flex items-center gap-2 shrink-0">
          <button
            type="button"
            onClick={handleManualRefresh}
            disabled={isBusy}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-semibold bg-white hover:bg-brand-50 text-navy hover:text-brand-600 border border-slate-200/90 hover:border-brand-300 shadow-sm transition-all disabled:opacity-50 cursor-pointer"
            title={meta.refreshTitle}
          >
            <RefreshCw className={`w-3.5 h-3.5 text-brand-500 ${isBusy ? 'animate-spin' : ''}`} />
            <span>{refreshing ? 'Đang đánh giá...' : 'Đánh giá lại'}</span>
          </button>
          <button
            type="button"
            onClick={() => setExpanded(prev => !prev)}
            className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-xl text-xs font-medium text-slate-500 hover:text-navy hover:bg-slate-100 transition-colors cursor-pointer"
            aria-label={expanded ? 'Thu gọn AI Đánh giá' : 'Mở rộng AI Đánh giá'}
          >
            <span>{expanded ? 'Thu gọn' : 'Mở rộng'}</span>
            {expanded ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
          </button>
        </div>
      </div>

      {/* Body */}
      {expanded && (
        <div className="p-5 space-y-4">
          {errorMsg && (
            <div className="flex items-center gap-2 px-3.5 py-2.5 rounded-xl bg-rose-50 border border-rose-200 text-xs text-rose-700">
              <AlertCircle className="w-4 h-4 shrink-0" />
              <span>{errorMsg}</span>
            </div>
          )}

          {loading ? (
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-3.5">
              {[0, 1, 2, 3].map(i => (
                <div key={i} className="rounded-xl border border-slate-100 bg-slate-50/70 p-4 space-y-2.5 animate-pulse">
                  <div className="h-3.5 w-36 bg-slate-200 rounded" />
                  <div className="h-3 w-full bg-slate-200/80 rounded" />
                  <div className="h-3 w-5/6 bg-slate-200/70 rounded" />
                  <div className="h-3 w-4/6 bg-slate-200/60 rounded" />
                </div>
              ))}
            </div>
          ) : !review ? (
            <div className="rounded-xl border border-dashed border-slate-200 bg-slate-50/60 p-6 text-center space-y-2">
              <p className="text-xs font-medium text-slate-600">
                {isBusy
                  ? meta.busyText
                  : 'Chưa có bản AI Đánh giá cho hôm nay. Nhấn "Đánh giá lại" để AI tổng hợp và phân tích ngay.'}
              </p>
            </div>
          ) : (
            <>
              {review.headline && (
                <div className="px-4 py-2.5 rounded-xl bg-slate-50/90 border border-slate-200/70 text-xs sm:text-[13px] text-navy leading-relaxed font-medium">
                  {renderInlineBold(review.headline)}
                </div>
              )}

              {channel === 'overview' ? (
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-3.5">
                  {/* 1. Đánh giá tổng quan */}
                  <div className="rounded-xl border border-slate-200/70 bg-slate-50/40 p-4 space-y-2.5">
                    <div className="flex items-center gap-2">
                      <div className="w-6 h-6 rounded-lg bg-brand-50 text-brand-600 flex items-center justify-center shrink-0">
                        <TrendingUp className="w-3.5 h-3.5" />
                      </div>
                      <h4 className="text-xs font-bold uppercase tracking-wider text-navy">
                        Đánh giá tổng quan
                      </h4>
                    </div>
                    <ul className="space-y-1.5 text-xs text-slate-600 leading-relaxed">
                      {(review.overview || []).map((item, idx) => (
                        <li key={idx} className="flex items-start gap-2">
                          <span className="w-1.5 h-1.5 rounded-full bg-brand-500 mt-1.5 shrink-0" />
                          <span>{renderInlineBold(item)}</span>
                        </li>
                      ))}
                    </ul>
                  </div>

                  {/* 2. Insight khách hàng */}
                  <div className="rounded-xl border border-slate-200/70 bg-slate-50/40 p-4 space-y-2.5">
                    <div className="flex items-center gap-2">
                      <div className="w-6 h-6 rounded-lg bg-amber-50 text-amber-600 flex items-center justify-center shrink-0">
                        <Users className="w-3.5 h-3.5" />
                      </div>
                      <h4 className="text-xs font-bold uppercase tracking-wider text-navy">
                        Insight khách hàng
                      </h4>
                    </div>
                    <ul className="space-y-1.5 text-xs text-slate-600 leading-relaxed">
                      {(review.customer_insight || []).map((item, idx) => (
                        <li key={idx} className="flex items-start gap-2">
                          <span className="w-1.5 h-1.5 rounded-full bg-amber-500 mt-1.5 shrink-0" />
                          <span>{renderInlineBold(item)}</span>
                        </li>
                      ))}
                    </ul>
                  </div>

                  {/* 3. Quy trình & Điểm nghẽn SLA */}
                  <div className="rounded-xl border border-slate-200/70 bg-slate-50/40 p-4 space-y-2.5">
                    <div className="flex items-center gap-2">
                      <div className="w-6 h-6 rounded-lg bg-rose-50 text-rose-600 flex items-center justify-center shrink-0">
                        <ShieldAlert className="w-3.5 h-3.5" />
                      </div>
                      <h4 className="text-xs font-bold uppercase tracking-wider text-navy">
                        Quy trình &amp; Điểm nghẽn SLA
                      </h4>
                    </div>
                    <ul className="space-y-1.5 text-xs text-slate-600 leading-relaxed">
                      {(review.process_sla || []).map((item, idx) => (
                        <li key={idx} className="flex items-start gap-2">
                          <span className="w-1.5 h-1.5 rounded-full bg-rose-500 mt-1.5 shrink-0" />
                          <span>{renderInlineBold(item)}</span>
                        </li>
                      ))}
                    </ul>
                  </div>

                  {/* 4. Hành động cải thiện Performance */}
                  <div className="rounded-xl border border-slate-200/70 bg-slate-50/40 p-4 space-y-2.5">
                    <div className="flex items-center gap-2">
                      <div className="w-6 h-6 rounded-lg bg-emerald-50 text-emerald-600 flex items-center justify-center shrink-0">
                        <Target className="w-3.5 h-3.5" />
                      </div>
                      <h4 className="text-xs font-bold uppercase tracking-wider text-navy">
                        Đề xuất cải thiện Performance
                      </h4>
                    </div>
                    <ol className="space-y-1.5 text-xs text-slate-600 leading-relaxed">
                      {(review.actions || []).map((item, idx) => (
                        <li key={idx} className="flex items-start gap-2">
                          <span className="w-4 h-4 rounded-md bg-emerald-100 text-emerald-700 text-[10px] font-bold flex items-center justify-center mt-0.5 shrink-0">
                            {idx + 1}
                          </span>
                          <span>{renderInlineBold(item)}</span>
                        </li>
                      ))}
                    </ol>
                  </div>
                </div>
              ) : (
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-3.5">
                  {/* 1. Đánh giá hiệu suất kênh */}
                  <div className="rounded-xl border border-slate-200/70 bg-slate-50/40 p-4 space-y-2.5">
                    <div className="flex items-center gap-2">
                      <div className="w-6 h-6 rounded-lg bg-brand-50 text-brand-600 flex items-center justify-center shrink-0">
                        <TrendingUp className="w-3.5 h-3.5" />
                      </div>
                      <h4 className="text-xs font-bold uppercase tracking-wider text-navy">
                        {channel === 'tiktok' ? 'Đánh giá hiệu suất TikTok' : 'Đánh giá hiệu suất Facebook'}
                      </h4>
                    </div>
                    <ul className="space-y-1.5 text-xs text-slate-600 leading-relaxed">
                      {(review.overview || []).map((item, idx) => (
                        <li key={idx} className="flex items-start gap-2">
                          <span className="w-1.5 h-1.5 rounded-full bg-brand-500 mt-1.5 shrink-0" />
                          <span>{renderInlineBold(item)}</span>
                        </li>
                      ))}
                    </ul>
                  </div>

                  {/* 2. Gợi ý bài đăng / video */}
                  <div className="rounded-xl border border-slate-200/70 bg-slate-50/40 p-4 space-y-2.5">
                    <div className="flex items-center gap-2">
                      <div className="w-6 h-6 rounded-lg bg-amber-50 text-amber-600 flex items-center justify-center shrink-0">
                        <Lightbulb className="w-3.5 h-3.5" />
                      </div>
                      <h4 className="text-xs font-bold uppercase tracking-wider text-navy">
                        {channel === 'tiktok' ? 'Gợi ý video & chủ đề nội dung' : 'Gợi ý bài đăng & nội dung'}
                      </h4>
                    </div>
                    <ol className="space-y-1.5 text-xs text-slate-600 leading-relaxed">
                      {(review.post_suggestions || []).map((item, idx) => (
                        <li key={idx} className="flex items-start gap-2">
                          <span className="w-4 h-4 rounded-md bg-amber-100 text-amber-700 text-[10px] font-bold flex items-center justify-center mt-0.5 shrink-0">
                            {idx + 1}
                          </span>
                          <span>{renderInlineBold(item)}</span>
                        </li>
                      ))}
                    </ol>
                  </div>

                  {/* 3. Gợi ý khung giờ đăng tối ưu */}
                  <div className="rounded-xl border border-slate-200/70 bg-slate-50/40 p-4 space-y-2.5">
                    <div className="flex items-center gap-2">
                      <div className="w-6 h-6 rounded-lg bg-violet-50 text-violet-600 flex items-center justify-center shrink-0">
                        <Clock className="w-3.5 h-3.5" />
                      </div>
                      <h4 className="text-xs font-bold uppercase tracking-wider text-navy">
                        {channel === 'tiktok' ? 'Khung giờ đăng tối ưu (0h–23h)' : 'Khung giờ đăng bài tối ưu'}
                      </h4>
                    </div>
                    <ul className="space-y-1.5 text-xs text-slate-600 leading-relaxed">
                      {(review.best_times || []).map((item, idx) => (
                        <li key={idx} className="flex items-start gap-2">
                          <span className="w-1.5 h-1.5 rounded-full bg-violet-500 mt-1.5 shrink-0" />
                          <span>{renderInlineBold(item)}</span>
                        </li>
                      ))}
                    </ul>
                  </div>

                  {/* 4. Insight kênh & Hành động hôm nay */}
                  <div className="rounded-xl border border-slate-200/70 bg-slate-50/40 p-4 space-y-2.5">
                    <div className="flex items-center gap-2">
                      <div className="w-6 h-6 rounded-lg bg-emerald-50 text-emerald-600 flex items-center justify-center shrink-0">
                        <Target className="w-3.5 h-3.5" />
                      </div>
                      <h4 className="text-xs font-bold uppercase tracking-wider text-navy">
                        Insight kênh &amp; Hành động ưu tiên
                      </h4>
                    </div>
                    <ul className="space-y-1.5 text-xs text-slate-600 leading-relaxed">
                      {(review.channel_insights || []).map((item, idx) => (
                        <li key={idx} className="flex items-start gap-2">
                          <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 mt-1.5 shrink-0" />
                          <span>{renderInlineBold(item)}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      )}
    </section>
  );
};
