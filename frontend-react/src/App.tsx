import { useState, useEffect, useCallback, useMemo, useRef, lazy, Suspense, type ComponentType } from 'react';
import { format } from 'date-fns';
import {
  Users, UserPlus, UserCheck, PhoneCall, PhoneForwarded, Percent, Calendar,
  RefreshCw, LayoutDashboard, Clock, Award, Bot, LogOut, KeyRound,
  Menu, X, Sparkles, Facebook, FileSpreadsheet, Receipt, ExternalLink,
  Wallet, Database, CheckCircle2, User, ChevronDown,
  BarChart3, Briefcase, Cpu, GraduationCap
} from 'lucide-react';
import { KpiCard } from './components/KpiCard';
import { TrendChart } from './components/TrendChart';
import { LeadTable } from './components/LeadTable';
import { RatioChart } from './components/RatioChart';
import { StatsPieChart } from './components/StatsPieChart';
import { ThemeToggle } from './components/ThemeToggle';
import { ErrorBoundary } from './components/ErrorBoundary';
import { ErrorBanner } from './components/ErrorBanner';
import { ToastHost } from './components/ToastHost';
import { LoginPage } from './components/LoginPage';
import { getVnTodayStr } from './utils/format';
import { showAppToast } from './utils/toast';
import {
  fetchSummary, fetchTrend, fetchLeads, fetchEmployees, fetchPages,
  fetchCurrentUser, updateStoredUser,
  getStoredAuth, logoutApi, clearClientApiCache, isAbortError,
  type SummaryData, type TrendData, type Lead, type AuthUser, type OverviewCrossFilters
} from './services/api';
import {
  canAccessTab,
  getEffectivePermissions,
  type AppTabId,
} from './config/permissions';

// Code-splitting: tải lười các tab phụ, card AI & modal giúp giảm mạnh bundle JS khởi đầu
const FacebookDashboard = lazy(() => import('./components/FacebookDashboard').then((m) => ({ default: m.FacebookDashboard })));
const TikTokDashboard = lazy(() => import('./components/TikTokDashboard').then((m) => ({ default: m.TikTokDashboard })));
const WorkReportDashboard = lazy(() => import('./components/WorkReportDashboard').then((m) => ({ default: m.WorkReportDashboard })));
const RemindLeadTable = lazy(() => import('./components/RemindLeadTable').then((m) => ({ default: m.RemindLeadTable })));
const DealWinDashboard = lazy(() => import('./components/DealWinDashboard').then((m) => ({ default: m.DealWinDashboard })));
const BulkMessengerDashboard = lazy(() => import('./components/BulkMessengerDashboard').then((m) => ({ default: m.BulkMessengerDashboard })));
const AutoAddFriendDashboard = lazy(() => import('./components/AutoAddFriendDashboard').then((m) => ({ default: m.AutoAddFriendDashboard })));
const AppScriptTool = lazy(() => import('./components/AppScriptTool').then((m) => ({ default: m.AppScriptTool })));
const AiAssistantDashboard = lazy(() => import('./components/AiAssistantDashboard').then((m) => ({ default: m.AiAssistantDashboard })));
const AiDailyReviewCard = lazy(() => import('./components/AiDailyReviewCard').then((m) => ({ default: m.AiDailyReviewCard })));
const BtvnGraderDashboard = lazy(() => import('./components/BtvnGraderDashboard').then((m) => ({ default: m.BtvnGraderDashboard })));
const DataExportDashboard = lazy(() => import('./components/DataExportDashboard').then((m) => ({ default: m.DataExportDashboard })));
const ProfilePage = lazy(() => import('./components/ProfilePage').then((m) => ({ default: m.ProfilePage })));
const ChangePasswordModal = lazy(() => import('./components/ChangePasswordModal').then((m) => ({ default: m.ChangePasswordModal })));

const INVOICE_SCRIPT_URL = 'https://script.google.com/macros/s/AKfycbywN2OeDtwsqXNW3Z-2j5KJ147auCNsZF6epEoWxzKK1QLO0JQvYYuXTiJWhXlXBm5h/exec';

const TAG_PIE_COLOR_MAP: Record<string, string> = {
  'Lead Other': '#1E5BD6',
  'Đào tạo': 'var(--ez-chart-navy)',
  'Other': '#F5B400',
};

type TabId = AppTabId | 'profile';

const VALID_TABS = new Set<TabId>([
  'overview', 'facebook', 'tiktok', 'work_report', 'remind',
  'deals', 'bot', 'data_export', 'add_friend', 'gas_tool',
  'invoice', 'ai_assistant', 'btvn_grader', 'profile',
]);

const TAB_TITLES: Record<TabId, string> = {
  overview: 'Tổng quan & Chỉ số',
  facebook: 'Facebook Analytics',
  tiktok: 'TikTok Analytics',
  work_report: 'Báo cáo công việc Tuần',
  remind: 'Chăm sóc Lead (Remind)',
  deals: 'Học viên Chốt (Deal Win)',
  bot: 'Bot Gửi Tin Nhắn Tự Động',
  data_export: 'Query & Kết Xuất Dữ Liệu Excel',
  add_friend: 'Kết Bạn Zalo Tự Động (Pancake)',
  gas_tool: 'Nhập Deal & Quản lý Công Nợ',
  invoice: 'Xuất Hoá Đơn Điện Tử',
  ai_assistant: 'Trợ Lý AI Nội Bộ (RAG + API)',
  btvn_grader: 'Chấm BTVN Power BI / Power Query (Gemini AI)',
  profile: 'Thông Tin Cá Nhân & Phân Quyền',
};

function readTabFromLocation(defaultTab: AppTabId = 'overview'): { tab: TabId; isLoginPath: boolean; isRoot: boolean } {
  if (typeof window === 'undefined') return { tab: defaultTab, isLoginPath: false, isRoot: true };
  const cleanPath = window.location.pathname.replace(/^\/+|\/+$/g, '') as string;
  const cleanHash = window.location.hash.replace(/^#\/?/, '') as string;

  if (cleanPath === 'login' || cleanHash === 'login') {
    return { tab: defaultTab, isLoginPath: true, isRoot: false };
  }
  if (cleanPath && VALID_TABS.has(cleanPath as TabId)) {
    return { tab: cleanPath as TabId, isLoginPath: false, isRoot: false };
  }
  if (cleanHash && VALID_TABS.has(cleanHash as TabId)) {
    return { tab: cleanHash as TabId, isLoginPath: false, isRoot: false };
  }
  return { tab: defaultTab, isLoginPath: false, isRoot: !cleanPath && !cleanHash };
}

function SidebarTikTokIcon({ className = 'w-4 h-4' }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
      <path d="M19.59 6.69a4.83 4.83 0 0 1-3.77-4.25V2h-3.45v13.67a2.89 2.89 0 0 1-5.2 1.74 2.89 2.89 0 0 1 2.31-4.64c.298-.002.595.042.88.13V9.4a6.33 6.33 0 0 0-1-.08A6.34 6.34 0 0 0 3 15.66a6.34 6.34 0 0 0 10.82 4.46 6.3 6.3 0 0 0 1.86-4.46V8.7a8.18 8.18 0 0 0 4.91 1.63V6.88a4.85 4.85 0 0 1-1-.19z" />
    </svg>
  );
}

const TabLoadingFallback = () => (
  <div className="flex items-center justify-center py-24">
    <div className="flex flex-col items-center gap-3">
      <div className="animate-spin rounded-full h-8 w-8 border-2 border-slate-200 border-t-brand-500" />
      <p className="text-xs font-medium text-slate-400">Đang tải giao diện...</p>
    </div>
  </div>
);

type NavGroupId = 'analytics' | 'sales' | 'automation' | 'ai_edu';

interface NavItemConfig {
  id: AppTabId;
  label: string;
  icon: ComponentType<{ className?: string }>;
  url?: string;
}

interface NavGroupConfig {
  id: NavGroupId;
  label: string;
  icon: ComponentType<{ className?: string }>;
  items: NavItemConfig[];
}

const SIDEBAR_GROUPS_STORAGE_KEY = 'ez_sidebar_open_groups';

const DEFAULT_OPEN_NAV_GROUPS: Record<NavGroupId, boolean> = {
  analytics: true,
  sales: true,
  automation: true,
  ai_edu: true,
};

const NAV_GROUPS: NavGroupConfig[] = [
  {
    id: 'analytics',
    label: 'Báo cáo & Phân tích',
    icon: BarChart3,
    items: [
      { id: 'overview', label: 'Tổng quan & Chỉ số', icon: LayoutDashboard },
      { id: 'facebook', label: 'Facebook Analytics', icon: Facebook },
      { id: 'tiktok', label: 'TikTok Analytics', icon: SidebarTikTokIcon },
    ],
  },
  {
    id: 'sales',
    label: 'Kinh doanh & Học viên',
    icon: Briefcase,
    items: [
      { id: 'work_report', label: 'Báo cáo công việc', icon: FileSpreadsheet },
      { id: 'remind', label: 'Chăm sóc Lead', icon: Clock },
      { id: 'deals', label: 'Deal Win', icon: Award },
      { id: 'gas_tool', label: 'Nhập Deal & Công Nợ', icon: Wallet },
      { id: 'invoice', label: 'Xuất hoá đơn', icon: Receipt, url: INVOICE_SCRIPT_URL },
    ],
  },
  {
    id: 'automation',
    label: 'Tự động hoá & Dữ liệu',
    icon: Cpu,
    items: [
      { id: 'bot', label: 'Bot Gửi Tin', icon: Bot },
      { id: 'add_friend', label: 'Kết Bạn Tự Động', icon: UserPlus },
      { id: 'data_export', label: 'Query & Xuất Excel', icon: Database },
    ],
  },
  {
    id: 'ai_edu',
    label: 'Trợ lý AI & Đào tạo',
    icon: GraduationCap,
    items: [
      { id: 'ai_assistant', label: 'Trợ Lý AI', icon: Sparkles },
      { id: 'btvn_grader', label: 'Chấm BTVN (AI)', icon: CheckCircle2 },
    ],
  },
];

function App() {
  const [currentUser, setCurrentUser] = useState<AuthUser | null>(() => getStoredAuth().user);
  const [isAuthenticated, setIsAuthenticated] = useState<boolean>(() => !!getStoredAuth().token);
  const [showChangePw, setShowChangePw] = useState<boolean>(false);
  const [isSidebarOpen, setIsSidebarOpen] = useState<boolean>(false);
  const [isProfileMenuOpen, setIsProfileMenuOpen] = useState<boolean>(false);
  const [openNavGroups, setOpenNavGroups] = useState<Record<NavGroupId, boolean>>(() => {
    try {
      const saved = localStorage.getItem(SIDEBAR_GROUPS_STORAGE_KEY);
      if (saved) {
        return { ...DEFAULT_OPEN_NAV_GROUPS, ...JSON.parse(saved) };
      }
    } catch {
      // Bỏ qua lỗi đọc localStorage nếu bị chặn
    }
    return DEFAULT_OPEN_NAV_GROUPS;
  });
  const profileMenuRef = useRef<HTMLDivElement | null>(null);

  const userPerms = useMemo(() => getEffectivePermissions(currentUser), [currentUser]);

  const [activeTab, setActiveTabState] = useState<TabId>(() => {
    const initialUser = getStoredAuth().user;
    const defTab = getEffectivePermissions(initialUser).defaultTab;
    const parsed = readTabFromLocation(defTab);
    if (initialUser && parsed.tab !== 'profile' && !canAccessTab(initialUser, parsed.tab)) {
      return defTab;
    }
    return parsed.tab;
  });
  const [startDate, setStartDate] = useState(() => getVnTodayStr(-7));
  const [endDate, setEndDate] = useState(() => getVnTodayStr(0));
  const [pageId, setPageId] = useState('');
  const [employee, setEmployee] = useState('');
  const [employeesList, setEmployeesList] = useState<string[]>([]);
  const [pagesList, setPagesList] = useState<string[]>([]);
  const [zaloPages, setZaloPages] = useState<string[]>([]);

  const [summary, setSummary] = useState<SummaryData | null>(null);
  const [trend, setTrend] = useState<TrendData[]>([]);
  const [leads, setLeads] = useState<Lead[]>([]);
  const [totalLeads, setTotalLeads] = useState(0);
  const [page, setPage] = useState(1);
  const pageSize = 15;
  const [loading, setLoading] = useState(false);
  const [loadingPage, setLoadingPage] = useState(false);
  const [overviewError, setOverviewError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const [phoneCategoryFilter, setPhoneCategoryFilter] = useState<'all' | 'new' | 'recontact'>('all');

  // Bộ lọc chéo kiểu Power BI (click ngày / biểu đồ / KPI để lọc đồng bộ các chỉ số & danh sách)
  const [selectedDate, setSelectedDate] = useState<string | null>(null);
  const [selectedLeadType, setSelectedLeadType] = useState<'new' | 'recontact' | null>(null);
  const [selectedTagCategory, setSelectedTagCategory] = useState<string | null>(null);
  const [onlyPhone, setOnlyPhone] = useState<boolean>(false);
  const [selectedChartEmployee, setSelectedChartEmployee] = useState<string | null>(null);

  const employeesAbortRef = useRef<AbortController | null>(null);
  const trendAbortRef = useRef<AbortController | null>(null);
  const summaryAbortRef = useRef<AbortController | null>(null);
  const leadsPageAbortRef = useRef<AbortController | null>(null);
  const pagesLoadedRef = useRef(false);

  const crossFilters = useMemo<OverviewCrossFilters>(
    () => ({
      selectedDate,
      leadType: selectedLeadType,
      tagCategory: selectedTagCategory,
      hasPhone: onlyPhone ? true : null,
      primaryEmployee: selectedChartEmployee,
    }),
    [selectedDate, selectedLeadType, selectedTagCategory, onlyPhone, selectedChartEmployee]
  );

  const trendCrossFilters = useMemo<OverviewCrossFilters>(
    () => ({
      leadType: selectedLeadType,
      tagCategory: selectedTagCategory,
      hasPhone: onlyPhone ? true : null,
      primaryEmployee: selectedChartEmployee,
    }),
    [selectedLeadType, selectedTagCategory, onlyPhone, selectedChartEmployee]
  );

  const hasCrossFilter = Boolean(
    selectedDate || selectedLeadType || selectedTagCategory || onlyPhone || selectedChartEmployee
  );

  const clearCrossFilters = useCallback(() => {
    setSelectedDate(null);
    setSelectedLeadType(null);
    setSelectedTagCategory(null);
    setOnlyPhone(false);
    setSelectedChartEmployee(null);
  }, []);

  useEffect(() => {
    if (selectedDate && (selectedDate < startDate || selectedDate > endDate)) {
      setSelectedDate(null);
    }
  }, [startDate, endDate, selectedDate]);

  useEffect(() => {
    setSelectedChartEmployee(null);
  }, [pageId, employee]);

  const setActiveTab = useCallback((nextTab: TabId) => {
    const targetTab: TabId =
      nextTab !== 'profile' && currentUser && !canAccessTab(currentUser, nextTab)
        ? userPerms.defaultTab
        : nextTab;
    setActiveTabState(targetTab);
    setIsProfileMenuOpen(false);
    if (typeof window !== 'undefined') {
      const targetUrl = `/${targetTab}`;
      if (window.location.pathname !== targetUrl || window.location.hash) {
        window.history.pushState(null, '', targetUrl);
      }
    }
  }, [currentUser, userPerms.defaultTab]);

  // Route Guard: chưa đăng nhập -> /login; đã đăng nhập ở /login, / hoặc trang không có quyền -> tự động chuyển về defaultTab
  useEffect(() => {
    if (typeof window === 'undefined') return;
    if (!isAuthenticated) {
      if (window.location.pathname !== '/login') {
        window.history.replaceState(null, '', '/login');
      }
      document.title = 'Đăng Nhập Hệ Thống | EzTech Lead Analytics';
      return;
    }

    const parsed = readTabFromLocation(userPerms.defaultTab);
    const isUnauthorized =
      parsed.tab !== 'profile' && currentUser && !canAccessTab(currentUser, parsed.tab);
    if (parsed.isLoginPath || parsed.isRoot || isUnauthorized) {
      const targetTab = userPerms.defaultTab;
      setActiveTabState(targetTab);
      window.history.replaceState(null, '', `/${targetTab}`);
    }
  }, [isAuthenticated, currentUser, userPerms.defaultTab]);

  // Xác thực & đồng bộ lại thông tin user + quyền mới nhất từ server khi reload trang
  useEffect(() => {
    if (!isAuthenticated) return;
    let cancelled = false;
    fetchCurrentUser()
      .then((freshUser) => {
        if (cancelled) return;
        setCurrentUser(freshUser);
        updateStoredUser(freshUser);
      })
      .catch(() => {
        // Nếu 401 thì interceptor đã tự kích hoạt auth_unauthorized
      });
    return () => {
      cancelled = true;
    };
  }, [isAuthenticated]);

  // Đồng bộ URL khi người dùng bấm Back/Forward trên trình duyệt
  useEffect(() => {
    const syncFromUrl = () => {
      if (!isAuthenticated) return;
      const parsed = readTabFromLocation(userPerms.defaultTab);
      const isUnauthorized =
        parsed.tab !== 'profile' && currentUser && !canAccessTab(currentUser, parsed.tab);
      if (parsed.isLoginPath || isUnauthorized) {
        window.history.replaceState(null, '', `/${userPerms.defaultTab}`);
        setActiveTabState(userPerms.defaultTab);
      } else {
        setActiveTabState(parsed.tab);
      }
    };
    window.addEventListener('popstate', syncFromUrl);
    window.addEventListener('hashchange', syncFromUrl);
    return () => {
      window.removeEventListener('popstate', syncFromUrl);
      window.removeEventListener('hashchange', syncFromUrl);
    };
  }, [isAuthenticated, currentUser, userPerms.defaultTab]);

  // Đóng dropdown cá nhân góc phải trên khi click ra ngoài
  useEffect(() => {
    if (!isProfileMenuOpen) return;
    const onDocClick = (e: MouseEvent) => {
      if (profileMenuRef.current && !profileMenuRef.current.contains(e.target as Node)) {
        setIsProfileMenuOpen(false);
      }
    };
    document.addEventListener('mousedown', onDocClick);
    return () => document.removeEventListener('mousedown', onDocClick);
  }, [isProfileMenuOpen]);

  useEffect(() => {
    if (!isAuthenticated) return;
    document.title = `${TAB_TITLES[activeTab]} | EzTech Lead Analytics`;
  }, [activeTab, isAuthenticated]);

  // Đóng mobile drawer bằng phím Escape
  useEffect(() => {
    if (!isSidebarOpen && !isProfileMenuOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setIsSidebarOpen(false);
        setIsProfileMenuOpen(false);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [isSidebarOpen, isProfileMenuOpen]);

  useEffect(() => {
    const onUnauthorized = () => {
      setIsAuthenticated(false);
      setCurrentUser(null);
      setIsProfileMenuOpen(false);
      pagesLoadedRef.current = false;
      if (typeof window !== 'undefined' && window.location.pathname !== '/login') {
        window.history.replaceState(null, '', '/login');
      }
      showAppToast('Phiên đăng nhập đã hết hạn, vui lòng đăng nhập lại.', 'warning');
    };
    window.addEventListener('auth_unauthorized', onUnauthorized);
    return () => window.removeEventListener('auth_unauthorized', onUnauthorized);
  }, []);

  const handleLoginSuccess = useCallback((loggedUser: AuthUser) => {
    const perms = getEffectivePermissions(loggedUser);
    pagesLoadedRef.current = false;
    setCurrentUser(loggedUser);
    setIsAuthenticated(true);
    setActiveTabState(perms.defaultTab);
    if (typeof window !== 'undefined') {
      window.history.replaceState(null, '', `/${perms.defaultTab}`);
    }
    showAppToast(`Xin chào ${loggedUser.full_name || loggedUser.username}!`, 'success');
  }, []);

  const handleLogout = async () => {
    setIsProfileMenuOpen(false);
    await logoutApi();
    pagesLoadedRef.current = false;
    setIsAuthenticated(false);
    setCurrentUser(null);
    if (typeof window !== 'undefined') {
      window.history.replaceState(null, '', '/login');
    }
    showAppToast('Đã đăng xuất tài khoản.', 'info');
  };

  // Chỉ tải danh sách pages khi đã đăng nhập và đang ở tab có quyền cần dùng (overview hoặc remind)
  useEffect(() => {
    if (!isAuthenticated || pagesLoadedRef.current) return;
    const allowedOverview = activeTab === 'overview' && canAccessTab(currentUser, 'overview');
    const allowedRemind = activeTab === 'remind' && canAccessTab(currentUser, 'remind');
    if (!allowedOverview && !allowedRemind) return;
    let cancelled = false;
    fetchPages()
      .then((pgRes) => {
        if (cancelled) return;
        pagesLoadedRef.current = true;
        setPagesList(pgRes.pages);
        setZaloPages(pgRes.zaloPages);
      })
      .catch((error) => {
        console.error('Error fetching pages:', error);
      });
    return () => {
      cancelled = true;
    };
  }, [activeTab, isAuthenticated, currentUser]);

  const loadEmployees = useCallback(
    async (opts?: { skipCache?: boolean }) => {
      if (startDate && endDate && startDate > endDate) return;
      employeesAbortRef.current?.abort();
      const controller = new AbortController();
      employeesAbortRef.current = controller;
      try {
        const empList = await fetchEmployees(startDate, endDate, pageId, {
          signal: controller.signal,
          skipCache: opts?.skipCache,
        });
        if (controller.signal.aborted) return;
        setEmployeesList(empList);
        setEmployee((prev) => (prev && !empList.includes(prev) ? '' : prev));
      } catch (error) {
        if (isAbortError(error)) return;
        console.error('Error fetching employees:', error);
      }
    },
    [startDate, endDate, pageId]
  );

  const loadTrendData = useCallback(
    async (opts?: { skipCache?: boolean }) => {
      if (startDate && endDate && startDate > endDate) return;
      trendAbortRef.current?.abort();
      const controller = new AbortController();
      trendAbortRef.current = controller;
      try {
        const trRes = await fetchTrend(startDate, endDate, pageId, employee, trendCrossFilters, {
          signal: controller.signal,
          skipCache: opts?.skipCache,
        });
        if (controller.signal.aborted) return;
        setTrend(trRes);
      } catch (error) {
        if (isAbortError(error)) return;
        console.error('Trend error:', error);
      }
    },
    [startDate, endDate, pageId, employee, trendCrossFilters]
  );

  const loadSummaryAndLeads = useCallback(
    async (opts?: { skipCache?: boolean }) => {
      if (startDate && endDate && startDate > endDate) {
        setOverviewError('Ngày bắt đầu không được lớn hơn ngày kết thúc.');
        return;
      }

      summaryAbortRef.current?.abort();
      const controller = new AbortController();
      summaryAbortRef.current = controller;

      setLoading(true);
      setOverviewError(null);

      try {
        const [sumRes, ldRes] = await Promise.all([
          fetchSummary(startDate, endDate, pageId, employee, crossFilters, {
            signal: controller.signal,
            skipCache: opts?.skipCache,
          }),
          fetchLeads(pageId, employee, startDate, endDate, 1, pageSize, crossFilters, {
            signal: controller.signal,
            skipCache: opts?.skipCache,
          }),
        ]);
        if (controller.signal.aborted) return;

        setSummary(sumRes);
        setLeads(ldRes.data);
        setTotalLeads(ldRes.total);
        setPage(1);
        setLastUpdated(new Date());
      } catch (error) {
        if (isAbortError(error)) return;
        console.error('Error fetching overview data:', error);
        setOverviewError('Không thể tải dữ liệu tổng quan. Máy chủ có thể đang khởi động lại — vui lòng thử lại.');
      } finally {
        if (summaryAbortRef.current === controller) {
          setLoading(false);
        }
      }
    },
    [startDate, endDate, pageId, employee, crossFilters]
  );

  // Chỉ fetch Tổng quan khi người dùng đã đăng nhập và có quyền xem tab Tổng quan
  const canViewOverview = isAuthenticated && canAccessTab(currentUser, 'overview');

  useEffect(() => {
    if (activeTab !== 'overview' || !canViewOverview) return;
    loadEmployees();
    return () => {
      employeesAbortRef.current?.abort();
    };
  }, [activeTab, canViewOverview, loadEmployees]);

  useEffect(() => {
    if (activeTab !== 'overview' || !canViewOverview) return;
    loadTrendData();
    return () => {
      trendAbortRef.current?.abort();
    };
  }, [activeTab, canViewOverview, loadTrendData]);

  useEffect(() => {
    if (activeTab !== 'overview' || !canViewOverview) return;
    loadSummaryAndLeads();
    return () => {
      summaryAbortRef.current?.abort();
    };
  }, [activeTab, canViewOverview, loadSummaryAndLeads]);

  const handleRefreshOverview = () => {
    clearClientApiCache('/metrics/');
    clearClientApiCache('/leads/list');
    clearClientApiCache('/employees/list');
    loadEmployees({ skipCache: true });
    loadTrendData({ skipCache: true });
    loadSummaryAndLeads({ skipCache: true });
  };

  const loadLeadsPage = useCallback(
    async (newPage: number) => {
      leadsPageAbortRef.current?.abort();
      const controller = new AbortController();
      leadsPageAbortRef.current = controller;
      setLoadingPage(true);
      try {
        const ldRes = await fetchLeads(pageId, employee, startDate, endDate, newPage, pageSize, crossFilters, {
          signal: controller.signal,
        });
        if (controller.signal.aborted) return;
        setLeads(ldRes.data);
        setTotalLeads(ldRes.total);
        setPage(newPage);
      } catch (error) {
        if (isAbortError(error)) return;
        console.error('Error fetching leads page:', error);
        showAppToast('Không thể tải trang danh sách Lead, vui lòng thử lại.', 'error');
      } finally {
        if (leadsPageAbortRef.current === controller) {
          setLoadingPage(false);
        }
      }
    },
    [pageId, employee, startDate, endDate, crossFilters]
  );

  const newLeadsCount = summary?.new_leads || 0;
  const recontactLeadsCount = summary?.recontact_leads || 0;
  const totalLeadsCount = summary?.total_leads || 0;
  const newPhoneCount = summary?.new_phone_leads || 0;
  const recontactPhoneCount = summary?.recontact_phone_leads || 0;
  const ratioNewCount = summary?.ratio_new_leads ?? newLeadsCount;
  const ratioRecontactCount = summary?.ratio_recontact_leads ?? recontactLeadsCount;
  const ratioTotalCount = ratioNewCount + ratioRecontactCount;

  const pct = (part: number, whole: number) => (whole > 0 ? (part / whole) * 100 : 0).toFixed(1);
  const fmtIsoDateVi = (iso: string) =>
    iso.length >= 10 && iso[4] === '-' && iso[7] === '-'
      ? `${iso.slice(8, 10)}/${iso.slice(5, 7)}/${iso.slice(0, 4)}`
      : iso;
  const fmtShortDateVi = (iso: string) =>
    iso.length >= 10 && iso[4] === '-' && iso[7] === '-'
      ? `${iso.slice(8, 10)}/${iso.slice(5, 7)}`
      : iso;

  const prevPeriod = summary?.previous_period;
  const prevRangeLabel = prevPeriod
    ? prevPeriod.start_date === prevPeriod.end_date
      ? fmtShortDateVi(prevPeriod.start_date)
      : `${fmtShortDateVi(prevPeriod.start_date)}–${fmtShortDateVi(prevPeriod.end_date)}`
    : '';

  const buildPeriodComparison = (current: number, previous?: number) => {
    if (previous === undefined) {
      return {
        trend: undefined as number | undefined,
        subtitle: 'So với kỳ trước: —',
        subtitleTone: 'neutral' as const,
        detail: '',
      };
    }
    const delta = current - previous;
    const trend = previous > 0 ? ((current - previous) / previous) * 100 : current === 0 ? 0 : undefined;
    const signedDelta = delta > 0 ? `+${delta.toLocaleString()}` : delta < 0 ? delta.toLocaleString() : '0';
    const subtitleTone: 'neutral' | 'positive' | 'negative' =
      delta > 0 ? 'positive' : delta < 0 ? 'negative' : 'neutral';
    const subtitle = `${signedDelta} so với kỳ trước`;
    const pctText = trend !== undefined ? `, ${trend > 0 ? '+' : ''}${trend.toFixed(1)}%` : '';
    const detail = `Kỳ trước${prevRangeLabel ? ` (${prevRangeLabel})` : ''}: ${previous.toLocaleString()} → ${current.toLocaleString()} (${signedDelta}${pctText})`;
    return { trend, subtitle, subtitleTone, detail };
  };

  const totalLeadsCmp = buildPeriodComparison(totalLeadsCount, prevPeriod?.total_leads);
  const newPhoneCmp = buildPeriodComparison(newPhoneCount, prevPeriod?.new_phone_leads);
  const recontactPhoneCmp = buildPeriodComparison(recontactPhoneCount, prevPeriod?.recontact_phone_leads);

  const visibleNavGroups = useMemo(
    () =>
      NAV_GROUPS.map((group) => ({
        ...group,
        items: group.items.filter((item) => canAccessTab(currentUser, item.id)),
      })).filter((group) => group.items.length > 0),
    [currentUser]
  );

  // Luôn ánh xạ về tab hợp lệ nếu activeTab không nằm trong danh sách được cấp quyền
  const effectiveTab: TabId =
    activeTab === 'profile' || canAccessTab(currentUser, activeTab)
      ? activeTab
      : userPerms.defaultTab;

  const toggleNavGroup = useCallback((groupId: NavGroupId) => {
    setOpenNavGroups((prev) => {
      const next = { ...prev, [groupId]: !prev[groupId] };
      try {
        localStorage.setItem(SIDEBAR_GROUPS_STORAGE_KEY, JSON.stringify(next));
      } catch {
        // Bỏ qua nếu trình duyệt chặn localStorage
      }
      return next;
    });
  }, []);

  // Tự động mở danh mục chứa trang hiện tại khi chuyển trang bằng URL/phím tắt
  useEffect(() => {
    const activeGroup = visibleNavGroups.find((g) => g.items.some((item) => item.id === effectiveTab));
    if (!activeGroup) return;
    setOpenNavGroups((prev) => {
      if (prev[activeGroup.id]) return prev;
      const next = { ...prev, [activeGroup.id]: true };
      try {
        localStorage.setItem(SIDEBAR_GROUPS_STORAGE_KEY, JSON.stringify(next));
      } catch {
        // ignore
      }
      return next;
    });
  }, [effectiveTab, visibleNavGroups]);

  // Bảo vệ toàn trang: nếu chưa đăng nhập -> hiển thị ngay trang Login (/login)
  if (!isAuthenticated || !currentUser) {
    return (
      <>
        <LoginPage onLoginSuccess={handleLoginSuccess} />
        <ToastHost />
      </>
    );
  }

  const displayName = currentUser.full_name || currentUser.username;

  return (
    <div className="min-h-screen bg-bg-page text-foreground flex">
      <a
        href="#main-content"
        className="skip-link fixed top-2 left-2 z-50 px-3 py-2 rounded-lg bg-eztech text-white text-xs font-semibold shadow-lg"
      >
        Chuyển đến nội dung chính
      </a>

      {/* 1. Backdrop on Mobile */}
      {isSidebarOpen && (
        <div
          className="fixed inset-0 bg-navy/40 z-30 lg:hidden backdrop-blur-sm transition-opacity"
          onClick={() => setIsSidebarOpen(false)}
          aria-hidden="true"
        />
      )}

      {/* 2. Left Sidebar Navigation (Fixed viewport height, never stretches on long pages) */}
      <aside
        aria-label="Thanh điều hướng chính"
        className={`fixed inset-y-0 left-0 z-40 w-64 h-screen max-h-screen bg-white border-r border-slate-200/80 flex flex-col overflow-hidden transition-transform duration-300 ease-in-out lg:translate-x-0 ${
          isSidebarOpen ? 'translate-x-0 shadow-2xl visible' : '-translate-x-full invisible lg:visible'
        }`}
      >
        {/* Brand / Logo Header */}
        <div className="shrink-0 h-16 px-4 border-b border-slate-100 flex items-center justify-between bg-white">
          <div className="flex items-center gap-2.5 min-w-0">
            <img
              src="/brand_ngang.png"
              alt="EzTech - Giải pháp dữ liệu cho doanh nghiệp"
              width={140}
              height={32}
              className="h-8 w-auto max-w-[148px] object-contain shrink-0 dark:brightness-125"
            />
            <div className="border-l border-slate-200 pl-2 shrink-0">
              <span className="text-[10px] font-bold text-navy uppercase tracking-wider block leading-tight">CRM</span>
              <span className="text-[9px] text-slate-400 font-medium block">Lead Analytics</span>
            </div>
          </div>
          <button
            type="button"
            onClick={() => setIsSidebarOpen(false)}
            aria-label="Đóng menu điều hướng"
            className="lg:hidden p-1.5 text-slate-400 hover:text-navy rounded-xl cursor-pointer shrink-0"
          >
            <X className="w-4 h-4" aria-hidden="true" />
          </button>
        </div>

        {/* Grouped Dropdown Navigation Menu */}
        <nav aria-label="Không gian làm việc" className="flex-1 min-h-0 px-3 py-3.5 space-y-2 overflow-y-auto custom-scrollbar">
          <p className="px-2.5 text-[10px] font-semibold uppercase tracking-[0.08em] text-slate-400">
            Danh mục chức năng
          </p>

          <div className="space-y-1.5">
            {visibleNavGroups.map((group) => {
              const GroupIcon = group.icon;
              const isOpen = !!openNavGroups[group.id];
              const hasActiveChild = group.items.some((item) => item.id === effectiveTab);
              const groupPanelId = `sidebar-group-${group.id}`;

              return (
                <div key={group.id} className="rounded-xl">
                  <button
                    type="button"
                    aria-expanded={isOpen}
                    aria-controls={groupPanelId}
                    onClick={() => toggleNavGroup(group.id)}
                    className={`group w-full flex items-center justify-between gap-2 px-2.5 py-2 rounded-xl text-[11px] font-bold uppercase tracking-wider transition-colors duration-150 cursor-pointer ${
                      hasActiveChild && !isOpen
                        ? 'bg-eztech-light/70 text-brand-600'
                        : hasActiveChild
                        ? 'text-navy hover:bg-slate-100/70'
                        : 'text-slate-500 hover:text-navy hover:bg-slate-100/70'
                    }`}
                  >
                    <span className="flex items-center gap-2 min-w-0">
                      <GroupIcon
                        aria-hidden="true"
                        className={`w-3.5 h-3.5 shrink-0 transition-colors ${
                          hasActiveChild ? 'text-brand-600' : 'text-slate-400 group-hover:text-brand-600'
                        }`}
                      />
                      <span className="truncate">{group.label}</span>
                    </span>
                    <span className="flex items-center gap-1.5 shrink-0">
                      {!isOpen && hasActiveChild && (
                        <span className="w-1.5 h-1.5 rounded-full bg-gold-500" aria-hidden="true" />
                      )}
                      <span className="text-[10px] font-mono font-semibold text-slate-400 px-1.5 py-0.5 rounded-md bg-slate-100">
                        {group.items.length}
                      </span>
                      <ChevronDown
                        aria-hidden="true"
                        className={`w-3.5 h-3.5 text-slate-400 transition-transform duration-200 motion-reduce:transition-none ${
                          isOpen ? 'rotate-0' : '-rotate-90'
                        }`}
                      />
                    </span>
                  </button>

                  <div
                    id={groupPanelId}
                    className={`grid transition-[grid-template-rows,opacity] duration-200 ease-out motion-reduce:transition-none ${
                      isOpen ? 'grid-rows-[1fr] opacity-100 mt-1' : 'grid-rows-[0fr] opacity-0 pointer-events-none'
                    }`}
                  >
                    <div className="overflow-hidden">
                      <div className="ml-3 pl-2.5 border-l border-slate-200/80 space-y-1 py-0.5">
                        {group.items.map((item) => {
                          const Icon = item.icon;
                          const isActive = effectiveTab === item.id;
                          return (
                            <button
                              key={item.id}
                              type="button"
                              tabIndex={isOpen ? undefined : -1}
                              aria-current={isActive ? 'page' : undefined}
                              onClick={() => {
                                if (item.url) {
                                  window.open(item.url, '_blank', 'noopener,noreferrer');
                                }
                                setActiveTab(item.id);
                                setIsSidebarOpen(false);
                              }}
                              className={`group relative w-full flex items-center justify-between px-3 py-2 rounded-xl text-xs transition-all duration-200 cursor-pointer active:scale-[0.985] ${
                                isActive
                                  ? 'gradient-brand text-white font-semibold shadow-md shadow-brand-500/20'
                                  : 'text-slate-600 font-medium hover:text-navy hover:bg-brand-50'
                              }`}
                            >
                              <div className="flex items-center gap-2.5 min-w-0">
                                <Icon
                                  aria-hidden="true"
                                  className={`w-4 h-4 shrink-0 transition-all duration-200 group-hover:scale-105 ${
                                    isActive ? 'text-gold-400' : 'text-slate-400 group-hover:text-brand-600'
                                  }`}
                                />
                                <span className="truncate">{item.label}</span>
                              </div>
                              {item.url ? (
                                <ExternalLink
                                  aria-hidden="true"
                                  className={`w-3.5 h-3.5 shrink-0 transition-colors ${isActive ? 'text-gold-400' : 'text-slate-400 group-hover:text-brand-600'}`}
                                />
                              ) : (
                                isActive && <div className="ez-nav-dot w-1.5 h-1.5 rounded-full bg-gold-400 shrink-0" aria-hidden="true" />
                              )}
                            </button>
                          );
                        })}
                      </div>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </nav>

        {/* Bottom User Summary in Sidebar (Always pinned to viewport bottom) */}
        <div className="shrink-0 p-3 border-t border-slate-100 bg-slate-50/50">
          <div className="p-2.5 bg-white border border-slate-200/80 rounded-xl shadow-card space-y-2">
            <button
              type="button"
              onClick={() => {
                setActiveTab('profile');
                setIsSidebarOpen(false);
              }}
              className="w-full flex items-center gap-2.5 text-left hover:opacity-90 transition-opacity cursor-pointer"
            >
              <div className="w-8 h-8 rounded-lg bg-navy text-gold text-xs font-bold flex items-center justify-center uppercase shrink-0">
                {displayName.slice(0, 2)}
              </div>
              <div className="flex-1 min-w-0">
                <span className="block text-xs font-semibold text-navy truncate">{displayName}</span>
                <span className="block text-[10px] font-medium text-slate-500 truncate">{userPerms.department}</span>
              </div>
            </button>
            <div className="flex items-center gap-1.5 pt-1.5 border-t border-slate-100">
              <button
                type="button"
                onClick={() => {
                  setActiveTab('profile');
                  setIsSidebarOpen(false);
                }}
                className="flex-1 py-1.5 px-2 text-[11px] font-medium text-slate-600 hover:text-eztech hover:bg-eztech-light rounded-lg flex items-center justify-center gap-1 transition-colors cursor-pointer"
              >
                <User className="w-3.5 h-3.5" aria-hidden="true" />
                <span>Trang cá nhân</span>
              </button>
              <button
                type="button"
                onClick={handleLogout}
                aria-label="Đăng xuất"
                title="Đăng xuất"
                className="py-1.5 px-2 text-[11px] font-medium text-rose-600 hover:bg-rose-50 rounded-lg flex items-center justify-center gap-1 transition-colors cursor-pointer"
              >
                <LogOut className="w-3.5 h-3.5" aria-hidden="true" />
              </button>
            </div>
          </div>
        </div>
      </aside>

      {/* 3. Main Content Area (Offset by fixed sidebar width on desktop) */}
      <div className="flex-1 min-w-0 flex flex-col min-h-screen lg:pl-64">
        {/* Top Header */}
        <header className="bg-white/90 backdrop-blur-md border-b border-slate-200/80 sticky top-0 z-20 h-16">
          <div className="px-4 sm:px-6 lg:px-8 h-full flex items-center justify-between max-w-[1440px] mx-auto w-full gap-2">
            {/* Left: Mobile hamburger & Active Tab Title */}
            <div className="flex items-center gap-3 min-w-0">
              <button
                type="button"
                onClick={() => setIsSidebarOpen(true)}
                aria-label="Mở menu điều hướng"
                aria-expanded={isSidebarOpen}
                className="lg:hidden p-2 text-slate-600 hover:text-navy hover:bg-slate-100 rounded-xl transition-colors cursor-pointer shrink-0"
              >
                <Menu className="w-5 h-5" aria-hidden="true" />
              </button>
              <div className="flex items-baseline gap-2.5 min-w-0">
                <h1 key={effectiveTab} className="ez-title-in text-base sm:text-lg font-bold text-navy tracking-tight truncate">
                  {TAB_TITLES[effectiveTab]}
                </h1>
              </div>
            </div>

            {/* Right: Overview refresh + Theme Toggle + User Profile Menu (Top-Right) */}
            <div className="flex items-center gap-2.5 shrink-0">
              {activeTab === 'overview' && canViewOverview && lastUpdated && (
                <span className="text-[11px] font-mono text-slate-400 hidden md:inline-block tabular-nums">
                  Cập nhật {format(lastUpdated, 'HH:mm')}
                </span>
              )}
              <ThemeToggle />
              {activeTab === 'overview' && canViewOverview && (
                <button
                  type="button"
                  onClick={handleRefreshOverview}
                  disabled={loading}
                  className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold bg-white hover:bg-brand-50 rounded-xl transition-all border border-slate-200/90 hover:border-brand-300 text-navy hover:text-brand-600 shadow-sm disabled:opacity-50 cursor-pointer active:scale-[0.97]"
                >
                  <RefreshCw className={`w-3.5 h-3.5 text-brand-500 ${loading ? 'animate-spin' : ''}`} aria-hidden="true" />
                  <span className="hidden sm:inline">Làm mới</span>
                </button>
              )}

              {/* Cụm Avatar + Tên nhân viên + Badge Phòng ban góc trên bên phải */}
              <div className="relative" ref={profileMenuRef}>
                <button
                  type="button"
                  onClick={() => setIsProfileMenuOpen((prev) => !prev)}
                  aria-expanded={isProfileMenuOpen}
                  aria-haspopup="menu"
                  className="flex items-center gap-2 pl-2 pr-2.5 py-1.5 bg-white hover:bg-slate-50 border border-slate-200/90 rounded-xl shadow-xs transition-all cursor-pointer"
                >
                  <div className="w-7 h-7 rounded-lg gradient-brand text-gold-400 text-[11px] font-bold flex items-center justify-center uppercase shrink-0">
                    {displayName.slice(0, 2)}
                  </div>
                  <div className="hidden sm:flex items-center gap-2 max-w-[220px]">
                    <span className="text-xs font-semibold text-navy truncate">{displayName}</span>
                    <span className={`text-[10px] font-semibold px-2 py-0.5 rounded-full border shrink-0 ${userPerms.badgeClass}`}>
                      {userPerms.department}
                    </span>
                  </div>
                  <ChevronDown className={`w-3.5 h-3.5 text-slate-400 transition-transform ${isProfileMenuOpen ? 'rotate-180' : ''}`} />
                </button>

                {isProfileMenuOpen && (
                  <div
                    role="menu"
                    className="absolute right-0 mt-2 w-64 bg-white rounded-2xl border border-slate-200 shadow-2xl py-2 z-50 divide-y divide-slate-100"
                  >
                    <div className="px-4 py-2.5">
                      <p className="text-xs font-bold text-navy truncate">{displayName}</p>
                      <div className="flex items-center gap-1.5 mt-1">
                        <span className={`text-[10px] font-semibold px-2 py-0.5 rounded-full border ${userPerms.badgeClass}`}>
                          {userPerms.department}
                        </span>
                        <span className="text-[11px] font-mono text-slate-400">
                          NV-{String(currentUser.id).padStart(3, '0')}
                        </span>
                      </div>
                    </div>

                    <div className="py-1">
                      <button
                        type="button"
                        role="menuitem"
                        onClick={() => setActiveTab('profile')}
                        className="w-full px-4 py-2 text-left text-xs font-medium text-slate-700 hover:bg-brand-50 hover:text-brand-600 flex items-center gap-2.5 transition-colors cursor-pointer"
                      >
                        <User className="w-4 h-4 text-brand-500" />
                        <span>Trang cá nhân & Quyền hạn</span>
                      </button>
                      <button
                        type="button"
                        role="menuitem"
                        onClick={() => {
                          setIsProfileMenuOpen(false);
                          setShowChangePw(true);
                        }}
                        className="w-full px-4 py-2 text-left text-xs font-medium text-slate-700 hover:bg-brand-50 hover:text-brand-600 flex items-center gap-2.5 transition-colors cursor-pointer"
                      >
                        <KeyRound className="w-4 h-4 text-slate-400" />
                        <span>Đổi mật khẩu nhanh</span>
                      </button>
                    </div>

                    <div className="pt-1">
                      <button
                        type="button"
                        role="menuitem"
                        onClick={handleLogout}
                        className="w-full px-4 py-2 text-left text-xs font-semibold text-rose-600 hover:bg-rose-50 flex items-center gap-2.5 transition-colors cursor-pointer"
                      >
                        <LogOut className="w-4 h-4" />
                        <span>Đăng xuất</span>
                      </button>
                    </div>
                  </div>
                )}
              </div>
            </div>
          </div>
        </header>

        {/* Content Body */}
        <main id="main-content" tabIndex={-1} className="flex-1 px-4 sm:px-6 lg:px-8 py-5 max-w-[1440px] w-full mx-auto focus:outline-none">
          <div key={effectiveTab} className="ez-page-stage space-y-4">
            <ErrorBoundary resetKey={effectiveTab}>
              <Suspense fallback={<TabLoadingFallback />}>
                {effectiveTab === 'profile' ? (
                  <ProfilePage
                    user={currentUser}
                    onUserUpdated={(u) => {
                      setCurrentUser(u);
                      updateStoredUser(u);
                    }}
                    onNavigateTab={(t) => setActiveTab(t)}
                    onLogout={handleLogout}
                  />
                ) : effectiveTab === 'facebook' && canAccessTab(currentUser, 'facebook') ? (
                  <FacebookDashboard />
                ) : effectiveTab === 'tiktok' && canAccessTab(currentUser, 'tiktok') ? (
                  <TikTokDashboard />
                ) : effectiveTab === 'work_report' && canAccessTab(currentUser, 'work_report') ? (
                  <WorkReportDashboard />
                ) : effectiveTab === 'deals' && canAccessTab(currentUser, 'deals') ? (
                  <DealWinDashboard />
                ) : effectiveTab === 'remind' && canAccessTab(currentUser, 'remind') ? (
                  <RemindLeadTable pagesList={pagesList} zaloPages={zaloPages} />
                ) : effectiveTab === 'bot' && canAccessTab(currentUser, 'bot') ? (
                  <BulkMessengerDashboard />
                ) : effectiveTab === 'data_export' && canAccessTab(currentUser, 'data_export') ? (
                  <DataExportDashboard />
                ) : effectiveTab === 'add_friend' && canAccessTab(currentUser, 'add_friend') ? (
                  <AutoAddFriendDashboard />
                ) : effectiveTab === 'gas_tool' && canAccessTab(currentUser, 'gas_tool') ? (
                  <AppScriptTool />
                ) : effectiveTab === 'ai_assistant' && canAccessTab(currentUser, 'ai_assistant') ? (
                  <AiAssistantDashboard />
                ) : effectiveTab === 'btvn_grader' && canAccessTab(currentUser, 'btvn_grader') ? (
                  <BtvnGraderDashboard />
                ) : effectiveTab === 'invoice' && canAccessTab(currentUser, 'invoice') ? (
                  <div className="bg-white rounded-2xl border border-slate-200/80 shadow-card p-6 sm:p-10 max-w-2xl mx-auto my-8 text-center space-y-5">
                    <div className="w-16 h-16 rounded-2xl bg-amber-500/10 border border-amber-200/90 text-amber-600 flex items-center justify-center mx-auto shadow-sm">
                      <Receipt className="w-8 h-8" aria-hidden="true" />
                    </div>
                    <div className="space-y-1.5">
                      <h2 className="text-lg font-bold text-navy">Hệ Thống Xuất Hoá Đơn Điện Tử</h2>
                      <p className="text-xs text-slate-500 max-w-md mx-auto leading-relaxed">
                        Trang xuất hoá đơn Google Apps Script được khởi chạy trong cửa sổ riêng để bảo đảm đầy đủ tính năng và bảo mật tài khoản.
                      </p>
                    </div>
                    <div className="pt-2">
                      <a
                        href={INVOICE_SCRIPT_URL}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="inline-flex items-center gap-2 px-6 py-3 bg-gradient-to-r from-amber-600 to-amber-700 hover:from-amber-700 hover:to-amber-800 text-white text-xs font-semibold rounded-xl shadow-md transition-all cursor-pointer hover:shadow-lg"
                      >
                        <Receipt className="w-4 h-4" aria-hidden="true" />
                        <span>Mở Trang Xuất Hoá Đơn (Google Apps Script)</span>
                        <ExternalLink className="w-4 h-4" aria-hidden="true" />
                      </a>
                    </div>
                  </div>
                ) : effectiveTab === 'overview' && canAccessTab(currentUser, 'overview') ? (
                  <>
                    {/* Compact Inline Filter Toolbar */}
                    <div className="bg-white rounded-2xl border border-slate-200/80 shadow-card px-5 py-3.5 flex flex-wrap items-center justify-between gap-3">
                      {/* Date Range Group */}
                      <div className="flex flex-wrap items-center gap-2">
                        <div className="flex items-center gap-1.5 text-xs font-semibold text-navy mr-1">
                          <Calendar className="w-3.5 h-3.5 text-eztech" aria-hidden="true" />
                          <span>Kỳ báo cáo</span>
                        </div>
                        <div className="flex items-center gap-1.5 bg-slate-50 border border-slate-200/80 rounded-lg px-2.5 py-1">
                          <input
                            type="date"
                            aria-label="Từ ngày"
                            value={startDate}
                            max={endDate}
                            onChange={(e) => setStartDate(e.target.value)}
                            className="bg-transparent text-xs font-mono font-medium text-navy focus:outline-none cursor-pointer tabular-nums"
                          />
                          <span className="text-slate-400 text-xs" aria-hidden="true">→</span>
                          <input
                            type="date"
                            aria-label="Đến ngày"
                            value={endDate}
                            min={startDate}
                            onChange={(e) => setEndDate(e.target.value)}
                            className="bg-transparent text-xs font-mono font-medium text-navy focus:outline-none cursor-pointer tabular-nums"
                          />
                        </div>
                      </div>

                      {/* Page & Employee Selectors */}
                      <div className="flex flex-wrap items-center gap-2.5 flex-1 sm:justify-end">
                        <div className="flex items-center gap-2 min-w-[220px] flex-1 sm:flex-initial">
                          <label htmlFor="overview-page-select" className="text-[11px] font-medium text-slate-400 uppercase tracking-wider shrink-0">
                            Page
                          </label>
                          <select
                            id="overview-page-select"
                            value={pageId}
                            onChange={(e) => setPageId(e.target.value)}
                            className="w-full px-2.5 py-1.5 border border-slate-200/90 rounded-lg text-xs font-medium bg-white hover:border-slate-300 focus:outline-none focus:ring-2 focus:ring-eztech/15 focus:border-eztech transition-all text-navy cursor-pointer"
                          >
                            <option value="">Tất cả page nguồn lead (trừ Zalo)</option>
                            <optgroup label="Nguồn lead">
                              {pagesList.filter((pg) => !zaloPages.includes(pg)).map((pg) => (
                                <option key={pg} value={pg}>{pg}</option>
                              ))}
                            </optgroup>
                            {zaloPages.length > 0 && (
                              <optgroup label="Zalo (chăm sóc)">
                                {zaloPages.map((pg) => (
                                  <option key={pg} value={pg}>{pg}</option>
                                ))}
                              </optgroup>
                            )}
                          </select>
                        </div>

                        <div className="flex items-center gap-2 min-w-[190px] flex-1 sm:flex-initial">
                          <label htmlFor="overview-emp-select" className="text-[11px] font-medium text-slate-400 uppercase tracking-wider shrink-0">
                            Nhân sự
                          </label>
                          <select
                            id="overview-emp-select"
                            value={employee}
                            onChange={(e) => setEmployee(e.target.value)}
                            className="w-full px-2.5 py-1.5 border border-slate-200/90 rounded-lg text-xs font-medium bg-white hover:border-slate-300 focus:outline-none focus:ring-2 focus:ring-eztech/15 focus:border-eztech transition-all text-navy cursor-pointer"
                          >
                            <option value="">Tất cả nhân viên</option>
                            {employeesList.map((emp) => (
                              <option key={emp} value={emp}>{emp}</option>
                            ))}
                          </select>
                        </div>
                      </div>
                    </div>

                    <ErrorBanner message={overviewError} onRetry={handleRefreshOverview} />

                    {(hasCrossFilter || (loading && !!summary)) && (
                      <div className="ez-tab-panel bg-white rounded-xl border border-eztech-border/80 shadow-card px-4 py-2.5 flex flex-wrap items-center justify-between gap-2">
                        <div className="flex flex-wrap items-center gap-2 text-xs">
                          <span className="text-[11px] font-semibold uppercase tracking-wider text-slate-400 mr-1">
                            Đang lọc tương tác:
                          </span>
                          {selectedDate && (
                            <button
                              type="button"
                              onClick={() => setSelectedDate(null)}
                              className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-eztech-light text-eztech border border-eztech-border font-semibold hover:bg-eztech-border/50 transition-colors cursor-pointer"
                            >
                              <span>Ngày: <span className="font-mono">{fmtIsoDateVi(selectedDate)}</span></span>
                              <X className="w-3 h-3" aria-hidden="true" />
                            </button>
                          )}
                          {selectedLeadType && (
                            <button
                              type="button"
                              onClick={() => setSelectedLeadType(null)}
                              className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-eztech-light text-eztech border border-eztech-border font-semibold hover:bg-eztech-border/50 transition-colors cursor-pointer"
                            >
                              <span>Loại: {selectedLeadType === 'new' ? 'Lead Mới' : 'Contact Lại'}</span>
                              <X className="w-3 h-3" aria-hidden="true" />
                            </button>
                          )}
                          {onlyPhone && (
                            <button
                              type="button"
                              onClick={() => setOnlyPhone(false)}
                              className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-gold-light text-gold-dark border border-gold-border font-semibold hover:bg-gold-tint-strong transition-colors cursor-pointer"
                            >
                              <span>Chỉ có SĐT</span>
                              <X className="w-3 h-3" aria-hidden="true" />
                            </button>
                          )}
                          {selectedChartEmployee && (
                            <button
                              type="button"
                              onClick={() => setSelectedChartEmployee(null)}
                              className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-eztech-light text-eztech border border-eztech-border font-semibold hover:bg-eztech-border/50 transition-colors cursor-pointer"
                            >
                              <span>Nhân sự: {selectedChartEmployee}</span>
                              <X className="w-3 h-3" aria-hidden="true" />
                            </button>
                          )}
                          {selectedTagCategory && (
                            <button
                              type="button"
                              onClick={() => setSelectedTagCategory(null)}
                              className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-eztech-light text-eztech border border-eztech-border font-semibold hover:bg-eztech-border/50 transition-colors cursor-pointer"
                            >
                              <span>Phân loại: {selectedTagCategory}</span>
                              <X className="w-3 h-3" aria-hidden="true" />
                            </button>
                          )}
                        </div>

                        <div className="flex items-center gap-3 ml-auto">
                          {loading && !!summary && (
                            <span className="inline-flex items-center gap-1.5 text-[11px] font-medium text-slate-400">
                              <RefreshCw className="w-3 h-3 animate-spin text-eztech" aria-hidden="true" />
                              Đang lọc...
                            </span>
                          )}
                          {hasCrossFilter && (
                            <button
                              type="button"
                              onClick={clearCrossFilters}
                              className="text-xs font-semibold text-rose-600 hover:text-rose-700 hover:bg-rose-50 px-2.5 py-1 rounded-lg transition-colors cursor-pointer"
                            >
                              Bỏ tất cả lọc
                            </button>
                          )}
                        </div>
                      </div>
                    )}

                    {loading && !summary ? (
                      <div className="flex items-center justify-center py-24">
                        <div className="flex flex-col items-center gap-3">
                          <div className="animate-spin rounded-full h-8 w-8 border-2 border-slate-200 border-t-brand-500" />
                          <p className="text-xs font-medium text-slate-400">Đang đồng bộ dữ liệu...</p>
                        </div>
                      </div>
                    ) : (
                      <>
                        {/* KPIs - 6 cards: Unified EzTech Navy/Blue for Leads & EzTech Gold for Phone Conversions */}
                        <div className="ez-kpi-grid grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6 gap-3.5">
                          <KpiCard
                            title="Tổng Lead"
                            value={totalLeadsCount.toLocaleString()}
                            subtitle={totalLeadsCmp.subtitle}
                            subtitleTone={totalLeadsCmp.subtitleTone}
                            trend={totalLeadsCmp.trend}
                            icon={<Users className="w-4 h-4" />}
                            color="navy"
                            onClick={() => {
                              setSelectedLeadType(null);
                              setOnlyPhone(false);
                            }}
                            tooltip={
                              totalLeadsCmp.detail
                                ? `${totalLeadsCmp.detail} • Nhấn để bỏ lọc nhóm`
                                : 'Hiển thị toàn bộ Lead Mới & Contact Lại (nhấn để bỏ lọc nhóm)'
                            }
                          />
                          <KpiCard
                            title="Lead Mới"
                            value={newLeadsCount.toLocaleString()}
                            subtitle={`${pct(newLeadsCount, totalLeadsCount)}% tổng lead`}
                            icon={<UserPlus className="w-4 h-4" />}
                            color="blue"
                            active={selectedLeadType === 'new' && !onlyPhone}
                            onClick={() => {
                              if (selectedLeadType === 'new' && !onlyPhone) {
                                setSelectedLeadType(null);
                              } else {
                                setSelectedLeadType('new');
                                setOnlyPhone(false);
                              }
                            }}
                            tooltip="Nhấn để lọc chỉ Lead Mới"
                          />
                          <KpiCard
                            title="Lead Contact Lại"
                            value={recontactLeadsCount.toLocaleString()}
                            subtitle={`${pct(recontactLeadsCount, totalLeadsCount)}% tổng lead`}
                            icon={<UserCheck className="w-4 h-4" />}
                            color="blue"
                            active={selectedLeadType === 'recontact' && !onlyPhone}
                            onClick={() => {
                              if (selectedLeadType === 'recontact' && !onlyPhone) {
                                setSelectedLeadType(null);
                              } else {
                                setSelectedLeadType('recontact');
                                setOnlyPhone(false);
                              }
                            }}
                            tooltip="Nhấn để lọc chỉ Lead Contact Lại"
                          />
                          <KpiCard
                            title="SĐT Mới"
                            value={newPhoneCount.toLocaleString()}
                            subtitle={newPhoneCmp.subtitle}
                            subtitleTone={newPhoneCmp.subtitleTone}
                            trend={newPhoneCmp.trend}
                            icon={<PhoneCall className="w-4 h-4" />}
                            color="gold"
                            active={selectedLeadType === 'new' && onlyPhone}
                            onClick={() => {
                              if (selectedLeadType === 'new' && onlyPhone) {
                                setSelectedLeadType(null);
                                setOnlyPhone(false);
                              } else {
                                setSelectedLeadType('new');
                                setOnlyPhone(true);
                              }
                            }}
                            tooltip={
                              newPhoneCmp.detail
                                ? `${newPhoneCmp.detail} • Nhấn để lọc chỉ Lead Mới có SĐT`
                                : 'Nhấn để lọc chỉ Lead Mới có SĐT'
                            }
                          />
                          <KpiCard
                            title="SĐT Contact Lại"
                            value={recontactPhoneCount.toLocaleString()}
                            subtitle={recontactPhoneCmp.subtitle}
                            subtitleTone={recontactPhoneCmp.subtitleTone}
                            trend={recontactPhoneCmp.trend}
                            icon={<PhoneForwarded className="w-4 h-4" />}
                            color="gold"
                            active={selectedLeadType === 'recontact' && onlyPhone}
                            onClick={() => {
                              if (selectedLeadType === 'recontact' && onlyPhone) {
                                setSelectedLeadType(null);
                                setOnlyPhone(false);
                              } else {
                                setSelectedLeadType('recontact');
                                setOnlyPhone(true);
                              }
                            }}
                            tooltip={
                              recontactPhoneCmp.detail
                                ? `${recontactPhoneCmp.detail} • Nhấn để lọc chỉ Lead Contact Lại có SĐT`
                                : 'Nhấn để lọc chỉ Lead Contact Lại có SĐT'
                            }
                          />
                          <KpiCard
                            title="SĐT / Tạo mới"
                            value={`${pct(newPhoneCount, newLeadsCount)}%`}
                            subtitle={`${newPhoneCount.toLocaleString()} / ${newLeadsCount.toLocaleString()} lead mới`}
                            icon={<Percent className="w-4 h-4" />}
                            color="gold"
                            highlight={true}
                            tooltip="Tỉ lệ chuyển đổi SĐT trên tổng Lead Mới trong phạm vi đang lọc"
                          />
                        </div>

                        {/* Charts row */}
                        <div className="grid grid-cols-1 lg:grid-cols-4 gap-4">
                          <div className="lg:col-span-3">
                            <TrendChart
                              data={trend}
                              selectedDate={selectedDate}
                              onSelectDate={setSelectedDate}
                            />
                          </div>
                          <div className="lg:col-span-1">
                            <RatioChart
                              newLeads={ratioNewCount}
                              recontactLeads={ratioRecontactCount}
                              totalLeads={ratioTotalCount}
                              newPhoneLeads={newPhoneCount}
                              selectedLeadType={selectedLeadType}
                              onSelectLeadType={setSelectedLeadType}
                            />
                          </div>
                        </div>

                        {/* Additional Charts Row */}
                        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
                          <StatsPieChart
                            title="Lead Mới / Nhân viên"
                            stats={summary?.new_leads_employee_stats}
                            selectedKey={selectedChartEmployee}
                            onSelectKey={setSelectedChartEmployee}
                          />
                          <StatsPieChart
                            title={
                              phoneCategoryFilter === 'new'
                                ? 'SĐT Mới / Lead Other & Đào tạo'
                                : phoneCategoryFilter === 'recontact'
                                ? 'SĐT Contact lại / Lead Other & Đào tạo'
                                : 'SĐT thu được / Lead Other & Đào tạo'
                            }
                            stats={
                              phoneCategoryFilter === 'new'
                                ? summary?.new_phone_tag_stats
                                : phoneCategoryFilter === 'recontact'
                                ? summary?.recontact_phone_tag_stats
                                : summary?.phone_tag_stats
                            }
                            unit="SĐT"
                            selectedKey={onlyPhone ? selectedTagCategory : null}
                            onSelectKey={(tag) => {
                              if (!tag || (selectedTagCategory === tag && onlyPhone)) {
                                setSelectedTagCategory(null);
                                setOnlyPhone(false);
                              } else {
                                setSelectedTagCategory(tag);
                                setOnlyPhone(true);
                                if (phoneCategoryFilter !== 'all') {
                                  setSelectedLeadType(phoneCategoryFilter);
                                }
                              }
                            }}
                            headerAction={
                              <select
                                aria-label="Lọc phân loại SĐT"
                                value={phoneCategoryFilter}
                                onChange={(e) => setPhoneCategoryFilter(e.target.value as 'all' | 'new' | 'recontact')}
                                className="text-[11px] font-semibold text-eztech bg-eztech-light border border-eztech-border rounded-lg px-2 py-1 focus:outline-none focus:ring-2 focus:ring-eztech/20 cursor-pointer hover:bg-eztech-border/50 transition-colors tabular-nums"
                              >
                                <option value="all">Tổng SĐT{summary ? ` (${summary.phone_leads})` : ''}</option>
                                <option value="new">SĐT Mới{summary ? ` (${summary.new_phone_leads})` : ''}</option>
                                <option value="recontact">SĐT Contact lại{summary ? ` (${summary.recontact_phone_leads})` : ''}</option>
                              </select>
                            }
                            colorMap={TAG_PIE_COLOR_MAP}
                          />
                          <StatsPieChart
                            title="Tổng Lead / Lead Other & Đào tạo"
                            stats={summary?.tag_stats}
                            selectedKey={selectedTagCategory}
                            onSelectKey={(tag) => {
                              if (!tag || (selectedTagCategory === tag && !onlyPhone)) {
                                setSelectedTagCategory(null);
                              } else {
                                setSelectedTagCategory(tag);
                                setOnlyPhone(false);
                              }
                            }}
                            colorMap={TAG_PIE_COLOR_MAP}
                          />
                        </div>

                        {/* AI Đánh giá Hiệu suất & Insight hằng ngày */}
                        <Suspense fallback={null}>
                          <AiDailyReviewCard />
                        </Suspense>

                        {/* Table */}
                        <LeadTable
                          leads={leads}
                          totalLeads={totalLeads}
                          page={page}
                          pageSize={pageSize}
                          loadingPage={loadingPage}
                          onPageChange={loadLeadsPage}
                        />
                      </>
                    )}
                  </>
                ) : null}
              </Suspense>
            </ErrorBoundary>
          </div>
        </main>
      </div>

      {/* Modal đổi mật khẩu */}
      {showChangePw && (
        <Suspense fallback={null}>
          <ChangePasswordModal
            isOpen={showChangePw}
            onClose={() => setShowChangePw(false)}
            onUserUpdated={(u) => {
              setCurrentUser(u);
              updateStoredUser(u);
            }}
          />
        </Suspense>
      )}

      <ToastHost />
    </div>
  );
}

export default App;
