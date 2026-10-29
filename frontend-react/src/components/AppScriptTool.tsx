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
  ChevronLeft,
  ChevronRight,
  MapPin,
  Mail,
  Briefcase,
  Link2,
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

const isUrl = (s: string | undefined | null) => {
  if (!s) return false;
  const trimmed = s.trim().toLowerCase();
  return trimmed.startsWith('http://') || trimmed.startsWith('https://') || trimmed.startsWith('zalo.me/');
};

const toSafeHref = (s: string) => {
  const trimmed = s.trim();
  if (trimmed.startsWith('http://') || trimmed.startsWith('https://')) return trimmed;
  return `https://${trimmed}`;
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
    'Chờ bổ sung',
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
  const [completionFilter, setCompletionFilter] = useState<'all' | 'incomplete' | 'completed'>('all');
  const [onlyStudentFilter, setOnlyStudentFilter] = useState<boolean>(true);
  const [searchQuery, setSearchQuery] = useState('');
  const [filterStartDate, setFilterStartDate] = useState('');
  const [filterEndDate, setFilterEndDate] = useState('');
  const [filterProgram, setFilterProgram] = useState('');
  const [filterClass, setFilterClass] = useState('');
  const [filterStatus, setFilterStatus] = useState('');
  const [filterSale, setFilterSale] = useState('');
  const [currentPage, setCurrentPage] = useState(1);
  const pageSize = 25;

  // Modal Nhập / Sửa Deal
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editingDealWinId, setEditingDealWinId] = useState<number | null | undefined>(null);
  const [formNgThu, setFormNgThu] = useState(format(new Date(), 'yyyy-MM-dd'));
  const [formNgContact, setFormNgContact] = useState('');
  const [formSdt, setFormSdt] = useState('');
  const [formHoTen, setFormHoTen] = useState('');
  const [formEmail, setFormEmail] = useState('');
  const [formNamSinh, setFormNamSinh] = useState('');
  const [formDiaChi, setFormDiaChi] = useState('');
  const [formLinhVuc, setFormLinhVuc] = useState('');
  const [formKyVong, setFormKyVong] = useState('');
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

  // Reset về trang 1 khi thay đổi bộ lọc
  useEffect(() => {
    setCurrentPage(1);
  }, [completionFilter, onlyStudentFilter, searchQuery, filterStartDate, filterEndDate, filterProgram, filterClass, filterStatus, filterSale]);

  // Tự động tra cứu SĐT khi người dùng nhập đủ 10 chữ số ở chế độ tạo mới
  useEffect(() => {
    if (!isModalOpen || editingId) return;
    const clean = formSdt.replace(/\D/g, '');
    if (clean.length < 10) {
      setPhoneLookup(null);
      return;
    }

    const timer = setTimeout(async () => {
      setLookingUpPhone(true);
      try {
        const res = await lookupDealPhone(clean);
        setPhoneLookup(res);
        if (res.found) {
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

  const openCreateModal = () => {
    setEditingId(null);
    setEditingDealWinId(null);
    setFormNgThu(format(new Date(), 'yyyy-MM-dd'));
    setFormNgContact('');
    setFormSdt('');
    setFormHoTen('');
    setFormEmail('');
    setFormNamSinh('');
    setFormDiaChi('');
    setFormLinhVuc('');
    setFormKyVong('');
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

  const openEditModal = (d: SalesDealRecord) => {
    setEditingId(d.id);
    setEditingDealWinId(d.dealWinId);
    setFormNgThu(d.ngayThu || format(new Date(), 'yyyy-MM-dd'));
    setFormNgContact(d.ngayContact || '');
    setFormSdt(d.sdt || '');
    setFormHoTen(d.hoTen || '');
    setFormEmail(d.email || '');
    setFormNamSinh(d.namSinh || '');
    setFormDiaChi(d.diaChi || '');
    setFormLinhVuc(d.linhVuc || '');
    setFormKyVong(d.kyVong || '');
    setFormZalo(d.zalo || '');
    setFormNhomCS(d.nhomCS || '');
    setFormChuongTrinh(d.chuongTrinh || lists.chuongTrinh[0] || '');
    setFormLop(d.lop || []);
    setNewClassInput('');
    setFormChucVu(d.chucVu || '');
    setFormNvCS(d.nvCS || '');
    setFormZaloCS(d.zaloCS || lists.zaloCS[0] || '');
    setFormNguon(d.nguon || '');
    setFormDaThu(d.daThu || 0);
    setFormPhaiThu(d.phaiThu || 0);
    setFormTongTien(d.tongTien || 0);
    setFormNgThuAR(d.ngayThuAR || '');
    setFormTrangThai(
      d.trangThai === 'Chờ bổ sung' ? 'Hoàn thành' : d.trangThai || 'Hoàn thành'
    );
    setFormNote(d.note || '');
    setPhoneLookup(null);
    setIsModalOpen(true);
  };

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
    setEditingDealWinId(null);
    setFormNgThu(format(new Date(), 'yyyy-MM-dd'));
    setFormNgContact('');
    setFormSdt(item.sdt);
    setFormHoTen(item.hoTen);
    setFormEmail('');
    setFormNamSinh('');
    setFormDiaChi('');
    setFormLinhVuc('');
    setFormKyVong('');
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
      if (val > 0 && formPhaiThu === 0 && formTrangThai === 'Chờ bổ sung') {
        setFormTrangThai('Hoàn thành');
      }
    }
  };

  const handlePhaiThuChange = (val: number) => {
    setFormPhaiThu(val);
    setFormTongTien(formDaThu + val);
    if (val > 0 && (formTrangThai === 'Hoàn thành' || formTrangThai === 'Chờ bổ sung')) {
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
        email: formEmail,
        namSinh: formNamSinh,
        diaChi: formDiaChi,
        linhVuc: formLinhVuc,
        kyVong: formKyVong,
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

  // Đếm số lượng chờ bổ sung thông tin
  const countsByCompletion = useMemo(() => {
    const base = onlyStudentFilter ? deals.filter((d) => d.isStudent !== false) : deals;
    let incomplete = 0;
    let completed = 0;
    for (const d of base) {
      const missingInfo = (d.daThu === 0 && d.phaiThu === 0) || (d.lop || []).length === 0 || !(d.nhomCS || '').trim();
      if (missingInfo) incomplete++;
      else completed++;
    }
    return { total: base.length, incomplete, completed };
  }, [deals, onlyStudentFilter]);

  // Lọc danh sách Deals
  const filteredDeals = useMemo(() => {
    return deals.filter((d) => {
      if (onlyStudentFilter && d.isStudent === false) return false;
      const missingInfo = (d.daThu === 0 && d.phaiThu === 0) || (d.lop || []).length === 0 || !(d.nhomCS || '').trim();
      if (completionFilter === 'incomplete' && !missingInfo) return false;
      if (completionFilter === 'completed' && missingInfo) return false;

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
        const matchEmail = (d.email || '').toLowerCase().includes(q);
        const matchNote = (d.note || '').toLowerCase().includes(q);
        const matchJob = (d.chucVu || '').toLowerCase().includes(q);
        const matchClass = (d.lop || []).some((c) => c.toLowerCase().includes(q));
        if (!matchName && !matchPhone && !matchEmail && !matchNote && !matchJob && !matchClass) return false;
      }
      return true;
    });
  }, [
    deals,
    onlyStudentFilter,
    completionFilter,
    filterStartDate,
    filterEndDate,
    filterProgram,
    filterClass,
    filterStatus,
    filterSale,
    searchQuery,
  ]);

  const totalPages = Math.max(1, Math.ceil(filteredDeals.length / pageSize));
  const pagedDeals = useMemo(() => {
    const start = (currentPage - 1) * pageSize;
    return filteredDeals.slice(start, start + pageSize);
  }, [filteredDeals, currentPage, pageSize]);

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
    return Array.from(s).sort();
  }, [deals]);

  // Xuất CSV
  const exportDealsCsv = () => {
    const headers = [
      'ID', 'Ngày thu tiền', 'Ngày contact đầu tiên', 'Số điện thoại', 'Họ tên', 'Email',
      'Năm sinh', 'Địa chỉ', 'Lĩnh vực', 'Chức vụ', 'Kỳ vọng',
      'Zalo (link Pancake)', 'Nhóm CS 1-1', 'Chương trình học', 'Lớp học',
      'NV chăm sóc', 'Zalo chăm sóc', 'Nguồn', 'Số tiền thu được', 'Phải thu khách hàng',
      'Tổng tiền', 'Ngày thu AR', 'Trạng thái', 'Note', 'Người nhập', 'Tạo lúc',
      'Trong đó thu nợ cũ', 'Đã thu nợ', 'Còn nợ'
    ];
    const rows = filteredDeals.map((d) => [
      d.id, fmtDateVi(d.ngayThu), fmtDateVi(d.ngayContact), `'${d.sdt}`, d.hoTen, d.email || '',
      d.namSinh || '', d.diaChi || '', d.linhVuc || '', d.chucVu || '', d.kyVong || '',
      d.zalo, d.nhomCS, d.chuongTrinh, (d.lop || []).join(', '),
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
    if (lower.includes('chờ bổ sung')) {
      return 'bg-orange-50 text-orange-700 border-orange-200';
    }
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
              <h2 className="text-sm font-bold text-navy">Quản Lý Deal Win, Bổ Sung Học Phí & Công Nợ</h2>
              <span className="px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider bg-eztech-light text-eztech rounded-md border border-eztech-border">
                Đồng bộ từ DB Deal Win
              </span>
            </div>
            <p className="text-xs text-slate-500 mt-0.5">
              Tự động lấy danh sách học viên từ bảng Deal Win — Nhân viên vào điền nốt Số tiền thu được, Lớp học, Link nhóm 1-1
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
              <span>Danh sách Deal ({countsByCompletion.total})</span>
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
            <span>+ Nhập Deal / Thu Nợ</span>
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
            <p className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">Chờ Điền Thông Tin</p>
            <p className="text-lg font-bold font-mono text-orange-600 mt-1 tabular-nums">
              {countsByCompletion.incomplete} <span className="text-xs font-normal text-slate-400">/ {countsByCompletion.total}</span>
            </p>
            <p className="text-[11px] text-slate-400 mt-0.5">Thiếu tiền / Lớp / Nhóm 1-1</p>
          </div>
          <div className="w-9 h-9 rounded-lg bg-orange-50 text-orange-600 flex items-center justify-center">
            <UserCheck className="w-4 h-4" />
          </div>
        </div>
      </div>

      {/* 3. Nội dung từng Sub-tab */}
      {subTab === 'deals' && (
        <div className="space-y-3">
          {/* Thanh lọc nhanh trạng thái điền thông tin */}
          <div className="bg-white rounded-xl border border-slate-200/80 shadow-card p-3 space-y-2.5">
            <div className="flex flex-wrap items-center justify-between gap-2 pb-2.5 border-b border-slate-100">
              <div className="flex flex-wrap items-center gap-1.5">
                <button
                  onClick={() => setCompletionFilter('all')}
                  className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-all cursor-pointer ${
                    completionFilter === 'all'
                      ? 'bg-navy text-white shadow-2xs'
                      : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
                  }`}
                >
                  Tất cả ({countsByCompletion.total})
                </button>

                <button
                  onClick={() => setCompletionFilter('incomplete')}
                  className={`px-3 py-1.5 rounded-lg text-xs font-semibold flex items-center gap-1.5 transition-all cursor-pointer ${
                    completionFilter === 'incomplete'
                      ? 'bg-orange-600 text-white shadow-2xs'
                      : 'bg-orange-50 text-orange-700 border border-orange-200 hover:bg-orange-100'
                  }`}
                >
                  <AlertTriangle className="w-3.5 h-3.5" />
                  <span>Cần điền Tiền / Lớp / Nhóm 1-1 ({countsByCompletion.incomplete})</span>
                </button>

                <button
                  onClick={() => setCompletionFilter('completed')}
                  className={`px-3 py-1.5 rounded-lg text-xs font-semibold flex items-center gap-1.5 transition-all cursor-pointer ${
                    completionFilter === 'completed'
                      ? 'bg-emerald-600 text-white shadow-2xs'
                      : 'bg-emerald-50 text-emerald-700 border border-emerald-200 hover:bg-emerald-100'
                  }`}
                >
                  <CheckCircle2 className="w-3.5 h-3.5" />
                  <span>Đã điền đủ ({countsByCompletion.completed})</span>
                </button>
              </div>

              <label className="inline-flex items-center gap-2 text-xs font-medium text-navy cursor-pointer select-none bg-slate-50 px-3 py-1.5 rounded-lg border border-slate-200">
                <input
                  type="checkbox"
                  checked={onlyStudentFilter}
                  onChange={(e) => setOnlyStudentFilter(e.target.checked)}
                  className="rounded border-slate-300 text-eztech focus:ring-eztech"
                />
                <span>Chỉ hiển thị tag "Đã là học viên"</span>
              </label>
            </div>

            {/* Bộ lọc chi tiết */}
            <div className="flex flex-wrap items-center gap-2.5">
              <div className="relative flex-1 min-w-[220px]">
                <Search className="w-3.5 h-3.5 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
                <input
                  type="text"
                  placeholder="Tìm SĐT, Họ tên, Email, Chức vụ, Lớp học, Ghi chú..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  className="w-full pl-8 pr-3 py-1.5 text-xs border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-eztech/20 focus:border-eztech"
                />
              </div>

              <div className="flex items-center gap-1.5 bg-slate-50 border border-slate-200 rounded-lg px-2 py-1">
                <span className="text-[11px] text-slate-500 font-medium">Ngày:</span>
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
                title="Đồng bộ từ Deal Win & Làm mới dữ liệu"
              >
                <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
              </button>
            </div>
          </div>

          {/* Bảng danh sách Deals */}
          <div className="bg-white rounded-xl border border-slate-200/80 shadow-card overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-left border-collapse">
                <thead>
                  <tr className="bg-slate-50/90 border-b border-slate-200 text-[11px] font-bold uppercase tracking-wider text-slate-500">
                    <th className="py-3 px-3 whitespace-nowrap">Ngày ĐK / Thu</th>
                    <th className="py-3 px-3 whitespace-nowrap">Thông tin Học viên (Deal Win)</th>
                    <th className="py-3 px-3 whitespace-nowrap">Ngành nghề & Kỳ vọng</th>
                    <th className="py-3 px-3 whitespace-nowrap">Chương trình & Lớp học</th>
                    <th className="py-3 px-3 whitespace-nowrap">Link Nhóm 1-1 & Zalo</th>
                    <th className="py-3 px-3 whitespace-nowrap text-right">Thực thu</th>
                    <th className="py-3 px-3 whitespace-nowrap text-right">Phải thu</th>
                    <th className="py-3 px-3 whitespace-nowrap text-right">Còn nợ</th>
                    <th className="py-3 px-3 whitespace-nowrap">Trạng thái</th>
                    <th className="py-3 px-3 whitespace-nowrap">NV CS / Nguồn</th>
                    <th className="py-3 px-3 whitespace-nowrap text-right">Điền / Thao tác</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 text-xs">
                  {loading ? (
                    <tr>
                      <td colSpan={11} className="py-12 text-center text-slate-400">
                        Đang đồng bộ và tải danh sách học viên từ bảng Deal Win...
                      </td>
                    </tr>
                  ) : pagedDeals.length === 0 ? (
                    <tr>
                      <td colSpan={11} className="py-12 text-center text-slate-400">
                        Không có học viên / deal nào khớp bộ lọc hiện tại.
                      </td>
                    </tr>
                  ) : (
                    pagedDeals.map((d) => {
                      const missingMoney = d.daThu === 0 && d.phaiThu === 0;
                      const missingClass = (d.lop || []).length === 0;
                      const missingGroup = !(d.nhomCS || '').trim();

                      return (
                        <tr key={d.id} className="hover:bg-slate-50/80 transition-colors">
                          {/* Ngày thu & Ngày contact */}
                          <td className="py-2.5 px-3 whitespace-nowrap align-top">
                            <div className="font-mono font-semibold text-navy">{fmtDateVi(d.ngayThu)}</div>
                            {d.ngayContact && (
                              <div className="text-[10px] text-slate-400 font-mono mt-0.5">
                                Contact: {fmtDateVi(d.ngayContact)}
                              </div>
                            )}
                            {d.dealWinId && (
                              <span className="inline-block mt-1 px-1.5 py-0.2 text-[9px] font-mono bg-slate-100 text-slate-500 rounded">
                                DW #{d.dealWinId}
                              </span>
                            )}
                          </td>

                          {/* Thông tin Học viên từ bảng Deal Win */}
                          <td className="py-2.5 px-3 align-top min-w-[190px]">
                            <div className="font-semibold text-navy flex items-center gap-1.5">
                              <span>{d.hoTen}</span>
                              {d.namSinh && (
                                <span className="text-[10px] font-mono text-slate-400">({d.namSinh})</span>
                              )}
                            </div>
                            <div className="font-mono text-[11px] font-semibold text-eztech mt-0.5">{d.sdt}</div>
                            {d.email && (
                              <div className="text-[10px] text-slate-400 flex items-center gap-1 mt-0.5 truncate max-w-[180px]" title={d.email}>
                                <Mail className="w-2.5 h-2.5 shrink-0" />
                                <span className="truncate">{d.email}</span>
                              </div>
                            )}
                            {d.diaChi && (
                              <div className="text-[10px] text-slate-400 flex items-center gap-1 mt-0.5">
                                <MapPin className="w-2.5 h-2.5 shrink-0" />
                                <span>{d.diaChi}</span>
                              </div>
                            )}
                          </td>

                          {/* Chức vụ, Lĩnh vực, Kỳ vọng */}
                          <td className="py-2.5 px-3 align-top max-w-[210px]">
                            {(d.chucVu || d.linhVuc) ? (
                              <div className="text-[11px] font-medium text-navy flex items-start gap-1">
                                <Briefcase className="w-3 h-3 text-slate-400 shrink-0 mt-0.5" />
                                <span>{[d.chucVu, d.linhVuc].filter(Boolean).join(' • ')}</span>
                              </div>
                            ) : (
                              <span className="text-slate-300 text-[11px]">—</span>
                            )}
                            {d.kyVong && (
                              <div
                                className="text-[10px] text-slate-500 line-clamp-2 mt-1 bg-slate-50 p-1 rounded border border-slate-100"
                                title={d.kyVong}
                              >
                                Kì vọng: {d.kyVong}
                              </div>
                            )}
                            {d.note && (
                              <div className="text-[10px] text-eztech font-medium mt-0.5" title={d.note}>
                                Note: {d.note}
                              </div>
                            )}
                          </td>

                          {/* Chương trình & Lớp học */}
                          <td className="py-2.5 px-3 align-top min-w-[160px]">
                            <div className="font-semibold text-navy">
                              {d.chuongTrinh || (
                                <span className="text-[11px] font-normal text-orange-500 italic">Chưa chọn CT học</span>
                              )}
                            </div>
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
                                className={`px-1.5 py-0.5 text-[10px] rounded inline-flex items-center gap-0.5 cursor-pointer ${
                                  missingClass
                                    ? 'bg-orange-50 text-orange-700 border border-orange-200 font-semibold hover:bg-orange-100'
                                    : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
                                }`}
                                title="Sửa & đồng bộ lớp học cho SĐT này"
                              >
                                <Tag className="w-2.5 h-2.5" />
                                <span>{missingClass ? '+ Gắn lớp' : 'Sửa'}</span>
                              </button>
                            </div>
                          </td>

                          {/* Nhóm CS 1-1 & Link Pancake */}
                          <td className="py-2.5 px-3 align-top min-w-[150px]">
                            {!missingGroup ? (
                              isUrl(d.nhomCS) ? (
                                <a
                                  href={toSafeHref(d.nhomCS)}
                                  target="_blank"
                                  rel="noopener noreferrer"
                                  className="inline-flex items-center gap-1 px-2 py-0.5 bg-emerald-50 text-emerald-700 border border-emerald-200 rounded text-[11px] font-semibold hover:bg-emerald-100"
                                >
                                  <Link2 className="w-3 h-3" />
                                  <span>Mở Nhóm 1-1</span>
                                </a>
                              ) : (
                                <div className="text-[11px] font-medium text-navy">{d.nhomCS}</div>
                              )
                            ) : (
                              <span className="text-[11px] text-orange-500 italic">Chưa có link 1-1</span>
                            )}

                            <div className="mt-1 flex items-center gap-2">
                              {d.zalo && (
                                <a
                                  href={d.zalo}
                                  target="_blank"
                                  rel="noopener noreferrer"
                                  className="inline-flex items-center gap-1 text-[10px] font-semibold text-eztech hover:underline"
                                >
                                  <ExternalLink className="w-2.5 h-2.5" />
                                  <span>Pancake</span>
                                </a>
                              )}
                              {d.zaloCS && (
                                <span className="text-[10px] text-slate-400">• {d.zaloCS}</span>
                              )}
                            </div>
                          </td>

                          {/* Thực thu */}
                          <td className="py-2.5 px-3 whitespace-nowrap text-right align-top font-mono">
                            {missingMoney ? (
                              <span className="text-[11px] font-sans text-orange-500 italic">Chưa nhập</span>
                            ) : (
                              <>
                                <div className="font-bold text-emerald-600">{fmtMoney(d.daThu)}</div>
                                {d.thuNo > 0 && (
                                  <div className="text-[10px] text-eztech font-medium">
                                    (Thu nợ: {fmtMoney(d.thuNo)})
                                  </div>
                                )}
                              </>
                            )}
                          </td>

                          {/* Phải thu */}
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

                          {/* Còn nợ */}
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

                          {/* Trạng thái */}
                          <td className="py-2.5 px-3 whitespace-nowrap align-top">
                            <span
                              className={`inline-block px-2 py-0.5 text-[11px] font-semibold rounded-full border ${getStatusBadgeStyle(
                                d.trangThai
                              )}`}
                            >
                              {d.trangThai || 'Chờ bổ sung'}
                            </span>
                          </td>

                          {/* NV CS & Nguồn */}
                          <td className="py-2.5 px-3 align-top">
                            <div className="font-semibold text-navy">{d.nvCS || '—'}</div>
                            <div className="text-[10px] text-slate-400 truncate max-w-[140px]" title={d.nguon}>
                              {d.nguon || '—'}
                            </div>
                          </td>

                          {/* Hành động */}
                          <td className="py-2.5 px-3 whitespace-nowrap text-right align-top">
                            <div className="flex items-center justify-end gap-1">
                              {missingMoney || missingClass || missingGroup ? (
                                <button
                                  onClick={() => openEditModal(d)}
                                  className="px-2.5 py-1 text-[11px] font-semibold bg-eztech hover:bg-eztech-dark text-white rounded-lg shadow-2xs transition-colors flex items-center gap-1 cursor-pointer"
                                  title="Điền số tiền thu được, lớp học và link nhóm 1-1"
                                >
                                  <Edit3 className="w-3 h-3" />
                                  <span>Điền thông tin</span>
                                </button>
                              ) : (
                                <button
                                  onClick={() => openEditModal(d)}
                                  className="p-1.5 text-slate-500 hover:text-eztech hover:bg-eztech-light rounded-md transition-colors cursor-pointer"
                                  title="Chỉnh sửa deal"
                                >
                                  <Edit3 className="w-3.5 h-3.5" />
                                </button>
                              )}

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
                                  className="px-2 py-1 text-[11px] font-semibold bg-amber-500 hover:bg-amber-600 text-white rounded-lg shadow-2xs transition-colors cursor-pointer"
                                  title="Nhập giao dịch thu nợ cho khoản này"
                                >
                                  Thu nợ
                                </button>
                              )}

                              <button
                                onClick={() => handleDeleteDeal(d)}
                                className="p-1.5 text-slate-400 hover:text-rose-600 hover:bg-rose-50 rounded-md transition-colors cursor-pointer"
                                title="Xoá dòng này"
                              >
                                <Trash2 className="w-3.5 h-3.5" />
                              </button>
                            </div>
                          </td>
                        </tr>
                      );
                    })
                  )}
                </tbody>
              </table>
            </div>

            {/* Phân trang */}
            {totalPages > 1 && (
              <div className="px-4 py-3 border-t border-slate-100 flex items-center justify-between text-xs text-slate-500">
                <div>
                  Hiển thị <strong>{(currentPage - 1) * pageSize + 1}</strong> –{' '}
                  <strong>{Math.min(currentPage * pageSize, filteredDeals.length)}</strong> trên tổng số{' '}
                  <strong>{filteredDeals.length}</strong> bản ghi
                </div>
                <div className="flex items-center gap-1.5">
                  <button
                    disabled={currentPage <= 1}
                    onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
                    className="p-1.5 rounded-lg border border-slate-200 disabled:opacity-40 hover:bg-slate-50"
                  >
                    <ChevronLeft className="w-4 h-4" />
                  </button>
                  <span className="px-2 font-mono font-semibold text-navy">
                    Trang {currentPage} / {totalPages}
                  </span>
                  <button
                    disabled={currentPage >= totalPages}
                    onClick={() => setCurrentPage((p) => Math.min(totalPages, p + 1))}
                    className="p-1.5 rounded-lg border border-slate-200 disabled:opacity-40 hover:bg-slate-50"
                  >
                    <ChevronRight className="w-4 h-4" />
                  </button>
                </div>
              </div>
            )}
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
              Nhật Ký Thao Tác Hệ Thống (50 hoạt động gần nhất)
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

      {/* MODAL ĐIỀN THÔNG TIN / NHẬP & SỬA DEAL */}
      {isModalOpen && (
        <div className="fixed inset-0 z-50 bg-navy/50 backdrop-blur-xs flex items-center justify-center p-4 overflow-y-auto">
          <div className="bg-white rounded-2xl border border-slate-200 shadow-2xl max-w-3xl w-full overflow-hidden my-8">
            <div className="px-5 py-3.5 bg-navy text-white flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Sparkles className="w-4 h-4 text-gold" />
                <h3 className="text-sm font-bold">
                  {editingId
                    ? `Điền Bổ Sung / Cập Nhật Học Viên ${editingDealWinId ? `(Deal Win #${editingDealWinId})` : ''}`
                    : 'Nhập Deal Mới / Thu Nợ Học Viên'}
                </h3>
              </div>
              <button
                onClick={() => setIsModalOpen(false)}
                className="p-1 text-slate-300 hover:text-white rounded-lg"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <form onSubmit={handleSubmitDeal} className="p-5 space-y-4 max-h-[84vh] overflow-y-auto">
              {/* Cảnh báo công nợ hoặc Gợi ý tự động từ Pancake khi nhập SĐT */}
              {phoneLookup?.found && !editingId && (
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

              {/* PHẦN QUAN TRỌNG NHẤT: ĐIỀN SỐ TIỀN THU ĐƯỢC, LỚP HỌC, LINK NHÓM 1-1 */}
              <div className="p-4 bg-eztech-light/40 rounded-xl border border-eztech-border space-y-3">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-bold text-eztech uppercase tracking-wider">
                    1. Điền Học Phí, Chương Trình, Lớp Học & Nhóm CS 1-1
                  </span>
                </div>

                <div className="grid grid-cols-1 sm:grid-cols-4 gap-3">
                  <div>
                    <label className="block text-[11px] font-semibold text-emerald-700 mb-1">
                      Số tiền thu được (VNĐ) <span className="text-rose-500">*</span>
                    </label>
                    <input
                      type="text"
                      autoFocus
                      value={formDaThu ? fmtMoney(formDaThu) : ''}
                      placeholder="VD: 3,500,000"
                      onChange={(e) => handleDaThuChange(parseMoneyInput(e.target.value))}
                      className="w-full px-3 py-2 text-xs font-mono font-bold text-emerald-700 bg-white border border-emerald-400 rounded-lg focus:outline-none focus:ring-2 focus:ring-emerald-500/20"
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

                <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                  <div>
                    <label className="block text-[11px] font-semibold text-navy mb-1">
                      Chương trình học
                    </label>
                    <select
                      value={formChuongTrinh}
                      onChange={(e) => setFormChuongTrinh(e.target.value)}
                      className="w-full px-2.5 py-2 text-xs border border-slate-200 rounded-lg bg-white text-navy font-medium"
                    >
                      <option value="">-- Chọn chương trình --</option>
                      {lists.chuongTrinh.map((c) => (
                        <option key={c} value={c}>{c}</option>
                      ))}
                    </select>
                  </div>

                  <div className="sm:col-span-2">
                    <label className="block text-[11px] font-semibold text-navy mb-1">
                      Link Nhóm CS 1-1 (Zalo Group / Tên nhóm)
                    </label>
                    <input
                      type="text"
                      value={formNhomCS}
                      onChange={(e) => setFormNhomCS(e.target.value)}
                      placeholder="Dán link nhóm Zalo 1-1 (https://zalo.me/g/...) hoặc tên nhóm..."
                      className="w-full px-3 py-2 text-xs bg-white border border-slate-200 rounded-lg focus:outline-none focus:border-eztech"
                    />
                  </div>
                </div>

                {/* Chọn Lớp học */}
                <div>
                  <label className="block text-[11px] font-semibold text-navy mb-1">
                    Lớp học (Tự động đồng bộ cho mọi deal cùng SĐT)
                  </label>
                  <div className="flex flex-wrap items-center gap-1.5 p-2.5 bg-white border border-slate-200 rounded-xl">
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
                              : 'bg-slate-50 text-slate-600 border border-slate-200 hover:border-eztech'
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
                        className="px-2 py-1 text-xs border border-slate-200 rounded-lg bg-slate-50 w-36"
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
              </div>

              {/* PHẦN 2: THÔNG TIN HỌC VIÊN TỪ BẢNG DEAL WIN & PANCAKE */}
              <div className="space-y-3 pt-1">
                <span className="block text-xs font-bold text-navy uppercase tracking-wider">
                  2. Hồ Sơ Học Viên (Từ Bảng Deal Win & Pancake)
                </span>

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
                      className="w-full px-3 py-2 text-xs font-mono font-semibold border border-slate-200 rounded-lg"
                    />
                  </div>

                  <div>
                    <label className="block text-[11px] font-semibold text-navy mb-1">
                      Họ và tên học viên <span className="text-rose-500">*</span>
                    </label>
                    <input
                      type="text"
                      required
                      value={formHoTen}
                      onChange={(e) => setFormHoTen(e.target.value)}
                      className="w-full px-3 py-2 text-xs font-semibold border border-slate-200 rounded-lg"
                    />
                  </div>

                  <div>
                    <label className="block text-[11px] font-semibold text-navy mb-1">
                      Email học viên
                    </label>
                    <input
                      type="text"
                      value={formEmail}
                      onChange={(e) => setFormEmail(e.target.value)}
                      placeholder="email@example.com"
                      className="w-full px-3 py-2 text-xs border border-slate-200 rounded-lg"
                    />
                  </div>

                  <div>
                    <label className="block text-[11px] font-semibold text-navy mb-1">
                      Ngày thu tiền / Đăng ký <span className="text-rose-500">*</span>
                    </label>
                    <input
                      type="date"
                      required
                      value={formNgThu}
                      onChange={(e) => setFormNgThu(e.target.value)}
                      className="w-full px-3 py-2 text-xs font-mono border border-slate-200 rounded-lg"
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
                      className="w-full px-3 py-2 text-xs font-mono border border-slate-200 rounded-lg"
                    />
                  </div>

                  <div>
                    <label className="block text-[11px] font-semibold text-navy mb-1">
                      Năm sinh & Địa chỉ
                    </label>
                    <div className="flex gap-1.5">
                      <input
                        type="text"
                        placeholder="Năm sinh"
                        value={formNamSinh}
                        onChange={(e) => setFormNamSinh(e.target.value)}
                        className="w-24 px-2.5 py-2 text-xs font-mono border border-slate-200 rounded-lg"
                      />
                      <input
                        type="text"
                        placeholder="Tỉnh / Thành phố"
                        value={formDiaChi}
                        onChange={(e) => setFormDiaChi(e.target.value)}
                        className="flex-1 px-2.5 py-2 text-xs border border-slate-200 rounded-lg"
                      />
                    </div>
                  </div>

                  <div>
                    <label className="block text-[11px] font-semibold text-navy mb-1">
                      Chức vụ / Vị trí công việc
                    </label>
                    <input
                      type="text"
                      value={formChucVu}
                      onChange={(e) => setFormChucVu(e.target.value)}
                      placeholder="VD: Kế toán trưởng..."
                      className="w-full px-3 py-2 text-xs border border-slate-200 rounded-lg"
                    />
                  </div>

                  <div>
                    <label className="block text-[11px] font-semibold text-navy mb-1">
                      Lĩnh vực hoạt động
                    </label>
                    <input
                      type="text"
                      value={formLinhVuc}
                      onChange={(e) => setFormLinhVuc(e.target.value)}
                      placeholder="VD: Thương mại, Sản xuất..."
                      className="w-full px-3 py-2 text-xs border border-slate-200 rounded-lg"
                    />
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
                      Nguồn khách hàng
                    </label>
                    <input
                      type="text"
                      list="nguon-options"
                      value={formNguon}
                      onChange={(e) => setFormNguon(e.target.value)}
                      placeholder="Chọn hoặc nhập nguồn..."
                      className="w-full px-3 py-2 text-xs border border-slate-200 rounded-lg"
                    />
                    <datalist id="nguon-options">
                      {lists.nguon.map((n) => (
                        <option key={n} value={n} />
                      ))}
                    </datalist>
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
                      Zalo (Link hội thoại Pancake)
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

                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  <div>
                    <label className="block text-[11px] font-semibold text-navy mb-1">
                      Mục đích / Kỳ vọng tham gia khoá học (Từ Form)
                    </label>
                    <textarea
                      rows={2}
                      value={formKyVong}
                      onChange={(e) => setFormKyVong(e.target.value)}
                      className="w-full px-3 py-2 text-xs border border-slate-200 rounded-lg bg-slate-50"
                    />
                  </div>

                  <div>
                    <label className="block text-[11px] font-semibold text-navy mb-1">
                      Ghi chú nội bộ (Note học phí / Lịch hẹn đóng nợ)
                    </label>
                    <textarea
                      rows={2}
                      value={formNote}
                      onChange={(e) => setFormNote(e.target.value)}
                      placeholder="Ghi chú thêm về lịch đóng tiền, ưu đãi học phí..."
                      className="w-full px-3 py-2 text-xs border border-slate-200 rounded-lg focus:outline-none focus:border-eztech"
                    />
                  </div>
                </div>
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
                  {saving ? 'Đang lưu lên DB...' : 'Lưu Thông Tin Lên DB'}
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
