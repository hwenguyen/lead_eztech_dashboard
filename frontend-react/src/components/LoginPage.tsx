import React, { useState, useEffect, useMemo, useRef } from 'react';
import {
  Lock,
  User,
  Eye,
  EyeOff,
  ShieldCheck,
  AlertCircle,
  ArrowRight,
  ChevronDown,
  Search,
  X,
  Clock,
  Check,
} from 'lucide-react';
import {
  loginApi,
  fetchLoginEmployees,
  type AuthUser,
  type EmployeeLoginOption,
} from '../services/api';
import {
  LAST_LOGIN_STORAGE_KEY,
  DEPARTMENT_PERMISSIONS,
  resolveDepartmentName,
  stripVnAccents,
} from '../config/permissions';
import { ThemeToggle } from './ThemeToggle';

interface LoginPageProps {
  onLoginSuccess: (user: AuthUser) => void;
  embedded?: boolean;
  title?: string;
  subtitle?: string;
}

export const LoginPage: React.FC<LoginPageProps> = ({
  onLoginSuccess,
  embedded = false,
  title,
  subtitle,
}) => {
  const [employees, setEmployees] = useState<EmployeeLoginOption[]>([]);
  const [loadingEmployees, setLoadingEmployees] = useState<boolean>(true);
  const [selectedEmployee, setSelectedEmployee] = useState<EmployeeLoginOption | null>(null);
  const [searchText, setSearchText] = useState<string>('');
  const [isDropdownOpen, setIsDropdownOpen] = useState<boolean>(false);
  const [highlightedIdx, setHighlightedIdx] = useState<number>(0);
  const [lastLoginUsername, setLastLoginUsername] = useState<string>(() => {
    try {
      return localStorage.getItem(LAST_LOGIN_STORAGE_KEY) || '';
    } catch {
      return '';
    }
  });

  const [password, setPassword] = useState<string>('');
  const [rememberMe, setRememberMe] = useState<boolean>(true);
  const [showPassword, setShowPassword] = useState<boolean>(false);
  const [loading, setLoading] = useState<boolean>(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const comboboxRef = useRef<HTMLDivElement | null>(null);
  const searchInputRef = useRef<HTMLInputElement | null>(null);
  const passwordInputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoadingEmployees(true);
    fetchLoginEmployees()
      .then((list) => {
        if (cancelled) return;
        setEmployees(list || []);
        const savedUser = (() => {
          try {
            return localStorage.getItem(LAST_LOGIN_STORAGE_KEY) || '';
          } catch {
            return '';
          }
        })();
        if (savedUser) {
          const found = (list || []).find(
            (e) =>
              e.username.toLowerCase() === savedUser.toLowerCase() ||
              stripVnAccents(e.full_name) === stripVnAccents(savedUser)
          );
          if (found) {
            setSelectedEmployee(found);
            setSearchText(found.full_name);
            setLastLoginUsername(found.username);
            window.setTimeout(() => passwordInputRef.current?.focus(), 60);
          }
        }
      })
      .catch((err) => {
        console.error('Không thể tải danh sách nhân viên:', err);
      })
      .finally(() => {
        if (!cancelled) setLoadingEmployees(false);
      });

    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    const onOutsideClick = (e: MouseEvent) => {
      if (comboboxRef.current && !comboboxRef.current.contains(e.target as Node)) {
        setIsDropdownOpen(false);
        if (selectedEmployee) {
          setSearchText(selectedEmployee.full_name);
        }
      }
    };
    document.addEventListener('mousedown', onOutsideClick);
    return () => document.removeEventListener('mousedown', onOutsideClick);
  }, [selectedEmployee]);

  // Ghim nhân viên đăng nhập gần nhất lên đầu danh sách & lọc không dấu tiếng Việt
  const filteredEmployees = useMemo(() => {
    const ordered = [...employees].sort((a, b) => {
      const aPinned = lastLoginUsername && a.username.toLowerCase() === lastLoginUsername.toLowerCase() ? 0 : 1;
      const bPinned = lastLoginUsername && b.username.toLowerCase() === lastLoginUsername.toLowerCase() ? 0 : 1;
      if (aPinned !== bPinned) return aPinned - bPinned;
      const aAdm = a.role === 'admin' ? 0 : 1;
      const bAdm = b.role === 'admin' ? 0 : 1;
      if (aAdm !== bAdm) return aAdm - bAdm;
      return stripVnAccents(a.full_name).localeCompare(stripVnAccents(b.full_name));
    });

    const q = stripVnAccents(searchText);
    // Nếu đang mở dropdown nhưng ô text đang giữ nguyên tên người đã chọn thì hiển thị toàn bộ danh sách để đổi nhanh
    if (!q || (selectedEmployee && stripVnAccents(selectedEmployee.full_name) === q)) {
      return ordered;
    }

    return ordered.filter((emp) => {
      const hayName = stripVnAccents(emp.full_name);
      const hayUser = stripVnAccents(emp.username);
      const hayDept = stripVnAccents(emp.department);
      return hayName.includes(q) || hayUser.includes(q) || hayDept.includes(q);
    });
  }, [employees, searchText, selectedEmployee, lastLoginUsername]);

  const handleSelectOption = (emp: EmployeeLoginOption) => {
    setSelectedEmployee(emp);
    setSearchText(emp.full_name);
    setIsDropdownOpen(false);
    setErrorMsg(null);
    window.setTimeout(() => passwordInputRef.current?.focus(), 30);
  };

  const handleClearSelection = () => {
    setSelectedEmployee(null);
    setSearchText('');
    setIsDropdownOpen(true);
    setHighlightedIdx(0);
    searchInputRef.current?.focus();
  };

  const handleKeyDownCombobox = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      if (!isDropdownOpen) {
        setIsDropdownOpen(true);
        setHighlightedIdx(0);
      } else {
        setHighlightedIdx((prev) => Math.min(prev + 1, Math.max(0, filteredEmployees.length - 1)));
      }
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setHighlightedIdx((prev) => Math.max(prev - 1, 0));
    } else if (e.key === 'Enter' && isDropdownOpen) {
      e.preventDefault();
      const target = filteredEmployees[highlightedIdx];
      if (target) {
        handleSelectOption(target);
      }
    } else if (e.key === 'Escape') {
      setIsDropdownOpen(false);
      if (selectedEmployee) {
        setSearchText(selectedEmployee.full_name);
      }
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const resolvedIdent = selectedEmployee?.username || searchText.trim();

    if (!resolvedIdent) {
      setErrorMsg('Vui lòng chọn tên nhân viên đăng nhập từ danh sách.');
      searchInputRef.current?.focus();
      return;
    }
    if (!password) {
      setErrorMsg('Vui lòng nhập mật khẩu đăng nhập.');
      passwordInputRef.current?.focus();
      return;
    }

    setLoading(true);
    setErrorMsg(null);

    try {
      const res = await loginApi(resolvedIdent, password, rememberMe);
      onLoginSuccess(res.user);
    } catch (err: any) {
      console.error('Lỗi đăng nhập:', err);
      const detail = err.response?.data?.detail;
      if (err.response?.status === 429) {
        setErrorMsg(detail || 'Tài khoản tạm thời bị khóa do nhập sai nhiều lần. Vui lòng thử lại sau ít phút.');
      } else if (err.response?.status === 401) {
        setErrorMsg(detail || 'Mật khẩu không chính xác. Vui lòng kiểm tra lại.');
      } else {
        setErrorMsg(detail || 'Không thể kết nối đến máy chủ xác thực. Vui lòng thử lại sau.');
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <div
      className={
        embedded
          ? 'py-6 flex items-center justify-center p-2 relative text-gray-800'
          : 'min-h-screen bg-gradient-to-br from-navy via-brand-950 to-[#071630] flex items-center justify-center p-4 relative overflow-hidden text-gray-800'
      }
    >
      {!embedded && (
        <>
          <div className="absolute top-4 right-4 z-20">
            <ThemeToggle />
          </div>
          <div className="absolute top-1/4 left-1/4 w-96 h-96 bg-brand-500/15 rounded-full blur-3xl pointer-events-none" />
          <div className="absolute bottom-1/4 right-1/4 w-96 h-96 bg-gold-500/10 rounded-full blur-3xl pointer-events-none" />
        </>
      )}

      <div className="max-w-md w-full relative z-10">
        <div
          className={
            embedded
              ? 'bg-white rounded-3xl shadow-xl border border-gray-200 p-8 sm:p-10 space-y-6'
              : 'bg-white/95 backdrop-blur-xl rounded-3xl shadow-2xl border border-white/20 dark:border-slate-700/80 p-8 sm:p-10 space-y-6'
          }
        >
          {/* Header & Logo */}
          <div className="text-center space-y-2">
            <div className="inline-flex items-center justify-center p-3 rounded-2xl bg-gradient-to-tr from-brand-50 to-white dark:from-slate-800 dark:to-slate-900 border border-brand-200/80 shadow-inner mb-1">
              {embedded ? (
                <Lock className="w-8 h-8 text-brand-500" />
              ) : (
                <img src="/brand_ngang.png" alt="EzTech" className="h-10 w-auto object-contain dark:brightness-125" />
              )}
            </div>
            <h1 className="text-2xl font-extrabold text-navy tracking-tight">
              {title || 'Đăng Nhập Hệ Thống'}
            </h1>
            <p className="text-xs text-gray-500 max-w-xs mx-auto">
              {subtitle || 'Chọn tên nhân sự của bạn để truy cập không gian làm việc EzTech CRM'}
            </p>
          </div>

          {/* Error Banner */}
          {errorMsg && (
            <div
              role="alert"
              className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-xl text-xs flex items-start gap-2.5 shadow-sm"
            >
              <AlertCircle className="w-4 h-4 text-red-500 flex-shrink-0 mt-0.5" />
              <div className="flex-1 font-medium leading-relaxed">{errorMsg}</div>
            </div>
          )}

          {/* Form */}
          <form onSubmit={handleSubmit} className="space-y-4">
            {/* Searchable Employee Combobox */}
            <div className="space-y-1.5" ref={comboboxRef}>
              <div className="flex items-center justify-between">
                <label htmlFor="login-employee-combobox" className="block text-xs font-bold text-gray-700">
                  Nhân viên đăng nhập
                </label>
                {selectedEmployee && (
                  <span
                    className={`text-[10px] font-semibold px-2 py-0.5 rounded-full border ${
                      DEPARTMENT_PERMISSIONS[resolveDepartmentName(selectedEmployee.department, selectedEmployee.role)]
                        .badgeClass
                    }`}
                  >
                    {resolveDepartmentName(selectedEmployee.department, selectedEmployee.role)}
                  </span>
                )}
              </div>

              <div className="relative">
                <div className="absolute inset-y-0 left-0 pl-3.5 flex items-center pointer-events-none text-gray-400">
                  {isDropdownOpen ? <Search className="w-4 h-4 text-brand-500" /> : <User className="w-4 h-4" />}
                </div>

                <input
                  ref={searchInputRef}
                  id="login-employee-combobox"
                  type="text"
                  role="combobox"
                  aria-expanded={isDropdownOpen}
                  aria-controls="employee-listbox"
                  aria-autocomplete="list"
                  autoComplete="off"
                  spellCheck={false}
                  value={searchText}
                  onFocus={() => {
                    setIsDropdownOpen(true);
                    setHighlightedIdx(0);
                  }}
                  onChange={(e) => {
                    setSearchText(e.target.value);
                    setSelectedEmployee(null);
                    setIsDropdownOpen(true);
                    setHighlightedIdx(0);
                  }}
                  onKeyDown={handleKeyDownCombobox}
                  placeholder={loadingEmployees ? 'Đang tải danh sách nhân sự...' : 'Gõ tìm hoặc chọn tên nhân viên...'}
                  className="w-full pl-10 pr-16 py-2.5 bg-gray-50/80 border border-gray-300 rounded-xl text-xs text-gray-900 placeholder-gray-400 focus:bg-white focus:outline-none focus:ring-2 focus:ring-brand-500/20 focus:border-brand-500 transition-all font-semibold"
                />

                <div className="absolute inset-y-0 right-0 pr-2 flex items-center gap-0.5">
                  {searchText && (
                    <button
                      type="button"
                      onClick={handleClearSelection}
                      aria-label="Xóa lựa chọn nhân viên"
                      className="p-1 text-gray-400 hover:text-gray-600 rounded-lg transition-colors cursor-pointer"
                    >
                      <X className="w-3.5 h-3.5" />
                    </button>
                  )}
                  <button
                    type="button"
                    onClick={() => setIsDropdownOpen((prev) => !prev)}
                    aria-label="Mở danh sách nhân viên"
                    className="p-1 text-gray-400 hover:text-navy rounded-lg transition-colors cursor-pointer"
                  >
                    <ChevronDown
                      className={`w-4 h-4 transition-transform duration-150 ${isDropdownOpen ? 'rotate-180 text-brand-600' : ''}`}
                    />
                  </button>
                </div>

                {/* Dropdown Menu */}
                {isDropdownOpen && (
                  <div
                    id="employee-listbox"
                    role="listbox"
                    className="absolute left-0 right-0 mt-1.5 max-h-64 overflow-y-auto bg-white rounded-2xl border border-gray-200 shadow-2xl z-30 py-1.5 divide-y divide-gray-50 custom-scrollbar"
                  >
                    {loadingEmployees ? (
                      <div className="px-4 py-6 text-center text-xs text-gray-400">
                        Đang tải danh sách nhân viên...
                      </div>
                    ) : filteredEmployees.length === 0 ? (
                      <div className="px-4 py-6 text-center text-xs text-gray-500">
                        Không tìm thấy nhân sự phù hợp với "{searchText}"
                      </div>
                    ) : (
                      filteredEmployees.map((emp, idx) => {
                        const isSelected = selectedEmployee?.id === emp.id;
                        const isPinned =
                          Boolean(lastLoginUsername) &&
                          emp.username.toLowerCase() === lastLoginUsername.toLowerCase();
                        const dept = resolveDepartmentName(emp.department, emp.role);
                        const badgeCls = DEPARTMENT_PERMISSIONS[dept].badgeClass;

                        return (
                          <button
                            key={emp.id}
                            type="button"
                            role="option"
                            aria-selected={isSelected}
                            onMouseEnter={() => setHighlightedIdx(idx)}
                            onClick={() => handleSelectOption(emp)}
                            className={`w-full px-3.5 py-2.5 text-left flex items-center justify-between gap-2 transition-colors cursor-pointer ${
                              idx === highlightedIdx
                                ? 'bg-brand-50/90 text-navy'
                                : isSelected
                                ? 'bg-slate-50 text-navy'
                                : 'text-gray-700 hover:bg-gray-50'
                            }`}
                          >
                            <div className="flex items-center gap-2.5 min-w-0">
                              <div
                                className={`w-7 h-7 rounded-lg flex items-center justify-center text-[11px] font-bold uppercase shrink-0 ${
                                  dept === 'Admin'
                                    ? 'bg-navy text-gold-400'
                                    : 'bg-brand-100/80 text-brand-700'
                                }`}
                              >
                                {emp.full_name.slice(0, 2)}
                              </div>
                              <div className="min-w-0">
                                <div className="flex items-center gap-1.5">
                                  <span className="text-xs font-semibold truncate">{emp.full_name}</span>
                                  {isSelected && <Check className="w-3.5 h-3.5 text-brand-600 shrink-0" />}
                                </div>
                                {isPinned && (
                                  <span className="inline-flex items-center gap-1 text-[10px] text-emerald-600 font-medium">
                                    <Clock className="w-2.5 h-2.5" />
                                    Đăng nhập gần nhất
                                  </span>
                                )}
                              </div>
                            </div>

                            <span
                              className={`text-[10px] font-semibold px-2 py-0.5 rounded-full border shrink-0 ${badgeCls}`}
                            >
                              {dept}
                            </span>
                          </button>
                        );
                      })
                    )}
                  </div>
                )}
              </div>
            </div>

            {/* Password Input */}
            <div className="space-y-1.5">
              <label htmlFor="login-password" className="block text-xs font-bold text-gray-700">
                Mật khẩu
              </label>
              <div className="relative">
                <div className="absolute inset-y-0 left-0 pl-3.5 flex items-center pointer-events-none text-gray-400">
                  <Lock className="w-4 h-4" />
                </div>
                <input
                  ref={passwordInputRef}
                  id="login-password"
                  name="password"
                  type={showPassword ? 'text' : 'password'}
                  autoComplete="current-password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="Nhập mật khẩu..."
                  className="w-full pl-10 pr-10 py-2.5 bg-gray-50/80 border border-gray-300 rounded-xl text-xs text-gray-900 placeholder-gray-400 focus:bg-white focus:outline-none focus:ring-2 focus:ring-brand-500/20 focus:border-brand-500 transition-all font-medium"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  aria-label={showPassword ? 'Ẩn mật khẩu' : 'Hiện mật khẩu'}
                  aria-pressed={showPassword}
                  className="absolute inset-y-0 right-0 pr-3.5 flex items-center text-gray-400 hover:text-gray-600 transition-colors cursor-pointer"
                >
                  {showPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                </button>
              </div>
            </div>

            {/* Remember Me Checkbox */}
            <div className="flex items-center justify-between pt-1">
              <label className="flex items-center gap-2 cursor-pointer select-none">
                <input
                  type="checkbox"
                  name="rememberMe"
                  checked={rememberMe}
                  onChange={(e) => setRememberMe(e.target.checked)}
                  className="rounded border-gray-300 text-brand-500 focus:ring-indigo-500 w-3.5 h-3.5"
                />
                <span className="text-xs text-gray-600 font-medium">Duy trì đăng nhập trên trình duyệt này</span>
              </label>
            </div>

            {/* Submit Button */}
            <button
              type="submit"
              disabled={loading}
              className="w-full py-2.5 px-4 gradient-brand text-white rounded-xl text-xs font-bold shadow-lg shadow-brand-500/25 hover:shadow-brand-500/35 flex items-center justify-center gap-2 transition-all transform active:scale-[0.99] disabled:opacity-70 disabled:cursor-not-allowed mt-2 cursor-pointer"
            >
              {loading ? (
                <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
              ) : (
                <>
                  <span>Đăng Nhập</span>
                  <ArrowRight className="w-4 h-4" />
                </>
              )}
            </button>
          </form>

          {/* Security Footer */}
          <div className="pt-2 border-t border-gray-100 flex items-center justify-center gap-2 text-[11px] text-gray-400">
            <ShieldCheck className="w-3.5 h-3.5 text-emerald-500" />
            <span>Phân quyền truy cập & bảo mật dữ liệu theo phòng ban</span>
          </div>
        </div>
      </div>
    </div>
  );
};
