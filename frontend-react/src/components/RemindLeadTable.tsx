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
  const [loading, setLoading] = useState(true);
  const [copiedPhone, setCopiedPhone] = useState<string | null>(null);

  const loadData = async () => {
    setLoading(true);
    try {
      const res = await fetchRemindLeads(
        employee || undefined,
        pageId || undefined,
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
    } catch (err) {
      console.error('Error fetching remind leads:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, [employee, pageId, search, daysBucket, sortOrder, page, pageSize]);

  // Reset về page 1 khi thay đổi bộ lọc
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
        label: `Hôm nay (${hours}h trước)`,
        bg: 'bg-emerald-50 text-emerald-700 border-emerald-200',
        dot: 'bg-emerald-500'
      };
    }
    if (daysInt <= 3) {
      return {
        label: `${daysFloat} ngày trước`,
        bg: 'bg-amber-50 text-amber-700 border-amber-200',
        dot: 'bg-amber-500'
      };
    }
    if (daysInt <= 7) {
      return {
        label: `${daysFloat} ngày trước`,
        bg: 'bg-orange-50 text-orange-700 border-orange-200',
        dot: 'bg-orange-500'
      };
    }
    return {
      label: `${daysFloat} ngày trước (Lâu)`,
      bg: 'bg-rose-50 text-rose-700 border-rose-200',
      dot: 'bg-rose-500 font-semibold'
    };
  };

  return (
    <div className="space-y-6">
      {/* Cards thống kê nhanh Remind */}
      <div className="grid grid-cols-2 sm:grid-cols-2 lg:grid-cols-5 gap-3.5">
        <div
          onClick={() => handleFilterChange(setDaysBucket, 'all')}
          className={`cursor-pointer bg-white p-4 rounded-2xl border transition-all hover:shadow-sm ${
            daysBucket === 'all' ? 'border-[#1E5BD6] ring-2 ring-[#1E5BD6]/10' : 'border-[#E5E7EB]'
          }`}
        >
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-[#4B5563]">Tổng Remind</span>
            <span className="p-1.5 rounded-lg bg-blue-50 text-[#1E5BD6]">
              <Clock className="w-4 h-4" />
            </span>
          </div>
          <div className="text-2xl font-bold text-navy mt-2">
            {(summary?.total || 0).toLocaleString()}
          </div>
          <div className="text-xs text-[#4B5563] mt-0.5">Tất cả lead đang cần Remind</div>
        </div>

        <div
          onClick={() => handleFilterChange(setDaysBucket, 'today')}
          className={`cursor-pointer bg-white p-4 rounded-2xl border transition-all hover:shadow-sm ${
            daysBucket === 'today' ? 'border-emerald-500 ring-2 ring-emerald-500/10' : 'border-[#E5E7EB]'
          }`}
        >
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-[#4B5563]">Hôm nay (&lt; 1 ngày)</span>
            <span className="p-1.5 rounded-lg bg-emerald-50 text-emerald-600">
              <CheckCircle2 className="w-4 h-4" />
            </span>
          </div>
          <div className="text-2xl font-bold text-emerald-700 mt-2">
            {(summary?.under_1_day || 0).toLocaleString()}
          </div>
          <div className="text-xs text-[#4B5563] mt-0.5">Mới tương tác hôm nay</div>
        </div>

        <div
          onClick={() => handleFilterChange(setDaysBucket, '1_to_3')}
          className={`cursor-pointer bg-white p-4 rounded-2xl border transition-all hover:shadow-sm ${
            daysBucket === '1_to_3' ? 'border-amber-500 ring-2 ring-amber-500/10' : 'border-[#E5E7EB]'
          }`}
        >
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-[#4B5563]">1 - 3 ngày</span>
            <span className="p-1.5 rounded-lg bg-amber-50 text-amber-600">
              <Calendar className="w-4 h-4" />
            </span>
          </div>
          <div className="text-2xl font-bold text-amber-700 mt-2">
            {(summary?.days_1_to_3 || 0).toLocaleString()}
          </div>
          <div className="text-xs text-[#4B5563] mt-0.5">Đã 1 - 3 ngày chưa chat lại</div>
        </div>

        <div
          onClick={() => handleFilterChange(setDaysBucket, '3_to_7')}
          className={`cursor-pointer bg-white p-4 rounded-2xl border transition-all hover:shadow-sm ${
            daysBucket === '3_to_7' ? 'border-orange-500 ring-2 ring-orange-500/10' : 'border-[#E5E7EB]'
          }`}
        >
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-[#4B5563]">3 - 7 ngày</span>
            <span className="p-1.5 rounded-lg bg-orange-50 text-orange-600">
              <AlertTriangle className="w-4 h-4" />
            </span>
          </div>
          <div className="text-2xl font-bold text-orange-700 mt-2">
            {(summary?.days_3_to_7 || 0).toLocaleString()}
          </div>
          <div className="text-xs text-[#4B5563] mt-0.5">Cần nhắc lịch sớm</div>
        </div>

        <div
          onClick={() => handleFilterChange(setDaysBucket, 'over_7')}
          className={`cursor-pointer bg-white p-4 rounded-2xl border transition-all hover:shadow-sm ${
            daysBucket === 'over_7' ? 'border-rose-500 ring-2 ring-rose-500/10' : 'border-[#E5E7EB]'
          }`}
        >
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-[#4B5563]">&gt; 7 ngày (Quá hạn)</span>
            <span className="p-1.5 rounded-lg bg-rose-50 text-rose-600">
              <Flame className="w-4 h-4" />
            </span>
          </div>
          <div className="text-2xl font-bold text-rose-700 mt-2">
            {(summary?.over_7_days || 0).toLocaleString()}
          </div>
          <div className="text-xs text-[#4B5563] mt-0.5">Quá 1 tuần chưa chăm sóc</div>
        </div>
      </div>

      {/* Bộ lọc bảng Remind */}
      <div className="bg-white rounded-2xl border border-[#E5E7EB] shadow-sm p-5 space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div className="flex items-center gap-2">
            <div className="p-1.5 rounded-lg bg-blue-50 text-[#1E5BD6]">
              <Clock className="w-4 h-4" />
            </div>
            <div>
              <h2 className="text-base font-bold text-navy">Bảng Remind Lead</h2>
              <p className="text-xs text-[#4B5563]">
                Chỉ hiển thị các lead có tag Remind, sắp xếp theo số ngày từ tin nhắn cuối cùng
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={() => handleFilterChange(setSortOrder, sortOrder === 'asc' ? 'desc' : 'asc')}
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-xl border border-[#E5E7EB] hover:bg-gray-50 text-[#111827] transition-colors"
              title="Nhấn để đổi chiều sắp xếp"
            >
              <ArrowUpDown className="w-3.5 h-3.5 text-[#1E5BD6]" />
              <span>
                Thứ tự: {sortOrder === 'asc' ? 'Thấp nhất → Xa nhất (Gần nhất)' : 'Xa nhất → Thấp nhất'}
              </span>
            </button>

            <button
              onClick={loadData}
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-[#1E5BD6] bg-blue-50 hover:bg-blue-100 rounded-xl transition-colors"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
              Làm mới
            </button>
          </div>
        </div>

        {/* Filter Controls Row */}
        <div className="flex flex-wrap gap-3 items-end pt-2 border-t border-[#E5E7EB]">
          {/* Lọc theo Nhân Viên (Trọng tâm) */}
          <div className="flex flex-col gap-1 min-w-[220px]">
            <label className="text-xs font-medium text-[#4B5563]">Nhân Viên Phụ Trách</label>
            <select
              value={employee}
              onChange={e => handleFilterChange(setEmployee, e.target.value)}
              className="px-3 py-2 border border-[#E5E7EB] rounded-xl text-sm bg-white focus:outline-none focus:ring-2 focus:ring-eztech/20 focus:border-eztech transition-all text-[#111827] cursor-pointer"
            >
              <option value="">-- Tất cả nhân viên --</option>
              {employeesList.map(emp => (
                <option key={emp} value={emp}>
                  {emp}
                </option>
              ))}
            </select>
          </div>

          {/* Lọc theo Page */}
          <div className="flex flex-col gap-1 min-w-[200px]">
            <label className="text-xs font-medium text-[#4B5563]">Page Nguồn Lead</label>
            <select
              value={pageId}
              onChange={e => handleFilterChange(setPageId, e.target.value)}
              className="px-3 py-2 border border-[#E5E7EB] rounded-xl text-sm bg-white focus:outline-none focus:ring-2 focus:ring-eztech/20 focus:border-eztech transition-all text-[#111827] cursor-pointer"
            >
              <option value="">-- Tất cả Page --</option>
              <optgroup label="Nguồn lead">
                {pagesList
                  .filter(pg => !zaloPages.includes(pg))
                  .map(pg => (
                    <option key={pg} value={pg}>
                      {pg}
                    </option>
                  ))}
              </optgroup>
              {zaloPages.length > 0 && (
                <optgroup label="Zalo (chăm sóc)">
                  {zaloPages.map(pg => (
                    <option key={pg} value={pg}>
                      {pg}
                    </option>
                  ))}
                </optgroup>
              )}
            </select>
          </div>

          {/* Tìm kiếm tên / SĐT */}
          <div className="flex flex-col gap-1 flex-1 min-w-[200px]">
            <label className="text-xs font-medium text-[#4B5563]">Tìm Tên / Số Điện Thoại</label>
            <div className="relative">
              <Search className="w-4 h-4 text-gray-400 absolute left-3 top-2.5" />
              <input
                type="text"
                placeholder="Nhập tên khách hàng hoặc SĐT..."
                value={search}
                onChange={e => handleFilterChange(setSearch, e.target.value)}
                className="w-full pl-9 pr-3 py-2 border border-[#E5E7EB] rounded-xl text-sm bg-white focus:outline-none focus:ring-2 focus:ring-eztech/20 focus:border-eztech transition-all text-[#111827]"
              />
            </div>
          </div>
        </div>
      </div>

      {/* Bảng Dữ Liệu Remind */}
      <div className="bg-white rounded-2xl border border-[#E5E7EB] shadow-sm overflow-hidden">
        {loading ? (
          <div className="flex flex-col items-center justify-center py-20 gap-3">
            <div className="animate-spin rounded-full h-8 w-8 border-2 border-blue-200 border-t-[#1E5BD6]" />
            <p className="text-xs text-[#4B5563]">Đang nạp danh sách Remind lead...</p>
          </div>
        ) : items.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-16 text-center">
            <Clock className="w-12 h-12 text-gray-300 mb-2" />
            <p className="text-sm font-semibold text-navy">Không có lead Remind nào phù hợp</p>
            <p className="text-xs text-[#4B5563] mt-1">
              Thử thay đổi bộ lọc nhân viên hoặc từ khóa tìm kiếm
            </p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse">
              <thead>
                <tr className="bg-gray-50/75 border-b border-[#E5E7EB] text-xs font-semibold text-[#4B5563] uppercase tracking-wider">
                  <th className="px-6 py-3.5">Khách Hàng</th>
                  <th className="px-6 py-3.5">Fanpage</th>
                  <th className="px-6 py-3.5">Nhân Viên Phụ Trách</th>
                  <th className="px-6 py-3.5">Thẻ (Tag)</th>
                  <th className="px-6 py-3.5">Tin Nhắn Cuối</th>
                  <th className="px-6 py-3.5 text-right">Khoảng Cách Ngày</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#E5E7EB] text-sm">
                {items.map(item => {
                  const badge = getDaysBadge(item.days_since_last_contact, item.days_int);
                  return (
                    <tr key={item.lead_id} className="hover:bg-blue-50/30 transition-colors">
                      {/* Khách hàng */}
                      <td className="px-6 py-4 align-top">
                        <div className="font-semibold text-[#111827]">
                          {item.name || 'Khách hàng chưa đặt tên'}
                        </div>
                        <div className="flex flex-wrap items-center gap-2 mt-1.5 text-xs">
                          {item.phone_number ? (
                            <span className="inline-flex items-center gap-1 font-mono text-[#1E5BD6] font-medium bg-blue-50 px-2 py-0.5 rounded-md border border-blue-100">
                              <Phone className="w-3 h-3" />
                              {item.phone_number}
                              <button
                                onClick={() => handleCopy(item.phone_number!)}
                                className="ml-1 hover:text-navy text-blue-400"
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
                            <span className="text-gray-400 italic">Chưa có SĐT</span>
                          )}

                          {item.pancake_url && (
                            <a
                              href={item.pancake_url}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="inline-flex items-center gap-1 font-medium text-[#1E5BD6] hover:text-[#0C2B64] hover:bg-blue-100/70 bg-blue-50 px-2 py-0.5 rounded-md border border-blue-200 transition-colors shadow-2xs"
                              title={`Mở Pancake: ${item.pancake_url}`}
                            >
                              <ExternalLink className="w-3 h-3" />
                              <span>Mở Pancake</span>
                            </a>
                          )}
                        </div>
                      </td>

                      {/* Fanpage */}
                      <td className="px-6 py-4 align-top text-xs font-medium text-[#4B5563]">
                        <span className="inline-block bg-gray-100 text-[#111827] px-2 py-1 rounded-lg">
                          {item.page_id}
                        </span>
                      </td>

                      {/* Nhân viên phụ trách */}
                      <td className="px-6 py-4 align-top">
                        <span className="inline-flex items-center px-2.5 py-1 rounded-lg text-xs font-medium bg-slate-100 text-slate-800 border border-slate-200">
                          {item.assigned_users || 'Chưa phân công'}
                        </span>
                      </td>

                      {/* Thẻ Tag */}
                      <td className="px-6 py-4 align-top">
                        <div className="flex flex-wrap gap-1">
                          <span
                            className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg text-xs font-bold bg-amber-100 text-amber-800 border border-amber-300"
                            title={
                              item.remind_tagged_at
                                ? `Gắn tag Remind lúc: ${item.remind_tagged_at}`
                                : 'Tag Remind'
                            }
                          >
                            <Clock className="w-3 h-3" />
                            Remind
                          </span>
                          {item.status_tag
                            ?.split(',')
                            .map(t => t.trim())
                            .filter(t => t.toLowerCase() !== 'remind')
                            .slice(0, 2)
                            .map((tag, idx) => (
                              <span
                                key={idx}
                                className="px-2 py-0.5 rounded text-xs text-gray-600 bg-gray-100 border border-gray-200"
                              >
                                {tag}
                              </span>
                            ))}
                        </div>
                      </td>

                      {/* Tin nhắn cuối */}
                      <td className="px-6 py-4 align-top text-xs text-[#4B5563]">
                        <div className="font-medium text-[#111827]">
                          {formatContactedDate(item.contacted_at)}
                        </div>
                      </td>

                      {/* Khoảng cách ngày (Trọng tâm) */}
                      <td className="px-6 py-4 align-top text-right">
                        <span
                          className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-bold border ${badge.bg}`}
                        >
                          <span className={`w-2 h-2 rounded-full ${badge.dot}`} />
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
        <div className="px-6 py-4 bg-gray-50 border-t border-[#E5E7EB] flex flex-wrap items-center justify-between gap-3 text-xs text-[#4B5563]">
          <div>
            Hiển thị{' '}
            <span className="font-semibold text-[#111827]">
              {total > 0 ? (page - 1) * pageSize + 1 : 0}
            </span>{' '}
            -{' '}
            <span className="font-semibold text-[#111827]">
              {Math.min(page * pageSize, total)}
            </span>{' '}
            trên tổng số <span className="font-semibold text-[#111827]">{total.toLocaleString()}</span> lead
          </div>

          <div className="flex items-center gap-4">
            <div className="flex items-center gap-1.5">
              <span>Mỗi trang:</span>
              <select
                value={pageSize}
                onChange={e => {
                  setPageSize(Number(e.target.value));
                  setPage(1);
                }}
                className="px-2 py-1 bg-white border border-[#E5E7EB] rounded-lg text-xs focus:outline-none"
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
                className="px-3 py-1 bg-white border border-[#E5E7EB] rounded-lg disabled:opacity-40 disabled:cursor-not-allowed hover:bg-gray-100 transition-colors"
              >
                Trang trước
              </button>
              <span className="px-2 font-medium text-[#111827]">
                {page} / {totalPages}
              </span>
              <button
                disabled={page >= totalPages}
                onClick={() => setPage(p => Math.min(totalPages, p + 1))}
                className="px-3 py-1 bg-white border border-[#E5E7EB] rounded-lg disabled:opacity-40 disabled:cursor-not-allowed hover:bg-gray-100 transition-colors"
              >
                Trang sau
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
