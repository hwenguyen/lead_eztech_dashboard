import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  Check,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Columns,
  Download,
  ExternalLink,
  Filter,
  Loader2,
  Play,
  RotateCcw,
  Search,
  X,
} from 'lucide-react';
import {
  downloadDataExportExcel,
  fetchDataExportOptions,
  previewDataExport,
  type DataExportFilterPayload,
  type DataExportOptions,
  type DataExportPreviewResponse,
} from '../services/api';

const COMPACT_COLUMNS = ['assigned_users', 'page_name', 'phone_number', 'name', 'pancake_link'];

interface MultiSelectDropdownProps {
  label: string;
  placeholder: string;
  options: { value: string; label: string }[];
  selected: string[];
  onChange: (next: string[]) => void;
}

const MultiSelectDropdown: React.FC<MultiSelectDropdownProps> = ({
  label,
  placeholder,
  options,
  selected,
  onChange,
}) => {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState('');
  const boxRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const onDocClick = (e: MouseEvent) => {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', onDocClick);
    return () => document.removeEventListener('mousedown', onDocClick);
  }, []);

  const filtered = useMemo(() => {
    const kw = q.trim().toLowerCase();
    if (!kw) return options;
    return options.filter((o) => o.label.toLowerCase().includes(kw));
  }, [options, q]);

  const toggleValue = (val: string) => {
    if (selected.includes(val)) {
      onChange(selected.filter((x) => x !== val));
    } else {
      onChange([...selected, val]);
    }
  };

  return (
    <div ref={boxRef} className="relative space-y-1">
      <label className="block text-[11px] font-semibold text-slate-600 uppercase tracking-wider">
        {label}
      </label>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="w-full px-3 py-2 bg-slate-50 hover:bg-white border border-slate-200/90 rounded-xl text-xs text-left flex items-center justify-between gap-2 transition-colors"
      >
        <span className="truncate font-medium text-navy">
          {selected.length === 0
            ? placeholder
            : selected.length === 1
            ? options.find((o) => o.value === selected[0])?.label || selected[0]
            : `Đã chọn ${selected.length} mục`}
        </span>
        <div className="flex items-center gap-1 shrink-0">
          {selected.length > 0 && (
            <span
              role="button"
              tabIndex={0}
              onClick={(e) => {
                e.stopPropagation();
                onChange([]);
              }}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.stopPropagation();
                  onChange([]);
                }
              }}
              className="p-0.5 text-slate-400 hover:text-rose-500 rounded"
              title="Bỏ chọn hết"
            >
              <X className="w-3.5 h-3.5" />
            </span>
          )}
          <ChevronDown className={`w-3.5 h-3.5 text-slate-400 transition-transform ${open ? 'rotate-180' : ''}`} />
        </div>
      </button>

      {open && (
        <div className="absolute left-0 right-0 mt-1.5 z-30 bg-white border border-slate-200 rounded-xl shadow-xl overflow-hidden">
          <div className="p-2 border-b border-slate-100 flex items-center gap-1.5">
            <Search className="w-3.5 h-3.5 text-slate-400 shrink-0" />
            <input
              type="text"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Tìm nhanh..."
              className="w-full text-xs text-navy placeholder-slate-400 focus:outline-none bg-transparent"
            />
          </div>
          <div className="max-h-56 overflow-y-auto p-1.5 space-y-0.5">
            {filtered.length === 0 ? (
              <p className="text-[11px] text-slate-400 text-center py-3">Không tìm thấy mục nào</p>
            ) : (
              filtered.map((opt) => {
                const checked = selected.includes(opt.value);
                return (
                  <button
                    key={opt.value}
                    type="button"
                    onClick={() => toggleValue(opt.value)}
                    className={`w-full px-2.5 py-1.5 rounded-lg text-xs flex items-center justify-between gap-2 text-left transition-colors ${
                      checked ? 'bg-brand-50 text-brand-700 font-semibold' : 'text-slate-700 hover:bg-slate-50'
                    }`}
                  >
                    <span className="truncate">{opt.label}</span>
                    {checked && <Check className="w-3.5 h-3.5 text-brand-600 shrink-0" />}
                  </button>
                );
              })
            )}
          </div>
          {selected.length > 0 && (
            <div className="px-2.5 py-1.5 border-t border-slate-100 bg-slate-50 flex items-center justify-between">
              <span className="text-[11px] text-slate-500">Đã chọn {selected.length}</span>
              <button
                type="button"
                onClick={() => onChange([])}
                className="text-[11px] font-semibold text-rose-600 hover:underline"
              >
                Xóa tất cả
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
};

export const DataExportDashboard: React.FC = () => {
  const [options, setOptions] = useState<DataExportOptions | null>(null);
  const [loadingOptions, setLoadingOptions] = useState(true);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [exportNotice, setExportNotice] = useState<string | null>(null);

  // Selected columns
  const [selectedColumns, setSelectedColumns] = useState<string[]>(COMPACT_COLUMNS);

  // Filters
  const [channelGroup, setChannelGroup] = useState<'all' | 'zalo' | 'source'>('all');
  const [selectedPages, setSelectedPages] = useState<string[]>([]);
  const [selectedEmployees, setSelectedEmployees] = useState<string[]>([]);
  const [employeeMatchMode, setEmployeeMatchMode] = useState<'any' | 'exact'>('any');
  const [studentFilter, setStudentFilter] = useState<'all' | 'non_student' | 'student'>('non_student');
  const [selectedTags, setSelectedTags] = useState<string[]>([]);
  const [phoneFilter, setPhoneFilter] = useState<'all' | 'has_phone' | 'no_phone'>('all');
  const [dateField, setDateField] = useState<'contacted_at' | 'first_created_at'>('contacted_at');
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');
  const [search, setSearch] = useState('');
  const [excludeZaloGroups, setExcludeZaloGroups] = useState(true);
  const [dedupePhone, setDedupePhone] = useState(false);
  const [sortBy, setSortBy] = useState<'contacted_at' | 'first_created_at' | 'message_count' | 'name'>('contacted_at');
  const [sortDir, setSortDir] = useState<'desc' | 'asc'>('desc');

  // Preview state
  const [pageSize, setPageSize] = useState(50);
  const [preview, setPreview] = useState<DataExportPreviewResponse | null>(null);
  const [loadingPreview, setLoadingPreview] = useState(false);
  const [exporting, setExporting] = useState(false);

  useEffect(() => {
    let active = true;
    const load = async () => {
      setLoadingOptions(true);
      setErrorMsg(null);
      try {
        const res = await fetchDataExportOptions();
        if (!active) return;
        setOptions(res);
        const defaults = res.columns.filter((c) => c.default).map((c) => c.key);
        if (defaults.length > 0) {
          setSelectedColumns(defaults);
        }
      } catch (err: any) {
        if (!active) return;
        setErrorMsg(err?.response?.data?.detail || 'Không thể tải cấu hình bộ lọc từ máy chủ.');
      } finally {
        if (active) setLoadingOptions(false);
      }
    };
    load();
    return () => {
      active = false;
    };
  }, []);

  const availablePageOptions = useMemo(() => {
    if (!options) return [];
    const list =
      channelGroup === 'zalo'
        ? options.zalo_pages
        : channelGroup === 'source'
        ? options.source_pages
        : options.pages;
    return list.map((p) => ({ value: p, label: p }));
  }, [options, channelGroup]);

  const employeeOptions = useMemo(
    () => (options?.employees || []).map((e) => ({ value: e, label: e })),
    [options]
  );

  const tagOptions = useMemo(() => {
    const base = [{ value: 'no_tag', label: 'Chưa gắn tag' }];
    if (!options) return base;
    const byPage = options.tags_by_page || {};
    let list: string[];
    if (selectedPages.length > 0) {
      const union = new Set<string>();
      selectedPages.forEach((pg) => {
        (byPage[pg] || []).forEach((t) => union.add(t));
      });
      list = (options.tags || []).filter((t) => union.has(t));
    } else if (channelGroup === 'zalo') {
      list = byPage['all_zalo'] || options.tags || [];
    } else if (channelGroup === 'source') {
      list = byPage['all_source'] || options.tags || [];
    } else {
      list = options.tags || [];
    }
    return base.concat(list.map((t) => ({ value: t, label: t })));
  }, [options, selectedPages, channelGroup]);

  useEffect(() => {
    const allowed = new Set(tagOptions.map((o) => o.value));
    setSelectedTags((prev) => {
      const next = prev.filter((t) => allowed.has(t));
      return next.length === prev.length ? prev : next;
    });
  }, [tagOptions]);

  const buildFilterPayload = (): DataExportFilterPayload => ({
    columns: selectedColumns,
    channel_group: channelGroup,
    pages: selectedPages,
    employees: selectedEmployees,
    employee_match_mode: employeeMatchMode,
    student_filter: studentFilter,
    tags: selectedTags,
    phone_filter: phoneFilter,
    date_field: dateField,
    date_from: dateFrom || null,
    date_to: dateTo || null,
    search: search.trim() || null,
    exclude_zalo_groups: excludeZaloGroups,
    dedupe_phone: dedupePhone,
    sort_by: sortBy,
    sort_dir: sortDir,
  });

  const toggleColumn = (key: string) => {
    setSelectedColumns((prev) =>
      prev.includes(key) ? prev.filter((k) => k !== key) : [...prev, key]
    );
  };

  const runPreview = async (targetPage = 1, targetPageSize = pageSize) => {
    if (selectedColumns.length === 0) {
      setErrorMsg('Vui lòng tích chọn ít nhất 1 cột dữ liệu.');
      return;
    }
    setLoadingPreview(true);
    setErrorMsg(null);
    try {
      const res = await previewDataExport({
        ...buildFilterPayload(),
        page: targetPage,
        page_size: targetPageSize,
      });
      setPreview(res);
      setPageSize(res.page_size);
    } catch (err: any) {
      setErrorMsg(err?.response?.data?.detail || 'Lỗi khi truy vấn dữ liệu xem trước.');
    } finally {
      setLoadingPreview(false);
    }
  };

  const handleExportExcel = async () => {
    if (selectedColumns.length === 0) {
      setErrorMsg('Vui lòng tích chọn ít nhất 1 cột để xuất Excel.');
      return;
    }
    setExporting(true);
    setErrorMsg(null);
    setExportNotice(null);
    try {
      const res = await downloadDataExportExcel({
        ...buildFilterPayload(),
        max_rows: options?.max_export_rows || 20000,
      });
      setExportNotice(
        `Đã tải xuống ${res.filename} (${res.rowCount.toLocaleString('vi-VN')} dòng).`
      );
    } catch (err: any) {
      setErrorMsg(err?.response?.data?.detail || 'Lỗi khi xuất file Excel. Vui lòng thử lại.');
    } finally {
      setExporting(false);
    }
  };

  const handleResetFilters = () => {
    setChannelGroup('all');
    setSelectedPages([]);
    setSelectedEmployees([]);
    setEmployeeMatchMode('any');
    setStudentFilter('non_student');
    setSelectedTags([]);
    setPhoneFilter('all');
    setDateField('contacted_at');
    setDateFrom('');
    setDateTo('');
    setSearch('');
    setExcludeZaloGroups(true);
    setDedupePhone(false);
    setSortBy('contacted_at');
    setSortDir('desc');
    setPreview(null);
    setExportNotice(null);
    setErrorMsg(null);
  };

  if (loadingOptions) {
    return (
      <div className="bg-white rounded-2xl border border-slate-200/80 shadow-card p-10 flex flex-col items-center justify-center gap-3 text-slate-500">
        <Loader2 className="w-6 h-6 animate-spin text-brand-500" />
        <p className="text-xs font-medium">Đang tải cấu hình bộ lọc & danh mục cột...</p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Column Selection Card */}
      <div className="bg-white rounded-2xl border border-slate-200/80 shadow-card p-4 sm:p-5 space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <Columns className="w-4 h-4 text-brand-500" />
            <h4 className="text-xs font-bold text-navy uppercase tracking-wider">
              1. Tích chọn các cột cần kết xuất ({selectedColumns.length}/{options?.columns.length || 0})
            </h4>
          </div>
          <div className="flex flex-wrap items-center gap-1.5">
            <button
              type="button"
              onClick={() => setSelectedColumns(COMPACT_COLUMNS)}
              className="px-2.5 py-1 rounded-lg text-[11px] font-semibold bg-brand-50 text-brand-700 hover:bg-brand-100 transition-colors"
            >
              5 cột chính
            </button>
            <button
              type="button"
              onClick={() =>
                setSelectedColumns(options?.columns.filter((c) => c.default).map((c) => c.key) || COMPACT_COLUMNS)
              }
              className="px-2.5 py-1 rounded-lg text-[11px] font-semibold bg-slate-100 text-slate-700 hover:bg-slate-200 transition-colors"
            >
              Mặc định
            </button>
            <button
              type="button"
              onClick={() => setSelectedColumns(options?.columns.map((c) => c.key) || [])}
              className="px-2.5 py-1 rounded-lg text-[11px] font-semibold bg-slate-100 text-slate-700 hover:bg-slate-200 transition-colors"
            >
              Chọn tất cả
            </button>
            <button
              type="button"
              onClick={() => setSelectedColumns([])}
              className="px-2.5 py-1 rounded-lg text-[11px] font-semibold text-rose-600 hover:bg-rose-50 transition-colors"
            >
              Bỏ chọn
            </button>
          </div>
        </div>

        <div className="flex flex-wrap gap-2">
          {(options?.columns || []).map((col) => {
            const checked = selectedColumns.includes(col.key);
            return (
              <button
                key={col.key}
                type="button"
                onClick={() => toggleColumn(col.key)}
                className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-medium border transition-all cursor-pointer ${
                  checked
                    ? 'bg-navy text-white border-navy shadow-xs'
                    : 'bg-slate-50 text-slate-600 border-slate-200 hover:border-brand-300 hover:text-navy'
                }`}
              >
                <span
                  className={`w-3.5 h-3.5 rounded flex items-center justify-center border ${
                    checked ? 'bg-gold-400 border-gold-400 text-navy' : 'border-slate-300 bg-white'
                  }`}
                >
                  {checked && <Check className="w-2.5 h-2.5 stroke-[3]" />}
                </span>
                <span>{col.label}</span>
              </button>
            );
          })}
        </div>
      </div>

      {/* Filter Builder Card */}
      <div className="bg-white rounded-2xl border border-slate-200/80 shadow-card p-4 sm:p-5 space-y-4">
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <Filter className="w-4 h-4 text-brand-500" />
            <h4 className="text-xs font-bold text-navy uppercase tracking-wider">
              2. Điều kiện lọc
            </h4>
          </div>
          <button
            type="button"
            onClick={handleResetFilters}
            className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg text-[11px] font-semibold text-slate-500 hover:text-navy hover:bg-slate-100 transition-colors"
          >
            <RotateCcw className="w-3 h-3" />
            <span>Đặt lại</span>
          </button>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3.5">
          {/* Nhóm kênh */}
          <div className="space-y-1">
            <label className="block text-[11px] font-semibold text-slate-600 uppercase tracking-wider">
              Nhóm kênh
            </label>
            <select
              value={channelGroup}
              onChange={(e) => {
                const next = e.target.value as 'all' | 'zalo' | 'source';
                setChannelGroup(next);
                setSelectedPages([]);
              }}
              className="w-full px-3 py-2 bg-slate-50 border border-slate-200/90 rounded-xl text-xs font-medium text-navy focus:bg-white focus:outline-none focus:ring-2 focus:ring-brand-500/20"
            >
              <option value="all">Tất cả kênh (Zalo + FB + TikTok)</option>
              <option value="zalo">Chỉ các Page Zalo cá nhân</option>
              <option value="source">Chỉ kênh nguồn (Facebook + TikTok)</option>
            </select>
          </div>

          {/* Page cụ thể */}
          <MultiSelectDropdown
            label="Tên kênh (Page cụ thể)"
            placeholder="Tất cả Page trong nhóm"
            options={availablePageOptions}
            selected={selectedPages}
            onChange={setSelectedPages}
          />

          {/* Nhân viên */}
          <MultiSelectDropdown
            label="Nhân viên phụ trách"
            placeholder="Tất cả nhân viên"
            options={employeeOptions}
            selected={selectedEmployees}
            onChange={setSelectedEmployees}
          />

          {/* Trạng thái học viên */}
          <div className="space-y-1">
            <label className="block text-[11px] font-semibold text-slate-600 uppercase tracking-wider">
              Trạng thái học viên
            </label>
            <select
              value={studentFilter}
              onChange={(e) => setStudentFilter(e.target.value as 'all' | 'non_student' | 'student')}
              className="w-full px-3 py-2 bg-slate-50 border border-slate-200/90 rounded-xl text-xs font-medium text-navy focus:bg-white focus:outline-none focus:ring-2 focus:ring-brand-500/20"
            >
              <option value="all">Tất cả (gồm cả Học viên)</option>
              <option value="non_student">Chưa phải học viên (lọc chặt theo Tag + Deal)</option>
              <option value="student">Chỉ khách Đã là học viên</option>
            </select>
          </div>

          {/* Tag trạng thái */}
          <MultiSelectDropdown
            label="Tag trạng thái"
            placeholder="Tất cả Tag"
            options={tagOptions}
            selected={selectedTags}
            onChange={setSelectedTags}
          />

          {/* SĐT */}
          <div className="space-y-1">
            <label className="block text-[11px] font-semibold text-slate-600 uppercase tracking-wider">
              Số điện thoại
            </label>
            <select
              value={phoneFilter}
              onChange={(e) => setPhoneFilter(e.target.value as 'all' | 'has_phone' | 'no_phone')}
              className="w-full px-3 py-2 bg-slate-50 border border-slate-200/90 rounded-xl text-xs font-medium text-navy focus:bg-white focus:outline-none focus:ring-2 focus:ring-brand-500/20"
            >
              <option value="all">Tất cả</option>
              <option value="has_phone">Chỉ Lead đã có SĐT</option>
              <option value="no_phone">Chỉ Lead chưa có SĐT</option>
            </select>
          </div>

          {/* Tìm kiếm nhanh */}
          <div className="space-y-1">
            <label className="block text-[11px] font-semibold text-slate-600 uppercase tracking-wider">
              Tìm tên khách / SĐT
            </label>
            <div className="relative">
              <Search className="w-3.5 h-3.5 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
              <input
                type="text"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') runPreview(1, pageSize);
                }}
                placeholder="Nhập tên hoặc SĐT..."
                className="w-full pl-8 pr-3 py-2 bg-slate-50 border border-slate-200/90 rounded-xl text-xs font-medium text-navy focus:bg-white focus:outline-none focus:ring-2 focus:ring-brand-500/20"
              />
            </div>
          </div>

          {/* Sắp xếp */}
          <div className="space-y-1">
            <label className="block text-[11px] font-semibold text-slate-600 uppercase tracking-wider">
              Sắp xếp kết quả
            </label>
            <div className="flex gap-1.5">
              <select
                value={sortBy}
                onChange={(e) => setSortBy(e.target.value as any)}
                className="flex-1 px-2.5 py-2 bg-slate-50 border border-slate-200/90 rounded-xl text-xs font-medium text-navy focus:bg-white focus:outline-none"
              >
                <option value="contacted_at">Tương tác gần nhất</option>
                <option value="first_created_at">Ngày tạo Lead</option>
                <option value="message_count">Số tin nhắn</option>
                <option value="name">Tên khách</option>
              </select>
              <select
                value={sortDir}
                onChange={(e) => setSortDir(e.target.value as 'desc' | 'asc')}
                className="w-24 px-2 py-2 bg-slate-50 border border-slate-200/90 rounded-xl text-xs font-medium text-navy focus:bg-white focus:outline-none"
              >
                <option value="desc">Giảm dần</option>
                <option value="asc">Tăng dần</option>
              </select>
            </div>
          </div>
        </div>

        {/* Date range + Toggles */}
        <div className="pt-2 border-t border-slate-100 flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap items-center gap-2">
            <select
              value={dateField}
              onChange={(e) => setDateField(e.target.value as 'contacted_at' | 'first_created_at')}
              className="px-2.5 py-1.5 bg-slate-50 border border-slate-200/90 rounded-lg text-xs font-medium text-navy focus:outline-none"
            >
              <option value="contacted_at">Lọc theo Tương tác gần nhất</option>
              <option value="first_created_at">Lọc theo Ngày tạo Lead</option>
            </select>
            <div className="flex items-center gap-1.5 bg-slate-50 border border-slate-200/80 rounded-lg px-2.5 py-1">
              <input
                type="date"
                value={dateFrom}
                onChange={(e) => setDateFrom(e.target.value)}
                className="bg-transparent text-xs font-mono text-navy focus:outline-none"
              />
              <span className="text-slate-300 text-xs">→</span>
              <input
                type="date"
                value={dateTo}
                onChange={(e) => setDateTo(e.target.value)}
                className="bg-transparent text-xs font-mono text-navy focus:outline-none"
              />
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-4 text-xs text-slate-700">
            {selectedEmployees.length > 0 && (
              <label className="inline-flex items-center gap-1.5 cursor-pointer select-none">
                <input
                  type="checkbox"
                  checked={employeeMatchMode === 'exact'}
                  onChange={(e) => setEmployeeMatchMode(e.target.checked ? 'exact' : 'any')}
                  className="rounded border-slate-300 text-brand-600 w-3.5 h-3.5"
                />
                <span>Chỉ hội thoại phụ trách riêng (bỏ phối hợp)</span>
              </label>
            )}
            <label className="inline-flex items-center gap-1.5 cursor-pointer select-none">
              <input
                type="checkbox"
                checked={excludeZaloGroups}
                onChange={(e) => setExcludeZaloGroups(e.target.checked)}
                className="rounded border-slate-300 text-brand-600 w-3.5 h-3.5"
              />
              <span>Loại nhóm chat Zalo (pzl_g_)</span>
            </label>
            <label className="inline-flex items-center gap-1.5 cursor-pointer select-none">
              <input
                type="checkbox"
                checked={dedupePhone}
                onChange={(e) => setDedupePhone(e.target.checked)}
                className="rounded border-slate-300 text-brand-600 w-3.5 h-3.5"
              />
              <span>Gộp trùng theo SĐT</span>
            </label>
          </div>
        </div>

        {/* Action buttons */}
        <div className="pt-2 border-t border-slate-100 flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap items-center gap-2.5">
            <button
              type="button"
              onClick={() => runPreview(1, pageSize)}
              disabled={loadingPreview || selectedColumns.length === 0}
              className="inline-flex items-center gap-2 px-4 py-2.5 gradient-brand text-white text-xs font-bold rounded-xl shadow-md shadow-brand-500/20 hover:opacity-95 transition-all disabled:opacity-50 cursor-pointer"
            >
              {loadingPreview ? <Loader2 className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4" />}
              <span>Chạy Query (Xem trước)</span>
            </button>

            <button
              type="button"
              onClick={handleExportExcel}
              disabled={exporting || selectedColumns.length === 0}
              className="inline-flex items-center gap-2 px-4 py-2.5 bg-emerald-600 hover:bg-emerald-700 text-white text-xs font-bold rounded-xl shadow-md shadow-emerald-600/20 transition-all disabled:opacity-50 cursor-pointer"
            >
              {exporting ? <Loader2 className="w-4 h-4 animate-spin" /> : <Download className="w-4 h-4" />}
              <span>Xuất Excel (.xlsx)</span>
            </button>
          </div>
        </div>

        {errorMsg && (
          <div className="px-3.5 py-2.5 rounded-xl bg-rose-50 border border-rose-200 text-rose-700 text-xs font-medium">
            {errorMsg}
          </div>
        )}
        {exportNotice && (
          <div className="px-3.5 py-2.5 rounded-xl bg-emerald-50 border border-emerald-200 text-emerald-800 text-xs font-medium">
            {exportNotice}
          </div>
        )}
      </div>

      {/* Preview Table Card */}
      <div className="bg-white rounded-2xl border border-slate-200/80 shadow-card overflow-hidden">
        <div className="px-5 py-3.5 border-b border-slate-100 flex flex-wrap items-center justify-between gap-2">
          <div className="flex flex-wrap items-center gap-2">
            <h4 className="text-xs font-bold text-navy uppercase tracking-wider">3. Kết quả xem trước</h4>
            {preview && (
              <span className="px-2.5 py-0.5 rounded-full text-[11px] font-mono font-bold bg-brand-50 text-brand-700 tabular-nums">
                {preview.total.toLocaleString('vi-VN')} dòng
              </span>
            )}
          </div>

          {preview && (
            <div className="flex items-center gap-2 text-xs">
              <span className="text-slate-400">Hiển thị:</span>
              <select
                value={pageSize}
                onChange={(e) => runPreview(1, Number(e.target.value))}
                className="px-2 py-1 bg-slate-50 border border-slate-200 rounded-lg text-xs font-mono text-navy"
              >
                <option value={25}>25 / trang</option>
                <option value={50}>50 / trang</option>
                <option value={100}>100 / trang</option>
              </select>
            </div>
          )}
        </div>

        {!preview ? (
          <div className="p-8 text-center">
            <p className="text-xs text-slate-500">
              Chọn cột & bộ lọc rồi bấm "Chạy Query (Xem trước)" hoặc "Xuất Excel (.xlsx)".
            </p>
          </div>
        ) : preview.rows.length === 0 ? (
          <div className="p-10 text-center text-xs text-slate-500">
            Không có bản ghi nào khớp với bộ lọc hiện tại.
          </div>
        ) : (
          <>
            <div className="overflow-x-auto">
              <table className="w-full text-left border-collapse">
                <thead>
                  <tr className="bg-slate-50/90 border-b border-slate-200/80">
                    <th className="py-2.5 px-3 text-[11px] font-bold text-slate-500 uppercase tracking-wider w-12">
                      #
                    </th>
                    {preview.columns.map((col) => (
                      <th
                        key={col.key}
                        className="py-2.5 px-3 text-[11px] font-bold text-slate-600 uppercase tracking-wider whitespace-nowrap"
                      >
                        {col.label}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 text-xs">
                  {preview.rows.map((row, idx) => (
                    <tr key={idx} className="hover:bg-slate-50/80 transition-colors">
                      <td className="py-2.5 px-3 font-mono text-[11px] text-slate-400 tabular-nums">
                        {(preview.page - 1) * preview.page_size + idx + 1}
                      </td>
                      {preview.columns.map((col) => {
                        const val = row[col.key];
                        const strVal = val === null || val === undefined ? '' : String(val);

                        if ((col.key === 'pancake_link' || col.key === 'post_url') && strVal.startsWith('http')) {
                          return (
                            <td key={col.key} className="py-2.5 px-3 whitespace-nowrap">
                              <a
                                href={strVal}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg bg-brand-50 hover:bg-brand-100 text-brand-700 font-semibold text-[11px] transition-colors"
                              >
                                <span>{col.key === 'pancake_link' ? 'Mở Pancake' : 'Mở bài viết'}</span>
                                <ExternalLink className="w-3 h-3" />
                              </a>
                            </td>
                          );
                        }

                        if (col.key === 'phone_number') {
                          return (
                            <td key={col.key} className="py-2.5 px-3 font-mono font-semibold text-navy whitespace-nowrap tabular-nums">
                              {strVal || <span className="text-slate-300">—</span>}
                            </td>
                          );
                        }

                        if (col.key === 'is_student') {
                          const isStu = strVal === 'Đã là học viên';
                          return (
                            <td key={col.key} className="py-2.5 px-3 whitespace-nowrap">
                              <span
                                className={`inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-semibold border ${
                                  isStu
                                    ? 'bg-amber-50 text-amber-800 border-amber-200'
                                    : 'bg-emerald-50 text-emerald-700 border-emerald-200'
                                }`}
                              >
                                {strVal}
                              </span>
                            </td>
                          );
                        }

                        return (
                          <td
                            key={col.key}
                            className={`py-2.5 px-3 text-slate-700 max-w-[260px] truncate ${
                              ['first_created_at', 'contacted_at', 'phone_at', 'message_count'].includes(col.key)
                                ? 'font-mono text-[11px] tabular-nums whitespace-nowrap'
                                : ''
                            }`}
                            title={strVal}
                          >
                            {strVal || <span className="text-slate-300">—</span>}
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* Pagination Footer */}
            <div className="px-5 py-3 border-t border-slate-100 bg-slate-50/50 flex flex-wrap items-center justify-between gap-2 text-xs">
              <span className="text-slate-500 font-mono tabular-nums">
                Trang {preview.page} / {preview.total_pages} (tổng {preview.total.toLocaleString('vi-VN')} dòng)
              </span>
              <div className="flex items-center gap-1.5">
                <button
                  type="button"
                  disabled={loadingPreview || preview.page <= 1}
                  onClick={() => runPreview(preview.page - 1, pageSize)}
                  className="inline-flex items-center gap-1 px-3 py-1.5 bg-white border border-slate-200 rounded-lg text-xs font-semibold text-navy hover:bg-slate-50 disabled:opacity-40 cursor-pointer"
                >
                  <ChevronLeft className="w-3.5 h-3.5" />
                  <span>Trước</span>
                </button>
                <button
                  type="button"
                  disabled={loadingPreview || preview.page >= preview.total_pages}
                  onClick={() => runPreview(preview.page + 1, pageSize)}
                  className="inline-flex items-center gap-1 px-3 py-1.5 bg-white border border-slate-200 rounded-lg text-xs font-semibold text-navy hover:bg-slate-50 disabled:opacity-40 cursor-pointer"
                >
                  <span>Sau</span>
                  <ChevronRight className="w-3.5 h-3.5" />
                </button>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
};
