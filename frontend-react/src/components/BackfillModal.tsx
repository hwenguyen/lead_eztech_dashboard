import React, { useState, useEffect, useRef } from 'react';
import {
  X,
  Play,
  Square,
  RefreshCw,
  History,
  AlertCircle,
  Database,
} from 'lucide-react';
import {
  fetchBackfillStatus,
  startBackfill,
  stopBackfill,
  type BackfillStatusResponse,
} from '../services/api';

interface BackfillModalProps {
  isOpen: boolean;
  onClose: () => void;
  pagesList?: string[];
}

export function BackfillModal({ isOpen, onClose, pagesList = [] }: BackfillModalProps) {
  const [status, setStatus] = useState<BackfillStatusResponse | null>(null);
  const [actionLoading, setActionLoading] = useState(false);
  const [selectedPage, setSelectedPage] = useState<string>('');
  const [limit, setLimit] = useState<number>(3000);
  const [stopDate, setStopDate] = useState<string>('2024-01-01');
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const logEndRef = useRef<HTMLDivElement>(null);

  const pollStatus = async () => {
    try {
      const data = await fetchBackfillStatus();
      setStatus(data);
      if (data.error) {
        setErrorMsg(data.error);
      }
    } catch (err: any) {
      console.error('Lỗi lấy trạng thái Backfill:', err);
    }
  };

  useEffect(() => {
    if (!isOpen) return;
    pollStatus();

    // Polling định kỳ mỗi 2 giây
    const timer = setInterval(() => {
      pollStatus();
    }, 2500);

    return () => clearInterval(timer);
  }, [isOpen]);

  useEffect(() => {
    if (logEndRef.current) {
      logEndRef.current.scrollTop = logEndRef.current.scrollHeight;
    }
  }, [status?.logs]);

  const handleStart = async (e: React.FormEvent) => {
    e.preventDefault();
    setActionLoading(true);
    setErrorMsg(null);
    try {
      await startBackfill({
        page: selectedPage || undefined,
        limit: Number(limit) || 2000,
        chunk: 120,
        stop_date: stopDate || '2024-01-01',
      });
      await pollStatus();
    } catch (err: any) {
      setErrorMsg(err?.response?.data?.detail || 'Không thể khởi động tiến trình cào dữ liệu.');
    } finally {
      setActionLoading(false);
    }
  };

  const handleStop = async () => {
    if (!confirm('Bạn có chắc muốn dừng tiến trình cào dữ liệu lịch sử? (Dữ liệu đã cào đến mốc hiện tại vẫn được giữ nguyên)')) {
      return;
    }
    setActionLoading(true);
    try {
      await stopBackfill();
      await pollStatus();
    } catch (err: any) {
      console.error('Lỗi dừng Backfill:', err);
    } finally {
      setActionLoading(false);
    }
  };

  if (!isOpen) return null;

  const isRunning = Boolean(status?.isRunning);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-3 sm:p-4 bg-navy/60 backdrop-blur-xs animate-in fade-in duration-200">
      <div className="relative w-full max-w-2xl bg-white rounded-2xl shadow-2xl border border-slate-200 overflow-hidden flex flex-col max-h-[92vh]">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-slate-100 bg-slate-50/70">
          <div className="flex items-center gap-2.5">
            <div className="w-9 h-9 rounded-xl bg-amber-500/10 text-amber-600 flex items-center justify-center">
              <History className="w-5 h-5" />
            </div>
            <div>
              <h3 className="text-sm font-bold text-navy flex items-center gap-2">
                Cào Vét Dữ Liệu Lịch Sử (Backfill)
                {isRunning && (
                  <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold bg-emerald-100 text-emerald-800 animate-pulse">
                    <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
                    Đang cào dữ liệu...
                  </span>
                )}
              </h3>
              <p className="text-[11px] text-slate-500">
                Tự động tìm mốc cũ nhất trong DB và lùi tiếp về quá khứ qua Pancake API
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="p-1.5 text-slate-400 hover:text-slate-600 rounded-lg hover:bg-slate-100 transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Content Body */}
        <div className="p-5 overflow-y-auto space-y-4 text-xs">
          {errorMsg && (
            <div className="p-3 bg-rose-50 border border-rose-200 text-rose-700 rounded-xl flex items-start gap-2">
              <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
              <span>{errorMsg}</span>
            </div>
          )}

          {/* Running Progress Card */}
          {isRunning ? (
            <div className="p-4 bg-gradient-to-br from-amber-50/80 to-blue-50/80 border border-amber-200/80 rounded-xl space-y-3">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <RefreshCw className="w-4 h-4 text-amber-600 animate-spin" />
                  <span className="font-bold text-navy text-xs">
                    {status?.currentPage || 'Đang kết nối...'}
                  </span>
                </div>
                <button
                  type="button"
                  onClick={handleStop}
                  disabled={actionLoading}
                  className="flex items-center gap-1.5 px-3 py-1.5 bg-rose-600 hover:bg-rose-700 text-white rounded-lg font-semibold text-xs transition-colors shadow-xs"
                >
                  <Square className="w-3 h-3 fill-white" />
                  Dừng cào
                </button>
              </div>

              <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 pt-1 text-[11px]">
                <div className="bg-white/80 p-2 rounded-lg border border-slate-200/60">
                  <span className="text-slate-500 block text-[10px]">Đã cào thêm</span>
                  <span className="font-bold text-navy font-mono text-sm">
                    {status?.totalAdded?.toLocaleString() || 0} hội thoại
                  </span>
                </div>
                <div className="bg-white/80 p-2 rounded-lg border border-slate-200/60">
                  <span className="text-slate-500 block text-[10px]">Mốc thời gian đạt đến</span>
                  <span className="font-semibold text-amber-700 font-mono">
                    {status?.currentDate || '—'}
                  </span>
                </div>
                <div className="bg-white/80 p-2 rounded-lg border border-slate-200/60 col-span-2 sm:col-span-1">
                  <span className="text-slate-500 block text-[10px]">Thời gian bắt đầu</span>
                  <span className="font-mono text-slate-700">
                    {status?.startedAt?.slice(11) || '—'}
                  </span>
                </div>
              </div>
            </div>
          ) : (
            <form onSubmit={handleStart} className="space-y-3.5 bg-slate-50/70 p-4 rounded-xl border border-slate-200/80">
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                {/* Chọn Page */}
                <div className="sm:col-span-3">
                  <label className="block font-semibold text-navy mb-1 text-[11px]">
                    Chọn Page cần cào lịch sử
                  </label>
                  <select
                    value={selectedPage}
                    onChange={(e) => setSelectedPage(e.target.value)}
                    className="w-full px-3 py-2 border border-slate-200 rounded-lg bg-white text-navy focus:outline-none focus:border-eztech"
                  >
                    <option value="">⚡ Tất cả các Page (Tự động ưu tiên page thiếu dữ liệu trước)</option>
                    {pagesList.map((p) => (
                      <option key={p} value={p}>{p}</option>
                    ))}
                  </select>
                </div>

                {/* Giới hạn số hội thoại */}
                <div>
                  <label className="block font-semibold text-navy mb-1 text-[11px]">
                    Số hội thoại tối đa / Page
                  </label>
                  <select
                    value={limit}
                    onChange={(e) => setLimit(Number(e.target.value))}
                    className="w-full px-3 py-2 border border-slate-200 rounded-lg bg-white text-navy focus:outline-none focus:border-eztech"
                  >
                    <option value={500}>500 hội thoại (~1 tháng)</option>
                    <option value={1000}>1.000 hội thoại (~2-3 tháng)</option>
                    <option value={2000}>2.000 hội thoại (~4-6 tháng)</option>
                    <option value={3000}>3.000 hội thoại (Khuyên dùng)</option>
                    <option value={5000}>5.000 hội thoại (Sâu nhất)</option>
                  </select>
                </div>

                {/* Dừng trước ngày */}
                <div>
                  <label className="block font-semibold text-navy mb-1 text-[11px]">
                    Dừng khi chạm ngày
                  </label>
                  <input
                    type="date"
                    value={stopDate}
                    onChange={(e) => setStopDate(e.target.value)}
                    className="w-full px-3 py-2 border border-slate-200 rounded-lg bg-white text-navy font-mono focus:outline-none focus:border-eztech"
                  />
                </div>

                {/* Submit button */}
                <div className="flex items-end">
                  <button
                    type="submit"
                    disabled={actionLoading}
                    className="w-full py-2 px-3 bg-amber-600 hover:bg-amber-700 text-white font-semibold rounded-lg flex items-center justify-center gap-1.5 transition-colors shadow-xs cursor-pointer"
                  >
                    <Play className="w-3.5 h-3.5 fill-white" />
                    Bắt đầu cào
                  </button>
                </div>
              </div>
            </form>
          )}

          {/* Terminal Logs Box */}
          <div>
            <div className="flex items-center justify-between mb-1.5">
              <span className="font-semibold text-navy text-[11px] flex items-center gap-1.5">
                <Database className="w-3.5 h-3.5 text-slate-400" />
                Nhật ký tiến trình cào dữ liệu
              </span>
              <button
                type="button"
                onClick={pollStatus}
                className="text-[10px] text-eztech hover:underline flex items-center gap-1"
              >
                <RefreshCw className="w-2.5 h-2.5" /> Làm mới log
              </button>
            </div>

            <div
              ref={logEndRef}
              className="w-full h-44 bg-slate-900 text-slate-200 p-3 rounded-xl font-mono text-[10.5px] overflow-y-auto space-y-1 select-text border border-slate-800 shadow-inner"
            >
              {status?.logs && status.logs.length > 0 ? (
                status.logs.map((line, idx) => (
                  <div key={idx} className="leading-relaxed hover:bg-slate-800/50 px-1 rounded">
                    {line}
                  </div>
                ))
              ) : (
                <div className="text-slate-500 py-3 text-center">Chưa có nhật ký cào dữ liệu gần đây.</div>
              )}
            </div>
          </div>
        </div>

        {/* Footer */}
        <div className="px-5 py-3 border-t border-slate-100 bg-slate-50/50 flex items-center justify-between">
          <span className="text-[11px] text-slate-400">
            * Dữ liệu cào về tự động ghi thẳng vào Postgres và map ngược sang bảng Deal Win.
          </span>
          <button
            type="button"
            onClick={onClose}
            className="px-4 py-1.5 text-xs font-semibold bg-white border border-slate-200 text-slate-700 hover:bg-slate-50 rounded-lg transition-colors cursor-pointer"
          >
            Đóng
          </button>
        </div>
      </div>
    </div>
  );
}
