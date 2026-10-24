import { useState, useEffect } from 'react';
import { format } from 'date-fns';
import {
  Clock,
  Search,
  ArrowUpDown,
  Phone,
  Copy,
  Check,
  Calendar,
  AlertTriangle,
  Flame,
  CheckCircle2,
  RefreshCw,
  ExternalLink
} from 'lucide-react';
import {
  fetchRemindLeads,
  type RemindLeadItem,
  type RemindSummary
} from '../services/api';

interface RemindLeadTableProps {
  pagesList: string[];
  zaloPages: string[];
}

export function RemindLeadTable({ pagesList, zaloPages }: RemindLeadTableProps) {
  const [employee, setEmployee] = useState('');
  const [pageId, setPageId] = useState('');
  const [tag, setTag] = useState('all');
  const [search, setSearch] = useState('');
  const [daysBucket, setDaysBucket] = useState('all');
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('asc');
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);

  const [items, setItems] = useState<RemindLeadItem[]>([]);
  const [total, setTotal] = useState(0);
  const [totalPages, setTotalPages] = useState(1);
  const [summary, setSummary] = useState<RemindSummary | null>(null);
  const [employeesList, setEmployeesList] = useState<string[]>([]);
  const [tagsList, setTagsList] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [copiedPhone, setCopiedPhone] = useState<string | null>(null);

  const loadData = async () => {
    setLoading(true);
    try {
      const res = await fetchRemindLeads(
        employee || undefined,
        pageId || undefined,
        tag || undefined,
        search || undefined,
        daysBucket,
        sortOrder,
        page,
        pageSize
      );
      setItems(res.items);
      setTotal(res.total);
      setTotalPages(res.total_pages);
      setSummary(res.summary);
      if (res.employees && res.employees.length > 0) {
        setEmployeesList(res.employees);
      }
      if (res.tags && res.tags.length > 0) {
        setTagsList(res.tags);
      }
    } catch (err) {
      console.error('Error fetching remind leads:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, [employee, pageId, tag, search, daysBucket, sortOrder, page, pageSize]);

  const handleFilterChange = (setter: (val: any) => void, val: any) => {
    setter(val);
    setPage(1);
  };

  const handleCopy = (text: string) => {
    navigator.clipboard.writeText(text);
    setCopiedPhone(text);
    setTimeout(() => setCopiedPhone(null), 2000);
  };

  const formatContactedDate = (dtStr: string | null) => {
    if (!dtStr) return 'Chưa rõ';
    try {
      const d = new Date(dtStr);
      if (!isNaN(d.getTime())) {
        return format(d, 'dd/MM/yyyy HH:mm');
      }
    } catch (_) {}
    return dtStr;
  };

  const getDaysBadge = (daysFloat: number, daysInt: number) => {
    if (daysInt === 0) {
      const hours = Math.round(daysFloat * 24);
      return {
        label: `Hôm nay (${hours}h)`,
        bg: 'bg-emerald-50/80 text-emerald-700 border-emerald-200/70',
        dot: 'bg-emerald-500'
      };
    }
    if (daysInt <= 3) {
      return {
        label: `${daysFloat} ngày`,
        bg: 'bg-gold-light text-gold-dark border-gold-border/80',
        dot: 'bg-gold'
      };
    }
    if (daysInt <= 7) {
      return {
        label: `${daysFloat} ngày`,
        bg: 'bg-orange-50/80 text-orange-700 border-orange-200/70',
        dot: 'bg-orange-500'
      };
    }
    return {
      label: `${daysFloat} ngày (Quá hạn)`,
      bg: 'bg-rose-50/80 text-rose-700 border-rose-200/70',
      dot: 'bg-rose-500'
    };
  };

  return (
    <div className="space-y-4">
      {/* Cards thống kê nhanh Remind */}
      <div className="grid grid-cols-2 sm:grid-cols-2 lg:grid-cols-5 gap-3.5">
        <div
          onClick={() => handleFilterChange(setDaysBucket, 'all')}
          className={`cursor-pointer bg-white p-4 rounded-xl border transition-all shadow-card hover:shadow-card-hover ${
            daysBucket === 'all' ? 'border-eztech ring-2 ring-eztech/10' : 'border-slate-200/80'
          }`}
        >
          <div className="flex items-center justify-between">
            <span className="text-[11px] font-semibold uppercase tracking-[0.05em] text-slate-500">Tổng Remind</span>
            <span className="p-1.5 rounded-lg bg-eztech-light text-eztech">
              <Clock className="w-4 h-4" />
            </span>
          </div>
          <div className="text-2xl font-bold text-navy mt-2 tabular-nums">
            {(summary?.total || 0).toLocaleString()}
          </div>
          <div className="text-[11px] text-slate-400 mt-1">Tất cả lead đang lọc</div>
        </div>

        <div
          onClick={() => handleFilterChange(setDaysBucket, 'today')}
          className={`cursor-pointer bg-white p-4 rounded-xl border transition-all shadow-card hover:shadow-card-hover ${
            daysBucket === 'today' ? 'border-emerald-500 ring-2 ring-emerald-500/10' : 'border-slate-200/80'
          }`}
        >
          <div className="flex items-center justify-between">
            <span className="text-[11px] font-semibold uppercase tracking-[0.05em] text-slate-500">Hôm nay</span>
            <span className="p-1.5 rounded-lg bg-emerald-50 text-emerald-600">
              <CheckCircle2 className="w-4 h-4" />
            </span>
          </div>
          <div className="text-2xl font-bold text-navy mt-2 tabular-nums">
            {(summary?.under_1_day || 0).toLocaleString()}
          </div>
          <div className="text-[11px] text-emerald-600 mt-1 flex items-center gap-1.5">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
            Mới tương tác &lt; 24h
          </div>
        </div>

        <div
          onClick={() => handleFilterChange(setDaysBucket, '1_to_3')}
          className={`cursor-pointer bg-white p-4 rounded-xl border transition-all shadow-card hover:shadow-card-hover ${
            daysBucket === '1_to_3' ? 'border-gold ring-2 ring-gold/15' : 'border-slate-200/80'
          }`}
        >
          <div className="flex items-center justify-between">
            <span className="text-[11px] font-semibold uppercase tracking-[0.05em] text-slate-500">1 – 3 ngày</span>
            <span className="p-1.5 rounded-lg bg-gold-light text-gold-dark">
              <Calendar className="w-4 h-4" />
            </span>
          </div>
          <div className="text-2xl font-bold text-navy mt-2 tabular-nums">
            {(summary?.days_1_to_3 || 0).toLocaleString()}
          </div>
          <div className="text-[11px] text-gold-dark mt-1 flex items-center gap-1.5">
            <span className="w-1.5 h-1.5 rounded-full bg-gold" />
            1 - 3 ngày chưa chat
          </div>
        </div>

        <div
          onClick={() => handleFilterChange(setDaysBucket, '3_to_7')}
          className={`cursor-pointer bg-white p-4 rounded-xl border transition-all shadow-card hover:shadow-card-hover ${
            daysBucket === '3_to_7' ? 'border-orange-500 ring-2 ring-orange-500/10' : 'border-slate-200/80'
          }`}
        >
          <div className="flex items-center justify-between">
            <span className="text-[11px] font-semibold uppercase tracking-[0.05em] text-slate-500">3 – 7 ngày</span>
            <span className="p-1.5 rounded-lg bg-orange-50 text-orange-600">
              <AlertTriangle className="w-4 h-4" />
            </span>
          </div>
          <div className="text-2xl font-bold text-navy mt-2 tabular-nums">
            {(summary?.days_3_to_7 || 0).toLocaleString()}
          </div>
          <div className="text-[11px] text-orange-600 mt-1 flex items-center gap-1.5">
            <span className="w-1.5 h-1.5 rounded-full bg-orange-500" />
            Cần nhắc lịch sớm
          </div>
        </div>

        <div
          onClick={() => handleFilterChange(setDaysBucket, 'over_7')}
          className={`cursor-pointer bg-white p-4 rounded-xl border transition-all shadow-card hover:shadow-card-hover ${
            daysBucket === 'over_7' ? 'border-rose-500 ring-2 ring-rose-500/10' : 'border-slate-200/80'
          }`}
        >
          <div className="flex items-center justify-between">
            <span className="text-[11px] font-semibold uppercase tracking-[0.05em] text-slate-500">&gt; 7 ngày</span>
            <span className="p-1.5 rounded-lg bg-rose-50 text-rose-600">
              <Flame className="w-4 h-4" />
            </span>
          </div>
          <div className="text-2xl font-bold text-navy mt-2 tabular-nums">
            {(summary?.over_7_days || 0).toLocaleString()}
          </div>
          <div className="text-[11px] text-rose-600 mt-1 flex items-center gap-1.5">
            <span className="w-1.5 h-1.5 rounded-full bg-rose-500" />
            Quá 1 tuần chưa chăm sóc
          </div>
        </div>
      </div>

      {/* Bộ lọc bảng Remind */}
      <div className="bg-white rounded-xl border border-slate-200/80 shadow-card p-4 space-y-3.5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-[15px] font-semibold text-navy tracking-[-0.01em]">
              {tag === 'remind'
                ? 'Danh sách Remind Lead (Thẻ Remind)'
                : tag === 'all'
                ? 'Danh sách Chăm Sóc Lead (Toàn Bộ)'
                : `Danh sách Chăm Sóc Lead (${tag})`}
            </h2>
            <p className="text-xs text-slate-500 mt-0.5">
              Theo dõi tiến độ tương tác và khoảng cách thời gian từ tin nhắn cuối cùng
            </p>
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={() => handleFilterChange(setSortOrder, sortOrder === 'asc' ? 'desc' : 'asc')}
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg border border-slate-200/90 hover:bg-slate-50 text-navy transition-colors"
              title="Nhấn để đổi chiều sắp xếp"
            >
              <ArrowUpDown className="w-3.5 h-3.5 text-eztech" />
              <span>
                {sortOrder === 'asc' ? 'Gần nhất → Xa nhất' : 'Xa nhất → Gần nhất'}
              </span>
            </button>

            <button
              onClick={loadData}
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-eztech bg-eztech-light hover:bg-eztech-border/50 rounded-lg transition-colors"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
              Làm mới
            </button>
          </div>
        </div>

        {/* Filter Controls Row */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 pt-3 border-t border-slate-100">
          <div className="flex flex-col gap-1">
            <label className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">Nhân Viên Phụ Trách</label>
            <select
              value={employee}
              onChange={e => handleFilterChange(setEmployee, e.target.value)}
              className="px-3 py-1.5 border border-slate-200/90 rounded-lg text-xs font-medium bg-white focus:outline-none focus:ring-2 focus:ring-eztech/15 focus:border-eztech transition-all text-navy cursor-pointer"
            >
              <option value="">Tất cả nhân viên</option>
              {employeesList.map(emp => (
                <option key={emp} value={emp}>{emp}</option>
              ))}
            </select>
          </div>

          <div className="flex flex-col gap-1">
            <label className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">Page Nguồn Lead</label>
            <select
              value={pageId}
              onChange={e => handleFilterChange(setPageId, e.target.value)}
              className="px-3 py-1.5 border border-slate-200/90 rounded-lg text-xs font-medium bg-white focus:outline-none focus:ring-2 focus:ring-eztech/15 focus:border-eztech transition-all text-navy cursor-pointer"
            >
              <option value="">Tất cả Page</option>
              <optgroup label="Nguồn lead">
                {pagesList
                  .filter(pg => !zaloPages.includes(pg))
                  .map(pg => (
                    <option key={pg} value={pg}>{pg}</option>
                  ))}
              </optgroup>
              {zaloPages.length > 0 && (
                <optgroup label="Zalo (chăm sóc)">
                  {zaloPages.map(pg => (
                    <option key={pg} value={pg}>{pg}</option>
                  ))}
                </optgroup>
              )}
            </select>
          </div>

          <div className="flex flex-col gap-1">
            <label className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">Thẻ Phân Loại (Tag)</label>
            <select
              value={tag}
              onChange={e => handleFilterChange(setTag, e.target.value)}
              className="px-3 py-1.5 border border-slate-200/90 rounded-lg text-xs font-medium bg-white focus:outline-none focus:ring-2 focus:ring-eztech/15 focus:border-eztech transition-all text-navy cursor-pointer"
            >
              <option value="all">Tất cả thẻ (Mọi Lead)</option>
              <option value="remind">⭐ Chỉ tag Remind</option>
              {tagsList
                .filter(t => t.toLowerCase() !== 'remind')
                .map((t, idx) => (
                  <option key={idx} value={t}>{t}</option>
                ))}
            </select>
          </div>

          <div className="flex flex-col gap-1">
            <label className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">Tìm Tên / Số Điện Thoại</label>
            <div className="relative">
              <Search className="w-3.5 h-3.5 text-slate-400 absolute left-3 top-2" />
              <input
                type="text"
                placeholder="Nhập tên hoặc SĐT..."
                value={search}
                onChange={e => handleFilterChange(setSearch, e.target.value)}
                className="w-full pl-8 pr-3 py-1.5 border border-slate-200/90 rounded-lg text-xs bg-white focus:outline-none focus:ring-2 focus:ring-eztech/15 focus:border-eztech transition-all text-navy"
              />
            </div>
          </div>
        </div>
      </div>

      {/* Bảng Dữ Liệu Remind */}
      <div className="bg-white rounded-xl border border-slate-200/80 shadow-card overflow-hidden">
        {loading ? (
          <div className="flex flex-col items-center justify-center py-20 gap-3">
            <div className="animate-spin rounded-full h-8 w-8 border-2 border-slate-200 border-t-eztech" />
            <p className="text-xs text-slate-400">Đang nạp danh sách Remind lead...</p>
          </div>
        ) : items.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-16 text-center">
            <Clock className="w-10 h-10 text-slate-300 mb-2" />
            <p className="text-sm font-semibold text-navy">Không có lead Remind nào phù hợp</p>
            <p className="text-xs text-slate-400 mt-1">
              Thử thay đổi bộ lọc nhân viên hoặc từ khóa tìm kiếm
            </p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse">
              <thead>
                <tr className="bg-slate-50/70 border-b border-slate-100 text-[11px] font-semibold text-slate-400 uppercase tracking-[0.06em]">
                  <th className="px-5 py-3">Khách Hàng</th>
                  <th className="px-5 py-3">Kênh / Page</th>
                  <th className="px-5 py-3">Nhân Viên</th>
                  <th className="px-5 py-3">Thẻ (Tag)</th>
                  <th className="px-5 py-3">Tương Tác Cuối</th>
                  <th className="px-5 py-3 text-right">Khoảng Cách</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 text-[13px]">
                {items.map(item => {
                  const badge = getDaysBadge(item.days_since_last_contact, item.days_int);
                  return (
                    <tr key={item.lead_id} className="hover:bg-slate-50/70 transition-colors">
                      {/* Khách hàng */}
                      <td className="px-5 py-3.5 align-top">
                        <div className="font-semibold text-navy">
                          {item.name || 'Khách hàng chưa đặt tên'}
                        </div>
                        <div className="flex flex-wrap items-center gap-1.5 mt-1.5 text-xs">
                          {item.phone_number ? (
                            <span className="inline-flex items-center gap-1 font-mono text-xs text-eztech font-medium bg-eztech-light/60 px-2 py-0.5 rounded-md border border-eztech-border/60 tabular-nums">
                              <Phone className="w-3 h-3" />
                              {item.phone_number}
                              <button
                                onClick={() => handleCopy(item.phone_number!)}
                                className="ml-1 hover:text-navy text-eztech/70"
                                title="Sao chép SĐT"
                              >
                                {copiedPhone === item.phone_number ? (
                                  <Check className="w-3 h-3 text-emerald-600" />
                                ) : (
                                  <Copy className="w-3 h-3" />
                                )}
                              </button>
                            </span>
                          ) : (
                            <span className="text-slate-300 text-xs italic">Chưa có SĐT</span>
                          )}

                          {item.pancake_url && (
                            <a
                              href={item.pancake_url}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="inline-flex items-center gap-1 text-[11px] font-medium text-slate-600 hover:text-eztech bg-white hover:bg-eztech-light px-2 py-0.5 rounded-md border border-slate-200 hover:border-eztech-border transition-colors"
                              title={`Mở Pancake: ${item.pancake_url}`}
                            >
                              <ExternalLink className="w-3 h-3" />
                              <span>Pancake</span>
                            </a>
                          )}
                        </div>
                      </td>

                      {/* Fanpage */}
                      <td className="px-5 py-3.5 align-top text-xs">
                        <span className="inline-block bg-slate-50 text-slate-600 border border-slate-200/80 px-2 py-1 rounded-md font-medium">
                          {item.page_id}
                        </span>
                      </td>

                      {/* Nhân viên phụ trách */}
                      <td className="px-5 py-3.5 align-top">
                        <span className="inline-flex items-center px-2.5 py-1 rounded-lg text-xs font-medium bg-eztech-light/60 text-navy border border-eztech-border/60">
                          {item.assigned_users || 'Chưa phân công'}
                        </span>
                      </td>

                      {/* Thẻ Tag */}
                      <td className="px-5 py-3.5 align-top">
                        <div className="flex flex-wrap gap-1">
                          {item.status_tag?.toLowerCase().includes('remind') && (
                            <span
                              className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-xs font-semibold bg-gold-light text-gold-dark border border-gold-border"
                              title={
                                item.remind_tagged_at
                                  ? `Gắn tag Remind lúc: ${item.remind_tagged_at}`
                                  : 'Tag Remind'
                              }
                            >
                              <Clock className="w-3 h-3" />
                              Remind
                            </span>
                          )}
                          {item.status_tag ? (
                            item.status_tag
                              .split(',')
                              .map(t => t.trim())
                              .filter(t => t.toLowerCase() !== 'remind')
                              .slice(0, 3)
                              .map((tName, idx) => (
                                <span
                                  key={idx}
                                  className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-xs text-slate-600 bg-slate-50 border border-slate-200/80"
                                >
                                  <span className="w-1.5 h-1.5 rounded-full bg-eztech" />
                                  {tName}
                                </span>
                              ))
                          ) : (
                            <span className="text-slate-300 italic text-xs">—</span>
                          )}
                        </div>
                      </td>

                      {/* Tin nhắn cuối */}
                      <td className="px-5 py-3.5 align-top text-xs font-mono text-slate-600 tabular-nums">
                        {formatContactedDate(item.contacted_at)}
                      </td>

                      {/* Khoảng cách ngày */}
                      <td className="px-5 py-3.5 align-top text-right whitespace-nowrap">
                        <span
                          className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-semibold border tabular-nums ${badge.bg}`}
                        >
                          <span className={`w-1.5 h-1.5 rounded-full ${badge.dot}`} />
                          {badge.label}
                        </span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}

        {/* Phân trang */}
        <div className="px-5 py-3.5 bg-slate-50/50 border-t border-slate-100 flex flex-wrap items-center justify-between gap-3 text-xs text-slate-500">
          <div className="tabular-nums">
            Hiển thị{' '}
            <span className="font-mono font-semibold text-navy">
              {total > 0 ? (page - 1) * pageSize + 1 : 0}
            </span>
            –
            <span className="font-mono font-semibold text-navy">
              {Math.min(page * pageSize, total)}
            </span>{' '}
            / <span className="font-mono font-semibold text-navy">{total.toLocaleString()}</span> lead
          </div>

          <div className="flex items-center gap-3">
            <div className="flex items-center gap-1.5">
              <span>Hiển thị:</span>
              <select
                value={pageSize}
                onChange={e => {
                  setPageSize(Number(e.target.value));
                  setPage(1);
                }}
                className="px-2 py-1 bg-white border border-slate-200 rounded-lg text-xs font-mono text-navy focus:outline-none"
              >
                <option value={15}>15</option>
                <option value={20}>20</option>
                <option value={50}>50</option>
                <option value={100}>100</option>
              </select>
            </div>

            <div className="flex items-center gap-1">
              <button
                disabled={page <= 1}
                onClick={() => setPage(p => Math.max(1, p - 1))}
                className="px-2.5 py-1 bg-white border border-slate-200 rounded-lg text-navy disabled:opacity-40 disabled:pointer-events-none hover:border-eztech/40 hover:text-eztech transition-colors"
              >
                Trước
              </button>
              <span className="px-2 font-mono font-medium text-navy tabular-nums">
                {page} / {totalPages}
              </span>
              <button
                disabled={page >= totalPages}
                onClick={() => setPage(p => Math.min(totalPages, p + 1))}
                className="px-2.5 py-1 bg-white border border-slate-200 rounded-lg text-navy disabled:opacity-40 disabled:pointer-events-none hover:border-eztech/40 hover:text-eztech transition-colors"
              >
                Sau
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
