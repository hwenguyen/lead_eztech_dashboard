import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  addMonths,
  eachDayOfInterval,
  endOfMonth,
  endOfWeek,
  format,
  isSameMonth,
  parseISO,
  startOfMonth,
  startOfWeek,
  subMonths,
} from 'date-fns';
import {
  Bell,
  Calendar as CalendarIcon,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Clock,
  FileSpreadsheet,
  Filter,
  GraduationCap,
  ListTodo,
  Plus,
  RefreshCw,
  Search,
  Settings2,
  Upload,
  Users,
  X,
} from 'lucide-react';
import {
  fetchChecklistsMonthSummary,
  fetchClassSchedule,
  fetchWorkReminders,
  syncClassSchedule,
  uploadClassScheduleFile,
  updateWorkReminder,
  type ClassScheduleEvent,
  type WorkReminderItem,
} from '../services/api';
import { showAppToast } from '../utils/toast';
import { AccessibleModal } from './AccessibleModal';

interface BulletinCalendarBlockProps {
  isAdmin: boolean;
  adminOwnerFilter: string;
  todayStr: string;
  refreshTrigger: number;
  onCreateReminderForDate: (dateStr: string) => void;
  onEditReminder: (rem: WorkReminderItem) => void;
  onSelectChecklistDate: (dateStr: string) => void;
  onReminderMutated: () => void;
}

type EventTypeFilter = 'all' | 'reminders' | 'classes' | 'checklists';
type StatusFilter = 'all' | 'active' | 'done';

const WEEKDAY_HEADERS = ['T2', 'T3', 'T4', 'T5', 'T6', 'T7', 'CN'];

const VIETNAMESE_WEEKDAYS: Record<number, string> = {
  0: 'Chủ nhật',
  1: 'Thứ 2',
  2: 'Thứ 3',
  3: 'Thứ 4',
  4: 'Thứ 5',
  5: 'Thứ 6',
  6: 'Thứ 7',
};

function formatDisplayDate(dateStr: string): string {
  try {
    const d = parseISO(dateStr);
    const wd = VIETNAMESE_WEEKDAYS[d.getDay()] || '';
    return `${wd}, ${format(d, 'dd/MM/yyyy')}`;
  } catch {
    return dateStr;
  }
}

function getClassChipStyle(ev: ClassScheduleEvent): string {
  if (ev.is_planned) {
    return 'bg-slate-50 text-slate-600 border-dashed border-slate-300';
  }
  const lower = (ev.course_type || '').toLowerCase();
  if (lower.includes('power bi') || lower.includes('pbi')) {
    return 'bg-violet-50 text-violet-700 border-violet-200';
  }
  if (lower.includes('power query')) {
    return 'bg-amber-50 text-amber-800 border-amber-200';
  }
  return 'bg-teal-50 text-teal-700 border-teal-200';
}

function getReminderChipStyle(r: WorkReminderItem): string {
  if (r.status === 'completed') {
    return 'bg-emerald-50 text-emerald-700 border-emerald-200 line-through opacity-80';
  }
  if (r.priority === 'urgent') {
    return 'bg-rose-50 text-rose-700 border-rose-200';
  }
  if (r.priority === 'high') {
    return 'bg-orange-50 text-orange-700 border-orange-200';
  }
  return 'bg-brand-50 text-brand-700 border-brand-200';
}

function isClassDone(status: string): boolean {
  const s = (status || '').toLowerCase();
  return s.includes('xong') || s.includes('hoàn thành');
}

export function BulletinCalendarBlock({
  isAdmin,
  adminOwnerFilter,
  todayStr,
  refreshTrigger,
  onCreateReminderForDate,
  onEditReminder,
  onSelectChecklistDate,
  onReminderMutated,
}: BulletinCalendarBlockProps) {
  const [currentMonth, setCurrentMonth] = useState<Date>(() => {
    try {
      return startOfMonth(parseISO(todayStr));
    } catch {
      return startOfMonth(new Date());
    }
  });
  const [selectedDate, setSelectedDate] = useState<string>(todayStr);

  // Filters
  const [typeFilter, setTypeFilter] = useState<EventTypeFilter>('all');
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all');
  const [searchText, setSearchText] = useState('');
  const [courseTypeFilter, setCourseTypeFilter] = useState<string>('all');

  // Data
  const [monthReminders, setMonthReminders] = useState<WorkReminderItem[]>([]);
  const [classEvents, setClassEvents] = useState<ClassScheduleEvent[]>([]);
  const [checklistDays, setChecklistDays] = useState<Record<string, { total_items: number; done_items: number }>>({});
  const [sheetUrl, setSheetUrl] = useState('');
  const [lastSyncedAt, setLastSyncedAt] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  // Google Sheet sync modal (Admin only)
  const [sheetModalOpen, setSheetModalOpen] = useState(false);
  const [sheetUrlDraft, setSheetUrlDraft] = useState('');
  const [autoSyncEnabled, setAutoSyncEnabled] = useState(true);
  const [syncIntervalMinutes, setSyncIntervalMinutes] = useState(15);
  const [autoSyncDraft, setAutoSyncDraft] = useState(true);
  const [syncIntervalDraft, setSyncIntervalDraft] = useState(15);
  const [csvTextDraft, setCsvTextDraft] = useState('');
  const [showCsvPaste, setShowCsvPaste] = useState(false);
  const [showAppsScriptGuide, setShowAppsScriptGuide] = useState(true);
  const [syncingSheet, setSyncingSheet] = useState(false);
  const [uploadingFile, setUploadingFile] = useState(false);

  const calendarRange = useMemo(() => {
    const mStart = startOfMonth(currentMonth);
    const mEnd = endOfMonth(currentMonth);
    const gridStart = startOfWeek(mStart, { weekStartsOn: 1 });
    const gridEnd = endOfWeek(mEnd, { weekStartsOn: 1 });
    return {
      gridStart,
      gridEnd,
      dateFrom: format(gridStart, 'yyyy-MM-dd'),
      dateTo: format(gridEnd, 'yyyy-MM-dd'),
      days: eachDayOfInterval({ start: gridStart, end: gridEnd }),
    };
  }, [currentMonth]);

  const loadCalendarData = useCallback(async () => {
    setLoading(true);
    try {
      const ownerId = isAdmin && adminOwnerFilter ? Number(adminOwnerFilter) : undefined;
      const [remRes, clsRes, clRes] = await Promise.all([
        fetchWorkReminders({
          status: 'all',
          date_from: calendarRange.dateFrom,
          date_to: calendarRange.dateTo,
          owner_user_id: ownerId,
        }),
        fetchClassSchedule({
          date_from: calendarRange.dateFrom,
          date_to: calendarRange.dateTo,
        }),
        fetchChecklistsMonthSummary({
          date_from: calendarRange.dateFrom,
          date_to: calendarRange.dateTo,
          owner_user_id: ownerId,
        }),
      ]);
      setMonthReminders(remRes.items || []);
      setClassEvents(clsRes.events || []);
      setSheetUrl(clsRes.sheet_url || '');
      setAutoSyncEnabled(clsRes.auto_sync_enabled ?? true);
      setSyncIntervalMinutes(clsRes.sync_interval_minutes ?? 15);
      setLastSyncedAt(clsRes.last_synced_at || null);
      setChecklistDays(clRes.days || {});
    } catch (err: any) {
      showAppToast(err?.response?.data?.detail || 'Không tải được dữ liệu lịch tháng', 'error');
    } finally {
      setLoading(false);
    }
  }, [calendarRange.dateFrom, calendarRange.dateTo, isAdmin, adminOwnerFilter]);

  useEffect(() => {
    loadCalendarData();
  }, [loadCalendarData, refreshTrigger]);

  // Filtered reminders & classes
  const kw = searchText.trim().toLowerCase();

  const filteredReminders = useMemo(() => {
    if (typeFilter === 'classes' || typeFilter === 'checklists') return [];
    return monthReminders.filter((r) => {
      if (statusFilter === 'active' && r.status === 'completed') return false;
      if (statusFilter === 'done' && r.status !== 'completed') return false;
      if (kw) {
        const hay = `${r.title} ${r.description || ''} ${r.owner_name || ''}`.toLowerCase();
        if (!hay.includes(kw)) return false;
      }
      return true;
    });
  }, [monthReminders, typeFilter, statusFilter, kw]);

  const filteredClasses = useMemo(() => {
    if (typeFilter === 'reminders' || typeFilter === 'checklists') return [];
    return classEvents.filter((ev) => {
      const done = isClassDone(ev.status);
      if (statusFilter === 'active' && done) return false;
      if (statusFilter === 'done' && !done) return false;
      if (courseTypeFilter !== 'all' && ev.course_type !== courseTypeFilter) return false;
      if (kw) {
        const hay = `${ev.course_code} ${ev.course_name} ${ev.session_label} ${ev.instructor} ${ev.assistants.join(' ')} ${ev.note}`.toLowerCase();
        if (!hay.includes(kw)) return false;
      }
      return true;
    });
  }, [classEvents, typeFilter, statusFilter, courseTypeFilter, kw]);

  // Group by date YYYY-MM-DD
  const eventsByDate = useMemo(() => {
    const map: Record<string, { reminders: WorkReminderItem[]; classes: ClassScheduleEvent[] }> = {};
    for (const r of filteredReminders) {
      const d = r.due_date;
      if (!d) continue;
      if (!map[d]) map[d] = { reminders: [], classes: [] };
      map[d].reminders.push(r);
    }
    for (const c of filteredClasses) {
      const d = c.date;
      if (!d) continue;
      if (!map[d]) map[d] = { reminders: [], classes: [] };
      map[d].classes.push(c);
    }
    return map;
  }, [filteredReminders, filteredClasses]);

  const courseTypes = useMemo(() => {
    const set = new Set<string>();
    classEvents.forEach((c) => {
      if (c.course_type) set.add(c.course_type);
    });
    return Array.from(set).sort();
  }, [classEvents]);

  const selectedDayData = eventsByDate[selectedDate] || { reminders: [], classes: [] };
  const selectedDayChecklist = typeFilter === 'reminders' || typeFilter === 'classes' ? undefined : checklistDays[selectedDate];

  const handleToggleReminderDone = async (r: WorkReminderItem) => {
    const nextStatus = r.status === 'completed' ? 'pending' : 'completed';
    try {
      await updateWorkReminder(r.id, { status: nextStatus });
      showAppToast(nextStatus === 'completed' ? 'Đã hoàn thành nhắc hẹn' : 'Đã mở lại nhắc hẹn', 'success');
      onReminderMutated();
      await loadCalendarData();
    } catch (err: any) {
      showAppToast(err?.response?.data?.detail || 'Lỗi cập nhật nhắc hẹn', 'error');
    }
  };

  const handleQuickRefreshSheet = async () => {
    if (!sheetUrl) {
      setSheetUrlDraft('');
      setAutoSyncDraft(autoSyncEnabled);
      setSyncIntervalDraft(syncIntervalMinutes);
      setCsvTextDraft('');
      setSheetModalOpen(true);
      return;
    }
    setSyncingSheet(true);
    try {
      const res = await syncClassSchedule({ sheet_url: sheetUrl });
      showAppToast(`Đã đồng bộ ${res.total} buổi học từ Apps Script`, 'success');
      await loadCalendarData();
    } catch (err: any) {
      showAppToast(err?.response?.data?.detail || 'Lỗi đồng bộ Google Apps Script', 'error');
    } finally {
      setSyncingSheet(false);
    }
  };

  const handleSaveSheetSync = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!sheetUrlDraft.trim() && !csvTextDraft.trim()) {
      showAppToast('Vui lòng nhập link Apps Script Web App hoặc dán nội dung CSV', 'error');
      return;
    }
    setSyncingSheet(true);
    try {
      const res = await syncClassSchedule({
        sheet_url: sheetUrlDraft.trim() || undefined,
        csv_text: csvTextDraft.trim() || undefined,
        auto_sync_enabled: autoSyncDraft,
        sync_interval_minutes: syncIntervalDraft,
      });
      showAppToast(
        `Đồng bộ thành công ${res.total} buổi học!${autoSyncDraft ? ` (Tự động mỗi ${syncIntervalDraft} phút)` : ''}`,
        'success'
      );
      setSheetModalOpen(false);
      setCsvTextDraft('');
      await loadCalendarData();
    } catch (err: any) {
      showAppToast(err?.response?.data?.detail || 'Không thể đồng bộ lịch lớp', 'error');
    } finally {
      setSyncingSheet(false);
    }
  };

  const handleUploadScheduleFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = '';
    if (!file) return;
    setUploadingFile(true);
    try {
      const res = await uploadClassScheduleFile(file);
      showAppToast(`Đã import ${res.total} buổi học từ file ${file.name}!`, 'success');
      setSheetModalOpen(false);
      await loadCalendarData();
    } catch (err: any) {
      showAppToast(err?.response?.data?.detail || 'Không thể đọc file lịch lớp', 'error');
    } finally {
      setUploadingFile(false);
    }
  };

  const APPS_SCRIPT_SNIPPET = `function doGet(e) {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var targets = ["Lịch QL lớp", "Lịch dự kiến khai giảng"];
  var sheets = ss.getSheets().filter(function(s) {
    var n = s.getName().trim().toLowerCase();
    return targets.some(function(t) { return n === t.toLowerCase(); }) || n.includes("lịch ql lớp") || n.includes("lịch quản lý lớp");
  });
  if (!sheets.length) sheets = [ss.getSheets()[0]];
  var csv = sheets.map(function(sheet) {
    return sheet.getDataRange().getDisplayValues().map(function(row) {
      return row.map(function(c) {
        return '"' + String(c).replace(/"/g, '""') + '"';
      }).join(',');
    }).join('\\n');
  }).join('\\n');
  return ContentService.createTextOutput(csv).setMimeType(ContentService.MimeType.CSV);
}`;

  const hasActiveFilters = typeFilter !== 'all' || statusFilter !== 'all' || courseTypeFilter !== 'all' || kw !== '';

  return (
    <div className="bg-white rounded-2xl border border-slate-200/80 shadow-card overflow-hidden">
      {/* Header */}
      <div className="px-4 py-3 border-b border-slate-100 flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <CalendarIcon className="w-4 h-4 text-brand-500" aria-hidden="true" />
          <h3 className="text-xs font-bold uppercase tracking-wider text-slate-600">
            Lịch làm việc &amp; Lịch lớp
          </h3>
          {loading && <span className="text-[10px] text-slate-400">Đang tải...</span>}
        </div>

        {isAdmin ? (
          <div className="flex items-center gap-1.5">
            <button
              type="button"
              onClick={handleQuickRefreshSheet}
              disabled={syncingSheet}
              title={lastSyncedAt ? `Đồng bộ lịch lớp (lần cuối: ${lastSyncedAt})` : 'Đồng bộ lịch lớp'}
              className="px-2 py-1 rounded-lg text-[11px] font-semibold bg-emerald-50 text-emerald-700 border border-emerald-200 hover:bg-emerald-100 flex items-center gap-1 cursor-pointer disabled:opacity-50"
            >
              <RefreshCw className={`w-3 h-3 ${syncingSheet ? 'animate-spin' : ''}`} />
              <span className="hidden sm:inline">{sheetUrl ? 'Đồng bộ lớp' : 'Cập nhật lịch lớp'}</span>
            </button>
            <button
              type="button"
              onClick={() => {
                setSheetUrlDraft(sheetUrl);
                setAutoSyncDraft(autoSyncEnabled);
                setSyncIntervalDraft(syncIntervalMinutes);
                setCsvTextDraft('');
                setShowCsvPaste(false);
                setSheetModalOpen(true);
              }}
              title="Cấu hình nguồn lịch lớp & tự động cập nhật (Chỉ Admin)"
              className="p-1.5 rounded-lg text-slate-500 hover:text-navy hover:bg-slate-100 border border-slate-200 cursor-pointer"
            >
              <Settings2 className="w-3.5 h-3.5" />
            </button>
          </div>
        ) : (
          lastSyncedAt && (
            <span className="text-[10px] text-slate-400 font-mono">
              Lịch lớp: {lastSyncedAt.slice(0, 16)}
            </span>
          )
        )}
      </div>

      {/* Month Navigator + Filter Bar */}
      <div className="px-4 py-2.5 bg-slate-50/70 border-b border-slate-100 space-y-2.5">
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-1">
            <button
              type="button"
              onClick={() => setCurrentMonth((m) => subMonths(m, 1))}
              className="p-1 rounded-lg border border-slate-200 bg-white text-slate-600 hover:bg-slate-100 cursor-pointer"
              aria-label="Tháng trước"
            >
              <ChevronLeft className="w-4 h-4" />
            </button>
            <span className="text-sm font-bold text-navy px-2 min-w-[120px] text-center capitalize">
              Tháng {format(currentMonth, 'MM / yyyy')}
            </span>
            <button
              type="button"
              onClick={() => setCurrentMonth((m) => addMonths(m, 1))}
              className="p-1 rounded-lg border border-slate-200 bg-white text-slate-600 hover:bg-slate-100 cursor-pointer"
              aria-label="Tháng sau"
            >
              <ChevronRight className="w-4 h-4" />
            </button>
          </div>

          <button
            type="button"
            onClick={() => {
              try {
                setCurrentMonth(startOfMonth(parseISO(todayStr)));
              } catch {
                setCurrentMonth(startOfMonth(new Date()));
              }
              setSelectedDate(todayStr);
            }}
            className="px-2.5 py-1 rounded-lg text-[11px] font-semibold bg-white border border-slate-200 text-navy hover:bg-slate-100 cursor-pointer"
          >
            Hôm nay
          </button>
        </div>

        {/* Filters */}
        <div className="space-y-2">
          <div className="flex flex-wrap items-center gap-1">
            {(
              [
                { id: 'all', label: 'Tất cả' },
                { id: 'reminders', label: 'Nhắc hẹn' },
                { id: 'classes', label: 'Lịch lớp' },
                { id: 'checklists', label: 'Checklist' },
              ] as { id: EventTypeFilter; label: string }[]
            ).map((tab) => (
              <button
                key={tab.id}
                type="button"
                onClick={() => setTypeFilter(tab.id)}
                className={`px-2 py-1 rounded-lg text-[11px] font-semibold transition-colors cursor-pointer ${
                  typeFilter === tab.id
                    ? 'bg-navy text-white'
                    : 'bg-white text-slate-600 border border-slate-200 hover:bg-slate-100'
                }`}
              >
                {tab.label}
              </button>
            ))}

            {hasActiveFilters && (
              <button
                type="button"
                onClick={() => {
                  setTypeFilter('all');
                  setStatusFilter('all');
                  setCourseTypeFilter('all');
                  setSearchText('');
                }}
                className="ml-auto text-[11px] font-medium text-rose-600 hover:underline flex items-center gap-0.5 cursor-pointer"
              >
                <X className="w-3 h-3" />
                Xóa lọc
              </button>
            )}
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-12 gap-1.5">
            <div className="sm:col-span-6 relative">
              <Search className="w-3.5 h-3.5 text-slate-400 absolute left-2.5 top-1/2 -translate-y-1/2" />
              <input
                type="text"
                value={searchText}
                onChange={(e) => setSearchText(e.target.value)}
                placeholder="Lọc lớp (PBIK63), GV, trợ giảng, hẹn..."
                className="w-full pl-7 pr-2.5 py-1 text-[11px] bg-white border border-slate-200 rounded-lg focus:outline-none focus:ring-1 focus:ring-brand-500"
              />
            </div>

            <div className="sm:col-span-3">
              <select
                value={statusFilter}
                onChange={(e) => setStatusFilter(e.target.value as StatusFilter)}
                aria-label="Lọc trạng thái"
                className="w-full text-[11px] bg-white border border-slate-200 rounded-lg px-2 py-1 text-navy focus:outline-none"
              >
                <option value="all">Mọi trạng thái</option>
                <option value="active">Đang mở / Học</option>
                <option value="done">Đã xong</option>
              </select>
            </div>

            <div className="sm:col-span-3">
              <select
                value={courseTypeFilter}
                onChange={(e) => setCourseTypeFilter(e.target.value)}
                aria-label="Lọc loại khóa học"
                className="w-full text-[11px] bg-white border border-slate-200 rounded-lg px-2 py-1 text-navy focus:outline-none"
              >
                <option value="all">Mọi khóa</option>
                {courseTypes.map((ct) => (
                  <option key={ct} value={ct}>
                    {ct}
                  </option>
                ))}
              </select>
            </div>
          </div>
        </div>
      </div>

      {/* 7-column Full Month Grid */}
      <div className="p-2.5">
        <div className="grid grid-cols-7 gap-1 mb-1">
          {WEEKDAY_HEADERS.map((wd, idx) => (
            <div
              key={wd}
              className={`text-center text-[10px] font-bold uppercase py-1 ${
                idx >= 5 ? 'text-rose-500' : 'text-slate-400'
              }`}
            >
              {wd}
            </div>
          ))}
        </div>

        <div className="grid grid-cols-7 gap-1">
          {calendarRange.days.map((dayObj) => {
            const dStr = format(dayObj, 'yyyy-MM-dd');
            const inMonth = isSameMonth(dayObj, currentMonth);
            const isToday = dStr === todayStr;
            const isSelected = dStr === selectedDate;
            const dayEvents = eventsByDate[dStr];
            const rems = dayEvents?.reminders || [];
            const clss = dayEvents?.classes || [];
            const clSummary = typeFilter === 'reminders' || typeFilter === 'classes' ? undefined : checklistDays[dStr];

            // Combine chips for compact display (classes first or reminders first, max 2 chips)
            const combinedChips: { key: string; label: string; cls: string }[] = [
              ...clss.map((c) => ({
                key: c.id,
                label: `${c.course_code} ${c.session_label.replace('Buổi ', 'B')}`,
                cls: getClassChipStyle(c),
              })),
              ...rems.map((r) => ({
                key: `r_${r.id}`,
                label: `${(r.remind_at || '').slice(11, 16)} ${r.title}`.trim(),
                cls: getReminderChipStyle(r),
              })),
            ];
            const visibleChips = combinedChips.slice(0, 2);
            const extraCount = combinedChips.length - visibleChips.length;

            return (
              <button
                key={dStr}
                type="button"
                onClick={() => setSelectedDate(dStr)}
                className={`min-h-[64px] p-1 rounded-xl border text-left flex flex-col transition-all cursor-pointer ${
                  isSelected
                    ? 'border-brand-500 ring-2 ring-brand-500/25 bg-brand-50/30'
                    : inMonth
                    ? 'border-slate-100 bg-white hover:border-slate-300 hover:bg-slate-50/60'
                    : 'border-transparent bg-slate-50/40 opacity-45 hover:opacity-75'
                }`}
              >
                <div className="flex items-center justify-between w-full mb-0.5">
                  <span
                    className={`text-[11px] font-bold font-mono tabular-nums w-5 h-5 flex items-center justify-center rounded-full ${
                      isToday
                        ? 'bg-brand-600 text-white'
                        : isSelected
                        ? 'text-brand-700'
                        : 'text-slate-700'
                    }`}
                  >
                    {format(dayObj, 'd')}
                  </span>

                  {clSummary && clSummary.total_items > 0 && (
                    <span
                      title={`Checklist: ${clSummary.done_items}/${clSummary.total_items}`}
                      className="text-[9px] font-mono font-semibold px-1 rounded bg-emerald-50 text-emerald-700"
                    >
                      {clSummary.done_items}/{clSummary.total_items}
                    </span>
                  )}
                </div>

                <div className="space-y-0.5 w-full overflow-hidden">
                  {visibleChips.map((chip) => (
                    <div
                      key={chip.key}
                      className={`text-[9px] leading-tight font-medium px-1 py-0.5 rounded border truncate ${chip.cls}`}
                      title={chip.label}
                    >
                      {chip.label}
                    </div>
                  ))}
                  {extraCount > 0 && (
                    <div className="text-[9px] font-semibold text-slate-500 pl-0.5">
                      +{extraCount} nữa
                    </div>
                  )}
                </div>
              </button>
            );
          })}
        </div>

        {/* Legend */}
        <div className="mt-2 pt-2 border-t border-slate-100 flex flex-wrap items-center gap-3 text-[10px] text-slate-500">
          <span className="flex items-center gap-1">
            <span className="w-2.5 h-2.5 rounded bg-brand-100 border border-brand-300 inline-block" />
            Nhắc hẹn
          </span>
          <span className="flex items-center gap-1">
            <span className="w-2.5 h-2.5 rounded bg-amber-100 border border-amber-300 inline-block" />
            Power Query
          </span>
          <span className="flex items-center gap-1">
            <span className="w-2.5 h-2.5 rounded bg-violet-100 border border-violet-300 inline-block" />
            Power BI
          </span>
          <span className="flex items-center gap-1">
            <span className="w-2.5 h-2.5 rounded bg-emerald-100 border border-emerald-300 inline-block" />
            Checklist
          </span>
        </div>
      </div>

      {/* Selected Day Agenda Detail */}
      <div className="border-t border-slate-200/80 bg-slate-50/50 p-3.5 space-y-2.5">
        <div className="flex items-center justify-between gap-2">
          <div>
            <h4 className="text-xs font-bold text-navy">{formatDisplayDate(selectedDate)}</h4>
            <p className="text-[11px] text-slate-500">
              {selectedDayData.classes.length} lịch lớp • {selectedDayData.reminders.length} nhắc hẹn
              {selectedDayChecklist && selectedDayChecklist.total_items > 0
                ? ` • ${selectedDayChecklist.done_items}/${selectedDayChecklist.total_items} checklist`
                : ''}
            </p>
          </div>
          <button
            type="button"
            onClick={() => onCreateReminderForDate(selectedDate)}
            className="px-2.5 py-1.5 rounded-lg text-[11px] font-semibold bg-brand-600 text-white hover:bg-brand-700 flex items-center gap-1 cursor-pointer shrink-0"
          >
            <Plus className="w-3.5 h-3.5" />
            <span>Thêm hẹn</span>
          </button>
        </div>

        {selectedDayData.classes.length === 0 &&
        selectedDayData.reminders.length === 0 &&
        (!selectedDayChecklist || selectedDayChecklist.total_items === 0) ? (
          <div className="rounded-xl border border-dashed border-slate-200 bg-white py-4 px-3 text-center text-xs text-slate-400">
            Không có lịch lớp hay nhắc hẹn nào trong ngày này.
          </div>
        ) : (
          <div className="space-y-2 max-h-[320px] overflow-y-auto pr-0.5">
            {/* Class Schedule Items */}
            {selectedDayData.classes.map((cls) => (
              <div
                key={cls.id}
                className="rounded-xl border border-slate-200 bg-white p-2.5 space-y-1.5 shadow-xs"
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="flex items-center gap-1.5 min-w-0">
                    <GraduationCap className="w-4 h-4 text-violet-600 shrink-0" />
                    <span className="text-xs font-bold text-navy truncate">
                      {cls.course_name}
                    </span>
                  </div>
                  <span className={`px-1.5 py-0.5 rounded-md text-[10px] font-semibold border shrink-0 ${getClassChipStyle(cls)}`}>
                    {cls.session_label}
                  </span>
                </div>

                <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-slate-600">
                  <span className="flex items-center gap-1 font-mono">
                    <Clock className="w-3 h-3 text-slate-400" />
                    {cls.time_range}
                  </span>
                  {cls.instructor && (
                    <span>
                      GV: <strong className="text-navy">{cls.instructor}</strong>
                    </span>
                  )}
                  <span className="px-1.5 py-0.2 rounded bg-slate-100 text-slate-600 text-[10px]">
                    {cls.status}
                  </span>
                </div>

                {cls.assistants.length > 0 && (
                  <div className="flex flex-wrap items-center gap-1 pt-0.5">
                    <Users className="w-3 h-3 text-slate-400 mr-0.5" />
                    {cls.assistants.map((a) => (
                      <span
                        key={a}
                        className="px-1.5 py-0.5 rounded-md bg-slate-100 text-slate-700 text-[10px] font-medium"
                      >
                        {a}
                      </span>
                    ))}
                  </div>
                )}

                {cls.note && <p className="text-[11px] text-amber-700 bg-amber-50 px-2 py-1 rounded-md">{cls.note}</p>}
              </div>
            ))}

            {/* Work Reminders */}
            {selectedDayData.reminders.map((rem) => (
              <div
                key={rem.id}
                className="rounded-xl border border-slate-200 bg-white p-2.5 flex items-start justify-between gap-2 shadow-xs"
              >
                <div className="flex items-start gap-2 min-w-0">
                  <button
                    type="button"
                    onClick={() => handleToggleReminderDone(rem)}
                    title={rem.status === 'completed' ? 'Mở lại' : 'Đánh dấu hoàn thành'}
                    className={`mt-0.5 shrink-0 cursor-pointer ${
                      rem.status === 'completed' ? 'text-emerald-600' : 'text-slate-300 hover:text-emerald-600'
                    }`}
                  >
                    <CheckCircle2 className="w-4 h-4" />
                  </button>
                  <div className="min-w-0">
                    <div className="flex items-center gap-1.5 flex-wrap">
                      <span className="text-[10px] font-mono font-bold text-brand-700 bg-brand-50 px-1.5 py-0.5 rounded">
                        {(rem.remind_at || '').slice(11, 16) || '--:--'}
                      </span>
                      <button
                        type="button"
                        onClick={() => onEditReminder(rem)}
                        className={`text-xs font-semibold text-left hover:underline cursor-pointer ${
                          rem.status === 'completed' ? 'line-through text-slate-400' : 'text-navy'
                        }`}
                      >
                        {rem.title}
                      </button>
                    </div>
                    {rem.description && (
                      <p className="text-[11px] text-slate-500 mt-0.5 line-clamp-2">{rem.description}</p>
                    )}
                    {isAdmin && rem.owner_name && (
                      <p className="text-[10px] text-slate-400 mt-0.5">Phụ trách: {rem.owner_name}</p>
                    )}
                  </div>
                </div>
                <Bell className="w-3.5 h-3.5 text-brand-400 shrink-0 mt-0.5" />
              </div>
            ))}

            {/* Checklist summary link */}
            {selectedDayChecklist && selectedDayChecklist.total_items > 0 && (
              <div className="rounded-xl border border-emerald-200 bg-emerald-50/50 p-2.5 flex items-center justify-between gap-2">
                <div className="flex items-center gap-2 text-xs text-emerald-900">
                  <ListTodo className="w-4 h-4 text-emerald-600" />
                  <span>
                    Checklist ngày: <strong>{selectedDayChecklist.done_items}/{selectedDayChecklist.total_items}</strong> đầu việc
                  </span>
                </div>
                <button
                  type="button"
                  onClick={() => onSelectChecklistDate(selectedDate)}
                  className="text-[11px] font-semibold text-emerald-700 hover:underline cursor-pointer"
                >
                  Xem checklist
                </button>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Modal cấu hình & đồng bộ Lịch lớp (Chỉ Admin) */}
      {isAdmin && (
        <AccessibleModal
          isOpen={sheetModalOpen}
          onClose={() => setSheetModalOpen(false)}
          ariaLabel="Tự động đồng bộ Google Sheet Private (Chỉ Admin)"
        >
          <div className="bg-white rounded-2xl border border-slate-200 shadow-xl w-full max-w-lg p-5 space-y-4 max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <FileSpreadsheet className="w-5 h-5 text-emerald-600" />
                <h3 className="text-sm font-bold text-navy">Tự động cập nhật Lịch lớp (Google Apps Script)</h3>
              </div>
              <button
                type="button"
                onClick={() => setSheetModalOpen(false)}
                className="p-1 rounded-lg text-slate-400 hover:text-navy hover:bg-slate-100 cursor-pointer"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            {/* Chính: Apps Script Web App URL + Auto-sync (Sheet giữ Private 100%) */}
            <form onSubmit={handleSaveSheetSync} className="space-y-3">
              <div>
                <div className="flex items-center justify-between mb-1">
                  <label className="text-xs font-semibold text-navy">
                    Link Apps Script Web App (Sheet giữ Private hoàn toàn)
                  </label>
                  <button
                    type="button"
                    onClick={() => setShowAppsScriptGuide((v) => !v)}
                    className="text-[11px] font-semibold text-brand-600 hover:underline cursor-pointer"
                  >
                    {showAppsScriptGuide ? 'Ẩn hướng dẫn' : 'Xem hướng dẫn & mã'}
                  </button>
                </div>
                <input
                  type="text"
                  value={sheetUrlDraft}
                  onChange={(e) => setSheetUrlDraft(e.target.value)}
                  placeholder="https://script.google.com/macros/s/.../exec"
                  className="w-full text-xs border border-slate-200 rounded-xl px-3 py-2 focus:outline-none focus:ring-2 focus:ring-brand-500"
                />

                {/* Tần suất tự động cập nhật */}
                <div className="mt-2.5 flex flex-wrap items-center justify-between gap-2 rounded-xl bg-slate-50 border border-slate-200/80 px-3 py-2">
                  <label className="flex items-center gap-2 text-xs font-semibold text-navy cursor-pointer">
                    <input
                      type="checkbox"
                      checked={autoSyncDraft}
                      onChange={(e) => setAutoSyncDraft(e.target.checked)}
                      className="rounded border-slate-300 text-brand-600 focus:ring-brand-500"
                    />
                    <span>Tự động cập nhật định kỳ</span>
                  </label>
                  <select
                    value={syncIntervalDraft}
                    disabled={!autoSyncDraft}
                    onChange={(e) => setSyncIntervalDraft(Number(e.target.value))}
                    className="text-xs bg-white border border-slate-200 rounded-lg px-2 py-1 text-navy disabled:opacity-50"
                  >
                    <option value={5}>Mỗi 5 phút</option>
                    <option value={15}>Mỗi 15 phút</option>
                    <option value={30}>Mỗi 30 phút</option>
                    <option value={60}>Mỗi 1 giờ</option>
                  </select>
                </div>

                {showAppsScriptGuide && (
                  <div className="mt-2.5 rounded-xl bg-slate-900 text-slate-100 p-3 space-y-2 text-[11px]">
                    <p className="text-slate-300 leading-relaxed">
                      1. Mở Google Sheet → <strong>Tiện ích mở rộng → Apps Script</strong>.<br />
                      2. Dán đoạn mã dưới đây → bấm <strong>Deploy → New deployment → Web app</strong> (Execute as: <em>Me</em>, Who has access: <em>Anyone</em>) → copy URL <code className="text-emerald-300">/exec</code> dán lên trên:
                    </p>
                    <pre className="overflow-x-auto font-mono text-[10px] leading-relaxed text-emerald-300">
                      {APPS_SCRIPT_SNIPPET}
                    </pre>
                    <button
                      type="button"
                      onClick={() => {
                        navigator.clipboard?.writeText(APPS_SCRIPT_SNIPPET);
                        showAppToast('Đã copy mã Apps Script!', 'success');
                      }}
                      className="px-2.5 py-1 rounded bg-slate-700 hover:bg-slate-600 text-white text-[10px] font-semibold cursor-pointer"
                    >
                      Copy mã Apps Script
                    </button>
                  </div>
                )}
              </div>

              <div>
                <button
                  type="button"
                  onClick={() => setShowCsvPaste((v) => !v)}
                  className="text-[11px] font-semibold text-slate-500 hover:text-navy hover:underline flex items-center gap-1 cursor-pointer"
                >
                  <Filter className="w-3 h-3" />
                  {showCsvPaste ? 'Ẩn ô dán CSV thủ công' : 'Tùy chọn phụ: Dán nhanh nội dung CSV'}
                </button>
                {showCsvPaste && (
                  <textarea
                    rows={4}
                    value={csvTextDraft}
                    onChange={(e) => setCsvTextDraft(e.target.value)}
                    placeholder="Dán nội dung CSV vào đây..."
                    className="mt-2 w-full text-[11px] font-mono border border-slate-200 rounded-xl px-3 py-2 focus:outline-none focus:ring-2 focus:ring-brand-500"
                  />
                )}
              </div>

              {lastSyncedAt && (
                <p className="text-[11px] text-slate-500">
                  Lần cập nhật gần nhất: <strong className="text-navy">{lastSyncedAt}</strong> ({classEvents.length} buổi trong tháng này)
                </p>
              )}

              <div className="flex items-center justify-between gap-2 pt-2 border-t border-slate-100">
                <label className="px-2.5 py-1.5 rounded-xl text-[11px] font-semibold text-slate-600 border border-slate-200 hover:bg-slate-50 flex items-center gap-1.5 cursor-pointer">
                  <Upload className="w-3.5 h-3.5" />
                  <span>{uploadingFile ? 'Đang đọc...' : 'Hoặc upload .xlsx/.csv'}</span>
                  <input
                    type="file"
                    accept=".xlsx,.xlsm,.csv"
                    onChange={handleUploadScheduleFile}
                    disabled={uploadingFile}
                    className="hidden"
                  />
                </label>

                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() => setSheetModalOpen(false)}
                    className="px-3 py-1.5 rounded-xl text-xs font-semibold text-slate-600 border border-slate-200 hover:bg-slate-50 cursor-pointer"
                  >
                    Đóng
                  </button>
                  <button
                    type="submit"
                    disabled={syncingSheet}
                    className="px-4 py-1.5 rounded-xl text-xs font-semibold bg-emerald-600 text-white hover:bg-emerald-700 disabled:opacity-50 flex items-center gap-1.5 cursor-pointer"
                  >
                    <RefreshCw className={`w-3.5 h-3.5 ${syncingSheet ? 'animate-spin' : ''}`} />
                    <span>{syncingSheet ? 'Đang đồng bộ...' : 'Lưu & Đồng bộ'}</span>
                  </button>
                </div>
              </div>
            </form>
          </div>
        </AccessibleModal>
      )}
    </div>
  );
}
