import { useState, useEffect, useMemo } from 'react';
import { format } from 'date-fns';
import {
  Plus,
  Search,
  RefreshCw,
  Edit3,
  Trash2,
  DollarSign,
  AlertTriangle,
  CheckCircle2,
  Clock,
  FileSpreadsheet,
  ListChecks,
  History,
  ExternalLink,
  X,
  Sparkles,
  Tag,
  Save,
  UserCheck,
  Wallet,
  CreditCard,
  TrendingUp,
} from 'lucide-react';
import {
  fetchDealEntryInit,
  lookupDealPhone,
  saveSalesDeal,
  updateSalesDealClasses,
  deleteSalesDeal,
  saveDealEntryLists,
  fetchDealEntryLogs,
  getStoredAuth,
  type SalesDealRecord,
  type DebtSummaryData,
  type DealEntryLists,
  type PhoneLookupResponse,
  type DealAuditLogItem,
} from '../services/api';

const fmtMoney = (n: number | undefined | null) => {
  const val = Number(n || 0);
  return val.toLocaleString('vi-VN');
};

const fmtDateVi = (iso: string | undefined | null) => {
  if (!iso) return '—';
  if (iso.length >= 10 && iso[4] === '-' && iso[7] === '-') {
    return `${iso.slice(8, 10)}/${iso.slice(5, 7)}/${iso.slice(0, 4)}`;
  }
  return iso;
};

const parseMoneyInput = (raw: string): number => {
  const digits = raw.replace(/\D/g, '');
  return digits ? parseInt(digits, 10) : 0;
};

export function AppScriptTool() {
  const currentUser = getStoredAuth().user;
  const actorName = currentUser?.username || 'admin';

  const [subTab, setSubTab] = useState<'deals' | 'debts' | 'lists' | 'logs'>('deals');
  const [loading, setLoading] = useState<boolean>(true);
  const [saving, setSaving] = useState<boolean>(false);

  const [deals, setDeals] = useState<SalesDealRecord[]>([]);
  const [debts, setDebts] = useState<DebtSummaryData>({
    items: [],
    totalPhaiThu: 0,
    totalDaThuNo: 0,
    totalConNo: 0,
    count: 0,
  });
  const [lists, setLists] = useState<DealEntryLists>({
    zaloCS: [],
    nguon: [],
    chuongTrinh: [],
    lop: [],
  });
  const [statuses, setStatuses] = useState<string[]>([
    'Hoàn thành',
    'Còn nợ',
    'Thu nợ',
    'Đã thu hết nợ',
    'Đặt cọc',
    'Bảo lưu',
    'Hoàn học phí',
  ]);
  const [logs, setLogs] = useState<DealAuditLogItem[]>([]);

  // Bộ lọc bảng Deals
  const [searchQuery, setSearchQuery] = useState('');
  const [filterStartDate, setFilterStartDate] = useState('');
  const [filterEndDate, setFilterEndDate] = useState('');
  const [filterProgram, setFilterProgram] = useState('');
  const [filterClass, setFilterClass] = useState('');
  const [filterStatus, setFilterStatus] = useState('');
  const [filterSale, setFilterSale] = useState('');

  // Modal Nhập / Sửa Deal
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [formNgThu, setFormNgThu] = useState(format(new Date(), 'yyyy-MM-dd'));
  const [formNgContact, setFormNgContact] = useState('');
  const [formSdt, setFormSdt] = useState('');
  const [formHoTen, setFormHoTen] = useState('');
  const [formZalo, setFormZalo] = useState('');
  const [formNhomCS, setFormNhomCS] = useState('');
  const [formChuongTrinh, setFormChuongTrinh] = useState('');
  const [formLop, setFormLop] = useState<string[]>([]);
  const [newClassInput, setNewClassInput] = useState('');
  const [formChucVu, setFormChucVu] = useState('');
  const [formNvCS, setFormNvCS] = useState('');
  const [formZaloCS, setFormZaloCS] = useState('');
  const [formNguon, setFormNguon] = useState('');
  const [formDaThu, setFormDaThu] = useState<number>(0);
  const [formPhaiThu, setFormPhaiThu] = useState<number>(0);
  const [formTongTien, setFormTongTien] = useState<number>(0);
  const [formNgThuAR, setFormNgThuAR] = useState('');
  const [formTrangThai, setFormTrangThai] = useState('Hoàn thành');
  const [formNote, setFormNote] = useState('');

  // Kết quả tra cứu SĐT thông minh
  const [phoneLookup, setPhoneLookup] = useState<PhoneLookupResponse | null>(null);
  const [lookingUpPhone, setLookingUpPhone] = useState(false);

  // Modal sửa nhanh Lớp học
  const [classModalDeal, setClassModalDeal] = useState<SalesDealRecord | null>(null);
  const [quickClasses, setQuickClasses] = useState<string[]>([]);
  const [quickNewClass, setQuickNewClass] = useState('');

  // Quản lý danh mục
  const [draftLists, setDraftLists] = useState<DealEntryLists>({
    zaloCS: [],
    nguon: [],
    chuongTrinh: [],
    lop: [],
  });
  const [newItemText, setNewItemText] = useState<Record<string, string>>({});

  const loadAll = async (force: boolean = false) => {
    setLoading(true);
    try {
      const res = await fetchDealEntryInit(force);
      if (res.ok) {
        setDeals(res.deals || []);
        setDebts(res.debts || { items: [], totalPhaiThu: 0, totalDaThuNo: 0, totalConNo: 0, count: 0 });
        setLists(res.lists);
        setDraftLists(res.lists);
        if (res.statuses?.length) setStatuses(res.statuses);
      }
    } catch (err) {
      console.error('Lỗi tải dữ liệu Deal Entry:', err);
    } finally {
      setLoading(false);
    }
  };

  const loadLogs = async () => {
    try {
      const res = await fetchDealEntryLogs(50);
      if (res.ok) setLogs(res.logs || []);
    } catch (err) {
      console.error('Lỗi tải nhật ký:', err);
    }
  };

  useEffect(() => {
    loadAll(false);
  }, []);

  useEffect(() => {
    if (subTab === 'logs') {
      loadLogs();
    }
  }, [subTab]);

  // Tự động tra cứu SĐT khi người dùng nhập đủ 10 chữ số
  useEffect(() => {
    if (!isModalOpen) return;
    const clean = formSdt.replace(/\D/g, '');
    if (clean.length < 10) {
      setPhoneLookup(null);
      return;
    }

    const timer = setTimeout(async () => {
      setLookingUpPhone(true);
      try {
        const res = await lookupDealPhone(clean, editingId || undefined);
        setPhoneLookup(res);
        if (res.found && !editingId) {
          if (res.hoTen && !formHoTen) setFormHoTen(res.hoTen);
          if (res.ngayContact && !formNgContact) setFormNgContact(res.ngayContact);
          if (res.zalo && !formZalo) setFormZalo(res.zalo);
          if (res.nhomCS && !formNhomCS) setFormNhomCS(res.nhomCS);
          if (res.chucVu && !formChucVu) setFormChucVu(res.chucVu);
          if (res.nvCS && !formNvCS) setFormNvCS(res.nvCS);
          if (res.zaloCS && !formZaloCS) setFormZaloCS(res.zaloCS);
          if (res.nguon && !formNguon) setFormNguon(res.nguon);
          if (res.lop && res.lop.length > 0 && formLop.length === 0) {
            setFormLop(res.lop);
          }
        }
      } catch (e) {
        console.error('Lookup phone error:', e);
      } finally {
        setLookingUpPhone(false);
      }
    }, 350);

    return () => clearTimeout(timer);
  }, [formSdt, isModalOpen, editingId]);

  // Mở modal thêm mới
  const openCreateModal = () => {
    setEditingId(null);
    setFormNgThu(format(new Date(), 'yyyy-MM-dd'));
    setFormNgContact('');
    setFormSdt('');
    setFormHoTen('');
    setFormZalo('');
    setFormNhomCS('');
    setFormChuongTrinh(lists.chuongTrinh[0] || '');
    setFormLop([]);
    setNewClassInput('');
    setFormChucVu('');
    setFormNvCS(actorName);
    setFormZaloCS(lists.zaloCS[0] || '');
    setFormNguon(lists.nguon[0] || '');
    setFormDaThu(0);
    setFormPhaiThu(0);
    setFormTongTien(0);
    setFormNgThuAR('');
    setFormTrangThai('Hoàn thành');
    setFormNote('');
    setPhoneLookup(null);
    setIsModalOpen(true);
  };

  // Mở modal sửa deal
  const openEditModal = (d: SalesDealRecord) => {
    setEditingId(d.id);
    setFormNgThu(d.ngayThu || format(new Date(), 'yyyy-MM-dd'));
    setFormNgContact(d.ngayContact || '');
    setFormSdt(d.sdt || '');
    setFormHoTen(d.hoTen || '');
    setFormZalo(d.zalo || '');
    setFormNhomCS(d.nhomCS || '');
    setFormChuongTrinh(d.chuongTrinh || '');
    setFormLop(d.lop || []);
    setNewClassInput('');
    setFormChucVu(d.chucVu || '');
    setFormNvCS(d.nvCS || '');
    setFormZaloCS(d.zaloCS || '');
    setFormNguon(d.nguon || '');
    setFormDaThu(d.daThu || 0);
    setFormPhaiThu(d.phaiThu || 0);
    setFormTongTien(d.tongTien || 0);
    setFormNgThuAR(d.ngayThuAR || '');
    setFormTrangThai(d.trangThai || 'Hoàn thành');
    setFormNote(d.note || '');
    setPhoneLookup(null);
    setIsModalOpen(true);
  };

  // Mở modal Thu nợ nhanh từ dòng deal hoặc bảng công nợ
  const openCollectDebtModal = (item: {
    sdt: string;
    hoTen: string;
    conNo: number;
    ngayThuGoc: string;
    chuongTrinh?: string;
    lop?: string[];
    nvCS?: string;
  }) => {
    setEditingId(null);
    setFormNgThu(format(new Date(), 'yyyy-MM-dd'));
    setFormNgContact('');
    setFormSdt(item.sdt);
    setFormHoTen(item.hoTen);
    setFormZalo('');
    setFormNhomCS('');
    setFormChuongTrinh(item.chuongTrinh || '');
    setFormLop(item.lop || []);
    setNewClassInput('');
    setFormChucVu('');
    setFormNvCS(item.nvCS || actorName);
    setFormZaloCS(lists.zaloCS[0] || '');
    setFormNguon(lists.nguon[0] || '');
    setFormDaThu(item.conNo);
    setFormPhaiThu(0);
    setFormTongTien(0);
    setFormNgThuAR(format(new Date(), 'yyyy-MM-dd'));
    setFormTrangThai('Thu nợ');
    setFormNote(`Thu nợ deal ngày ${fmtDateVi(item.ngayThuGoc)}`);
    setIsModalOpen(true);
  };

  const handleDaThuChange = (val: number) => {
    setFormDaThu(val);
    if (formTrangThai !== 'Thu nợ') {
      setFormTongTien(val + formPhaiThu);
    }
  };

  const handlePhaiThuChange = (val: number) => {
    setFormPhaiThu(val);
    setFormTongTien(formDaThu + val);
    if (val > 0 && formTrangThai === 'Hoàn thành') {
      setFormTrangThai('Còn nợ');
    } else if (val === 0 && formTrangThai === 'Còn nợ') {
      setFormTrangThai('Hoàn thành');
    }
  };

  const toggleClassInForm = (cls: string) => {
    setFormLop((prev) =>
      prev.includes(cls) ? prev.filter((x) => x !== cls) : [...prev, cls]
    );
  };

  const addCustomClassToForm = () => {
    const c = newClassInput.trim();
    if (!c) return;
    if (!formLop.includes(c)) {
      setFormLop((prev) => [...prev, c]);
    }
    setNewClassInput('');
  };

  const handleSubmitDeal = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!formSdt.trim() || !formHoTen.trim()) {
      alert('Vui lòng nhập đầy đủ Số điện thoại và Họ tên học viên!');
      return;
    }
    setSaving(true);
    try {
      const res = await saveSalesDeal({
        id: editingId || undefined,
        ngayThu: formNgThu,
        ngayContact: formNgContact,
        sdt: formSdt,
        hoTen: formHoTen,
        zalo: formZalo,
        nhomCS: formNhomCS,
        chuongTrinh: formChuongTrinh,
        lop: formLop,
        chucVu: formChucVu,
        nvCS: formNvCS,
        zaloCS: formZaloCS,
        nguon: formNguon,
        daThu: formDaThu,
        phaiThu: formPhaiThu,
        tongTien: formTongTien,
        ngayThuAR: formNgThuAR,
        trangThai: formTrangThai,
        note: formNote,
        actor: actorName,
      });
      if (res.ok) {
        setDeals(res.deals || []);
        setDebts(res.debts);
        if (res.lists) {
          setLists(res.lists);
          setDraftLists(res.lists);
        }
        setIsModalOpen(false);
      }
    } catch (err: any) {
      alert(err?.response?.data?.detail || 'Có lỗi xảy ra khi lưu deal');
    } finally {
      setSaving(false);
    }
  };

  const handleDeleteDeal = async (d: SalesDealRecord) => {
    if (!window.confirm(`Bạn có chắc chắn muốn xoá deal của "${d.hoTen}" (${d.sdt}) ngày ${fmtDateVi(d.ngayThu)} không?`)) {
      return;
    }
    try {
      const res = await deleteSalesDeal(d.id, actorName);
      if (res.ok) {
        setDeals(res.deals || []);
        setDebts(res.debts);
      }
    } catch (err: any) {
      alert(err?.response?.data?.detail || 'Không thể xoá deal');
    }
  };

  const handleSaveQuickClasses = async () => {
    if (!classModalDeal) return;
    setSaving(true);
    try {
      const res = await updateSalesDealClasses(classModalDeal.id, quickClasses, actorName);
      if (res.ok) {
        setDeals(res.deals || []);
        setDebts(res.debts);
        if (res.lists) {
          setLists(res.lists);
          setDraftLists(res.lists);
        }
        setClassModalDeal(null);
      }
    } catch (err: any) {
      alert(err?.response?.data?.detail || 'Không thể cập nhật lớp học');
    } finally {
      setSaving(false);
    }
  };

  const handleSaveLists = async () => {
    setSaving(true);
    try {
      const res = await saveDealEntryLists(draftLists, actorName);
      if (res.ok) {
        setLists(res.lists);
        setDraftLists(res.lists);
        alert('Đã lưu Danh mục thành công!');
      }
    } catch (err: any) {
      alert(err?.response?.data?.detail || 'Không thể lưu danh mục');
    } finally {
      setSaving(false);
    }
  };

  // Lọc danh sách Deals
  const filteredDeals = useMemo(() => {
    return deals.filter((d) => {
      if (filterStartDate && d.ngayThu < filterStartDate) return false;
      if (filterEndDate && d.ngayThu > filterEndDate) return false;
      if (filterProgram && d.chuongTrinh !== filterProgram) return false;
      if (filterClass && !(d.lop || []).includes(filterClass)) return false;
      if (filterStatus && d.trangThai !== filterStatus) return false;
      if (filterSale && d.nvCS !== filterSale) return false;
      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase().trim();
        const matchName = (d.hoTen || '').toLowerCase().includes(q);
        const matchPhone = (d.sdt || '').toLowerCase().includes(q);
        const matchNote = (d.note || '').toLowerCase().includes(q);
        const matchClass = (d.lop || []).some((c) => c.toLowerCase().includes(q));
        if (!matchName && !matchPhone && !matchNote && !matchClass) return false;
      }
      return true;
    });
  }, [deals, filterStartDate, filterEndDate, filterProgram, filterClass, filterStatus, filterSale, searchQuery]);

  // Tính toán chỉ số KPI theo bộ lọc hiện tại
  const kpiStats = useMemo(() => {
    let totalDaThu = 0;
    let totalThuNo = 0;
    let totalConNo = 0;
    let totalDoanhThu = 0;
    const uniquePhones = new Set<string>();

    for (const d of filteredDeals) {
      totalDaThu += d.daThu || 0;
      totalThuNo += d.thuNo || 0;
      totalConNo += d.conNo || 0;
      if (d.trangThai !== 'Thu nợ') {
        totalDoanhThu += (d.daThu - (d.thuNo || 0)) + (d.phaiThu || 0);
      }
      if (d.sdt) uniquePhones.add(d.sdt);
    }

    return {
      totalDoanhThu,
      totalDaThu,
      totalThuNo,
      totalConNo,
      dealCount: filteredDeals.length,
      studentCount: uniquePhones.size,
    };
  }, [filteredDeals]);

  const distinctSales = useMemo(() => {
    const s = new Set<string>();
    deals.forEach((d) => {
      if (d.nvCS) s.add(d.nvCS);
    });
    return Array.from(s);
  }, [deals]);

  // Xuất CSV
  const exportDealsCsv = () => {
    const headers = [
      'ID', 'Ngày thu tiền', 'Ngày contact đầu tiên', 'Số điện thoại', 'Họ tên',
      'Zalo (link Pancake)', 'Nhóm CS 1-1', 'Chương trình học', 'Lớp học', 'Chức vụ',
      'NV chăm sóc', 'Zalo chăm sóc', 'Nguồn', 'Số tiền thu được', 'Phải thu khách hàng',
      'Tổng tiền', 'Ngày thu AR', 'Trạng thái', 'Note', 'Người nhập', 'Tạo lúc',
      'Trong đó thu nợ cũ', 'Đã thu nợ', 'Còn nợ'
    ];
    const rows = filteredDeals.map((d) => [
      d.id, fmtDateVi(d.ngayThu), fmtDateVi(d.ngayContact), `'${d.sdt}`, d.hoTen,
      d.zalo, d.nhomCS, d.chuongTrinh, (d.lop || []).join(', '), d.chucVu,
      d.nvCS, d.zaloCS, d.nguon, d.daThu, d.phaiThu,
      d.tongTien, fmtDateVi(d.ngayThuAR), d.trangThai, d.note, d.nguoiNhap, d.taoLuc,
      d.thuNo, d.daThuNo, d.conNo
    ]);
    const csvContent =
      '\uFEFF' +
      [headers, ...rows]
        .map((r) => r.map((cell) => `"${String(cell ?? '').replace(/"/g, '""')}"`).join(','))
        .join('\n');
    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `EzTech_Deals_${format(new Date(), 'yyyyMMdd_HHmm')}.csv`;
    a.click();
  };

  const getStatusBadgeStyle = (st: string) => {
    const lower = (st || '').toLowerCase();
    if (lower.includes('còn nợ')) {
      return 'bg-amber-50 text-amber-700 border-amber-200';
    }
    if (lower.includes('thu nợ')) {
      return 'bg-blue-50 text-eztech border-eztech-border';
    }
    if (lower.includes('hoàn học phí') || lower.includes('bảo lưu')) {
      return 'bg-rose-50 text-rose-700 border-rose-200';
    }
    return 'bg-emerald-50 text-emerald-700 border-emerald-200';
  };

  return (
    <div className="space-y-4">
      {/* 1. Header & Sub-navigation */}
      <div className="bg-white rounded-xl border border-slate-200/80 shadow-card p-4 flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-navy text-gold flex items-center justify-center shadow-sm">
            <Wallet className="w-5 h-5" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-sm font-bold text-navy">Quản Lý Nhập Deal & Công Nợ Học Viên</h2>
              <span className="px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider bg-eztech-light text-eztech rounded-md border border-eztech-border">
                EzTech CRM Native
              </span>
            </div>
            <p className="text-xs text-slate-500 mt-0.5">
              Tự động tra cứu SĐT từ Pancake, đồng bộ Lớp học và đối trừ Công nợ FIFO
            </p>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {/* Sub-tabs */}
          <div className="flex items-center bg-slate-100 p-1 rounded-xl border border-slate-200/70">
            <button
              onClick={() => setSubTab('deals')}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${
                subTab === 'deals'
                  ? 'bg-white text-navy shadow-xs'
                  : 'text-slate-600 hover:text-navy'
              }`}
            >
              <FileSpreadsheet className="w-3.5 h-3.5 text-eztech" />
              <span>Danh sách Deal ({deals.length})</span>
            </button>

            <button
              onClick={() => setSubTab('debts')}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${
                subTab === 'debts'
                  ? 'bg-white text-navy shadow-xs'
                  : 'text-slate-600 hover:text-navy'
              }`}
            >
              <AlertTriangle className="w-3.5 h-3.5 text-amber-500" />
              <span>Sổ Công Nợ</span>
              {debts.count > 0 && (
                <span className="px-1.5 py-0.2 bg-amber-100 text-amber-800 rounded-full text-[10px] font-mono font-bold">
                  {debts.count}
                </span>
              )}
            </button>

            <button
              onClick={() => setSubTab('lists')}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${
                subTab === 'lists'
                  ? 'bg-white text-navy shadow-xs'
                  : 'text-slate-600 hover:text-navy'
              }`}
            >
              <ListChecks className="w-3.5 h-3.5 text-emerald-600" />
              <span>Danh mục</span>
            </button>

            <button
              onClick={() => setSubTab('logs')}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${
                subTab === 'logs'
                  ? 'bg-white text-navy shadow-xs'
                  : 'text-slate-600 hover:text-navy'
              }`}
            >
              <History className="w-3.5 h-3.5 text-slate-500" />
              <span>Nhật ký</span>
            </button>
          </div>

          <button
            onClick={openCreateModal}
            className="flex items-center gap-1.5 px-3.5 py-2 bg-eztech hover:bg-eztech-dark text-white text-xs font-semibold rounded-xl shadow-sm transition-all cursor-pointer"
          >
            <Plus className="w-4 h-4" />
            <span>Nhập Deal Mới</span>
          </button>
        </div>
      </div>

      {/* 2. KPI Summary Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-3">
        <div className="bg-white rounded-xl border border-slate-200/80 shadow-card p-3.5 flex items-center justify-between">
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">Tổng Doanh Thu</p>
            <p className="text-lg font-bold font-mono text-navy mt-1 tabular-nums">
              {fmtMoney(kpiStats.totalDoanhThu)} <span className="text-xs font-normal text-slate-400">đ</span>
            </p>
            <p className="text-[11px] text-slate-400 mt-0.5">Thực thu + Phải thu</p>
          </div>
          <div className="w-9 h-9 rounded-lg bg-eztech-light text-eztech flex items-center justify-center">
            <TrendingUp className="w-4 h-4" />
          </div>
        </div>

        <div className="bg-white rounded-xl border border-slate-200/80 shadow-card p-3.5 flex items-center justify-between">
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">Số Tiền Thực Thu</p>
            <p className="text-lg font-bold font-mono text-emerald-600 mt-1 tabular-nums">
              {fmtMoney(kpiStats.totalDaThu)} <span className="text-xs font-normal text-slate-400">đ</span>
            </p>
            <p className="text-[11px] text-slate-400 mt-0.5">Đã vào tài khoản</p>
          </div>
          <div className="w-9 h-9 rounded-lg bg-emerald-50 text-emerald-600 flex items-center justify-center">
            <DollarSign className="w-4 h-4" />
          </div>
        </div>

        <div className="bg-white rounded-xl border border-slate-200/80 shadow-card p-3.5 flex items-center justify-between">
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">Trong Đó Thu Nợ Cũ</p>
            <p className="text-lg font-bold font-mono text-eztech mt-1 tabular-nums">
              {fmtMoney(kpiStats.totalThuNo)} <span className="text-xs font-normal text-slate-400">đ</span>
            </p>
            <p className="text-[11px] text-slate-400 mt-0.5">Cấn trừ tự động FIFO</p>
          </div>
          <div className="w-9 h-9 rounded-lg bg-blue-50 text-eztech flex items-center justify-center">
            <CreditCard className="w-4 h-4" />
          </div>
        </div>

        <div className="bg-white rounded-xl border border-amber-200/90 shadow-card p-3.5 flex items-center justify-between">
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-wider text-amber-700">Tổng Còn Nợ (AR)</p>
            <p className="text-lg font-bold font-mono text-amber-600 mt-1 tabular-nums">
              {fmtMoney(debts.totalConNo)} <span className="text-xs font-normal text-amber-500">đ</span>
            </p>
            <p className="text-[11px] text-amber-600/80 mt-0.5">{debts.count} khoản chưa tất toán</p>
          </div>
          <div className="w-9 h-9 rounded-lg bg-amber-50 text-amber-600 flex items-center justify-center">
            <Clock className="w-4 h-4" />
          </div>
        </div>

        <div className="bg-white rounded-xl border border-slate-200/80 shadow-card p-3.5 flex items-center justify-between">
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">Số Lượng Giao Dịch</p>
            <p className="text-lg font-bold font-mono text-navy mt-1 tabular-nums">
              {kpiStats.dealCount} <span className="text-xs font-normal text-slate-400">deal</span>
            </p>
            <p className="text-[11px] text-slate-400 mt-0.5">{kpiStats.studentCount} học viên duy nhất</p>
          </div>
          <div className="w-9 h-9 rounded-lg bg-slate-100 text-navy flex items-center justify-center">
            <UserCheck className="w-4 h-4" />
          </div>
        </div>
      </div>

      {/* 3. Nội dung từng Sub-tab */}
      {subTab === 'deals' && (
        <div className="space-y-3">
          {/* Thanh bộ lọc */}
          <div className="bg-white rounded-xl border border-slate-200/80 shadow-card p-3 flex flex-wrap items-center gap-2.5">
            <div className="relative flex-1 min-w-[220px]">
              <Search className="w-3.5 h-3.5 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
              <input
                type="text"
                placeholder="Tìm SĐT, Họ tên, Lớp học, Ghi chú..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="w-full pl-8 pr-3 py-1.5 text-xs border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-eztech/20 focus:border-eztech"
              />
            </div>

            <div className="flex items-center gap-1.5 bg-slate-50 border border-slate-200 rounded-lg px-2 py-1">
              <span className="text-[11px] text-slate-500 font-medium">Ngày thu:</span>
              <input
                type="date"
                value={filterStartDate}
                onChange={(e) => setFilterStartDate(e.target.value)}
                className="bg-transparent text-xs font-mono text-navy focus:outline-none"
              />
              <span className="text-slate-300 text-xs">→</span>
              <input
                type="date"
                value={filterEndDate}
                onChange={(e) => setFilterEndDate(e.target.value)}
                className="bg-transparent text-xs font-mono text-navy focus:outline-none"
              />
            </div>

            <select
              value={filterProgram}
              onChange={(e) => setFilterProgram(e.target.value)}
              className="px-2.5 py-1.5 text-xs border border-slate-200 rounded-lg bg-white text-navy"
            >
              <option value="">Tất cả Chương trình</option>
              {lists.chuongTrinh.map((c) => (
                <option key={c} value={c}>{c}</option>
              ))}
            </select>

            <select
              value={filterClass}
              onChange={(e) => setFilterClass(e.target.value)}
              className="px-2.5 py-1.5 text-xs border border-slate-200 rounded-lg bg-white text-navy"
            >
              <option value="">Tất cả Lớp học</option>
              {lists.lop.map((l) => (
                <option key={l} value={l}>{l}</option>
              ))}
            </select>

            <select
              value={filterStatus}
              onChange={(e) => setFilterStatus(e.target.value)}
              className="px-2.5 py-1.5 text-xs border border-slate-200 rounded-lg bg-white text-navy"
            >
              <option value="">Tất cả Trạng thái</option>
              {statuses.map((st) => (
                <option key={st} value={st}>{st}</option>
              ))}
            </select>

            <select
              value={filterSale}
              onChange={(e) => setFilterSale(e.target.value)}
              className="px-2.5 py-1.5 text-xs border border-slate-200 rounded-lg bg-white text-navy"
            >
              <option value="">Tất cả NV CS</option>
              {distinctSales.map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>

            <button
              onClick={exportDealsCsv}
              className="px-2.5 py-1.5 text-xs font-medium text-slate-600 hover:text-navy bg-slate-50 hover:bg-slate-100 border border-slate-200 rounded-lg flex items-center gap-1 transition-colors"
              title="Xuất file Excel / CSV"
            >
              <FileSpreadsheet className="w-3.5 h-3.5 text-emerald-600" />
              <span>Xuất CSV</span>
            </button>

            <button
              onClick={() => loadAll(true)}
              className="p-1.5 text-slate-500 hover:text-eztech bg-slate-50 hover:bg-eztech-light border border-slate-200 rounded-lg transition-colors"
              title="Làm mới dữ liệu"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
            </button>
          </div>

          {/* Bảng danh sách Deals */}
          <div className="bg-white rounded-xl border border-slate-200/80 shadow-card overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-left border-collapse">
                <thead>
                  <tr className="bg-slate-50/90 border-b border-slate-200 text-[11px] font-bold uppercase tracking-wider text-slate-500">
                    <th className="py-3 px-3 whitespace-nowrap">Ngày thu</th>
                    <th className="py-3 px-3 whitespace-nowrap">Học viên & SĐT</th>
                    <th className="py-3 px-3 whitespace-nowrap">Chương trình & Lớp</th>
                    <th className="py-3 px-3 whitespace-nowrap text-right">Thực thu</th>
                    <th className="py-3 px-3 whitespace-nowrap text-right">Phải thu</th>
                    <th className="py-3 px-3 whitespace-nowrap text-right">Tổng tiền</th>
                    <th className="py-3 px-3 whitespace-nowrap text-right">Còn nợ</th>
                    <th className="py-3 px-3 whitespace-nowrap">Trạng thái</th>
                    <th className="py-3 px-3 whitespace-nowrap">NV CS / Nguồn</th>
                    <th className="py-3 px-3 whitespace-nowrap">Ghi chú</th>
                    <th className="py-3 px-3 whitespace-nowrap text-right">Thao tác</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 text-xs">
                  {loading ? (
                    <tr>
                      <td colSpan={11} className="py-12 text-center text-slate-400">
                        Đang tải danh sách deal...
                      </td>
                    </tr>
                  ) : filteredDeals.length === 0 ? (
                    <tr>
                      <td colSpan={11} className="py-12 text-center text-slate-400">
                        Chưa có dữ liệu deal nào khớp bộ lọc. Hãy bấm <strong>"+ Nhập Deal Mới"</strong> để thêm deal đầu tiên!
                      </td>
                    </tr>
                  ) : (
                    filteredDeals.map((d) => (
                      <tr key={d.id} className="hover:bg-slate-50/80 transition-colors">
                        <td className="py-2.5 px-3 whitespace-nowrap align-top">
                          <div className="font-mono font-semibold text-navy">{fmtDateVi(d.ngayThu)}</div>
                          {d.ngayContact && (
                            <div className="text-[10px] text-slate-400 font-mono">
                              Contact: {fmtDateVi(d.ngayContact)}
                            </div>
                          )}
                        </td>

                        <td className="py-2.5 px-3 align-top">
                          <div className="font-semibold text-navy flex items-center gap-1.5">
                            <span>{d.hoTen}</span>
                            {d.zalo && (
                              <a
                                href={d.zalo}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="text-eztech hover:underline inline-flex items-center"
                                title="Mở hội thoại Zalo / Pancake"
                              >
                                <ExternalLink className="w-3 h-3" />
                              </a>
                            )}
                          </div>
                          <div className="font-mono text-[11px] text-slate-500">{d.sdt}</div>
                          {(d.chucVu || d.nhomCS) && (
                            <div className="text-[10px] text-slate-400 mt-0.5">
                              {[d.chucVu, d.nhomCS ? `Nhóm: ${d.nhomCS}` : ''].filter(Boolean).join(' • ')}
                            </div>
                          )}
                        </td>

                        <td className="py-2.5 px-3 align-top">
                          <div className="font-semibold text-navy">{d.chuongTrinh || '—'}</div>
                          <div className="flex flex-wrap items-center gap-1 mt-1">
                            {(d.lop || []).map((cl) => (
                              <span
                                key={cl}
                                className="px-1.5 py-0.5 text-[10px] font-mono font-semibold bg-eztech-light text-eztech rounded border border-eztech-border"
                              >
                                {cl}
                              </span>
                            ))}
                            <button
                              onClick={() => {
                                setClassModalDeal(d);
                                setQuickClasses(d.lop || []);
                                setQuickNewClass('');
                              }}
                              className="px-1.5 py-0.5 text-[10px] text-slate-500 hover:text-navy bg-slate-100 hover:bg-slate-200 rounded inline-flex items-center gap-0.5"
                              title="Sửa & đồng bộ lớp học cho SĐT này"
                            >
                              <Tag className="w-2.5 h-2.5" />
                              <span>{(d.lop || []).length ? 'Sửa lớp' : '+ Gắn lớp'}</span>
                            </button>
                          </div>
                        </td>

                        <td className="py-2.5 px-3 whitespace-nowrap text-right align-top font-mono">
                          <div className="font-bold text-emerald-600">{fmtMoney(d.daThu)}</div>
                          {d.thuNo > 0 && (
                            <div className="text-[10px] text-eztech font-medium">
                              (Thu nợ cũ: {fmtMoney(d.thuNo)})
                            </div>
                          )}
                        </td>

                        <td className="py-2.5 px-3 whitespace-nowrap text-right align-top font-mono">
                          <div className={d.phaiThu > 0 ? 'font-semibold text-slate-700' : 'text-slate-300'}>
                            {fmtMoney(d.phaiThu)}
                          </div>
                          {d.daThuNo > 0 && (
                            <div className="text-[10px] text-emerald-600">
                              Đã thu nợ: {fmtMoney(d.daThuNo)}
                            </div>
                          )}
                        </td>

                        <td className="py-2.5 px-3 whitespace-nowrap text-right align-top font-mono font-semibold text-navy">
                          {fmtMoney(d.tongTien)}
                        </td>

                        <td className="py-2.5 px-3 whitespace-nowrap text-right align-top font-mono">
                          {d.conNo > 0 ? (
                            <span className="font-bold text-amber-600 bg-amber-50 px-1.5 py-0.5 rounded border border-amber-200">
                              {fmtMoney(d.conNo)}
                            </span>
                          ) : (
                            <span className="text-slate-300">0</span>
                          )}
                          {d.ngayThuAR && (
                            <div className="text-[10px] text-slate-400 mt-0.5">
                              AR: {fmtDateVi(d.ngayThuAR)}
                            </div>
                          )}
                        </td>

                        <td className="py-2.5 px-3 whitespace-nowrap align-top">
                          <span
                            className={`inline-block px-2 py-0.5 text-[11px] font-semibold rounded-full border ${getStatusBadgeStyle(
                              d.trangThai
                            )}`}
                          >
                            {d.trangThai || 'Hoàn thành'}
                          </span>
                        </td>

                        <td className="py-2.5 px-3 align-top">
                          <div className="font-medium text-navy">{d.nvCS || '—'}</div>
                          <div className="text-[10px] text-slate-400">
                            {[d.zaloCS, d.nguon].filter(Boolean).join(' • ')}
                          </div>
                        </td>

                        <td className="py-2.5 px-3 align-top max-w-[200px]">
                          <div className="text-slate-600 line-clamp-2" title={d.note}>
                            {d.note || '—'}
                          </div>
                          <div className="text-[10px] text-slate-400 mt-0.5">
                            Nhập: {d.nguoiNhap} ({d.taoLuc})
                          </div>
                        </td>

                        <td className="py-2.5 px-3 whitespace-nowrap text-right align-top">
                          <div className="flex items-center justify-end gap-1">
                            {d.conNo > 0 && (
                              <button
                                onClick={() =>
                                  openCollectDebtModal({
                                    sdt: d.sdt,
                                    hoTen: d.hoTen,
                                    conNo: d.conNo,
                                    ngayThuGoc: d.ngayThu,
                                    chuongTrinh: d.chuongTrinh,
                                    lop: d.lop,
                                    nvCS: d.nvCS,
                                  })
                                }
                                className="px-2 py-1 text-[11px] font-semibold bg-amber-500 hover:bg-amber-600 text-white rounded-md shadow-2xs transition-colors"
                                title="Nhập giao dịch thu nợ cho khoản này"
                              >
                                Thu nợ
                              </button>
                            )}
                            <button
                              onClick={() => openEditModal(d)}
                              className="p-1.5 text-slate-500 hover:text-eztech hover:bg-eztech-light rounded-md transition-colors"
                              title="Chỉnh sửa deal"
                            >
                              <Edit3 className="w-3.5 h-3.5" />
                            </button>
                            <button
                              onClick={() => handleDeleteDeal(d)}
                              className="p-1.5 text-slate-400 hover:text-rose-600 hover:bg-rose-50 rounded-md transition-colors"
                              title="Xoá deal"
                            >
                              <Trash2 className="w-3.5 h-3.5" />
                            </button>
                          </div>
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {/* TAB 2: SỔ CÔNG NỢ (CongNo) */}
      {subTab === 'debts' && (
        <div className="bg-white rounded-xl border border-slate-200/80 shadow-card overflow-hidden">
          <div className="px-4 py-3 border-b border-slate-100 flex items-center justify-between">
            <div>
              <h3 className="text-xs font-bold text-navy uppercase tracking-wider">
                Danh Sách Công Nợ Chưa Tất Toán ({debts.count} khoản)
              </h3>
              <p className="text-[11px] text-slate-400 mt-0.5">
                Khi nhập một deal mới có trạng thái <strong>"Thu nợ"</strong> cùng SĐT, hệ thống sẽ tự động trừ lùi công nợ từ khoản nợ cũ nhất (FIFO).
              </p>
            </div>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse">
              <thead>
                <tr className="bg-amber-50/60 border-b border-amber-200/70 text-[11px] font-bold uppercase tracking-wider text-amber-900">
                  <th className="py-3 px-3">Số điện thoại</th>
                  <th className="py-3 px-3">Họ tên</th>
                  <th className="py-3 px-3">Ngày thu deal gốc</th>
                  <th className="py-3 px-3">Tháng PS</th>
                  <th className="py-3 px-3 text-right">Phải thu ban đầu</th>
                  <th className="py-3 px-3 text-right">Đã thu nợ</th>
                  <th className="py-3 px-3 text-right">Còn nợ</th>
                  <th className="py-3 px-3">Lần thu gần nhất</th>
                  <th className="py-3 px-3">NV chăm sóc</th>
                  <th className="py-3 px-3">Lớp học</th>
                  <th className="py-3 px-3 text-right">Hành động</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 text-xs">
                {debts.items.length === 0 ? (
                  <tr>
                    <td colSpan={11} className="py-12 text-center text-emerald-600 font-medium">
                      <CheckCircle2 className="w-6 h-6 mx-auto mb-1.5 text-emerald-500" />
                      Tuyệt vời! Hiện tại không có khoản công nợ nào tồn đọng.
                    </td>
                  </tr>
                ) : (
                  <>
                    {debts.items.map((item) => (
                      <tr key={item.id} className="hover:bg-amber-50/30 transition-colors">
                        <td className="py-2.5 px-3 font-mono font-semibold text-navy">{item.sdt}</td>
                        <td className="py-2.5 px-3 font-semibold text-navy">{item.hoTen}</td>
                        <td className="py-2.5 px-3 font-mono">{fmtDateVi(item.ngayThuGoc)}</td>
                        <td className="py-2.5 px-3 font-mono text-slate-500">{item.thangPhatSinh}</td>
                        <td className="py-2.5 px-3 font-mono text-right">{fmtMoney(item.phaiThuBanDau)}</td>
                        <td className="py-2.5 px-3 font-mono text-right text-emerald-600">
                          {fmtMoney(item.daThuNo)}
                        </td>
                        <td className="py-2.5 px-3 font-mono text-right font-bold text-amber-600">
                          {fmtMoney(item.conNo)}
                        </td>
                        <td className="py-2.5 px-3 font-mono text-slate-500">
                          {fmtDateVi(item.lanThuGanNhat)}
                        </td>
                        <td className="py-2.5 px-3">{item.nvCS || '—'}</td>
                        <td className="py-2.5 px-3">{(item.lop || []).join(', ') || '—'}</td>
                        <td className="py-2.5 px-3 text-right">
                          <button
                            onClick={() => openCollectDebtModal(item)}
                            className="px-2.5 py-1 bg-amber-500 hover:bg-amber-600 text-white font-semibold text-[11px] rounded-lg shadow-2xs transition-colors"
                          >
                            + Thu nợ ngay
                          </button>
                        </td>
                      </tr>
                    ))}
                    <tr className="bg-slate-100/90 font-bold text-navy border-t-2 border-slate-300">
                      <td colSpan={4} className="py-3 px-3 uppercase text-xs">
                        TỔNG CỘNG CÔNG NỢ
                      </td>
                      <td className="py-3 px-3 text-right font-mono">{fmtMoney(debts.totalPhaiThu)}</td>
                      <td className="py-3 px-3 text-right font-mono text-emerald-700">
                        {fmtMoney(debts.totalDaThuNo)}
                      </td>
                      <td className="py-3 px-3 text-right font-mono text-amber-700 text-sm">
                        {fmtMoney(debts.totalConNo)} đ
                      </td>
                      <td colSpan={4} />
                    </tr>
                  </>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* TAB 3: QUẢN LÝ DANH MỤC (DanhMuc) */}
      {subTab === 'lists' && (
        <div className="space-y-4">
          <div className="bg-white rounded-xl border border-slate-200/80 shadow-card p-4 flex items-center justify-between">
            <div>
              <h3 className="text-xs font-bold text-navy uppercase tracking-wider">
                Cấu Hình Danh Mục Hệ Thống (Sheet DanhMuc)
              </h3>
              <p className="text-[11px] text-slate-400 mt-0.5">
                Thêm hoặc xoá các lựa chọn trong dropdown khi nhập Deal (Chương trình học, Lớp học, Zalo chăm sóc, Nguồn).
              </p>
            </div>
            <button
              onClick={handleSaveLists}
              disabled={saving}
              className="flex items-center gap-1.5 px-4 py-2 bg-eztech hover:bg-eztech-dark text-white text-xs font-semibold rounded-xl shadow-sm transition-colors cursor-pointer"
            >
              <Save className="w-4 h-4" />
              <span>{saving ? 'Đang lưu...' : 'Lưu Toàn Bộ Danh Mục'}</span>
            </button>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
            {(
              [
                { key: 'chuongTrinh', title: 'Chương trình học' },
                { key: 'lop', title: 'Lớp học' },
                { key: 'zaloCS', title: 'Zalo chăm sóc' },
                { key: 'nguon', title: 'Nguồn kênh' },
              ] as const
            ).map(({ key, title }) => (
              <div
                key={key}
                className="bg-white rounded-xl border border-slate-200/80 shadow-card p-4 flex flex-col"
              >
                <h4 className="text-xs font-bold text-navy mb-2 flex items-center justify-between">
                  <span>{title}</span>
                  <span className="px-1.5 py-0.5 text-[10px] bg-slate-100 text-slate-600 rounded font-mono">
                    {draftLists[key]?.length || 0}
                  </span>
                </h4>

                <div className="flex items-center gap-1.5 mb-3">
                  <input
                    type="text"
                    placeholder={`Thêm ${title.toLowerCase()}...`}
                    value={newItemText[key] || ''}
                    onChange={(e) => setNewItemText((prev) => ({ ...prev, [key]: e.target.value }))}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') {
                        e.preventDefault();
                        const val = (newItemText[key] || '').trim();
                        if (val && !draftLists[key].includes(val)) {
                          setDraftLists((prev) => ({ ...prev, [key]: [...prev[key], val] }));
                          setNewItemText((prev) => ({ ...prev, [key]: '' }));
                        }
                      }
                    }}
                    className="flex-1 px-2.5 py-1.5 text-xs border border-slate-200 rounded-lg focus:outline-none focus:border-eztech"
                  />
                  <button
                    type="button"
                    onClick={() => {
                      const val = (newItemText[key] || '').trim();
                      if (val && !draftLists[key].includes(val)) {
                        setDraftLists((prev) => ({ ...prev, [key]: [...prev[key], val] }));
                        setNewItemText((prev) => ({ ...prev, [key]: '' }));
                      }
                    }}
                    className="px-2.5 py-1.5 bg-slate-100 hover:bg-eztech hover:text-white text-navy text-xs font-semibold rounded-lg transition-colors"
                  >
                    +
                  </button>
                </div>

                <div className="flex-1 max-h-[340px] overflow-y-auto space-y-1 pr-1">
                  {(draftLists[key] || []).map((item, idx) => (
                    <div
                      key={`${item}-${idx}`}
                      className="flex items-center justify-between px-2.5 py-1.5 bg-slate-50 hover:bg-slate-100 rounded-lg text-xs text-navy group"
                    >
                      <span className="truncate">{item}</span>
                      <button
                        type="button"
                        onClick={() =>
                          setDraftLists((prev) => ({
                            ...prev,
                            [key]: prev[key].filter((x) => x !== item),
                          }))
                        }
                        className="text-slate-400 hover:text-rose-600 opacity-60 group-hover:opacity-100"
                      >
                        <X className="w-3.5 h-3.5" />
                      </button>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* TAB 4: NHẬT KÝ HỆ THỐNG (Log) */}
      {subTab === 'logs' && (
        <div className="bg-white rounded-xl border border-slate-200/80 shadow-card overflow-hidden">
          <div className="px-4 py-3 border-b border-slate-100 flex items-center justify-between">
            <h3 className="text-xs font-bold text-navy uppercase tracking-wider">
              Nhật Ký Thao Tác Hệ Thống (150 hoạt động gần nhất)
            </h3>
            <button
              onClick={loadLogs}
              className="px-2.5 py-1 text-xs font-medium bg-slate-50 hover:bg-slate-100 border border-slate-200 rounded-lg flex items-center gap-1"
            >
              <RefreshCw className="w-3 h-3" />
              <span>Tải lại</span>
            </button>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse">
              <thead>
                <tr className="bg-slate-50 border-b border-slate-200 text-[11px] font-bold uppercase text-slate-500">
                  <th className="py-2.5 px-3">Thời gian</th>
                  <th className="py-2.5 px-3">Người thực hiện</th>
                  <th className="py-2.5 px-3">Hành động</th>
                  <th className="py-2.5 px-3">Mã Deal</th>
                  <th className="py-2.5 px-3">Chi tiết thay đổi</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 text-xs">
                {logs.map((lg) => (
                  <tr key={lg.id} className="hover:bg-slate-50">
                    <td className="py-2 px-3 font-mono whitespace-nowrap text-slate-500">
                      {lg.createdAt}
                    </td>
                    <td className="py-2 px-3 font-semibold text-navy whitespace-nowrap">
                      {lg.userEmail}
                    </td>
                    <td className="py-2 px-3 whitespace-nowrap">
                      <span className="px-2 py-0.5 bg-eztech-light text-eztech font-semibold rounded text-[11px]">
                        {lg.action}
                      </span>
                    </td>
                    <td className="py-2 px-3 font-mono text-[11px] text-slate-400 whitespace-nowrap">
                      {lg.dealId ? lg.dealId.slice(0, 8) : '—'}
                    </td>
                    <td className="py-2 px-3 font-mono text-[11px] text-slate-600 max-w-[520px] truncate" title={lg.detail}>
                      {lg.detail}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* MODAL NHẬP / SỬA DEAL */}
      {isModalOpen && (
        <div className="fixed inset-0 z-50 bg-navy/50 backdrop-blur-xs flex items-center justify-center p-4 overflow-y-auto">
          <div className="bg-white rounded-2xl border border-slate-200 shadow-2xl max-w-3xl w-full overflow-hidden my-8">
            <div className="px-5 py-3.5 bg-navy text-white flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Sparkles className="w-4 h-4 text-gold" />
                <h3 className="text-sm font-bold">
                  {editingId ? 'Chỉnh Sửa Thông Tin Deal' : 'Nhập Deal Mới / Thu Nợ Học Viên'}
                </h3>
              </div>
              <button
                onClick={() => setIsModalOpen(false)}
                className="p-1 text-slate-300 hover:text-white rounded-lg"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <form onSubmit={handleSubmitDeal} className="p-5 space-y-4 max-h-[82vh] overflow-y-auto">
              {/* Cảnh báo công nợ hoặc Gợi ý tự động từ Pancake khi nhập SĐT */}
              {phoneLookup?.found && (
                <div className="space-y-2">
                  {phoneLookup.conNo && phoneLookup.conNo > 0 ? (
                    <div className="p-3 bg-amber-50 border border-amber-300 rounded-xl flex flex-wrap items-center justify-between gap-2">
                      <div className="flex items-center gap-2 text-xs text-amber-900">
                        <AlertTriangle className="w-4 h-4 text-amber-600 shrink-0" />
                        <span>
                          Học viên <strong>{phoneLookup.hoTen}</strong> đang còn nợ{' '}
                          <strong className="font-mono text-amber-700">{fmtMoney(phoneLookup.conNo)} đ</strong>
                          {phoneLookup.noTuNgay ? ` (từ ngày ${fmtDateVi(phoneLookup.noTuNgay)})` : ''}.
                        </span>
                      </div>
                      <button
                        type="button"
                        onClick={() => {
                          setFormTrangThai('Thu nợ');
                          setFormDaThu(phoneLookup.conNo || 0);
                          setFormPhaiThu(0);
                          setFormTongTien(0);
                          setFormNgThuAR(format(new Date(), 'yyyy-MM-dd'));
                          setFormNote(`Thu nợ cũ phát sinh ngày ${fmtDateVi(phoneLookup.noTuNgay)}`);
                        }}
                        className="px-2.5 py-1 bg-amber-600 hover:bg-amber-700 text-white text-[11px] font-semibold rounded-lg shadow-2xs transition-colors"
                      >
                        ⚡ Điền nhanh Thu nợ ({fmtMoney(phoneLookup.conNo)} đ)
                      </button>
                    </div>
                  ) : null}

                  {phoneLookup.pancake?.foundInPancake && (
                    <div className="px-3 py-2 bg-eztech-light/70 border border-eztech-border rounded-xl flex items-center justify-between text-[11px] text-eztech">
                      <span>
                        ✨ Đã tự động đồng bộ thông tin khách từ <strong>Pancake CRM</strong> (
                        {[
                          phoneLookup.pancake.hoTen,
                          phoneLookup.pancake.nguon,
                          phoneLookup.pancake.ngayContact ? `Contact: ${fmtDateVi(phoneLookup.pancake.ngayContact)}` : '',
                        ]
                          .filter(Boolean)
                          .join(' • ')}
                        )
                      </span>
                    </div>
                  )}
                </div>
              )}

              {/* Nhóm 1: Thông tin học viên & Ngày tháng */}
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                <div>
                  <label className="block text-[11px] font-semibold text-navy mb-1">
                    Số điện thoại <span className="text-rose-500">*</span>
                    {lookingUpPhone && <span className="ml-1 text-[10px] text-eztech">(Đang tra cứu...)</span>}
                  </label>
                  <input
                    type="text"
                    required
                    placeholder="VD: 0987654321"
                    value={formSdt}
                    onChange={(e) => setFormSdt(e.target.value)}
                    className="w-full px-3 py-2 text-xs font-mono font-semibold border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-eztech/20 focus:border-eztech"
                  />
                </div>

                <div className="sm:col-span-2">
                  <label className="block text-[11px] font-semibold text-navy mb-1">
                    Họ và tên học viên <span className="text-rose-500">*</span>
                  </label>
                  <input
                    type="text"
                    required
                    placeholder="Nhập họ và tên..."
                    value={formHoTen}
                    onChange={(e) => setFormHoTen(e.target.value)}
                    className="w-full px-3 py-2 text-xs font-semibold border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-eztech/20 focus:border-eztech"
                  />
                </div>

                <div>
                  <label className="block text-[11px] font-semibold text-navy mb-1">
                    Ngày thu tiền <span className="text-rose-500">*</span>
                  </label>
                  <input
                    type="date"
                    required
                    value={formNgThu}
                    onChange={(e) => setFormNgThu(e.target.value)}
                    className="w-full px-3 py-2 text-xs font-mono border border-slate-200 rounded-lg focus:outline-none focus:border-eztech"
                  />
                </div>

                <div>
                  <label className="block text-[11px] font-semibold text-navy mb-1">
                    Ngày contact đầu tiên
                  </label>
                  <input
                    type="date"
                    value={formNgContact}
                    onChange={(e) => setFormNgContact(e.target.value)}
                    className="w-full px-3 py-2 text-xs font-mono border border-slate-200 rounded-lg focus:outline-none focus:border-eztech"
                  />
                </div>

                <div>
                  <label className="block text-[11px] font-semibold text-navy mb-1">
                    Chức vụ / Công việc
                  </label>
                  <input
                    type="text"
                    placeholder="VD: Kế toán trưởng, FP&A..."
                    value={formChucVu}
                    onChange={(e) => setFormChucVu(e.target.value)}
                    className="w-full px-3 py-2 text-xs border border-slate-200 rounded-lg focus:outline-none focus:border-eztech"
                  />
                </div>
              </div>

              {/* Nhóm 2: Số tiền & Trạng thái */}
              <div className="p-3.5 bg-slate-50 rounded-xl border border-slate-200/80 grid grid-cols-1 sm:grid-cols-4 gap-3">
                <div>
                  <label className="block text-[11px] font-semibold text-emerald-700 mb-1">
                    Số tiền thu được (VNĐ)
                  </label>
                  <input
                    type="text"
                    value={formDaThu ? fmtMoney(formDaThu) : ''}
                    placeholder="0"
                    onChange={(e) => handleDaThuChange(parseMoneyInput(e.target.value))}
                    className="w-full px-3 py-2 text-xs font-mono font-bold text-emerald-700 bg-white border border-emerald-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-emerald-500/20"
                  />
                </div>

                <div>
                  <label className="block text-[11px] font-semibold text-amber-700 mb-1">
                    Phải thu KH (Còn nợ)
                  </label>
                  <input
                    type="text"
                    value={formPhaiThu ? fmtMoney(formPhaiThu) : ''}
                    placeholder="0"
                    onChange={(e) => handlePhaiThuChange(parseMoneyInput(e.target.value))}
                    className="w-full px-3 py-2 text-xs font-mono font-bold text-amber-700 bg-white border border-amber-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-amber-500/20"
                  />
                </div>

                <div>
                  <label className="block text-[11px] font-semibold text-navy mb-1">
                    Tổng tiền khoá học
                  </label>
                  <input
                    type="text"
                    value={formTongTien ? fmtMoney(formTongTien) : ''}
                    placeholder="0"
                    onChange={(e) => setFormTongTien(parseMoneyInput(e.target.value))}
                    className="w-full px-3 py-2 text-xs font-mono font-bold text-navy bg-white border border-slate-200 rounded-lg focus:outline-none focus:border-eztech"
                  />
                </div>

                <div>
                  <label className="block text-[11px] font-semibold text-navy mb-1">
                    Trạng thái deal
                  </label>
                  <select
                    value={formTrangThai}
                    onChange={(e) => setFormTrangThai(e.target.value)}
                    className="w-full px-2.5 py-2 text-xs font-semibold bg-white border border-slate-200 rounded-lg text-navy focus:outline-none focus:border-eztech"
                  >
                    {statuses.map((st) => (
                      <option key={st} value={st}>{st}</option>
                    ))}
                  </select>
                </div>
              </div>

              {/* Nhóm 3: Chương trình, Nguồn, Nhân viên chăm sóc */}
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                <div>
                  <label className="block text-[11px] font-semibold text-navy mb-1">
                    Chương trình học
                  </label>
                  <select
                    value={formChuongTrinh}
                    onChange={(e) => setFormChuongTrinh(e.target.value)}
                    className="w-full px-2.5 py-2 text-xs border border-slate-200 rounded-lg bg-white text-navy"
                  >
                    <option value="">-- Chọn chương trình --</option>
                    {lists.chuongTrinh.map((c) => (
                      <option key={c} value={c}>{c}</option>
                    ))}
                  </select>
                </div>

                <div>
                  <label className="block text-[11px] font-semibold text-navy mb-1">
                    Nguồn khách hàng
                  </label>
                  <select
                    value={formNguon}
                    onChange={(e) => setFormNguon(e.target.value)}
                    className="w-full px-2.5 py-2 text-xs border border-slate-200 rounded-lg bg-white text-navy"
                  >
                    <option value="">-- Chọn nguồn --</option>
                    {lists.nguon.map((n) => (
                      <option key={n} value={n}>{n}</option>
                    ))}
                  </select>
                </div>

                <div>
                  <label className="block text-[11px] font-semibold text-navy mb-1">
                    Zalo chăm sóc
                  </label>
                  <select
                    value={formZaloCS}
                    onChange={(e) => setFormZaloCS(e.target.value)}
                    className="w-full px-2.5 py-2 text-xs border border-slate-200 rounded-lg bg-white text-navy"
                  >
                    <option value="">-- Chọn Zalo CS --</option>
                    {lists.zaloCS.map((z) => (
                      <option key={z} value={z}>{z}</option>
                    ))}
                  </select>
                </div>

                <div>
                  <label className="block text-[11px] font-semibold text-navy mb-1">
                    NV chăm sóc (Sale)
                  </label>
                  <input
                    type="text"
                    value={formNvCS}
                    onChange={(e) => setFormNvCS(e.target.value)}
                    placeholder="Tên nhân viên sale..."
                    className="w-full px-3 py-2 text-xs border border-slate-200 rounded-lg"
                  />
                </div>

                <div>
                  <label className="block text-[11px] font-semibold text-navy mb-1">
                    Nhóm CS 1-1
                  </label>
                  <input
                    type="text"
                    value={formNhomCS}
                    onChange={(e) => setFormNhomCS(e.target.value)}
                    placeholder="Tên nhóm Zalo hỗ trợ 1-1..."
                    className="w-full px-3 py-2 text-xs border border-slate-200 rounded-lg"
                  />
                </div>

                <div>
                  <label className="block text-[11px] font-semibold text-navy mb-1">
                    Zalo (Link Pancake)
                  </label>
                  <input
                    type="text"
                    value={formZalo}
                    onChange={(e) => setFormZalo(e.target.value)}
                    placeholder="https://pancake.vn/..."
                    className="w-full px-3 py-2 text-xs border border-slate-200 rounded-lg"
                  />
                </div>
              </div>

              {/* Nhóm 4: Chọn Lớp học (Đồng bộ mọi deal cùng SĐT) */}
              <div>
                <label className="block text-[11px] font-semibold text-navy mb-1.5">
                  Lớp học (Tự động đồng bộ cho mọi deal cùng SĐT)
                </label>
                <div className="flex flex-wrap items-center gap-1.5 p-2.5 bg-slate-50 border border-slate-200 rounded-xl">
                  {lists.lop.map((cls) => {
                    const active = formLop.includes(cls);
                    return (
                      <button
                        type="button"
                        key={cls}
                        onClick={() => toggleClassInForm(cls)}
                        className={`px-2.5 py-1 rounded-lg text-xs font-mono font-semibold transition-all cursor-pointer ${
                          active
                            ? 'bg-eztech text-white shadow-2xs'
                            : 'bg-white text-slate-600 border border-slate-200 hover:border-eztech'
                        }`}
                      >
                        {cls}
                      </button>
                    );
                  })}
                  <div className="flex items-center gap-1 ml-auto">
                    <input
                      type="text"
                      placeholder="Thêm mã lớp mới..."
                      value={newClassInput}
                      onChange={(e) => setNewClassInput(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') {
                          e.preventDefault();
                          addCustomClassToForm();
                        }
                      }}
                      className="px-2 py-1 text-xs border border-slate-200 rounded-lg bg-white w-36"
                    />
                    <button
                      type="button"
                      onClick={addCustomClassToForm}
                      className="px-2 py-1 text-xs font-semibold bg-navy text-white rounded-lg"
                    >
                      + Thêm
                    </button>
                  </div>
                </div>
              </div>

              {/* Nhóm 5: Ghi chú */}
              <div>
                <label className="block text-[11px] font-semibold text-navy mb-1">
                  Ghi chú (Note)
                </label>
                <textarea
                  rows={2}
                  value={formNote}
                  onChange={(e) => setFormNote(e.target.value)}
                  placeholder="Ghi chú thêm về lịch đóng tiền, ưu đãi học phí, hoặc yêu cầu của học viên..."
                  className="w-full px-3 py-2 text-xs border border-slate-200 rounded-lg focus:outline-none focus:border-eztech"
                />
              </div>

              <div className="pt-2 border-t border-slate-100 flex items-center justify-end gap-2">
                <button
                  type="button"
                  onClick={() => setIsModalOpen(false)}
                  className="px-4 py-2 text-xs font-semibold text-slate-600 hover:bg-slate-100 rounded-xl"
                >
                  Huỷ
                </button>
                <button
                  type="submit"
                  disabled={saving}
                  className="px-5 py-2 bg-eztech hover:bg-eztech-dark text-white text-xs font-semibold rounded-xl shadow-sm transition-colors cursor-pointer"
                >
                  {saving ? 'Đang lưu...' : editingId ? 'Lưu Thay Đổi' : 'Thêm Deal Mới'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* MODAL SỬA NHANH LỚP HỌC */}
      {classModalDeal && (
        <div className="fixed inset-0 z-50 bg-navy/50 backdrop-blur-xs flex items-center justify-center p-4">
          <div className="bg-white rounded-2xl border border-slate-200 shadow-xl max-w-md w-full p-5 space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <h4 className="text-sm font-bold text-navy">Xếp Lớp Cho Học Viên</h4>
                <p className="text-xs text-slate-500">
                  {classModalDeal.hoTen} ({classModalDeal.sdt})
                </p>
              </div>
              <button onClick={() => setClassModalDeal(null)} className="text-slate-400 hover:text-navy">
                <X className="w-4 h-4" />
              </button>
            </div>

            <div className="flex flex-wrap gap-1.5 p-3 bg-slate-50 rounded-xl border border-slate-200">
              {Array.from(new Set([...lists.lop, ...quickClasses])).map((cls) => {
                const active = quickClasses.includes(cls);
                return (
                  <button
                    type="button"
                    key={cls}
                    onClick={() =>
                      setQuickClasses((prev) =>
                        prev.includes(cls) ? prev.filter((x) => x !== cls) : [...prev, cls]
                      )
                    }
                    className={`px-2.5 py-1 rounded-lg text-xs font-mono font-semibold transition-all ${
                      active
                        ? 'bg-eztech text-white'
                        : 'bg-white text-slate-600 border border-slate-200'
                    }`}
                  >
                    {cls}
                  </button>
                );
              })}
            </div>

            <div className="flex items-center gap-2">
              <input
                type="text"
                placeholder="Nhập mã lớp mới (VD: DF-K3)..."
                value={quickNewClass}
                onChange={(e) => setQuickNewClass(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') {
                    e.preventDefault();
                    const c = quickNewClass.trim();
                    if (c && !quickClasses.includes(c)) {
                      setQuickClasses((prev) => [...prev, c]);
                      setQuickNewClass('');
                    }
                  }
                }}
                className="flex-1 px-3 py-1.5 text-xs border border-slate-200 rounded-lg"
              />
              <button
                type="button"
                onClick={() => {
                  const c = quickNewClass.trim();
                  if (c && !quickClasses.includes(c)) {
                    setQuickClasses((prev) => [...prev, c]);
                    setQuickNewClass('');
                  }
                }}
                className="px-3 py-1.5 bg-slate-100 hover:bg-slate-200 text-navy text-xs font-semibold rounded-lg"
              >
                + Thêm
              </button>
            </div>

            <div className="flex justify-end gap-2 pt-2">
              <button
                type="button"
                onClick={() => setClassModalDeal(null)}
                className="px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-100 rounded-lg"
              >
                Huỷ
              </button>
              <button
                type="button"
                onClick={handleSaveQuickClasses}
                disabled={saving}
                className="px-4 py-1.5 bg-eztech hover:bg-eztech-dark text-white text-xs font-semibold rounded-lg"
              >
                {saving ? 'Đang lưu...' : 'Lưu & Đồng Bộ Lớp'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
