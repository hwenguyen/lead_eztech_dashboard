import React, { useState, useEffect, useMemo } from 'react';
import {
  User,
  ShieldCheck,
  KeyRound,
  LogOut,
  CheckCircle2,
  AlertCircle,
  Eye,
  EyeOff,
  Lock,
  Users,
  UserPlus,
  Trash2,
  RotateCcw,
  RefreshCw,
  Search,
  ArrowUpRight,
  Building2,
  Hash,
} from 'lucide-react';
import {
  changePasswordApi,
  fetchAdminUsers,
  createAdminUser,
  updateAdminUser,
  deleteAdminUser,
  syncAdminUsersFromDb,
  type AuthUser,
} from '../services/api';
import {
  DEPARTMENT_PERMISSIONS,
  TAB_LABELS,
  getEffectivePermissions,
  resolveDepartmentName,
  stripVnAccents,
  type AppTabId,
  type DepartmentName,
} from '../config/permissions';
import { showAppToast } from '../utils/toast';

interface ProfilePageProps {
  user: AuthUser;
  onUserUpdated: (updated: AuthUser) => void;
  onNavigateTab: (tab: AppTabId) => void;
  onLogout: () => void;
}

const SELECTABLE_DEPARTMENTS: DepartmentName[] = [
  'Consultant',
  'Marketing',
  'Quản lý lớp học',
  'Admin',
];

export const ProfilePage: React.FC<ProfilePageProps> = ({
  user,
  onUserUpdated,
  onNavigateTab,
  onLogout,
}) => {
  const perms = useMemo(() => getEffectivePermissions(user), [user]);

  // Change password state
  const [oldPassword, setOldPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [showPw, setShowPw] = useState(false);
  const [pwLoading, setPwLoading] = useState(false);
  const [pwError, setPwError] = useState<string | null>(null);
  const [pwSuccess, setPwSuccess] = useState<string | null>(null);

  // Admin employee management state
  const [staffList, setStaffList] = useState<AuthUser[]>([]);
  const [staffLoading, setStaffLoading] = useState(false);
  const [staffSearch, setStaffSearch] = useState('');
  const [newStaffName, setNewStaffName] = useState('');
  const [newStaffDept, setNewStaffDept] = useState<DepartmentName>('Consultant');
  const [addingStaff, setAddingStaff] = useState(false);
  const [syncingDb, setSyncingDb] = useState(false);

  const loadAdminUsers = async () => {
    if (!perms.isAdmin) return;
    setStaffLoading(true);
    try {
      const list = await fetchAdminUsers();
      setStaffList(list || []);
    } catch (err: any) {
      showAppToast(err.response?.data?.detail || 'Không thể tải danh sách nhân sự.', 'error');
    } finally {
      setStaffLoading(false);
    }
  };

  useEffect(() => {
    if (perms.isAdmin) {
      loadAdminUsers();
    }
  }, [perms.isAdmin]);

  const handleChangePassword = async (e: React.FormEvent) => {
    e.preventDefault();
    setPwError(null);
    setPwSuccess(null);

    if (!oldPassword.trim() || !newPassword.trim() || !confirmPassword.trim()) {
      setPwError('Vui lòng điền đầy đủ mật khẩu hiện tại, mật khẩu mới và xác nhận mật khẩu.');
      return;
    }
    if (newPassword !== confirmPassword) {
      setPwError('Mật khẩu mới và xác nhận mật khẩu mới không trùng khớp.');
      return;
    }

    setPwLoading(true);
    try {
      const res = await changePasswordApi(oldPassword, newPassword, confirmPassword);
      const msg = res.message || 'Đổi mật khẩu thành công!';
      setPwSuccess(msg);
      showAppToast(msg, 'success');
      setOldPassword('');
      setNewPassword('');
      setConfirmPassword('');
      if (res.user) {
        onUserUpdated(res.user);
      } else {
        onUserUpdated({ ...user, is_default_password: false });
      }
    } catch (err: any) {
      setPwError(err.response?.data?.detail || 'Mật khẩu hiện tại không chính xác.');
    } finally {
      setPwLoading(false);
    }
  };

  const handleCreateEmployee = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newStaffName.trim()) {
      showAppToast('Vui lòng nhập họ tên nhân viên cần thêm.', 'warning');
      return;
    }
    setAddingStaff(true);
    try {
      const created = await createAdminUser({
        full_name: newStaffName.trim(),
        department: newStaffDept,
        password: '1',
      });
      setStaffList((prev) => [...prev, created]);
      setNewStaffName('');
      showAppToast(`Đã thêm nhân viên "${created.full_name}" (Mật khẩu mặc định: 1).`, 'success');
    } catch (err: any) {
      showAppToast(err.response?.data?.detail || 'Không thể thêm nhân viên.', 'error');
    } finally {
      setAddingStaff(false);
    }
  };

  const handleChangeStaffDepartment = async (target: AuthUser, nextDept: DepartmentName) => {
    try {
      const updated = await updateAdminUser(target.id, { department: nextDept });
      setStaffList((prev) => prev.map((item) => (item.id === target.id ? updated : item)));
      showAppToast(`Đã chuyển "${updated.full_name}" sang phòng ${updated.department}.`, 'success');
    } catch (err: any) {
      showAppToast(err.response?.data?.detail || 'Không thể cập nhật phòng ban.', 'error');
    }
  };

  const handleResetPassword = async (target: AuthUser) => {
    if (!window.confirm(`Đặt lại mật khẩu của "${target.full_name}" về mặc định "1"?`)) return;
    try {
      const updated = await updateAdminUser(target.id, { reset_password: true });
      setStaffList((prev) => prev.map((item) => (item.id === target.id ? updated : item)));
      showAppToast(`Đã reset mật khẩu của "${updated.full_name}" về "1".`, 'success');
    } catch (err: any) {
      showAppToast(err.response?.data?.detail || 'Không thể reset mật khẩu.', 'error');
    }
  };

  const handleDeleteStaff = async (target: AuthUser) => {
    if (!window.confirm(`Bạn có chắc chắn muốn xóa tài khoản "${target.full_name}" khỏi hệ thống?`)) return;
    try {
      const res = await deleteAdminUser(target.id);
      setStaffList((prev) => prev.filter((item) => item.id !== target.id));
      showAppToast(res.message || 'Đã xóa nhân viên.', 'info');
    } catch (err: any) {
      showAppToast(err.response?.data?.detail || 'Không thể xóa tài khoản này.', 'error');
    }
  };

  const handleSyncFromDb = async () => {
    setSyncingDb(true);
    try {
      const res = await syncAdminUsersFromDb();
      showAppToast(res.message, 'success');
      await loadAdminUsers();
    } catch (err: any) {
      showAppToast(err.response?.data?.detail || 'Không thể đồng bộ nhân sự từ DB.', 'error');
    } finally {
      setSyncingDb(false);
    }
  };

  const filteredStaff = useMemo(() => {
    const q = stripVnAccents(staffSearch);
    if (!q) return staffList;
    return staffList.filter(
      (s) =>
        stripVnAccents(s.full_name).includes(q) ||
        stripVnAccents(s.username).includes(q) ||
        stripVnAccents(s.department).includes(q)
    );
  }, [staffList, staffSearch]);

  const displayName = user.full_name || user.username;

  return (
    <div className="max-w-5xl mx-auto space-y-5">
      {/* 1. Thông tin cá nhân & Nút Đăng xuất */}
      <div className="bg-white rounded-2xl border border-slate-200/80 shadow-card p-6 flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div className="flex items-center gap-4">
          <div className="w-14 h-14 rounded-2xl gradient-brand text-gold-400 font-extrabold text-lg flex items-center justify-center uppercase shadow-md shrink-0">
            {displayName.slice(0, 2)}
          </div>
          <div className="space-y-1">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="text-lg font-bold text-navy">{displayName}</h2>
              <span className={`text-xs font-semibold px-2.5 py-0.5 rounded-full border ${perms.badgeClass}`}>
                {perms.department}
              </span>
              {user.is_default_password && (
                <span className="text-[11px] font-semibold px-2 py-0.5 rounded-full bg-amber-50 text-amber-700 border border-amber-200">
                  Đang dùng mật khẩu mặc định "1"
                </span>
              )}
            </div>
            <div className="flex flex-wrap items-center gap-4 text-xs text-slate-500">
              <span className="inline-flex items-center gap-1">
                <Hash className="w-3.5 h-3.5 text-slate-400" />
                Mã NV: <strong className="font-mono text-navy">NV-{String(user.id).padStart(3, '0')}</strong> ({user.username})
              </span>
              <span className="inline-flex items-center gap-1">
                <Building2 className="w-3.5 h-3.5 text-slate-400" />
                Phòng ban: <strong className="text-navy">{perms.department}</strong>
              </span>
            </div>
          </div>
        </div>

        <button
          type="button"
          onClick={onLogout}
          className="inline-flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl text-xs font-bold text-rose-600 bg-rose-50 hover:bg-rose-100 border border-rose-200/80 transition-colors cursor-pointer shrink-0"
        >
          <LogOut className="w-4 h-4" />
          <span>Đăng xuất tài khoản</span>
        </button>
      </div>

      {/* Grid 2 cột: Quyền được phân & Đổi mật khẩu */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-5">
        {/* 2. Quyền được phân (Permissions Overview) */}
        <div className="lg:col-span-7 bg-white rounded-2xl border border-slate-200/80 shadow-card p-6 space-y-4">
          <div className="flex items-center gap-2.5 pb-3 border-b border-slate-100">
            <div className="p-2 rounded-xl bg-emerald-50 text-emerald-600">
              <ShieldCheck className="w-4 h-4" />
            </div>
            <div>
              <h3 className="text-sm font-bold text-navy">Quyền Truy Cập & Phạm Vi Dữ Liệu</h3>
              <p className="text-[11px] text-slate-500">Cấu hình tự động theo phòng ban {perms.department}</p>
            </div>
          </div>

          {/* Tóm tắt Data Scope */}
          <div className="p-3.5 rounded-xl bg-slate-50 border border-slate-200/70 space-y-1">
            <span className="text-[11px] font-bold uppercase tracking-wider text-slate-500 block">
              Phạm vi dữ liệu (Data Scope)
            </span>
            <p className="text-xs font-medium text-navy leading-relaxed">{perms.scopeSummary}</p>
          </div>

          {/* Danh sách trang được phép truy cập */}
          <div className="space-y-2">
            <span className="text-[11px] font-bold uppercase tracking-wider text-slate-500 block">
              Các trang được phép truy cập ({perms.allowedTabs.length} module)
            </span>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
              {perms.allowedTabs.map((tabId) => {
                const scope = perms.moduleScopes[tabId] || 'personal';
                return (
                  <button
                    key={tabId}
                    type="button"
                    onClick={() => onNavigateTab(tabId)}
                    className="group flex items-center justify-between gap-2 p-2.5 rounded-xl border border-slate-200/80 hover:border-brand-300 hover:bg-brand-50/40 transition-all text-left cursor-pointer"
                  >
                    <div className="min-w-0">
                      <div className="text-xs font-semibold text-navy group-hover:text-brand-600 flex items-center gap-1 truncate">
                        <span>{TAB_LABELS[tabId] || tabId}</span>
                        <ArrowUpRight className="w-3 h-3 opacity-0 group-hover:opacity-100 transition-opacity shrink-0" />
                      </div>
                      <span
                        className={`inline-block mt-0.5 text-[10px] font-medium px-1.5 py-0.2 rounded ${
                          scope === 'all'
                            ? 'bg-emerald-50 text-emerald-700'
                            : 'bg-blue-50 text-blue-700'
                        }`}
                      >
                        {scope === 'all' ? 'Toàn bộ nhân viên' : 'Chỉ dữ liệu cá nhân'}
                      </span>
                    </div>
                    <CheckCircle2 className="w-4 h-4 text-emerald-500 shrink-0" />
                  </button>
                );
              })}
            </div>
          </div>
        </div>

        {/* 3. Đổi mật khẩu (Change Password) */}
        <div className="lg:col-span-5 bg-white rounded-2xl border border-slate-200/80 shadow-card p-6 space-y-4">
          <div className="flex items-center justify-between pb-3 border-b border-slate-100">
            <div className="flex items-center gap-2.5">
              <div className="p-2 rounded-xl bg-brand-50 text-brand-600">
                <KeyRound className="w-4 h-4" />
              </div>
              <div>
                <h3 className="text-sm font-bold text-navy">Đổi Mật Khẩu</h3>
                <p className="text-[11px] text-slate-500">Bảo mật tài khoản cá nhân của bạn</p>
              </div>
            </div>
            <button
              type="button"
              onClick={() => setShowPw((v) => !v)}
              className="text-[11px] font-medium text-slate-500 hover:text-navy inline-flex items-center gap-1 cursor-pointer"
            >
              {showPw ? <EyeOff className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}
              <span>{showPw ? 'Ẩn' : 'Hiện'}</span>
            </button>
          </div>

          {pwError && (
            <div role="alert" className="p-3 rounded-xl bg-rose-50 border border-rose-200 text-rose-700 text-xs flex items-start gap-2">
              <AlertCircle className="w-4 h-4 text-rose-500 shrink-0 mt-0.5" />
              <span>{pwError}</span>
            </div>
          )}

          {pwSuccess && (
            <div role="status" className="p-3 rounded-xl bg-emerald-50 border border-emerald-200 text-emerald-700 text-xs flex items-start gap-2">
              <CheckCircle2 className="w-4 h-4 text-emerald-500 shrink-0 mt-0.5" />
              <span>{pwSuccess}</span>
            </div>
          )}

          <form onSubmit={handleChangePassword} className="space-y-3.5">
            <div>
              <label htmlFor="pf-old-pw" className="block text-xs font-semibold text-slate-700 mb-1">
                Mật khẩu hiện tại
              </label>
              <div className="relative">
                <Lock className="w-3.5 h-3.5 text-slate-400 absolute left-3 top-2.5" />
                <input
                  id="pf-old-pw"
                  type={showPw ? 'text' : 'password'}
                  value={oldPassword}
                  onChange={(e) => setOldPassword(e.target.value)}
                  placeholder="Nhập mật khẩu hiện tại..."
                  className="w-full pl-9 pr-3 py-2 bg-slate-50 border border-slate-200 rounded-xl text-xs text-navy focus:bg-white focus:outline-none focus:ring-2 focus:ring-brand-500/20 focus:border-brand-500"
                />
              </div>
            </div>

            <div>
              <label htmlFor="pf-new-pw" className="block text-xs font-semibold text-slate-700 mb-1">
                Mật khẩu mới
              </label>
              <div className="relative">
                <Lock className="w-3.5 h-3.5 text-slate-400 absolute left-3 top-2.5" />
                <input
                  id="pf-new-pw"
                  type={showPw ? 'text' : 'password'}
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  placeholder="Nhập mật khẩu mới..."
                  className="w-full pl-9 pr-3 py-2 bg-slate-50 border border-slate-200 rounded-xl text-xs text-navy focus:bg-white focus:outline-none focus:ring-2 focus:ring-brand-500/20 focus:border-brand-500"
                />
              </div>
            </div>

            <div>
              <label htmlFor="pf-confirm-pw" className="block text-xs font-semibold text-slate-700 mb-1">
                Xác nhận mật khẩu mới
              </label>
              <div className="relative">
                <Lock className="w-3.5 h-3.5 text-slate-400 absolute left-3 top-2.5" />
                <input
                  id="pf-confirm-pw"
                  type={showPw ? 'text' : 'password'}
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  placeholder="Nhập lại mật khẩu mới..."
                  className="w-full pl-9 pr-3 py-2 bg-slate-50 border border-slate-200 rounded-xl text-xs text-navy focus:bg-white focus:outline-none focus:ring-2 focus:ring-brand-500/20 focus:border-brand-500"
                />
              </div>
            </div>

            <button
              type="submit"
              disabled={pwLoading}
              className="w-full py-2.5 px-4 gradient-brand text-white rounded-xl text-xs font-bold shadow-sm hover:opacity-95 transition-all disabled:opacity-60 cursor-pointer"
            >
              {pwLoading ? 'Đang cập nhật...' : 'Cập nhật mật khẩu mới'}
            </button>
          </form>
        </div>
      </div>

      {/* 4. Quản trị Nhân sự & Phòng ban (Chỉ hiển thị cho Admin) */}
      {perms.isAdmin && (
        <div className="bg-white rounded-2xl border border-slate-200/80 shadow-card p-6 space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-3 pb-3 border-b border-slate-100">
            <div className="flex items-center gap-2.5">
              <div className="p-2 rounded-xl bg-amber-50 text-amber-600">
                <Users className="w-4 h-4" />
              </div>
              <div>
                <h3 className="text-sm font-bold text-navy">
                  Quản Lý Tài Khoản Nhân Sự ({staffList.length} tài khoản)
                </h3>
                <p className="text-[11px] text-slate-500">
                  Thêm mới, xóa bớt nhân viên, phân bổ Phòng ban hoặc đặt lại mật khẩu mặc định "1"
                </p>
              </div>
            </div>

            <button
              type="button"
              onClick={handleSyncFromDb}
              disabled={syncingDb}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-semibold bg-slate-100 hover:bg-slate-200 text-navy transition-colors cursor-pointer disabled:opacity-50"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${syncingDb ? 'animate-spin' : ''}`} />
              <span>Quét bổ sung nhân sự từ DB</span>
            </button>
          </div>

          {/* Form Thêm nhân viên mới + Ô tìm kiếm */}
          <div className="flex flex-col md:flex-row items-stretch md:items-center justify-between gap-3 bg-slate-50/80 p-3.5 rounded-xl border border-slate-200/70">
            <form onSubmit={handleCreateEmployee} className="flex flex-wrap items-center gap-2 flex-1">
              <div className="relative flex-1 min-w-[200px]">
                <User className="w-3.5 h-3.5 text-slate-400 absolute left-3 top-2.5" />
                <input
                  type="text"
                  value={newStaffName}
                  onChange={(e) => setNewStaffName(e.target.value)}
                  placeholder="Nhập họ tên nhân viên mới ( khớp tên Pancake )..."
                  className="w-full pl-8 pr-3 py-1.5 bg-white border border-slate-200 rounded-lg text-xs text-navy focus:outline-none focus:border-brand-500"
                />
              </div>
              <select
                value={newStaffDept}
                onChange={(e) => setNewStaffDept(e.target.value as DepartmentName)}
                className="px-3 py-1.5 bg-white border border-slate-200 rounded-lg text-xs font-semibold text-navy cursor-pointer focus:outline-none focus:border-brand-500"
              >
                {SELECTABLE_DEPARTMENTS.map((d) => (
                  <option key={d} value={d}>
                    {d}
                  </option>
                ))}
              </select>
              <button
                type="submit"
                disabled={addingStaff}
                className="inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg text-xs font-bold bg-eztech hover:bg-eztech-hover text-white transition-colors cursor-pointer disabled:opacity-50"
              >
                <UserPlus className="w-3.5 h-3.5" />
                <span>{addingStaff ? 'Đang thêm...' : 'Thêm nhân viên (Pass: 1)'}</span>
              </button>
            </form>

            <div className="relative min-w-[220px]">
              <Search className="w-3.5 h-3.5 text-slate-400 absolute left-3 top-2.5" />
              <input
                type="search"
                value={staffSearch}
                onChange={(e) => setStaffSearch(e.target.value)}
                placeholder="Tìm nhanh nhân sự..."
                className="w-full pl-8 pr-3 py-1.5 bg-white border border-slate-200 rounded-lg text-xs text-navy focus:outline-none focus:border-brand-500"
              />
            </div>
          </div>

          {/* Bảng danh sách nhân viên */}
          <div className="overflow-x-auto border border-slate-200/80 rounded-xl max-h-[420px] overflow-y-auto custom-scrollbar">
            <table className="w-full text-left border-collapse text-xs">
              <thead className="bg-slate-50 sticky top-0 z-10 border-b border-slate-200 text-[11px] font-bold uppercase tracking-wider text-slate-500">
                <tr>
                  <th className="py-2.5 px-3.5">Mã NV</th>
                  <th className="py-2.5 px-3.5">Họ tên nhân sự</th>
                  <th className="py-2.5 px-3.5">Phòng ban (RBAC)</th>
                  <th className="py-2.5 px-3.5">Mật khẩu</th>
                  <th className="py-2.5 px-3.5">Đăng nhập cuối</th>
                  <th className="py-2.5 px-3.5 text-right">Thao tác</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {staffLoading ? (
                  <tr>
                    <td colSpan={6} className="py-8 text-center text-slate-400">
                      Đang tải danh sách tài khoản...
                    </td>
                  </tr>
                ) : filteredStaff.length === 0 ? (
                  <tr>
                    <td colSpan={6} className="py-8 text-center text-slate-400">
                      Không tìm thấy nhân viên nào khớp từ khóa.
                    </td>
                  </tr>
                ) : (
                  filteredStaff.map((st) => {
                    const stDept = resolveDepartmentName(st.department, st.role);
                    const isSelf = st.id === user.id || st.username === 'admin';
                    return (
                      <tr key={st.id} className="hover:bg-slate-50/70 transition-colors">
                        <td className="py-2.5 px-3.5 font-mono text-[11px] text-slate-500">
                          NV-{String(st.id).padStart(3, '0')}
                        </td>
                        <td className="py-2.5 px-3.5">
                          <div className="font-semibold text-navy">{st.full_name || st.username}</div>
                          <div className="text-[10px] font-mono text-slate-400">{st.username}</div>
                        </td>
                        <td className="py-2.5 px-3.5">
                          <select
                            value={stDept}
                            disabled={st.id === user.id}
                            onChange={(e) => handleChangeStaffDepartment(st, e.target.value as DepartmentName)}
                            className={`px-2.5 py-1 rounded-lg text-xs font-semibold border cursor-pointer focus:outline-none disabled:opacity-60 disabled:cursor-not-allowed ${
                              DEPARTMENT_PERMISSIONS[stDept].badgeClass
                            }`}
                          >
                            {SELECTABLE_DEPARTMENTS.map((d) => (
                              <option key={d} value={d} className="bg-white text-navy">
                                {d}
                              </option>
                            ))}
                          </select>
                        </td>
                        <td className="py-2.5 px-3.5">
                          {st.is_default_password ? (
                            <span className="text-[11px] px-2 py-0.5 rounded-full bg-amber-50 text-amber-700 border border-amber-200 font-medium">
                              Mặc định ("1")
                            </span>
                          ) : (
                            <span className="text-[11px] px-2 py-0.5 rounded-full bg-emerald-50 text-emerald-700 border border-emerald-200 font-medium">
                              Đã đổi pass
                            </span>
                          )}
                        </td>
                        <td className="py-2.5 px-3.5 font-mono text-[11px] text-slate-500">
                          {st.last_login_at || 'Chưa đăng nhập'}
                        </td>
                        <td className="py-2.5 px-3.5 text-right">
                          <div className="inline-flex items-center gap-1.5">
                            {st.username !== 'admin' && (
                              <button
                                type="button"
                                onClick={() => handleResetPassword(st)}
                                title='Đặt lại mật khẩu về "1"'
                                className="px-2 py-1 rounded-lg text-[11px] font-medium text-slate-600 hover:text-brand-600 hover:bg-brand-50 border border-slate-200 transition-colors inline-flex items-center gap-1 cursor-pointer"
                              >
                                <RotateCcw className="w-3 h-3" />
                                <span>Reset pass</span>
                              </button>
                            )}
                            {!isSelf && (
                              <button
                                type="button"
                                onClick={() => handleDeleteStaff(st)}
                                title="Xóa nhân viên"
                                className="p-1.5 rounded-lg text-rose-500 hover:bg-rose-50 border border-transparent hover:border-rose-200 transition-colors cursor-pointer"
                              >
                                <Trash2 className="w-3.5 h-3.5" />
                              </button>
                            )}
                          </div>
                        </td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
};
