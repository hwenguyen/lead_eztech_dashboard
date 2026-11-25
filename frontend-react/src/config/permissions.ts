import type { AuthUser } from '../services/api';

export type DepartmentName = 'Admin' | 'Consultant' | 'Marketing' | 'Quản lý lớp học';

export type DataScopeType = 'all' | 'personal';

export type AppTabId =
  | 'overview'
  | 'facebook'
  | 'tiktok'
  | 'work_report'
  | 'remind'
  | 'deals'
  | 'bot'
  | 'data_export'
  | 'add_friend'
  | 'gas_tool'
  | 'invoice'
  | 'ai_assistant'
  | 'btvn_grader';

export const LAST_LOGIN_STORAGE_KEY = 'last_login_employee';

export const ALL_APP_TABS: AppTabId[] = [
  'overview',
  'facebook',
  'tiktok',
  'work_report',
  'remind',
  'deals',
  'gas_tool',
  'invoice',
  'bot',
  'data_export',
  'add_friend',
  'ai_assistant',
  'btvn_grader',
];

export const CONSULTANT_TABS: AppTabId[] = [
  'work_report',
  'remind',
  'deals',
  'gas_tool',
  'ai_assistant',
  'invoice',
];

export const MARKETING_TABS: AppTabId[] = [
  'overview',
  'facebook',
  'tiktok',
  ...CONSULTANT_TABS,
];

export const TAB_LABELS: Record<AppTabId, string> = {
  overview: 'Tổng quan & Chỉ số',
  facebook: 'Facebook Analytics',
  tiktok: 'TikTok Analytics',
  work_report: 'Báo cáo công việc',
  remind: 'Chăm sóc Lead',
  deals: 'Deal Win',
  gas_tool: 'Nhập Deal & Công Nợ',
  invoice: 'Xuất hoá đơn',
  bot: 'Bot Gửi Tin',
  data_export: 'Query & Xuất Excel',
  add_friend: 'Kết Bạn Tự Động',
  ai_assistant: 'Trợ Lý AI',
  btvn_grader: 'Chấm BTVN (AI)',
};

export interface DepartmentPermissionConfig {
  department: DepartmentName;
  allowedTabs: AppTabId[];
  defaultTab: AppTabId;
  moduleScopes: Partial<Record<AppTabId, DataScopeType>>;
  scopeSummary: string;
  badgeClass: string;
}

const buildScopeMap = (tabs: AppTabId[], scope: DataScopeType): Partial<Record<AppTabId, DataScopeType>> => {
  const out: Partial<Record<AppTabId, DataScopeType>> = {};
  tabs.forEach((t) => {
    out[t] = scope;
  });
  return out;
};

export const DEPARTMENT_PERMISSIONS: Record<DepartmentName, DepartmentPermissionConfig> = {
  Admin: {
    department: 'Admin',
    allowedTabs: ALL_APP_TABS,
    defaultTab: 'overview',
    moduleScopes: buildScopeMap(ALL_APP_TABS, 'all'),
    scopeSummary: 'Toàn quyền hệ thống (Admin): Truy cập đầy đủ 13 chức năng và xem toàn bộ dữ liệu tất cả nhân viên.',
    badgeClass: 'bg-amber-100 text-amber-800 border-amber-300',
  },
  Consultant: {
    department: 'Consultant',
    allowedTabs: CONSULTANT_TABS,
    defaultTab: 'work_report',
    moduleScopes: buildScopeMap(CONSULTANT_TABS, 'personal'),
    scopeSummary: 'Chỉ dữ liệu cá nhân: Chỉ xem, lọc và thao tác trên dữ liệu gắn với chính bạn trên cả 6 trang nghiệp vụ.',
    badgeClass: 'bg-blue-50 text-blue-700 border-blue-200',
  },
  Marketing: {
    department: 'Marketing',
    allowedTabs: MARKETING_TABS,
    defaultTab: 'overview',
    moduleScopes: {
      overview: 'all',
      facebook: 'all',
      tiktok: 'all',
      ...buildScopeMap(CONSULTANT_TABS, 'personal'),
    },
    scopeSummary: 'Xem toàn bộ dữ liệu tại các trang Marketing (Tổng quan, Facebook, TikTok); chỉ xem dữ liệu cá nhân tại 6 trang nghiệp vụ Consultant.',
    badgeClass: 'bg-purple-50 text-purple-700 border-purple-200',
  },
  'Quản lý lớp học': {
    department: 'Quản lý lớp học',
    allowedTabs: CONSULTANT_TABS,
    defaultTab: 'work_report',
    moduleScopes: buildScopeMap(CONSULTANT_TABS, 'all'),
    scopeSummary: 'Full dữ liệu tất cả nhân viên trên cả 6 trang nghiệp vụ được phân quyền (hỗ trợ bộ lọc theo từng nhân viên).',
    badgeClass: 'bg-emerald-50 text-emerald-700 border-emerald-200',
  },
};

export function stripVnAccents(input?: string | null): string {
  if (!input) return '';
  return input
    .normalize('NFC')
    .trim()
    .toLowerCase()
    .replace(/đ/g, 'd')
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/\s+/g, ' ')
    .trim();
}

export function resolveDepartmentName(rawDept?: string | null, role?: string | null): DepartmentName {
  if (role?.toLowerCase() === 'admin') return 'Admin';
  const clean = stripVnAccents(rawDept);
  if (clean === 'admin') return 'Admin';
  if (clean === 'marketing') return 'Marketing';
  if (clean === 'quan ly lop hoc' || clean === 'quan ly lop') return 'Quản lý lớp học';
  return 'Consultant';
}

export function getEffectivePermissions(user: AuthUser | null | undefined) {
  if (!user) {
    return {
      department: 'Consultant' as DepartmentName,
      isAdmin: false,
      allowedTabs: [] as AppTabId[],
      defaultTab: 'work_report' as AppTabId,
      moduleScopes: {} as Partial<Record<AppTabId, DataScopeType>>,
      scopeSummary: '',
      badgeClass: DEPARTMENT_PERMISSIONS.Consultant.badgeClass,
    };
  }

  const dept = resolveDepartmentName(user.department, user.role);
  const fallback = DEPARTMENT_PERMISSIONS[dept];
  const isAdmin = dept === 'Admin' || user.role === 'admin';

  const allowedTabs: AppTabId[] =
    user.allowed_tabs && user.allowed_tabs.length > 0
      ? (user.allowed_tabs.filter((t): t is AppTabId => ALL_APP_TABS.includes(t as AppTabId)))
      : fallback.allowedTabs;

  const defaultTab: AppTabId =
    user.default_tab && ALL_APP_TABS.includes(user.default_tab as AppTabId)
      ? (user.default_tab as AppTabId)
      : fallback.defaultTab;

  const moduleScopes: Partial<Record<AppTabId, DataScopeType>> =
    user.module_scopes && Object.keys(user.module_scopes).length > 0
      ? (user.module_scopes as Partial<Record<AppTabId, DataScopeType>>)
      : fallback.moduleScopes;

  return {
    department: dept,
    isAdmin,
    allowedTabs: isAdmin ? ALL_APP_TABS : allowedTabs,
    defaultTab,
    moduleScopes: isAdmin ? buildScopeMap(ALL_APP_TABS, 'all') : moduleScopes,
    scopeSummary: user.scope_summary || fallback.scopeSummary,
    badgeClass: fallback.badgeClass,
  };
}

export function canAccessTab(user: AuthUser | null | undefined, tabId: AppTabId): boolean {
  if (!user) return false;
  const perms = getEffectivePermissions(user);
  return perms.isAdmin || perms.allowedTabs.includes(tabId);
}

export function getTabDataScope(user: AuthUser | null | undefined, tabId: AppTabId): DataScopeType {
  if (!user) return 'personal';
  const perms = getEffectivePermissions(user);
  if (perms.isAdmin) return 'all';
  return perms.moduleScopes[tabId] || 'personal';
}
