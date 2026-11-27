import { useState, useEffect, useMemo, useRef, useCallback } from 'react';
import {
  BookOpen,
  Search,
  RefreshCw,
  Copy,
  Check,
  ExternalLink,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Users,
  X,
} from 'lucide-react';
import {
  fetchClassListStudents,
  clearClientApiCache,
  type ClassStudentItem,
} from '../services/api';
import { stripVnAccents } from '../config/permissions';
import { toSafeHttpUrl, copyToClipboard } from '../utils/format';
import { showAppToast } from '../utils/toast';
import { ErrorBanner } from './ErrorBanner';

const PAGE_SIZE = 25;

const formatShortLink = (raw: string): string => {
  const s = raw.trim();
  if (s.length <= 34) return s;
  return `${s.slice(0, 20)}…${s.slice(-10)}`;
};

const splitClassPrefixNum = (cls: string): { prefix: string; num: number } | null => {
  const m = cls.trim().match(/^(.*?)(\d+)\s*$/);
  if (!m) return null;
  return { prefix: m[1].trim().toLowerCase(), num: parseInt(m[2], 10) };
};

const sortClassesChronologically = (classes: string[]): string[] => {
  if (classes.length <= 1) return classes;
  const result = [...classes];
  // Sắp xếp tự nhiên theo số khóa cho các lớp cùng tiền tố (vd: K62, K61 -> K61, K62)
  for (let i = 0; i < result.length; i++) {
    for (let j = i + 1; j < result.length; j++) {
      const a = splitClassPrefixNum(result[i]);
      const b = splitClassPrefixNum(result[j]);
      if (a && b && a.prefix === b.prefix && a.num > b.num) {
        [result[i], result[j]] = [result[j], result[i]];
      }
    }
  }
  return result;
};

const getStudentTypeInfo = (
  lop: string[],
  selectedClass: string
): { isOld: boolean; label: string; fromClasses: string[] } => {
  const ordered = sortClassesChronologically(lop);
  if (ordered.length <= 1) {
    return { isOld: false, label: 'Học viên mới', fromClasses: [] };
  }
  if (selectedClass && selectedClass !== '__NONE__') {
    const idx = ordered.indexOf(selectedClass);
    if (idx > 0) {
      const prev = ordered.slice(0, idx);
      return {
        isOld: true,
        label: `Học viên cũ (Từ ${prev.join(', ')})`,
        fromClasses: prev,
      };
    }
    return { isOld: false, label: 'Học viên mới', fromClasses: [] };
  }
  const prev = ordered.slice(0, -1);
  return {
    isOld: true,
    label: `Học viên cũ (Từ ${prev.join(', ')})`,
    fromClasses: prev,
  };
};

export function ClassListDashboard() {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [students, setStudents] = useState<ClassStudentItem[]>([]);
  const [classes, setClasses] = useState<string[]>([]);
  const [classCounts, setClassCounts] = useState<Record<string, number>>({});
  const [unassignedClassCount, setUnassignedClassCount] = useState(0);
  const [staffList, setStaffList] = useState<string[]>([]);

  // Filters
  const [selectedClass, setSelectedClass] = useState<string>(''); // '' = Tất cả các lớp
  const [classDropdownOpen, setClassDropdownOpen] = useState(false);
  const [classSearch, setClassSearch] = useState('');
  const [selectedStaff, setSelectedStaff] = useState<string>('');
  const [searchQuery, setSearchQuery] = useState('');
  const [currentPage, setCurrentPage] = useState(1);

  // Copy feedback key (e.g. "phone:<id>" | "pancake:<id>" | "support:<id>")
  const [copiedKey, setCopiedKey] = useState<string | null>(null);
  const copyTimerRef = useRef<number | null>(null);
  const classDropdownRef = useRef<HTMLDivElement | null>(null);

  const loadData = useCallback(async (force: boolean = false) => {
    setLoading(true);
    setError(null);
    try {
      if (force) {
        clearClientApiCache('/class-list/students');
      }
      const res = await fetchClassListStudents({ force }, { skipCache: force });
      if (res.ok) {
        setStudents(res.students || []);
        setClasses(res.classes || []);
        setClassCounts(res.class_counts || {});
        setUnassignedClassCount(res.unassigned_class_count || 0);
        setStaffList(res.staff_list || []);
      }
    } catch (err: any) {
      const msg =
        err?.response?.data?.detail ||
        'Không thể tải danh sách lớp học. Vui lòng thử lại.';
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadData(false);
  }, [loadData]);

  useEffect(() => {
    return () => {
      if (copyTimerRef.current) window.clearTimeout(copyTimerRef.current);
    };
  }, []);

  useEffect(() => {
    if (!classDropdownOpen) return;
    const onDocClick = (e: MouseEvent) => {
      if (classDropdownRef.current && !classDropdownRef.current.contains(e.target as Node)) {
        setClassDropdownOpen(false);
      }
    };
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setClassDropdownOpen(false);
    };
    document.addEventListener('mousedown', onDocClick);
    window.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('mousedown', onDocClick);
      window.removeEventListener('keydown', onKeyDown);
    };
  }, [classDropdownOpen]);

  useEffect(() => {
    setCurrentPage(1);
  }, [selectedClass, selectedStaff, searchQuery]);

  const filteredClassOptions = useMemo(() => {
    const q = stripVnAccents(classSearch);
    if (!q) return classes;
    return classes.filter((c) => stripVnAccents(c).includes(q));
  }, [classes, classSearch]);

  const filteredStudents = useMemo(() => {
    const q = stripVnAccents(searchQuery);
    const qDigits = searchQuery.replace(/\D/g, '');
    const staffAscii = stripVnAccents(selectedStaff);

    return students.filter((st) => {
      if (selectedClass) {
        if (selectedClass === '__NONE__') {
          if (st.lop.length > 0) return false;
        } else if (!st.lop.includes(selectedClass)) {
          return false;
        }
      }

      if (selectedStaff) {
        const rawNv = (st.nvCS || '').trim();
        if (selectedStaff === 'Chưa phân công') {
          if (rawNv && rawNv.toLowerCase() !== 'chưa phân công') return false;
        } else {
          const parts = rawNv.split(/[,;/]+/).map((p) => stripVnAccents(p)).filter(Boolean);
          if (!parts.includes(staffAscii)) return false;
        }
      }

      if (q) {
        const matchName = stripVnAccents(st.hoTen).includes(q);
        const matchPhone = Boolean(qDigits && st.sdt.replace(/\D/g, '').includes(qDigits));
        const matchStaff = stripVnAccents(st.nvCS).includes(q);
        const matchClass = st.lop.some((c) => stripVnAccents(c).includes(q));
        if (!matchName && !matchPhone && !matchStaff && !matchClass) return false;
      }

      return true;
    });
  }, [students, selectedClass, selectedStaff, searchQuery]);

  const totalPages = Math.max(1, Math.ceil(filteredStudents.length / PAGE_SIZE));
  const pagedStudents = useMemo(() => {
    const start = (currentPage - 1) * PAGE_SIZE;
    return filteredStudents.slice(start, start + PAGE_SIZE);
  }, [filteredStudents, currentPage]);

  const handleCopy = async (key: string, value: string, label: string) => {
    if (!value) return;
    const ok = await copyToClipboard(value);
    if (ok) {
      setCopiedKey(key);
      showAppToast(`Đã copy ${label}`, 'success');
      if (copyTimerRef.current) window.clearTimeout(copyTimerRef.current);
      copyTimerRef.current = window.setTimeout(() => {
        setCopiedKey((prev) => (prev === key ? null : prev));
      }, 1800);
    } else {
      showAppToast('Không thể copy vào bộ nhớ tạm.', 'error');
    }
  };

  const selectedClassLabel =
    selectedClass === ''
      ? `Tất cả các lớp (${classes.length})`
      : selectedClass === '__NONE__'
      ? 'Chưa xếp lớp'
      : `Lớp ${selectedClass}`;

  return (
    <div className="space-y-4">
      {error && <ErrorBanner message={error} onRetry={() => loadData(true)} />}

      {/* Header + Filter Toolbar */}
      <div className="bg-white rounded-2xl border border-slate-200/80 shadow-card p-4 space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2.5">
            <div className="w-9 h-9 rounded-xl bg-eztech-light border border-eztech-border text-eztech flex items-center justify-center shrink-0">
              <BookOpen className="w-4.5 h-4.5" aria-hidden="true" />
            </div>
            <div>
              <h2 className="text-sm font-bold text-navy">Danh Sách Lớp Học & Học Viên</h2>
              <p className="text-[11px] text-slate-500">
                Chọn lớp để theo dõi học viên, sao chép nhanh link Pancake & nhóm Support 1-1.
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            {/* Tổng số học viên theo lớp đang lọc */}
            <div className="inline-flex items-center gap-2 px-3 py-1.5 rounded-xl bg-eztech-light border border-eztech-border text-eztech">
              <Users className="w-4 h-4 shrink-0" aria-hidden="true" />
              <span className="text-xs font-medium">
                {selectedClass && selectedClass !== '__NONE__' ? `Sĩ số ${selectedClass}:` : 'Tổng học viên:'}
              </span>
              <span className="text-sm font-bold font-mono tabular-nums">
                {filteredStudents.length.toLocaleString('vi-VN')}
              </span>
            </div>

            <button
              type="button"
              disabled={loading}
              onClick={() => loadData(true)}
              aria-label="Làm mới danh sách lớp học"
              title="Làm mới dữ liệu"
              className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold text-navy bg-slate-50 hover:bg-eztech-light hover:text-eztech border border-slate-200 rounded-xl transition-colors cursor-pointer disabled:opacity-50"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} aria-hidden="true" />
              <span className="hidden sm:inline">Làm mới</span>
            </button>
          </div>
        </div>

        {/* Bộ lọc chính + phụ */}
        <div className="flex flex-wrap items-center gap-2.5 pt-2 border-t border-slate-100">
          {/* 1. Dropdown chọn lớp học có tìm kiếm nhanh */}
          <div className="relative min-w-[230px] flex-1 sm:flex-initial" ref={classDropdownRef}>
            <div className="flex items-center gap-1">
              <button
                type="button"
                aria-haspopup="listbox"
                aria-expanded={classDropdownOpen}
                onClick={() => setClassDropdownOpen((prev) => !prev)}
                className={`w-full flex items-center justify-between gap-2 px-3 py-2 text-xs font-semibold rounded-xl border transition-all cursor-pointer ${
                  selectedClass
                    ? 'bg-eztech text-white border-eztech shadow-sm'
                    : 'bg-white text-navy border-slate-200 hover:border-eztech/60'
                }`}
              >
                <span className="truncate">{selectedClassLabel}</span>
                <ChevronDown
                  className={`w-3.5 h-3.5 shrink-0 transition-transform ${classDropdownOpen ? 'rotate-180' : ''}`}
                  aria-hidden="true"
                />
              </button>
              {selectedClass && (
                <button
                  type="button"
                  onClick={() => setSelectedClass('')}
                  aria-label="Bỏ chọn lớp"
                  title="Xem tất cả các lớp"
                  className="p-2 text-slate-400 hover:text-rose-600 hover:bg-rose-50 rounded-xl border border-slate-200 transition-colors cursor-pointer"
                >
                  <X className="w-3.5 h-3.5" aria-hidden="true" />
                </button>
              )}
            </div>

            {classDropdownOpen && (
              <div
                role="listbox"
                className="absolute left-0 mt-1.5 w-72 bg-white rounded-xl border border-slate-200 shadow-xl z-30 overflow-hidden"
              >
                <div className="p-2 border-b border-slate-100">
                  <div className="relative">
                    <Search className="w-3.5 h-3.5 text-slate-400 absolute left-2.5 top-1/2 -translate-y-1/2 pointer-events-none" />
                    <input
                      type="text"
                      autoFocus
                      placeholder="Tìm nhanh tên lớp..."
                      value={classSearch}
                      onChange={(e) => setClassSearch(e.target.value)}
                      className="w-full pl-8 pr-2.5 py-1.5 text-xs bg-slate-50 border border-slate-200 rounded-lg text-navy focus:outline-none focus:ring-2 focus:ring-eztech/20 focus:border-eztech"
                    />
                  </div>
                </div>

                <div className="max-h-64 overflow-y-auto py-1">
                  {!classSearch.trim() && (
                    <>
                      <button
                        type="button"
                        role="option"
                        aria-selected={selectedClass === ''}
                        onClick={() => {
                          setSelectedClass('');
                          setClassDropdownOpen(false);
                          setClassSearch('');
                        }}
                        className={`w-full px-3 py-2 text-left text-xs flex items-center justify-between transition-colors cursor-pointer ${
                          selectedClass === ''
                            ? 'bg-eztech-light text-eztech font-semibold'
                            : 'text-navy hover:bg-slate-50'
                        }`}
                      >
                        <span>Tất cả các lớp</span>
                        <span className="font-mono text-[11px] px-1.5 py-0.5 rounded bg-slate-100 text-slate-600">
                          {students.length}
                        </span>
                      </button>
                      {unassignedClassCount > 0 && (
                        <button
                          type="button"
                          role="option"
                          aria-selected={selectedClass === '__NONE__'}
                          onClick={() => {
                            setSelectedClass('__NONE__');
                            setClassDropdownOpen(false);
                            setClassSearch('');
                          }}
                          className={`w-full px-3 py-2 text-left text-xs flex items-center justify-between transition-colors cursor-pointer ${
                            selectedClass === '__NONE__'
                              ? 'bg-eztech-light text-eztech font-semibold'
                              : 'text-slate-600 hover:bg-slate-50'
                          }`}
                        >
                          <span>Chưa xếp lớp</span>
                          <span className="font-mono text-[11px] px-1.5 py-0.5 rounded bg-slate-100 text-slate-500">
                            {unassignedClassCount}
                          </span>
                        </button>
                      )}
                      <div className="my-1 border-t border-slate-100" />
                    </>
                  )}

                  {filteredClassOptions.length === 0 ? (
                    <div className="px-3 py-4 text-center text-xs text-slate-400">
                      Không tìm thấy lớp phù hợp
                    </div>
                  ) : (
                    filteredClassOptions.map((cls) => {
                      const active = selectedClass === cls;
                      return (
                        <button
                          key={cls}
                          type="button"
                          role="option"
                          aria-selected={active}
                          onClick={() => {
                            setSelectedClass(cls);
                            setClassDropdownOpen(false);
                            setClassSearch('');
                          }}
                          className={`w-full px-3 py-2 text-left text-xs flex items-center justify-between transition-colors cursor-pointer ${
                            active
                              ? 'bg-eztech-light text-eztech font-semibold'
                              : 'text-navy hover:bg-slate-50'
                          }`}
                        >
                          <span className="truncate">{cls}</span>
                          <span className="font-mono text-[11px] px-1.5 py-0.5 rounded bg-slate-100 text-slate-600 shrink-0 ml-2">
                            {classCounts[cls] ?? 0}
                          </span>
                        </button>
                      );
                    })
                  )}
                </div>
              </div>
            )}
          </div>

          {/* 2. Tìm kiếm nhanh Tên học viên / SĐT */}
          <div className="relative flex-1 min-w-[210px]">
            <Search className="w-3.5 h-3.5 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2 pointer-events-none" />
            <input
              type="text"
              aria-label="Tìm theo tên học viên hoặc số điện thoại"
              placeholder="Tìm tên học viên, SĐT..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full pl-8 pr-8 py-2 text-xs bg-white text-navy border border-slate-200 rounded-xl focus:outline-none focus:ring-2 focus:ring-eztech/20 focus:border-eztech"
            />
            {searchQuery && (
              <button
                type="button"
                onClick={() => setSearchQuery('')}
                aria-label="Xóa từ khóa tìm kiếm"
                className="absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600 cursor-pointer"
              >
                <X className="w-3.5 h-3.5" aria-hidden="true" />
              </button>
            )}
          </div>

          {/* 3. Lọc theo Nhân viên chăm sóc */}
          <div className="flex items-center gap-1 shrink-0">
            <select
              aria-label="Lọc theo nhân viên chăm sóc"
              value={selectedStaff}
              onChange={(e) => setSelectedStaff(e.target.value)}
              className="px-3 py-2 text-xs font-medium border border-slate-200 rounded-xl bg-white text-navy focus:outline-none focus:ring-2 focus:ring-eztech/20 focus:border-eztech cursor-pointer max-w-[200px]"
            >
              <option value="">Tất cả NV chăm sóc ({staffList.length})</option>
              {staffList.map((st) => (
                <option key={st} value={st}>
                  {st}
                </option>
              ))}
            </select>
            {selectedStaff && (
              <button
                type="button"
                onClick={() => setSelectedStaff('')}
                aria-label="Bỏ lọc nhân viên chăm sóc"
                className="p-1.5 text-slate-400 hover:text-slate-600 rounded-lg cursor-pointer"
                title="Bỏ lọc NV chăm sóc"
              >
                <X className="w-3.5 h-3.5" aria-hidden="true" />
              </button>
            )}
          </div>
        </div>
      </div>

      {/* Bảng 7 cột danh sách học viên */}
      <div className="bg-white rounded-2xl border border-slate-200/80 shadow-card overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="bg-slate-50/90 border-b border-slate-200/80 text-[11px] font-bold uppercase tracking-wider text-slate-500">
                <th className="py-3 px-4">Tên học viên</th>
                <th className="py-3 px-4">Số điện thoại (SĐT)</th>
                <th className="py-3 px-4">Link Pancake</th>
                <th className="py-3 px-4">Link Support 1-1</th>
                <th className="py-3 px-4">Lớp đang học</th>
                <th className="py-3 px-4">Học viên</th>
                <th className="py-3 px-4">Nhân viên chăm sóc</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 text-xs">
              {loading && students.length === 0 ? (
                <tr>
                  <td colSpan={7} className="py-16 text-center text-slate-400">
                    <div className="inline-flex flex-col items-center gap-2">
                      <div className="animate-spin rounded-full h-6 w-6 border-2 border-slate-200 border-t-eztech" />
                      <span>Đang tải danh sách lớp học...</span>
                    </div>
                  </td>
                </tr>
              ) : pagedStudents.length === 0 ? (
                <tr>
                  <td colSpan={7} className="py-14 text-center text-slate-400">
                    Không có học viên nào khớp với bộ lọc hiện tại.
                  </td>
                </tr>
              ) : (
                pagedStudents.map((st) => {
                  const safePancakeUrl = toSafeHttpUrl(st.linkPancake);
                  const safeSupportUrl = toSafeHttpUrl(st.linkSupport);
                  const phoneCopied = copiedKey === `phone:${st.id}`;
                  const pancakeCopied = copiedKey === `pancake:${st.id}`;
                  const supportCopied = copiedKey === `support:${st.id}`;
                  const studentType = getStudentTypeInfo(st.lop, selectedClass);

                  return (
                    <tr key={st.id} className="hover:bg-slate-50/70 transition-colors">
                      {/* 1. Tên học viên */}
                      <td className="py-3 px-4 font-semibold text-navy whitespace-nowrap">
                        {st.hoTen || '—'}
                      </td>

                      {/* 2. Số điện thoại (SĐT) + nút copy nhanh */}
                      <td className="py-3 px-4 whitespace-nowrap">
                        {st.sdt ? (
                          <div className="inline-flex items-center gap-1.5">
                            <span className="font-mono font-medium text-navy tabular-nums">
                              {st.sdt}
                            </span>
                            <button
                              type="button"
                              onClick={() => handleCopy(`phone:${st.id}`, st.sdt, `SĐT ${st.sdt}`)}
                              aria-label={`Copy số điện thoại ${st.sdt}`}
                              title="Copy SĐT"
                              className="p-1 rounded-md text-slate-400 hover:text-eztech hover:bg-eztech-light transition-colors cursor-pointer"
                            >
                              {phoneCopied ? (
                                <Check className="w-3.5 h-3.5 text-emerald-600" aria-hidden="true" />
                              ) : (
                                <Copy className="w-3.5 h-3.5" aria-hidden="true" />
                              )}
                            </button>
                          </div>
                        ) : (
                          <span className="text-slate-400">-</span>
                        )}
                      </td>

                      {/* 3. Link Pancake: click vào link để copy + nút mở tab mới */}
                      <td className="py-3 px-4">
                        {st.linkPancake ? (
                          <div className="flex items-center gap-1.5 flex-wrap">
                            <button
                              type="button"
                              onClick={() => handleCopy(`pancake:${st.id}`, st.linkPancake, 'Link Pancake')}
                              title={`Click để copy: ${st.linkPancake}`}
                              className="inline-flex items-center gap-1 max-w-[200px] px-2 py-1 rounded-lg bg-slate-50 hover:bg-eztech-light border border-slate-200 hover:border-eztech-border text-eztech font-mono text-[11px] transition-colors cursor-pointer"
                            >
                              {pancakeCopied ? (
                                <Check className="w-3 h-3 text-emerald-600 shrink-0" aria-hidden="true" />
                              ) : (
                                <Copy className="w-3 h-3 shrink-0 opacity-70" aria-hidden="true" />
                              )}
                              <span className="truncate">{formatShortLink(st.linkPancake)}</span>
                            </button>
                            {safePancakeUrl && (
                              <a
                                href={safePancakeUrl}
                                target="_blank"
                                rel="noopener noreferrer"
                                title="Mở hội thoại Pancake trong tab mới"
                                className="inline-flex items-center gap-1 px-2 py-1 rounded-lg bg-eztech-light hover:bg-eztech text-eztech hover:text-white border border-eztech-border text-[11px] font-semibold transition-colors whitespace-nowrap"
                              >
                                <span>Mở Pancake</span>
                                <ExternalLink className="w-3 h-3" aria-hidden="true" />
                              </a>
                            )}
                          </div>
                        ) : (
                          <span className="text-slate-400">-</span>
                        )}
                      </td>

                      {/* 4. Link Support 1-1: click vào link để copy + nút mở Pancake */}
                      <td className="py-3 px-4">
                        {st.linkSupport ? (
                          <div className="flex items-center gap-1.5 flex-wrap">
                            <button
                              type="button"
                              onClick={() => handleCopy(`support:${st.id}`, st.linkSupport, 'Link Support 1-1')}
                              title={`Click để copy: ${st.linkSupport}`}
                              className="inline-flex items-center gap-1 max-w-[200px] px-2 py-1 rounded-lg bg-slate-50 hover:bg-emerald-50 border border-slate-200 hover:border-emerald-200 text-emerald-700 font-mono text-[11px] transition-colors cursor-pointer"
                            >
                              {supportCopied ? (
                                <Check className="w-3 h-3 text-emerald-600 shrink-0" aria-hidden="true" />
                              ) : (
                                <Copy className="w-3 h-3 shrink-0 opacity-70" aria-hidden="true" />
                              )}
                              <span className="truncate">{formatShortLink(st.linkSupport)}</span>
                            </button>
                            {safeSupportUrl && (
                              <a
                                href={safeSupportUrl}
                                target="_blank"
                                rel="noopener noreferrer"
                                title="Mở Link Support 1-1 trên Pancake trong tab mới"
                                className="inline-flex items-center gap-1 px-2 py-1 rounded-lg bg-emerald-50 hover:bg-emerald-600 text-emerald-700 hover:text-white border border-emerald-200 text-[11px] font-semibold transition-colors whitespace-nowrap"
                              >
                                <span>Mở Pancake</span>
                                <ExternalLink className="w-3 h-3" aria-hidden="true" />
                              </a>
                            )}
                          </div>
                        ) : (
                          <span className="text-slate-400">-</span>
                        )}
                      </td>

                      {/* 5. Lớp đang học (badge/tag) */}
                      <td className="py-3 px-4">
                        {st.lop.length > 0 ? (
                          <div className="flex flex-wrap gap-1">
                            {st.lop.map((cls) => (
                              <button
                                key={cls}
                                type="button"
                                onClick={() => setSelectedClass(cls)}
                                title={`Lọc theo lớp ${cls}`}
                                className={`inline-flex items-center px-2 py-0.5 rounded-md text-[11px] font-semibold border transition-colors cursor-pointer ${
                                  selectedClass === cls
                                    ? 'bg-eztech text-white border-eztech'
                                    : 'bg-eztech-light text-eztech border-eztech-border hover:bg-eztech hover:text-white'
                                }`}
                              >
                                {cls}
                              </button>
                            ))}
                          </div>
                        ) : (
                          <span className="inline-flex items-center px-2 py-0.5 rounded-md text-[11px] font-medium bg-slate-100 text-slate-500 border border-slate-200">
                            Chưa xếp lớp
                          </span>
                        )}
                      </td>

                      {/* 6. Học viên (Mới / Cũ từ K...) */}
                      <td className="py-3 px-4 whitespace-nowrap">
                        {studentType.isOld ? (
                          <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[11px] font-semibold bg-amber-50 text-amber-800 border border-amber-200">
                            <span>Học viên cũ</span>
                            <span className="font-normal text-amber-700">
                              (Từ {studentType.fromClasses.join(', ')})
                            </span>
                          </span>
                        ) : (
                          <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-[11px] font-semibold bg-emerald-50 text-emerald-700 border border-emerald-200">
                            Học viên mới
                          </span>
                        )}
                      </td>

                      {/* 7. Nhân viên chăm sóc */}
                      <td className="py-3 px-4 text-slate-700 whitespace-nowrap">
                        {st.nvCS || <span className="text-slate-400">-</span>}
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>

        {/* Pagination */}
        {filteredStudents.length > PAGE_SIZE && (
          <div className="px-4 py-3 border-t border-slate-100 flex items-center justify-between text-xs text-slate-500">
            <span>
              Hiển thị{' '}
              <strong className="text-navy font-mono">
                {(currentPage - 1) * PAGE_SIZE + 1}–
                {Math.min(currentPage * PAGE_SIZE, filteredStudents.length)}
              </strong>{' '}
              / <strong className="text-navy font-mono">{filteredStudents.length}</strong> học viên
            </span>
            <div className="flex items-center gap-1.5">
              <button
                type="button"
                aria-label="Trang trước"
                disabled={currentPage <= 1}
                onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
                className="p-1.5 rounded-lg border border-slate-200 disabled:opacity-40 hover:bg-slate-50 cursor-pointer disabled:cursor-not-allowed"
              >
                <ChevronLeft className="w-4 h-4" />
              </button>
              <span className="px-2 font-mono font-semibold text-navy">
                Trang {currentPage} / {totalPages}
              </span>
              <button
                type="button"
                aria-label="Trang sau"
                disabled={currentPage >= totalPages}
                onClick={() => setCurrentPage((p) => Math.min(totalPages, p + 1))}
                className="p-1.5 rounded-lg border border-slate-200 disabled:opacity-40 hover:bg-slate-50 cursor-pointer disabled:cursor-not-allowed"
              >
                <ChevronRight className="w-4 h-4" />
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
