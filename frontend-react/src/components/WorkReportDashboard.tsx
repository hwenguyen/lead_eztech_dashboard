import { useState, useEffect, useCallback } from 'react';
import { format, subDays, startOfWeek, endOfWeek, subWeeks, startOfMonth } from 'date-fns';
import {
  Copy,
  Check,
  Calendar,
  UserCheck,
  Sparkles,
  Plus,
  Trash2,
  Award,
  Lightbulb,
  Users,
  FileSpreadsheet,
  RotateCcw,
} from 'lucide-react';
import { fetchWorkReport, type WorkReportResponse } from '../services/api';

export interface SheetSubRow {
  id: string;
  task: string;       // Col B: Công việc
  completed: string;  // Col C: Đã hoàn thành trong tuần
  nextPlan: string;   // Col D: Kế hoạch cho tuần tiếp theo
  feedback: string;   // Col E: Feedback Anh/chị
}

export interface SheetSection {
  sectionNumber: number; // Col A: 1..6
  title: string;         // Col B (header row of section)
  completed: string;     // Col C (header row of section)
  nextPlan: string;      // Col D (header row of section)
  feedback: string;      // Col E (header row of section)
  rows: SheetSubRow[];
}

const STORAGE_KEY_PREFIX = 'eztech_work_report_v1_';

function createDefaultSections(report?: WorkReportResponse | null): SheetSection[] {
  const ttLine = report?.lead_stats?.tiktok?.formatted_line || 'Tiktok: Tạo mới: 0, Contact trong tuần: 0, SĐT 0.';
  const fbLine = report?.lead_stats?.facebook?.formatted_line || 'FB: Tạo mới: 0, Contact: 0, SĐT: 0';
  const studentLine = report?.student_stats?.formatted_line || '';
  const insightLines = report?.insights?.formatted_lines || [];
  const classesStr = report?.student_stats?.classes?.length
    ? report.student_stats.classes.join(', ')
    : 'PBIK59';

  const section1Rows: SheetSubRow[] = [
    {
      id: 's1_r1',
      task: 'Chăm sóc Lead',
      completed: ttLine,
      nextPlan: '',
      feedback: '',
    },
    {
      id: 's1_r2',
      task: '',
      completed: fbLine,
      nextPlan: '',
      feedback: '',
    },
  ];

  if (report?.lead_stats?.zalo && report.lead_stats.zalo.total_contacted > 0) {
    section1Rows.push({
      id: 's1_r_zalo',
      task: 'Chăm sóc Zalo',
      completed: `Zalo: Tạo mới: ${report.lead_stats.zalo.new_leads}, Contact: ${report.lead_stats.zalo.total_contacted}, SĐT: ${report.lead_stats.zalo.phone_leads}`,
      nextPlan: '',
      feedback: '',
    });
  }

  if (studentLine) {
    section1Rows.push({
      id: 's1_r3',
      task: 'Học viên chốt',
      completed: studentLine,
      nextPlan: '',
      feedback: '',
    });
  }

  if (insightLines.length > 0) {
    section1Rows.push({
      id: 's1_r4',
      task: 'Insight tuần',
      completed: insightLines.join('\n'),
      nextPlan: '',
      feedback: '',
    });
  } else {
    section1Rows.push({
      id: 's1_r4',
      task: '',
      completed: '',
      nextPlan: '',
      feedback: '',
    });
  }

  return [
    {
      sectionNumber: 1,
      title: 'Chăm sóc khách hàng',
      completed: '',
      nextPlan: '',
      feedback: '',
      rows: section1Rows,
    },
    {
      sectionNumber: 2,
      title: 'Quản Lý Lớp học',
      completed: '',
      nextPlan: '',
      feedback: '',
      rows: [
        { id: 's2_r1', task: 'Support lớp học', completed: classesStr, nextPlan: '', feedback: '' },
        { id: 's2_r2', task: '', completed: '', nextPlan: '', feedback: '' },
        { id: 's2_r3', task: '', completed: '', nextPlan: '', feedback: '' },
      ],
    },
    {
      sectionNumber: 3,
      title: 'Deal B2C Customize/ support',
      completed: '',
      nextPlan: '',
      feedback: '',
      rows: [
        { id: 's3_r1', task: '', completed: '', nextPlan: '', feedback: '' },
        { id: 's3_r2', task: 'B2B', completed: '', nextPlan: '', feedback: '' },
        { id: 's3_r3', task: '', completed: '', nextPlan: '', feedback: '' },
      ],
    },
    {
      sectionNumber: 4,
      title: 'Các công việc khác',
      completed: '',
      nextPlan: '',
      feedback: '',
      rows: [
        { id: 's4_r1', task: 'Tối ưu quy trình', completed: '', nextPlan: '', feedback: '' },
        { id: 's4_r2', task: '', completed: '', nextPlan: '', feedback: '' },
        { id: 's4_r3', task: '', completed: '', nextPlan: '', feedback: '' },
      ],
    },
    {
      sectionNumber: 5,
      title: 'Tự tìm hiểu và học tập',
      completed: '',
      nextPlan: '',
      feedback: '',
      rows: [
        { id: 's5_r1', task: '', completed: '', nextPlan: '', feedback: '' },
        { id: 's5_r2', task: '', nextPlan: '', completed: '', feedback: '' },
        { id: 's5_r3', task: '', nextPlan: '', completed: '', feedback: '' },
      ],
    },
    {
      sectionNumber: 6,
      title: 'Đề xuất với công việc và cấp quản lý & công ty',
      completed: '',
      nextPlan: '',
      feedback: '',
      rows: [
        { id: 's6_r1', task: '', completed: '', nextPlan: '', feedback: '' },
        { id: 's6_r2', task: '', completed: '', nextPlan: '', feedback: '' },
        { id: 's6_r3', task: '', completed: '', nextPlan: '', feedback: '' },
      ],
    },
  ];
}

// Escape một ô TSV để khi paste vào Google Sheet không bị nhảy dòng nếu trong ô có dấu xuống dòng (\n)
function formatTsvCell(val: string): string {
  const clean = (val ?? '').replace(/\r\n/g, '\n');
  if (clean.includes('\t') || clean.includes('\n') || clean.includes('"')) {
    return `"${clean.replace(/"/g, '""')}"`;
  }
  return clean;
}

function escapeHtml(str: string): string {
  return (str ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/\n/g, '<br/>');
}

export function WorkReportDashboard() {
  // Mặc định chọn tuần hiện tại (Thứ 2 -> Hôm nay)
  const [startDate, setStartDate] = useState(() =>
    format(startOfWeek(new Date(), { weekStartsOn: 1 }), 'yyyy-MM-dd')
  );
  const [endDate, setEndDate] = useState(() => format(new Date(), 'yyyy-MM-dd'));
  const [activePreset, setActivePreset] = useState<'this_week' | '7d' | 'last_week' | 'month' | 'custom'>('this_week');
  const [selectedEmployee, setSelectedEmployee] = useState<string>(() => {
    return localStorage.getItem('eztech_work_report_selected_emp') || 'Nguyen Gia Huy';
  });

  const [reportData, setReportData] = useState<WorkReportResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [sections, setSections] = useState<SheetSection[]>(() => createDefaultSections(null));
  const [copiedMode, setCopiedMode] = useState<'all' | 'body' | string | null>(null);

  const storageKey = `${STORAGE_KEY_PREFIX}${selectedEmployee || 'ALL'}`;

  // Đồng bộ dữ liệu từ API và tự động điền vào Mục 1 (Chăm sóc khách hàng)
  const applyDataToSections = useCallback((data: WorkReportResponse, currentSections: SheetSection[], forceReset = false) => {
    if (forceReset) {
      return createDefaultSections(data);
    }

    const ttLine = data.lead_stats.tiktok.formatted_line || 'Tiktok: Tạo mới: 0, Contact trong tuần: 0, SĐT 0.';
    const fbLine = data.lead_stats.facebook.formatted_line || 'FB: Tạo mới: 0, Contact: 0, SĐT: 0';
    const studentLine = data.student_stats.formatted_line || '';
    const insightStr = (data.insights.formatted_lines || []).join('\n');

    return currentSections.map((sec) => {
      if (sec.sectionNumber === 1) {
        const updatedRows: SheetSubRow[] = [
          {
            id: sec.rows[0]?.id || 's1_r1',
            task: 'Chăm sóc Lead',
            completed: ttLine,
            nextPlan: sec.rows[0]?.nextPlan || '',
            feedback: sec.rows[0]?.feedback || '',
          },
          {
            id: sec.rows[1]?.id || 's1_r2',
            task: '',
            completed: fbLine,
            nextPlan: sec.rows[1]?.nextPlan || '',
            feedback: sec.rows[1]?.feedback || '',
          },
        ];

        if (data.lead_stats.zalo && data.lead_stats.zalo.total_contacted > 0) {
          const existingZalo = sec.rows.find((r) => r.task === 'Chăm sóc Zalo');
          updatedRows.push({
            id: existingZalo?.id || 's1_r_zalo',
            task: 'Chăm sóc Zalo',
            completed: `Zalo: Tạo mới: ${data.lead_stats.zalo.new_leads}, Contact: ${data.lead_stats.zalo.total_contacted}, SĐT: ${data.lead_stats.zalo.phone_leads}`,
            nextPlan: existingZalo?.nextPlan || '',
            feedback: existingZalo?.feedback || '',
          });
        }

        const existingStudent = sec.rows.find((r) => r.task === 'Học viên chốt');
        updatedRows.push({
          id: existingStudent?.id || 's1_r3',
          task: 'Học viên chốt',
          completed: studentLine,
          nextPlan: existingStudent?.nextPlan || '',
          feedback: existingStudent?.feedback || '',
        });

        const existingInsight = sec.rows.find((r) => r.task === 'Insight tuần');
        updatedRows.push({
          id: existingInsight?.id || 's1_r4',
          task: 'Insight tuần',
          completed: insightStr,
          nextPlan: existingInsight?.nextPlan || '',
          feedback: existingInsight?.feedback || '',
        });

        // Giữ lại các dòng tự thêm khác của người dùng trong mục 1 (nếu có)
        const extraRows = sec.rows.slice(2).filter(
          (r) => !['Chăm sóc Zalo', 'Học viên chốt', 'Insight tuần'].includes(r.task) && (r.task || r.completed || r.nextPlan)
        );

        return {
          ...sec,
          rows: [...updatedRows, ...extraRows],
        };
      }

      if (sec.sectionNumber === 2 && data.student_stats.classes.length > 0) {
        const classesStr = data.student_stats.classes.join(', ');
        const newRows = [...sec.rows];
        if (newRows.length > 0 && (!newRows[0].completed || newRows[0].completed === 'PBIK59')) {
          newRows[0] = { ...newRows[0], task: newRows[0].task || 'Support lớp học', completed: classesStr };
        }
        return { ...sec, rows: newRows };
      }

      return sec;
    });
  }, []);

  const loadReport = useCallback(async (forceReset = false) => {
    setLoading(true);
    try {
      const res = await fetchWorkReport(startDate, endDate, selectedEmployee);
      setReportData(res);

      // Kiểm tra bản nháp đã lưu của nhân viên này
      const savedJson = localStorage.getItem(storageKey);
      let baseSections: SheetSection[];
      if (savedJson && !forceReset) {
        try {
          baseSections = JSON.parse(savedJson);
        } catch {
          baseSections = createDefaultSections(res);
        }
      } else {
        baseSections = createDefaultSections(res);
      }

      const merged = applyDataToSections(res, baseSections, forceReset);
      setSections(merged);
      localStorage.setItem(storageKey, JSON.stringify(merged));
    } catch (err) {
      console.error('Lỗi tải báo cáo công việc:', err);
    } finally {
      setLoading(false);
    }
  }, [startDate, endDate, selectedEmployee, storageKey, applyDataToSections]);

  useEffect(() => {
    loadReport(false);
  }, [loadReport]);

  const handleEmployeeChange = (emp: string) => {
    setSelectedEmployee(emp);
    localStorage.setItem('eztech_work_report_selected_emp', emp);
  };

  const applyDatePreset = (preset: 'this_week' | '7d' | 'last_week' | 'month') => {
    const now = new Date();
    setActivePreset(preset);
    if (preset === 'this_week') {
      setStartDate(format(startOfWeek(now, { weekStartsOn: 1 }), 'yyyy-MM-dd'));
      setEndDate(format(now, 'yyyy-MM-dd'));
    } else if (preset === '7d') {
      setStartDate(format(subDays(now, 6), 'yyyy-MM-dd'));
      setEndDate(format(now, 'yyyy-MM-dd'));
    } else if (preset === 'last_week') {
      const prevWeek = subWeeks(now, 1);
      setStartDate(format(startOfWeek(prevWeek, { weekStartsOn: 1 }), 'yyyy-MM-dd'));
      setEndDate(format(endOfWeek(prevWeek, { weekStartsOn: 1 }), 'yyyy-MM-dd'));
    } else if (preset === 'month') {
      setStartDate(format(startOfMonth(now), 'yyyy-MM-dd'));
      setEndDate(format(now, 'yyyy-MM-dd'));
    }
  };

  // Cập nhật ô trong bảng và lưu tự động vào localStorage
  const updateSubRow = (secIndex: number, rowIndex: number, field: keyof SheetSubRow, value: string) => {
    setSections((prev) => {
      const next = prev.map((sec, sIdx) => {
        if (sIdx !== secIndex) return sec;
        const newRows = sec.rows.map((r, rIdx) => (rIdx === rowIndex ? { ...r, [field]: value } : r));
        return { ...sec, rows: newRows };
      });
      localStorage.setItem(storageKey, JSON.stringify(next));
      return next;
    });
  };

  const updateSectionHeader = (secIndex: number, field: 'title' | 'completed' | 'nextPlan' | 'feedback', value: string) => {
    setSections((prev) => {
      const next = prev.map((sec, sIdx) => (sIdx === secIndex ? { ...sec, [field]: value } : sec));
      localStorage.setItem(storageKey, JSON.stringify(next));
      return next;
    });
  };

  const addSubRow = (secIndex: number) => {
    setSections((prev) => {
      const next = prev.map((sec, sIdx) => {
        if (sIdx !== secIndex) return sec;
        return {
          ...sec,
          rows: [
            ...sec.rows,
            {
              id: `s${sec.sectionNumber}_${Date.now()}`,
              task: '',
              completed: '',
              nextPlan: '',
              feedback: '',
            },
          ],
        };
      });
      localStorage.setItem(storageKey, JSON.stringify(next));
      return next;
    });
  };

  const removeSubRow = (secIndex: number, rowIndex: number) => {
    setSections((prev) => {
      const next = prev.map((sec, sIdx) => {
        if (sIdx !== secIndex || sec.rows.length <= 1) return sec;
        return {
          ...sec,
          rows: sec.rows.filter((_, idx) => idx !== rowIndex),
        };
      });
      localStorage.setItem(storageKey, JSON.stringify(next));
      return next;
    });
  };

  // Xây dựng dữ liệu TSV & HTML chuẩn Google Sheets để Paste 1 chạm khớp 100% cột A -> E
  const handleCopySheet = async (includeHeader: boolean) => {
    const tsvRows: string[] = [];
    const htmlRows: string[] = [];

    if (includeHeader) {
      tsvRows.push(['', 'Công việc', 'Đã hoàn thành trong tuần', 'Kế hoạch cho tuần tiếp theo', 'Feedback Anh/chị'].join('\t'));
      htmlRows.push(`
        <tr style="background-color:#fff2cc;font-weight:bold;text-align:center;font-family:Arial,sans-serif;font-size:10pt;">
          <td style="border:1px solid #000000;"></td>
          <td style="border:1px solid #000000;">Công việc</td>
          <td style="border:1px solid #000000;">Đã hoàn thành trong tuần</td>
          <td style="border:1px solid #000000;">Kế hoạch cho tuần tiếp theo</td>
          <td style="border:1px solid #000000;">Feedback Anh/chị</td>
        </tr>
      `);
    }

    for (const sec of sections) {
      // Dòng tiêu đề Mục (1..6)
      tsvRows.push(
        [
          String(sec.sectionNumber),
          formatTsvCell(sec.title),
          formatTsvCell(sec.completed),
          formatTsvCell(sec.nextPlan),
          formatTsvCell(sec.feedback),
        ].join('\t')
      );

      htmlRows.push(`
        <tr style="font-weight:bold;font-family:Arial,sans-serif;font-size:10pt;">
          <td style="border-top:1px solid #000000;border-bottom:1px dotted #999999;border-left:1px solid #000000;border-right:1px solid #000000;text-align:right;">${sec.sectionNumber}</td>
          <td style="border-top:1px solid #000000;border-bottom:1px dotted #999999;border-right:1px solid #000000;">${escapeHtml(sec.title)}</td>
          <td style="border-top:1px solid #000000;border-bottom:1px dotted #999999;border-right:1px solid #000000;">${escapeHtml(sec.completed)}</td>
          <td style="border-top:1px solid #000000;border-bottom:1px dotted #999999;border-right:1px solid #000000;">${escapeHtml(sec.nextPlan)}</td>
          <td style="border-top:1px solid #000000;border-bottom:1px dotted #999999;border-right:1px solid #000000;">${escapeHtml(sec.feedback)}</td>
        </tr>
      `);

      // Các dòng con của Mục
      sec.rows.forEach((r, idx) => {
        const isLast = idx === sec.rows.length - 1;
        const bottomBorder = isLast ? '1px solid #000000' : '1px dotted #999999';
        tsvRows.push(
          [
            '',
            formatTsvCell(r.task),
            formatTsvCell(r.completed),
            formatTsvCell(r.nextPlan),
            formatTsvCell(r.feedback),
          ].join('\t')
        );

        htmlRows.push(`
          <tr style="font-family:Arial,sans-serif;font-size:10pt;">
            <td style="border-bottom:${bottomBorder};border-left:1px solid #000000;border-right:1px solid #000000;"></td>
            <td style="border-bottom:${bottomBorder};border-right:1px solid #000000;">${escapeHtml(r.task)}</td>
            <td style="border-bottom:${bottomBorder};border-right:1px solid #000000;">${escapeHtml(r.completed)}</td>
            <td style="border-bottom:${bottomBorder};border-right:1px solid #000000;">${escapeHtml(r.nextPlan)}</td>
            <td style="border-bottom:${bottomBorder};border-right:1px solid #000000;">${escapeHtml(r.feedback)}</td>
          </tr>
        `);
      });
    }

    const tsvString = tsvRows.join('\n');
    const htmlString = `<table style="border-collapse:collapse;"><tbody>${htmlRows.join('')}</tbody></table>`;

    try {
      if (navigator.clipboard && window.ClipboardItem) {
        const item = new ClipboardItem({
          'text/plain': new Blob([tsvString], { type: 'text/plain' }),
          'text/html': new Blob([htmlString], { type: 'text/html' }),
        });
        await navigator.clipboard.write([item]);
      } else {
        await navigator.clipboard.writeText(tsvString);
      }
      setCopiedMode(includeHeader ? 'all' : 'body');
      setTimeout(() => setCopiedMode(null), 2500);
    } catch {
      await navigator.clipboard.writeText(tsvString);
      setCopiedMode(includeHeader ? 'all' : 'body');
      setTimeout(() => setCopiedMode(null), 2500);
    }
  };

  const handleCopyText = async (text: string, id: string) => {
    await navigator.clipboard.writeText(text);
    setCopiedMode(id);
    setTimeout(() => setCopiedMode(null), 2000);
  };

  const ttStat = reportData?.lead_stats.tiktok;
  const fbStat = reportData?.lead_stats.facebook;
  const totalStat = reportData?.lead_stats.total;
  const studentStat = reportData?.student_stats;

  return (
    <div className="space-y-4">
      {/* 1. Thanh công cụ lọc Nhân viên, Tuần báo cáo & Nút Copy Sheet */}
      <div className="bg-white rounded-xl border border-slate-200/80 shadow-card p-4 flex flex-col xl:flex-row xl:items-center justify-between gap-4">
        <div className="flex flex-wrap items-center gap-3">
          {/* Chọn Nhân viên */}
          <div className="flex items-center gap-2 bg-eztech-light/60 border border-eztech-border rounded-lg px-3 py-1.5">
            <UserCheck className="w-4 h-4 text-eztech shrink-0" />
            <span className="text-[11px] font-bold uppercase tracking-wider text-navy shrink-0">Nhân sự:</span>
            <select
              value={selectedEmployee}
              onChange={(e) => handleEmployeeChange(e.target.value)}
              className="bg-transparent text-xs font-bold text-eztech focus:outline-none cursor-pointer pr-2"
            >
              <option value="">Tất cả nhân viên</option>
              {(reportData?.employees_list || []).map((emp) => (
                <option key={emp} value={emp}>
                  {emp}
                </option>
              ))}
            </select>
          </div>

          {/* Nút chọn nhanh Tuần */}
          <div className="inline-flex items-center bg-slate-100/90 p-0.5 rounded-lg border border-slate-200/70">
            {[
              { id: 'this_week' as const, label: 'Tuần này' },
              { id: '7d' as const, label: '7 ngày qua' },
              { id: 'last_week' as const, label: 'Tuần trước' },
              { id: 'month' as const, label: 'Tháng này' },
            ].map((p) => (
              <button
                key={p.id}
                type="button"
                onClick={() => applyDatePreset(p.id)}
                className={`px-2.5 py-1 rounded-md text-xs font-semibold transition-all ${
                  activePreset === p.id
                    ? 'bg-white text-eztech shadow-2xs'
                    : 'text-slate-600 hover:text-navy'
                }`}
              >
                {p.label}
              </button>
            ))}
          </div>

          {/* Khoảng ngày */}
          <div className="flex items-center gap-1.5 bg-slate-50 border border-slate-200/80 rounded-lg px-2.5 py-1">
            <Calendar className="w-3.5 h-3.5 text-eztech" />
            <input
              type="date"
              value={startDate}
              onChange={(e) => {
                setStartDate(e.target.value);
                setActivePreset('custom');
              }}
              className="bg-transparent text-xs font-mono font-medium text-navy focus:outline-none cursor-pointer tabular-nums"
            />
            <span className="text-slate-300 text-xs">→</span>
            <input
              type="date"
              value={endDate}
              onChange={(e) => {
                setEndDate(e.target.value);
                setActivePreset('custom');
              }}
              className="bg-transparent text-xs font-mono font-medium text-navy focus:outline-none cursor-pointer tabular-nums"
            />
          </div>
        </div>

        {/* Các nút thao tác: Tự điền lại & Copy Paste Sheet */}
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => loadReport(true)}
            disabled={loading}
            title="Khôi phục & tự động điền lại số liệu mới nhất từ hệ thống"
            className="px-3 py-1.5 rounded-lg text-xs font-semibold bg-white hover:bg-slate-50 text-slate-700 border border-slate-200/90 flex items-center gap-1.5 transition-all shadow-2xs cursor-pointer"
          >
            <RotateCcw className={`w-3.5 h-3.5 text-eztech ${loading ? 'animate-spin' : ''}`} />
            <span>Tự điền lại số liệu</span>
          </button>

          <button
            type="button"
            onClick={() => handleCopySheet(false)}
            className="px-3 py-1.5 rounded-lg text-xs font-semibold bg-amber-50 hover:bg-amber-100/80 text-navy border border-amber-300 flex items-center gap-1.5 transition-all cursor-pointer"
          >
            {copiedMode === 'body' ? (
              <>
                <Check className="w-3.5 h-3.5 text-emerald-600" />
                <span className="text-emerald-700">Đã copy phần nội dung!</span>
              </>
            ) : (
              <>
                <Copy className="w-3.5 h-3.5 text-amber-600" />
                <span>Copy nội dung (Paste vào A2)</span>
              </>
            )}
          </button>

          <button
            type="button"
            onClick={() => handleCopySheet(true)}
            className="px-3.5 py-1.5 rounded-lg text-xs font-bold bg-eztech hover:bg-eztech/90 text-white flex items-center gap-1.5 transition-all shadow-sm cursor-pointer"
          >
            {copiedMode === 'all' ? (
              <>
                <Check className="w-4 h-4 text-gold" />
                <span>Đã Copy chuẩn Google Sheet! (Bấm Ctrl+V)</span>
              </>
            ) : (
              <>
                <FileSpreadsheet className="w-4 h-4 text-gold" />
                <span>Copy toàn bộ bảng (Paste vào Sheet)</span>
              </>
            )}
          </button>
        </div>
      </div>

      {/* 2. Thẻ tóm tắt nhanh Số liệu & Insight của Nhân viên trong tuần */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-3.5">
        {/* Card 1: TikTok Lead */}
        <div className="bg-white rounded-xl border border-slate-200/80 shadow-card p-3.5 flex flex-col justify-between">
          <div className="flex items-center justify-between">
            <span className="text-xs font-bold text-navy flex items-center gap-1.5">
              <span className="w-2 h-2 rounded-full bg-eztech" />
              Lead TikTok trong tuần
            </span>
            <button
              type="button"
              onClick={() => handleCopyText(ttStat?.formatted_line || '', 'tt_line')}
              className="text-[11px] font-semibold text-eztech hover:underline flex items-center gap-1 cursor-pointer"
            >
              {copiedMode === 'tt_line' ? <Check className="w-3 h-3 text-emerald-600" /> : <Copy className="w-3 h-3" />}
              <span>{copiedMode === 'tt_line' ? 'Đã copy' : 'Copy dòng'}</span>
            </button>
          </div>
          <div className="my-2 grid grid-cols-3 gap-2 text-center bg-slate-50/80 rounded-lg p-2 border border-slate-100">
            <div>
              <p className="text-[10px] text-slate-400 font-medium">Tạo mới</p>
              <p className="text-base font-extrabold text-navy tabular-nums">{ttStat?.new_leads ?? 0}</p>
            </div>
            <div className="border-x border-slate-200/70">
              <p className="text-[10px] text-slate-400 font-medium">Contact</p>
              <p className="text-base font-extrabold text-eztech tabular-nums">{ttStat?.total_contacted ?? 0}</p>
            </div>
            <div>
              <p className="text-[10px] text-slate-400 font-medium">SĐT</p>
              <p className="text-base font-extrabold text-emerald-600 tabular-nums">{ttStat?.phone_leads ?? 0}</p>
            </div>
          </div>
          <p className="text-[11px] font-mono text-slate-600 bg-slate-50 px-2 py-1 rounded border border-slate-200/60 truncate">
            {ttStat?.formatted_line || 'Tiktok: Tạo mới: 0, Contact trong tuần: 0, SĐT 0.'}
          </p>
        </div>

        {/* Card 2: Facebook Lead */}
        <div className="bg-white rounded-xl border border-slate-200/80 shadow-card p-3.5 flex flex-col justify-between">
          <div className="flex items-center justify-between">
            <span className="text-xs font-bold text-navy flex items-center gap-1.5">
              <span className="w-2 h-2 rounded-full bg-amber-500" />
              Lead Facebook trong tuần
            </span>
            <button
              type="button"
              onClick={() => handleCopyText(fbStat?.formatted_line || '', 'fb_line')}
              className="text-[11px] font-semibold text-eztech hover:underline flex items-center gap-1 cursor-pointer"
            >
              {copiedMode === 'fb_line' ? <Check className="w-3 h-3 text-emerald-600" /> : <Copy className="w-3 h-3" />}
              <span>{copiedMode === 'fb_line' ? 'Đã copy' : 'Copy dòng'}</span>
            </button>
          </div>
          <div className="my-2 grid grid-cols-3 gap-2 text-center bg-slate-50/80 rounded-lg p-2 border border-slate-100">
            <div>
              <p className="text-[10px] text-slate-400 font-medium">Tạo mới</p>
              <p className="text-base font-extrabold text-navy tabular-nums">{fbStat?.new_leads ?? 0}</p>
            </div>
            <div className="border-x border-slate-200/70">
              <p className="text-[10px] text-slate-400 font-medium">Contact</p>
              <p className="text-base font-extrabold text-eztech tabular-nums">{fbStat?.total_contacted ?? 0}</p>
            </div>
            <div>
              <p className="text-[10px] text-slate-400 font-medium">SĐT</p>
              <p className="text-base font-extrabold text-emerald-600 tabular-nums">{fbStat?.phone_leads ?? 0}</p>
            </div>
          </div>
          <p className="text-[11px] font-mono text-slate-600 bg-slate-50 px-2 py-1 rounded border border-slate-200/60 truncate">
            {fbStat?.formatted_line || 'FB: Tạo mới: 0, Contact: 0, SĐT: 0'}
          </p>
        </div>

        {/* Card 3: Học viên & Lớp học */}
        <div className="bg-white rounded-xl border border-slate-200/80 shadow-card p-3.5 flex flex-col justify-between">
          <div className="flex items-center justify-between">
            <span className="text-xs font-bold text-navy flex items-center gap-1.5">
              <Award className="w-3.5 h-3.5 text-amber-500" />
              Học viên chốt & Lớp học
            </span>
            <span className="text-[11px] font-bold text-emerald-700 bg-emerald-50 px-2 py-0.5 rounded-full border border-emerald-200">
              {studentStat?.total_deals ?? 0} học viên
            </span>
          </div>
          <div className="my-2 space-y-1 text-xs">
            <div className="flex items-center justify-between text-slate-600">
              <span>Tổng Lead liên hệ:</span>
              <span className="font-bold text-navy tabular-nums">
                {totalStat?.total_contacted ?? 0} lead ({totalStat?.phone_leads ?? 0} SĐT - {totalStat?.phone_rate ?? 0}%)
              </span>
            </div>
            <div className="flex items-center justify-between text-slate-600">
              <span>Mã lớp phụ trách:</span>
              <span className="font-bold text-eztech">
                {studentStat?.classes?.length ? studentStat.classes.join(', ') : 'PBIK59'}
              </span>
            </div>
          </div>
          <p className="text-[11px] text-slate-600 bg-amber-50/60 px-2 py-1 rounded border border-amber-200/60 truncate">
            {studentStat?.formatted_line || 'Chưa phát sinh học viên mới trong tuần'}
          </p>
        </div>

        {/* Card 4: Insight khách hàng thu được */}
        <div className="bg-white rounded-xl border border-slate-200/80 shadow-card p-3.5 flex flex-col justify-between">
          <div className="flex items-center justify-between">
            <span className="text-xs font-bold text-navy flex items-center gap-1.5">
              <Lightbulb className="w-3.5 h-3.5 text-eztech" />
              Insight & Tag chăm sóc
            </span>
            <button
              type="button"
              onClick={() =>
                handleCopyText((reportData?.insights.formatted_lines || []).join('\n'), 'insight_line')
              }
              className="text-[11px] font-semibold text-eztech hover:underline flex items-center gap-1 cursor-pointer"
            >
              {copiedMode === 'insight_line' ? <Check className="w-3 h-3 text-emerald-600" /> : <Copy className="w-3 h-3" />}
              <span>{copiedMode === 'insight_line' ? 'Đã copy' : 'Copy'}</span>
            </button>
          </div>
          <div className="my-1.5 flex flex-wrap gap-1">
            {(reportData?.lead_stats.top_tags || []).slice(0, 4).map((t) => (
              <span
                key={t.tag}
                className="px-2 py-0.5 text-[10px] font-semibold rounded bg-eztech-light text-eztech border border-eztech-border"
              >
                {t.tag}: {t.count}
              </span>
            ))}
            {(!reportData?.lead_stats.top_tags || reportData.lead_stats.top_tags.length === 0) && (
              <span className="text-[11px] text-slate-400">Chưa có tag phân loại trong tuần</span>
            )}
          </div>
          <p className="text-[11px] text-slate-600 line-clamp-2 leading-snug">
            {reportData?.insights.formatted_lines?.[2] ||
              reportData?.insights.formatted_lines?.[0] ||
              'Chọn nhân viên để tổng hợp insight ngành nghề & kỳ vọng học viên.'}
          </p>
        </div>
      </div>

      {/* 3. Bảng Form Báo cáo Công việc chuẩn Google Sheet (5 cột A -> E) */}
      <div className="bg-white rounded-xl border border-slate-300 shadow-card overflow-hidden">
        {/* Thanh tiêu đề kiểu Google Sheet */}
        <div className="bg-[#f8f9fa] border-b border-slate-300 px-4 py-2.5 flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <div className="w-6 h-6 rounded bg-emerald-600 text-white flex items-center justify-center font-bold text-xs shadow-2xs">
              <FileSpreadsheet className="w-3.5 h-3.5" />
            </div>
            <div>
              <h3 className="text-xs sm:text-sm font-bold text-navy">
                Báo cáo công việc - EzTech - {selectedEmployee || 'Tất cả nhân sự'}
              </h3>
              <p className="text-[11px] text-slate-500">
                Kỳ báo cáo: <span className="font-mono font-semibold text-navy">{startDate}</span> →{' '}
                <span className="font-mono font-semibold text-navy">{endDate}</span> • Nhấp trực tiếp vào từng ô để chỉnh sửa trước khi Copy sang Google Sheet
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2 text-[11px] text-slate-500">
            <span className="inline-flex items-center gap-1 bg-white px-2.5 py-1 rounded border border-slate-200 font-medium">
              <Sparkles className="w-3 h-3 text-amber-500" />
              Tự động lưu nháp trên trình duyệt
            </span>
          </div>
        </div>

        {/* Bảng Spreadsheet */}
        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-xs font-sans">
            {/* Thanh ký hiệu cột A, B, C, D, E giống Google Sheet */}
            <thead>
              <tr className="bg-[#f1f3f4] text-slate-600 text-[11px] font-semibold select-none">
                <th className="w-10 border-b border-r border-slate-300 py-1 text-center"></th>
                <th className="w-12 border-b border-r border-slate-300 py-1 text-center">A</th>
                <th className="w-56 border-b border-r border-slate-300 py-1 text-center">B</th>
                <th className="min-w-[360px] border-b border-r border-slate-300 py-1 text-center">C</th>
                <th className="w-64 border-b border-r border-slate-300 py-1 text-center">D</th>
                <th className="w-56 border-b border-slate-300 py-1 text-center">E</th>
              </tr>
              {/* Hàng 1: Tiêu đề cột nền vàng nhạt #fff2cc chuẩn theo mẫu */}
              <tr className="bg-[#fff2cc] text-navy font-bold text-xs">
                <td className="bg-[#f1f3f4] text-slate-500 text-[11px] font-normal text-center border-b border-r border-slate-300 py-2">
                  1
                </td>
                <td className="border-b border-r border-slate-400 px-2 py-2 text-center"></td>
                <td className="border-b border-r border-slate-400 px-3 py-2 text-center">Công việc</td>
                <td className="border-b border-r border-slate-400 px-3 py-2 text-center">Đã hoàn thành trong tuần</td>
                <td className="border-b border-r border-slate-400 px-3 py-2 text-center">Kế hoạch cho tuần tiếp theo</td>
                <td className="border-b border-slate-400 px-3 py-2 text-center">Feedback Anh/chị</td>
              </tr>
            </thead>

            <tbody>
              {(() => {
                let sheetRowNumber = 1;
                return sections.map((sec, secIdx) => {
                  sheetRowNumber += 1;
                  const headerRowNum = sheetRowNumber;

                  return (
                    <FragmentSection
                      key={sec.sectionNumber}
                      sec={sec}
                      secIdx={secIdx}
                      headerRowNum={headerRowNum}
                      getNextRowNum={() => {
                        sheetRowNumber += 1;
                        return sheetRowNumber;
                      }}
                      onUpdateHeader={updateSectionHeader}
                      onUpdateSubRow={updateSubRow}
                      onAddSubRow={addSubRow}
                      onRemoveSubRow={removeSubRow}
                    />
                  );
                });
              })()}
            </tbody>
          </table>
        </div>
      </div>

      {/* 4. Chi tiết Lead theo Fanpage & Danh sách Học viên trong kỳ (Để đối chiếu nhanh) */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Bảng chi tiết Lead theo từng Page của Nhân viên */}
        <div className="bg-white rounded-xl border border-slate-200/80 shadow-card p-4">
          <div className="flex items-center justify-between mb-3">
            <div>
              <h4 className="text-xs font-bold text-navy uppercase tracking-wider flex items-center gap-1.5">
                <Users className="w-3.5 h-3.5 text-eztech" />
                Chi tiết Lead theo Kênh của {selectedEmployee || 'Tất cả nhân sự'}
              </h4>
              <p className="text-[11px] text-slate-400 mt-0.5">
                Số liệu bóc tách tự động từ Pancake CRM trong kỳ đã chọn
              </p>
            </div>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-slate-200 text-slate-400 text-[10px] font-bold uppercase">
                  <th className="py-2 text-left">Kênh / Fanpage</th>
                  <th className="py-2 text-right">Tạo mới</th>
                  <th className="py-2 text-right">Contact lại</th>
                  <th className="py-2 text-right">Tổng Contact</th>
                  <th className="py-2 text-right">SĐT</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {(reportData?.lead_stats.by_page || []).map((pg) => (
                  <tr key={pg.page_name} className="hover:bg-slate-50/80">
                    <td className="py-2 font-medium text-navy flex items-center gap-1.5">
                      <span
                        className={`w-2 h-2 rounded-full shrink-0 ${
                          pg.platform === 'tiktok' ? 'bg-eztech' : 'bg-amber-500'
                        }`}
                      />
                      <span className="truncate max-w-[220px]">{pg.page_name}</span>
                    </td>
                    <td className="py-2 text-right font-mono tabular-nums text-slate-700">{pg.new_leads}</td>
                    <td className="py-2 text-right font-mono tabular-nums text-slate-500">{pg.recontact_leads}</td>
                    <td className="py-2 text-right font-mono font-bold tabular-nums text-eztech">{pg.total_contacted}</td>
                    <td className="py-2 text-right font-mono font-bold tabular-nums text-emerald-600">{pg.phone_leads}</td>
                  </tr>
                ))}
                {(!reportData?.lead_stats.by_page || reportData.lead_stats.by_page.length === 0) && (
                  <tr>
                    <td colSpan={5} className="py-6 text-center text-slate-400">
                      Không có dữ liệu liên hệ trong khoảng thời gian này.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>

        {/* Bảng chi tiết Học viên & Insight kỳ vọng */}
        <div className="bg-white rounded-xl border border-slate-200/80 shadow-card p-4">
          <div className="flex items-center justify-between mb-3">
            <div>
              <h4 className="text-xs font-bold text-navy uppercase tracking-wider flex items-center gap-1.5">
                <Award className="w-3.5 h-3.5 text-amber-500" />
                Học viên chốt & Insight kỳ vọng ({studentStat?.students.length || 0})
              </h4>
              <p className="text-[11px] text-slate-400 mt-0.5">
                Tổng hợp từ Form Học viên (Deal Win) & Quản lý Công nợ
              </p>
            </div>
          </div>

          <div className="space-y-2 max-h-60 overflow-y-auto pr-1">
            {(studentStat?.students || []).map((st, idx) => (
              <div
                key={`${st.phone_number}_${idx}`}
                className="p-2.5 rounded-lg bg-slate-50/90 border border-slate-200/70 space-y-1"
              >
                <div className="flex items-center justify-between">
                  <span className="text-xs font-bold text-navy">
                    {st.full_name}{' '}
                    {st.phone_number && (
                      <span className="font-mono text-[11px] font-normal text-slate-500">({st.phone_number})</span>
                    )}
                  </span>
                  <span className="text-[10px] font-semibold text-eztech bg-eztech-light px-2 py-0.5 rounded">
                    {st.class_code || st.course || st.page_id || 'Học viên mới'}
                  </span>
                </div>
                {(st.industry || st.job_title) && (
                  <p className="text-[11px] text-slate-600">
                    <span className="font-semibold text-slate-700">Ngành/Vị trí:</span>{' '}
                    {[st.job_title, st.industry].filter(Boolean).join(' • ')}
                  </p>
                )}
                {st.expectation && (
                  <p className="text-[11px] text-slate-600 italic">
                    <span className="font-semibold not-italic text-slate-700">Kỳ vọng:</span> "{st.expectation}"
                  </p>
                )}
              </div>
            ))}
            {(!studentStat?.students || studentStat.students.length === 0) && (
              <div className="py-6 text-center text-xs text-slate-400">
                Chưa có học viên chốt mới trong khoảng ngày này.
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

interface FragmentSectionProps {
  sec: SheetSection;
  secIdx: number;
  headerRowNum: number;
  getNextRowNum: () => number;
  onUpdateHeader: (secIndex: number, field: 'title' | 'completed' | 'nextPlan' | 'feedback', value: string) => void;
  onUpdateSubRow: (secIndex: number, rowIndex: number, field: keyof SheetSubRow, value: string) => void;
  onAddSubRow: (secIndex: number) => void;
  onRemoveSubRow: (secIndex: number, rowIndex: number) => void;
}

function FragmentSection({
  sec,
  secIdx,
  headerRowNum,
  getNextRowNum,
  onUpdateHeader,
  onUpdateSubRow,
  onAddSubRow,
  onRemoveSubRow,
}: FragmentSectionProps) {
  return (
    <>
      {/* Dòng tiêu đề Mục (1, 2, 3, 4, 5, 6) */}
      <tr className="bg-slate-50/90 font-bold text-navy border-t border-slate-400">
        <td className="bg-[#f1f3f4] text-slate-500 text-[11px] font-normal text-center border-b border-r border-slate-300 py-1.5 select-none">
          {headerRowNum}
        </td>
        <td className="border-b border-dotted border-slate-300 border-r border-r-slate-400 px-2.5 py-1.5 text-right font-bold text-navy">
          {sec.sectionNumber}
        </td>
        <td className="border-b border-dotted border-slate-300 border-r border-r-slate-400 px-2.5 py-1.5">
          <div className="flex items-center justify-between gap-1">
            <input
              type="text"
              value={sec.title}
              onChange={(e) => onUpdateHeader(secIdx, 'title', e.target.value)}
              className="w-full bg-transparent font-bold text-navy focus:outline-none focus:bg-white focus:ring-1 focus:ring-eztech rounded px-1 py-0.5"
            />
            <button
              type="button"
              onClick={() => onAddSubRow(secIdx)}
              title="Thêm dòng công việc vào mục này"
              className="p-1 text-slate-400 hover:text-eztech hover:bg-eztech-light rounded transition-colors shrink-0 cursor-pointer"
            >
              <Plus className="w-3.5 h-3.5" />
            </button>
          </div>
        </td>
        <td className="border-b border-dotted border-slate-300 border-r border-r-slate-400 px-2.5 py-1">
          <input
            type="text"
            value={sec.completed}
            onChange={(e) => onUpdateHeader(secIdx, 'completed', e.target.value)}
            className="w-full bg-transparent font-semibold text-navy focus:outline-none focus:bg-white focus:ring-1 focus:ring-eztech rounded px-1 py-0.5"
          />
        </td>
        <td className="border-b border-dotted border-slate-300 border-r border-r-slate-400 px-2.5 py-1">
          <input
            type="text"
            value={sec.nextPlan}
            onChange={(e) => onUpdateHeader(secIdx, 'nextPlan', e.target.value)}
            className="w-full bg-transparent font-semibold text-navy focus:outline-none focus:bg-white focus:ring-1 focus:ring-eztech rounded px-1 py-0.5"
          />
        </td>
        <td className="border-b border-dotted border-slate-300 px-2.5 py-1">
          <input
            type="text"
            value={sec.feedback}
            onChange={(e) => onUpdateHeader(secIdx, 'feedback', e.target.value)}
            className="w-full bg-transparent font-semibold text-navy focus:outline-none focus:bg-white focus:ring-1 focus:ring-eztech rounded px-1 py-0.5"
          />
        </td>
      </tr>

      {/* Các dòng con thuộc Mục */}
      {sec.rows.map((row, rIdx) => {
        const rowNum = getNextRowNum();
        const isLast = rIdx === sec.rows.length - 1;
        const borderBottomClass = isLast ? 'border-b border-slate-400' : 'border-b border-dotted border-slate-300';
        const lineCount = Math.max(
          1,
          (row.completed || '').split('\n').length,
          (row.nextPlan || '').split('\n').length
        );

        return (
          <tr key={row.id} className="group hover:bg-eztech-light/20 transition-colors">
            <td className="bg-[#f1f3f4] text-slate-500 text-[11px] font-normal text-center border-b border-r border-slate-300 py-1 select-none">
              {rowNum}
            </td>
            <td className={`${borderBottomClass} border-r border-r-slate-400 px-2 py-1 text-center relative`}>
              {sec.rows.length > 1 && (
                <button
                  type="button"
                  onClick={() => onRemoveSubRow(secIdx, rIdx)}
                  title="Xoá dòng này"
                  className="opacity-0 group-hover:opacity-100 p-0.5 text-slate-300 hover:text-rose-600 transition-opacity cursor-pointer"
                >
                  <Trash2 className="w-3 h-3" />
                </button>
              )}
            </td>
            <td className={`${borderBottomClass} border-r border-r-slate-400 px-2.5 py-1 align-top`}>
              <input
                type="text"
                value={row.task}
                placeholder="..."
                onChange={(e) => onUpdateSubRow(secIdx, rIdx, 'task', e.target.value)}
                className="w-full bg-transparent text-slate-800 placeholder:text-slate-300 focus:outline-none focus:bg-white focus:ring-1 focus:ring-eztech rounded px-1 py-0.5"
              />
            </td>
            <td className={`${borderBottomClass} border-r border-r-slate-400 px-2.5 py-1 align-top`}>
              <textarea
                rows={lineCount}
                value={row.completed}
                placeholder="Nhập kết quả hoàn thành..."
                onChange={(e) => onUpdateSubRow(secIdx, rIdx, 'completed', e.target.value)}
                className="w-full bg-transparent text-slate-800 placeholder:text-slate-300 focus:outline-none focus:bg-white focus:ring-1 focus:ring-eztech rounded px-1 py-0.5 resize-y leading-relaxed"
              />
            </td>
            <td className={`${borderBottomClass} border-r border-r-slate-400 px-2.5 py-1 align-top`}>
              <textarea
                rows={lineCount}
                value={row.nextPlan}
                placeholder="Nhập kế hoạch tuần tới..."
                onChange={(e) => onUpdateSubRow(secIdx, rIdx, 'nextPlan', e.target.value)}
                className="w-full bg-transparent text-slate-800 placeholder:text-slate-300 focus:outline-none focus:bg-white focus:ring-1 focus:ring-eztech rounded px-1 py-0.5 resize-y leading-relaxed"
              />
            </td>
            <td className={`${borderBottomClass} px-2.5 py-1 align-top`}>
              <textarea
                rows={lineCount}
                value={row.feedback}
                placeholder="..."
                onChange={(e) => onUpdateSubRow(secIdx, rIdx, 'feedback', e.target.value)}
                className="w-full bg-transparent text-slate-800 placeholder:text-slate-300 focus:outline-none focus:bg-white focus:ring-1 focus:ring-eztech rounded px-1 py-0.5 resize-y leading-relaxed"
              />
            </td>
          </tr>
        );
      })}
    </>
  );
}
