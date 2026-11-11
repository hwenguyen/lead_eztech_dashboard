import axios from 'axios';

// Client In-Memory & Session Cache: Chuyển tab & F5 tức thì (<0.01s), giảm 95% request, tiết kiệm tối đa Neon Egress
const _CLIENT_CACHE = new Map<string, { time: number; data: any }>();
const CLIENT_CACHE_TTL = 5 * 60 * 1000; // 5 phút
const SESSION_CACHE_PREFIX = 'ez_cache_';

export const clearClientApiCache = () => {
  _CLIENT_CACHE.clear();
  try {
    const keysToRemove: string[] = [];
    for (let i = 0; i < sessionStorage.length; i++) {
      const k = sessionStorage.key(i);
      if (k && k.startsWith(SESSION_CACHE_PREFIX)) {
        keysToRemove.push(k);
      }
    }
    keysToRemove.forEach(k => sessionStorage.removeItem(k));
  } catch (e) {
    // ignore storage error
  }
};

// Get API URL from env, or default to relative /api if deployed together
let API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000/api';
// Đảm bảo URL luôn có đuôi /api
if (import.meta.env.VITE_API_URL && !API_BASE_URL.endsWith('/api')) {
  API_BASE_URL = `${API_BASE_URL.replace(/\/$/, '')}/api`;
}

const apiClient = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
});

// Tự động gắn Bearer token vào Header Authorization
apiClient.interceptors.request.use((config) => {
  const token = localStorage.getItem('eztech_auth_token') || sessionStorage.getItem('eztech_auth_token');
  if (token && config.headers) {
    config.headers.Authorization = 'Bearer ' + token;
  }
  return config;
});

// Bắt lỗi 401 Unauthorized để yêu cầu đăng nhập lại & Tự động xóa cache khi có thay đổi dữ liệu (POST/PUT/DELETE)
apiClient.interceptors.response.use(
  (response) => {
    const method = response.config.method?.toLowerCase();
    if (method && ['post', 'put', 'delete', 'patch'].includes(method)) {
      clearClientApiCache();
    }
    return response;
  },
  (error) => {
    if (error.response?.status === 401 && !error.config?.url?.includes('/auth/login')) {
      localStorage.removeItem('eztech_auth_token');
      sessionStorage.removeItem('eztech_auth_token');
      localStorage.removeItem('eztech_auth_user');
      sessionStorage.removeItem('eztech_auth_user');
      window.dispatchEvent(new Event('auth_unauthorized'));
    }
    return Promise.reject(error);
  }
);


// Bọc apiClient.get với in-memory cache tự động cho toàn bộ dashboard
const originalGet = apiClient.get.bind(apiClient);
apiClient.get = (async (url: string, config?: any): Promise<any> => {
  const isNoCache = config?.params?.bypass_cache || config?.headers?.['Cache-Control'] === 'no-cache';
  const shouldSkip = isNoCache || url.includes('/broadcast/status') || url.includes('/auth/me') || url.includes('/health');
  if (shouldSkip) {
    return originalGet(url, config);
  }

  const paramEntries = Object.entries(config?.params || {}).filter(([_, v]) => v !== undefined && v !== null);
  paramEntries.sort(([a], [b]) => a.localeCompare(b));
  const paramStr = paramEntries.map(([k, v]) => `${k}=${v}`).join('&');
  const cacheKey = `${url}?${paramStr}`;
  const now = Date.now();

  // 1. Kiểm tra RAM cache
  if (_CLIENT_CACHE.has(cacheKey)) {
    const entry = _CLIENT_CACHE.get(cacheKey)!;
    if (now - entry.time < CLIENT_CACHE_TTL) {
      return {
        data: entry.data,
        status: 200,
        statusText: 'OK (from memory cache)',
        headers: {},
        config: config || {},
      };
    }
    _CLIENT_CACHE.delete(cacheKey);
  }

  // 2. Kiểm tra sessionStorage (giữ cache ngay cả khi người dùng F5 reload hoặc mở tab mới trong cùng session!)
  try {
    const sessionRaw = sessionStorage.getItem(SESSION_CACHE_PREFIX + cacheKey);
    if (sessionRaw) {
      const parsed = JSON.parse(sessionRaw);
      if (now - parsed.time < CLIENT_CACHE_TTL) {
        _CLIENT_CACHE.set(cacheKey, parsed);
        return {
          data: parsed.data,
          status: 200,
          statusText: 'OK (from session cache)',
          headers: {},
          config: config || {},
        };
      }
      sessionStorage.removeItem(SESSION_CACHE_PREFIX + cacheKey);
    }
  } catch (e) {
    // ignore
  }

  const res = await originalGet(url, config);
  if (res && res.status === 200) {
    const entry = { time: now, data: res.data };
    _CLIENT_CACHE.set(cacheKey, entry);
    try {
      sessionStorage.setItem(SESSION_CACHE_PREFIX + cacheKey, JSON.stringify(entry));
    } catch (e) {
      // ignore
    }
  }
  return res;
}) as any;

export interface SummaryData {
  new_leads: number;
  recontact_leads: number;
  total_leads: number;
  phone_leads: number;
  new_phone_leads: number;
  recontact_phone_leads: number;
  new_leads_employee_stats?: Record<string, number>;
  phone_leads_employee_stats?: Record<string, number>;
  tag_stats?: Record<string, number>;
  phone_tag_stats?: Record<string, number>;
  new_phone_tag_stats?: Record<string, number>;
  recontact_phone_tag_stats?: Record<string, number>;
}

export interface TrendData {
  date: string;
  new_leads: number;
  recontact_leads: number;
  phone_leads: number;
}

export interface TagEvent {
  tag: string;
  action: string;
  tagged_at: string;
  editor?: string;
}

export interface Lead {
  id: number;
  customer_id: string;
  name?: string;
  phone_number?: string;
  page_id: string;
  first_created_at: string | null;
  status_tag?: string;
  tag_timeline?: TagEvent[];
  assigned_users?: string;
  messages?: string;
  is_contacted: boolean;
  is_new: boolean;
  pancake_url?: string;
  post_id?: string;
  post_url?: string;
}

export const fetchSummary = async (startDate: string, endDate: string, pageId?: string, employee?: string) => {
  const params: any = { start_date: startDate, end_date: endDate };
  if (pageId) params.page_id = pageId;
  if (employee) params.employee = employee;
  const res = await apiClient.get<SummaryData>('/metrics/summary', { params });
  return res.data;
};

export const fetchTrend = async (startDate: string, endDate: string, pageId?: string, employee?: string) => {
  const params: any = { start_date: startDate, end_date: endDate };
  if (pageId) params.page_id = pageId;
  if (employee) params.employee = employee;
  const res = await apiClient.get<{data: TrendData[]}>('/metrics/trend', { params });
  return res.data.data;
};

export const fetchLeads = async (pageId?: string, employee?: string, startDate?: string, endDate?: string, page: number = 1, size: number = 50) => {
  const params: any = { page, size };
  if (pageId) params.page_id = pageId;
  if (employee) params.employee = employee;
  if (startDate) params.start_date = startDate;
  if (endDate) params.end_date = endDate;
  const res = await apiClient.get<{data: Lead[], total: number, page: number, size: number}>('/leads/list', { params });
  return res.data;
};

export const fetchEmployees = async (startDate?: string, endDate?: string, pageId?: string): Promise<string[]> => {
  const params: any = {};
  if (startDate) params.start_date = startDate;
  if (endDate) params.end_date = endDate;
  if (pageId) params.page_id = pageId;
  const response = await apiClient.get<{data: string[]}>('/employees/list', { params });
  return response.data.data;
};

export interface PagesData {
  pages: string[];
  // Page Zalo (kênh chăm sóc): không được cộng vào "Tất cả Page", chỉ xem khi chọn riêng
  zaloPages: string[];
}

export const fetchPages = async (): Promise<PagesData> => {
  const response = await apiClient.get<{data: string[], zalo_pages?: string[]}>('/pages/list');
  return { pages: response.data.data, zaloPages: response.data.zalo_pages ?? [] };
};

export interface RemindLeadItem {
  lead_id: number;
  customer_id: string;
  name?: string;
  phone_number?: string;
  page_id: string;
  assigned_users?: string;
  status_tag?: string;
  remind_tag: string;
  remind_tagged_at?: string;
  contacted_at: string | null;
  days_since_last_contact: number;
  days_int: number;
  conversation_id?: string;
  pancake_url?: string;
}

export interface RemindSummary {
  total: number;
  under_1_day: number;
  days_1_to_3: number;
  days_3_to_7: number;
  over_7_days: number;
}

export interface RemindLeadResponse {
  total: number;
  page: number;
  size: number;
  total_pages: number;
  summary: RemindSummary;
  employees: string[];
  tags?: string[];
  items: RemindLeadItem[];
}

export const fetchRemindLeads = async (
  employee?: string,
  pageId?: string,
  tag?: string,
  search?: string,
  daysBucket?: string,
  sortOrder: 'asc' | 'desc' = 'asc',
  page: number = 1,
  size: number = 20
): Promise<RemindLeadResponse> => {
  const params: any = { page, size, sort_order: sortOrder };
  if (employee) params.employee = employee;
  if (pageId) params.page_id = pageId;
  if (tag && tag !== 'all') params.tag = tag;
  if (search) params.search = search;
  if (daysBucket && daysBucket !== 'all') params.days_bucket = daysBucket;
  const res = await apiClient.get<RemindLeadResponse>('/leads/remind', { params });
  return res.data;
};

// ===================================// DEAL WIN (Google Sheet / Form Học Viên)
// ===================================
export interface DealWinItem {
  id: number;
  sheet_row_id?: string;
  timestamp?: string;
  email?: string;
  full_name?: string;
  phone_number?: string;
  birth_year?: string;
  address?: string;
  industry?: string;
  job_title?: string;
  expectation?: string;
  care_by?: string;
  page_id?: string;
  is_student?: boolean;
  lead_tag?: string;
  dim_lead_id?: number;
  raw_data?: Record<string, any>;
  created_at?: string;
}

export interface DealWinSummary {
  total_deals: number;
  total_phones?: number;
  conversion_rate?: number;
  top_sales_person?: string;
  sales_person_stats: Record<string, number>;
  daily_trend: Array<{ date: string; count: number }>;
}

export interface DealWinListResponse {
  total: number;
  page: number;
  size: number;
  total_pages: number;
  data: DealWinItem[];
}

export interface DealWinOptions {
  sales_persons: string[];
  pages?: string[];
}

export const fetchDealWinSummary = async (
  startDate?: string,
  endDate?: string,
  salesPerson?: string,
  onlyStudent: boolean = true,
  pageId?: string
): Promise<DealWinSummary> => {
  const params: any = { only_student: onlyStudent };
  if (startDate) params.start_date = startDate;
  if (endDate) params.end_date = endDate;
  if (salesPerson) params.sales_person = salesPerson;
  if (pageId) params.page_id = pageId;
  const res = await apiClient.get<DealWinSummary>('/deals/summary', { params });
  return res.data;
};

export const fetchDealWinList = async (
  page: number = 1,
  size: number = 20,
  startDate?: string,
  endDate?: string,
  salesPerson?: string,
  search?: string,
  onlyStudent: boolean = true,
  pageId?: string
): Promise<DealWinListResponse> => {
  const params: any = { page, size, only_student: onlyStudent };
  if (startDate) params.start_date = startDate;
  if (endDate) params.end_date = endDate;
  if (salesPerson) params.sales_person = salesPerson;
  if (pageId) params.page_id = pageId;
  if (search) params.search = search;
  const res = await apiClient.get<DealWinListResponse>('/deals/list', { params });
  return res.data;
};

export const fetchDealWinOptions = async (onlyStudent: boolean = true): Promise<DealWinOptions> => {
  const res = await apiClient.get<DealWinOptions>('/deals/options', { params: { only_student: onlyStudent } });
  return res.data;
};

export const fetchDealWinDetail = async (dealId: number): Promise<DealWinItem> => {
  const res = await apiClient.get<DealWinItem>(`/deals/${dealId}`);
  return res.data;
};

export const syncDealsWithLeads = async (): Promise<{ status: string; total_deals: number; students_count: number; care_by_updated: number; message: string }> => {
  const res = await apiClient.post('/deals/sync-leads');
  return res.data;
};


// ==========================================
// BROADCAST / BOT GỬI TIN HÀNG LOẠT
// ==========================================

export interface BroadcastOptions {
  pages: string[];
  source_pages: string[];
  zalo_pages: string[];
  employees: string[];
  employees_by_page?: Record<string, string[]>;
  tags: string[];
  tags_by_page?: Record<string, string[]>;
  gender_options: Array<{ value: string; label: string }>;
  has_token_configured?: boolean;
  configured_pages_count?: number;
}

export interface BroadcastPreviewParams {
  page_id?: string;
  name_filter?: string;
  employee?: string;
  gender?: string;
  tag?: string;
  tags?: string[];
  time_filter?: string;
  days_ago?: number;
  phone_filter?: string;
  limit?: number;
  template: string;
  exclude_already_sent?: boolean;
  exclude_students?: boolean;
  campaign_name?: string;
}

export interface BroadcastRecipientItem {
  lead_id: number;
  customer_id: string;
  conversation_id: string;
  name: string;
  gender: string;
  gender_title: string;
  phone_number?: string;
  page_id: string;
  api_page_id?: string;
  is_zalo?: boolean;
  status_tag?: string;
  assigned_users?: string;
  rendered_message: string;
  first_created_at?: string;
  last_contacted_at?: string;
  days_since_contact?: number;
  pancake_url?: string;
}

export interface BroadcastPreviewResponse {
  total_matching: number;
  limit: number;
  zalo_count?: number;
  recipients: BroadcastRecipientItem[];
}

export interface BroadcastStartParams {
  campaign_name: string;
  template: string;
  page_id?: string;
  name_filter?: string;
  employee?: string;
  gender?: string;
  tag?: string;
  tags?: string[];
  time_filter?: string;
  days_ago?: number;
  phone_filter?: string;
  limit: number;
  delay: number;
  dry_run: boolean;
  exclude_already_sent: boolean;
  exclude_students?: boolean;
  target_conversation_ids?: string[];
  zalo_protection?: boolean;
  zalo_min_delay?: number;
  zalo_max_delay?: number;
  zalo_batch_size?: number;
  zalo_batch_pause?: number;
  enable_spintax?: boolean;
  max_consecutive_errors?: number;
  custom_token?: string;
}

export interface TokenChannelStatus {
  page_name: string;
  api_page_id: string;
  is_zalo: boolean;
  has_token: boolean;
  masked_token?: string;
}

export interface TokenStatusResponse {
  has_token: boolean;
  channels: TokenChannelStatus[];
}

export interface BroadcastStatusResponse {
  task_id: string;
  campaign_name: string;
  is_running: boolean;
  total: number;
  processed: number;
  success: number;
  failed: number;
  dry_run: boolean;
  current_recipient?: string;
  started_at?: string;
  finished_at?: string;
  logs: Array<{
    index: number;
    customer_name: string;
    phone_number: string;
    conversation_id: string;
    page_id: string;
    status: string;
    error_message?: string;
    time: string;
  }>;
}

export interface BroadcastHistoryItem {
  id: number;
  campaign_name: string;
  conversation_id: string;
  customer_id?: string;
  customer_name?: string;
  phone_number?: string;
  page_id: string;
  message: string;
  status: string;
  error_message?: string;
  sent_at: string;
  pancake_url?: string;
}

export interface BroadcastCampaignSummary {
  campaign_name: string;
  page_id?: string;
  total_messages: number;
  success_count: number;
  failed_count: number;
  dry_run_count: number;
  first_sent_at?: string;
  last_sent_at?: string;
  status: string;
}

export const fetchBroadcastOptions = async (pageId?: string, refresh?: boolean): Promise<BroadcastOptions> => {
  const params: any = {};
  if (pageId && pageId !== 'all') {
    params.page_id = pageId;
  }
  if (refresh) {
    params.refresh = true;
  }
  const res = await apiClient.get<BroadcastOptions>('/broadcast/options', { params });
  return res.data;
};

export const previewBroadcast = async (params: BroadcastPreviewParams): Promise<BroadcastPreviewResponse> => {
  const res = await apiClient.post<BroadcastPreviewResponse>('/broadcast/preview', params);
  return res.data;
};

export const startBroadcast = async (params: BroadcastStartParams): Promise<{ status: string; task_id: string; campaign_name: string }> => {
  const res = await apiClient.post<{ status: string; task_id: string; campaign_name: string }>('/broadcast/start', params);
  return res.data;
};

export const fetchActiveBroadcast = async (): Promise<BroadcastStatusResponse | null> => {
  const res = await apiClient.get<BroadcastStatusResponse | null>('/broadcast/active');
  return res.data;
};

export const fetchBroadcastStatus = async (taskId: string): Promise<BroadcastStatusResponse> => {
  const res = await apiClient.get<BroadcastStatusResponse>('/broadcast/status/' + taskId);
  return res.data;
};

export const stopBroadcast = async (taskId: string): Promise<{ status: string; task_id: string }> => {
  const res = await apiClient.post('/broadcast/stop/' + taskId);
  return res.data;
};

export const fetchBroadcastHistory = async (campaignName?: string, limit: number = 100): Promise<{ campaigns: BroadcastCampaignSummary[]; logs: BroadcastHistoryItem[] }> => {
  const params: any = { limit };
  if (campaignName && campaignName !== 'all') params.campaign_name = campaignName;
  const res = await apiClient.get<{ campaigns: BroadcastCampaignSummary[]; logs: BroadcastHistoryItem[] }>('/broadcast/history', { params });
  return res.data;
};

export const fetchTokenStatus = async (): Promise<TokenStatusResponse> => {
  const res = await apiClient.get<TokenStatusResponse>('/broadcast/token-status');
  return res.data;
};

export const saveTokenConfig = async (defaultToken?: string, pagesJson?: string): Promise<{ status: string; message: string; token_status: TokenStatusResponse }> => {
  const res = await apiClient.post('/broadcast/token-config', {
    default_token: defaultToken,
    pages_json: pagesJson
  });
  return res.data;
};

export const clearFailedBroadcastLogs = async (campaignName?: string): Promise<{ status: string; deleted_count: number; message: string }> => {
  const params: any = {};
  if (campaignName && campaignName !== 'all') params.campaign_name = campaignName;
  const res = await apiClient.post('/broadcast/clear-failed', null, { params });
  return res.data;
};


// ==========================================
// AUTHENTICATION & SECURITY APIs
// ==========================================

export interface AuthUser {
  id: number;
  username: string;
  full_name?: string;
  role: string;
  last_login_at?: string;
}

export interface LoginResponse {
  access_token: string;
  token_type: string;
  expires_in_hours: number;
  user: AuthUser;
}

export const loginApi = async (username: string, password: string, rememberMe: boolean = false): Promise<LoginResponse> => {
  const res = await apiClient.post<LoginResponse>('/auth/login', {
    username,
    password,
    remember_me: rememberMe
  });
  const token = res.data.access_token;
  const user = res.data.user;
  if (rememberMe) {
    localStorage.setItem('eztech_auth_token', token);
    localStorage.setItem('eztech_auth_user', JSON.stringify(user));
  } else {
    sessionStorage.setItem('eztech_auth_token', token);
    sessionStorage.setItem('eztech_auth_user', JSON.stringify(user));
  }
  return res.data;
};

export const fetchCurrentUser = async (): Promise<AuthUser> => {
  const res = await apiClient.get<AuthUser>('/auth/me');
  return res.data;
};

export const changePasswordApi = async (oldPassword: string, newPassword: string): Promise<{ status: string; message: string }> => {
  const res = await apiClient.post('/auth/change-password', {
    old_password: oldPassword,
    new_password: newPassword
  });
  return res.data;
};

export const logoutApi = async (): Promise<void> => {
  try {
    await apiClient.post('/auth/logout');
  } catch (e) {
    // ignore
  } finally {
    localStorage.removeItem('eztech_auth_token');
    sessionStorage.removeItem('eztech_auth_token');
    localStorage.removeItem('eztech_auth_user');
    sessionStorage.removeItem('eztech_auth_user');
  }
};

export const getStoredAuth = (): { token: string | null; user: AuthUser | null } => {
  const token = localStorage.getItem('eztech_auth_token') || sessionStorage.getItem('eztech_auth_token');
  const userStr = localStorage.getItem('eztech_auth_user') || sessionStorage.getItem('eztech_auth_user');
  let user: AuthUser | null = null;
  if (userStr) {
    try {
      user = JSON.parse(userStr);
    } catch {
      // ignore
    }
  }
  return { token, user };
};


// ==============================================================================
// QUẢN LÝ NHẬP DEAL & CÔNG NỢ HỌC VIÊN (DEAL ENTRY & DEBT MANAGEMENT)
// ==============================================================================

export interface DealPaymentApp {
  ngay: string;
  soTien: number;
  dealId: string;
}

export interface SalesDealRecord {
  id: string;
  dealWinId?: number | null;
  ngayThu: string;
  ngayContact: string;
  sdt: string;
  hoTen: string;
  email?: string;
  namSinh?: string;
  diaChi?: string;
  linhVuc?: string;
  kyVong?: string;
  isStudent?: boolean;
  leadTag?: string;
  zalo: string;
  nhomCS: string;
  chuongTrinh: string;
  lop: string[];
  chucVu: string;
  nvCS: string;
  zaloCS: string;
  nguon: string;
  daThu: number;
  phaiThu: number;
  tongTien: number;
  ngayThuAR: string;
  trangThai: string;
  note: string;
  nguoiNhap: string;
  taoLuc: string;
  nguoiSua: string;
  suaLuc: string;
  thuNo: number;
  daThuNo: number;
  conNo: number;
  isIncomplete?: boolean;
  apps?: DealPaymentApp[];
}

export interface DebtRecordItem {
  id: string;
  sdt: string;
  hoTen: string;
  ngayThuGoc: string;
  thangPhatSinh: string;
  phaiThuBanDau: number;
  daThuNo: number;
  conNo: number;
  lanThuGanNhat: string;
  nvCS: string;
  nguoiNhap: string;
  lop: string[];
  chuongTrinh: string;
  note: string;
}

export interface DebtSummaryData {
  items: DebtRecordItem[];
  totalPhaiThu: number;
  totalDaThuNo: number;
  totalConNo: number;
  count: number;
}

export interface DealEntryLists {
  zaloCS: string[];
  nguon: string[];
  chuongTrinh: string[];
  lop: string[];
}

export interface DealEntryInitResponse {
  ok: boolean;
  statuses: string[];
  lists: DealEntryLists;
  deals: SalesDealRecord[];
  debts: DebtSummaryData;
}

export interface PhoneLookupResponse {
  ok: boolean;
  found: boolean;
  foundInDeals?: boolean;
  hoTen?: string;
  chucVu?: string;
  zalo?: string;
  nhomCS?: string;
  nvCS?: string;
  zaloCS?: string;
  nguon?: string;
  ngayContact?: string;
  lop?: string[];
  conNo?: number;
  noTuNgay?: string;
  previousDeals?: Array<{
    id: string;
    ngayThu: string;
    chuongTrinh: string;
    daThu: number;
    phaiThu: number;
    conNo: number;
    trangThai: string;
  }>;
  pancake?: {
    foundInPancake?: boolean;
    hoTen?: string;
    ngayContact?: string;
    zalo?: string;
    nguon?: string;
    nvCS?: string;
  };
}

export interface DealAuditLogItem {
  id: number;
  createdAt: string;
  userEmail: string;
  action: string;
  dealId: string;
  detail: string;
}

export const fetchDealEntryInit = async (force: boolean = false): Promise<DealEntryInitResponse> => {
  const res = await apiClient.get<DealEntryInitResponse>('/deal-entry/init', {
    params: force ? { force: true } : undefined,
  });
  return res.data;
};

export const lookupDealPhone = async (sdt: string, excludeId?: string): Promise<PhoneLookupResponse> => {
  const params: Record<string, string> = { sdt };
  if (excludeId) params.exclude_id = excludeId;
  const res = await apiClient.get<PhoneLookupResponse>('/deal-entry/lookup-phone', { params });
  return res.data;
};

export const saveSalesDeal = async (payload: Partial<SalesDealRecord> & { actor?: string }) => {
  const res = await apiClient.post('/deal-entry/deals', payload);
  return res.data;
};

export const updateSalesDealClasses = async (dealId: string, lop: string[], actor?: string) => {
  const res = await apiClient.put(`/deal-entry/deals/${dealId}/classes`, { lop, actor });
  return res.data;
};

export const deleteSalesDeal = async (dealId: string, actor?: string) => {
  const res = await apiClient.delete(`/deal-entry/deals/${dealId}`, { params: { actor } });
  return res.data;
};

export const saveDealEntryLists = async (lists: DealEntryLists, actor?: string) => {
  const res = await apiClient.put('/deal-entry/lists', { lists, actor });
  return res.data;
};

export const fetchDealEntryLogs = async (limit: number = 100): Promise<{ ok: boolean; logs: DealAuditLogItem[] }> => {
  const res = await apiClient.get('/deal-entry/logs', { params: { limit } });
  return res.data;
};

// ==========================================
// FACEBOOK ANALYTICS
// ==========================================

export interface FacebookSummaryData {
  total_posts: number;
  total_reactions: number;
  total_comments: number;
  total_post_comments: number;
  total_shares: number;
  total_leads: number;
  new_leads: number;
  recontact_leads: number;
  phone_leads: number;
  comment_phones: number;
  deal_wins: number;
  phone_conversion_rate: number;
  deal_conversion_rate: number;
  avg_reactions_per_post: number;
  avg_comments_per_post: number;
  ads_leads?: number;
  ads_phones?: number;
  ads_phone_rate?: number;
  post_leads?: number;
  post_phones?: number;
  post_phone_rate?: number;
  organic_leads?: number;
  organic_phones?: number;
  organic_phone_rate?: number;
}

export interface FacebookAdItem {
  ad_id: string;
  post_id?: string | null;
  post_url?: string | null;
  post_message?: string;
  lead_count: number;
  phone_count: number;
  phone_rate: number;
  deal_count: number;
}

export interface FacebookPostItem {
  post_id: string;
  page_id: string;
  page_name: string;
  type: string;
  message: string;
  post_url: string | null;
  inserted_at: string | null;
  reactions_total: number;
  like_count: number;
  love_count: number;
  comment_count: number;
  lead_count: number;
  phone_count: number;
  deal_count: number;
}

export interface FacebookTrendData {
  date: string;
  posts: number;
  reactions: number;
  comments: number;
  leads: number;
  phones: number;
  ads_leads?: number;
  ads_phones?: number;
  post_leads?: number;
  organic_leads?: number;
  post_phones?: number;
  organic_phones?: number;
}

export interface ChannelBreakdownItem {
  name: string;
  leads: number;
  phones: number;
  conversion_rate: number;
}

export interface FacebookMetricsResponse {
  summary: FacebookSummaryData;
  reaction_breakdown: Record<string, number>;
  post_type_stats: Record<string, number>;
  trend: FacebookTrendData[];
  top_posts: FacebookPostItem[];
  top_ads?: FacebookAdItem[];
  employee_stats: Record<string, number>;
  tag_stats: Record<string, number>;
  channel_breakdown?: {
    ads?: ChannelBreakdownItem;
    post: ChannelBreakdownItem;
    organic: ChannelBreakdownItem;
  };
}

export interface FacebookPageItem {
  id: string;
  name: string;
}

export const fetchFacebookPages = async (): Promise<FacebookPageItem[]> => {
  const res = await apiClient.get<{ pages: FacebookPageItem[] }>('/facebook/pages');
  return res.data.pages;
};

export const fetchFacebookMetrics = async (
  startDate?: string,
  endDate?: string,
  pageId?: string
): Promise<FacebookMetricsResponse> => {
  const params: any = {};
  if (startDate) params.start_date = startDate;
  if (endDate) params.end_date = endDate;
  if (pageId) params.page_id = pageId;
  const res = await apiClient.get<FacebookMetricsResponse>('/facebook/metrics', { params });
  return res.data;
};

// ==========================================
// TIKTOK ANALYTICS
// ==========================================

export interface TikTokPageItem {
  id: string;
  name: string;
}

export const fetchTikTokPages = async (): Promise<TikTokPageItem[]> => {
  const res = await apiClient.get<{ pages: TikTokPageItem[] }>('/tiktok/pages');
  return res.data.pages;
};

export const fetchTikTokMetrics = async (
  startDate?: string,
  endDate?: string,
  pageId?: string
): Promise<FacebookMetricsResponse> => {
  const params: any = {};
  if (startDate) params.start_date = startDate;
  if (endDate) params.end_date = endDate;
  if (pageId) params.page_id = pageId;
  const res = await apiClient.get<FacebookMetricsResponse>('/tiktok/metrics', { params });
  return res.data;
};

// ==========================================
// WORK REPORT (BÁO CÁO CÔNG VIỆC TUẦN)
// ==========================================

export interface WorkReportChannelStat {
  new_leads: number;
  recontact_leads: number;
  total_contacted: number;
  phone_leads: number;
  phone_rate?: number;
  formatted_line?: string;
}

export interface WorkReportStudentItem {
  full_name: string;
  phone_number: string;
  page_id: string;
  industry: string;
  job_title: string;
  expectation: string;
  course: string;
  class_code: string;
  revenue: number;
  total_amount: number;
  date: string;
  care_by: string;
  note: string;
}

export interface WorkReportResponse {
  period: {
    start_date: string;
    end_date: string;
  };
  employee: string;
  employees_list: string[];
  lead_stats: {
    total: WorkReportChannelStat;
    tiktok: WorkReportChannelStat;
    facebook: WorkReportChannelStat;
    zalo: WorkReportChannelStat;
    by_page: Array<{
      page_name: string;
      platform: 'tiktok' | 'facebook';
      new_leads: number;
      recontact_leads: number;
      total_contacted: number;
      phone_leads: number;
    }>;
    top_tags: Array<{ tag: string; count: number }>;
  };
  student_stats: {
    total_deals: number;
    total_revenue: number;
    total_contract_value: number;
    classes: string[];
    courses: string[];
    students: WorkReportStudentItem[];
    formatted_line: string;
  };
  insights: {
    industries: Array<{ name: string; count: number }>;
    job_titles: Array<{ name: string; count: number }>;
    expectations: string[];
    formatted_lines: string[];
  };
}

export const fetchWorkReport = async (
  startDate?: string,
  endDate?: string,
  employee?: string
): Promise<WorkReportResponse> => {
  const params: any = {};
  if (startDate) params.start_date = startDate;
  if (endDate) params.end_date = endDate;
  if (employee) params.employee = employee;
  const res = await apiClient.get<WorkReportResponse>('/work-report', { params });
  return res.data;
};

export interface BackfillStatusResponse {
  isRunning: boolean;
  currentPage: string;
  currentPageIdx: number;
  totalPages: number;
  totalAdded: number;
  currentDate: string;
  startedAt?: string | null;
  finishedAt?: string | null;
  error?: string | null;
  logs: string[];
}

export const fetchBackfillStatus = async (): Promise<BackfillStatusResponse> => {
  const res = await apiClient.get<BackfillStatusResponse>('/admin/backfill/status');
  return res.data;
};

export const startBackfill = async (payload?: {
  page?: string;
  limit?: number;
  chunk?: number;
  stop_date?: string;
}): Promise<{ status: string; message: string }> => {
  const res = await apiClient.post<{ status: string; message: string }>('/admin/backfill/start', payload || {});
  return res.data;
};

export const stopBackfill = async (): Promise<{ status: string; message: string }> => {
  const res = await apiClient.post<{ status: string; message: string }>('/admin/backfill/stop');
  return res.data;
};



// ==========================================
// AUTO ADD FRIEND ZALO VIA PANCAKE
// ==========================================

export interface AddFriendPageOption {
  id: string;
  name: string;
  badge: string;
}

export interface AddFriendTemplateOption {
  key: string;
  label: string;
  source_key: string;
  message: string;
}

export interface PancakeStateInfo {
  has_state: boolean;
  source?: string | null;
  storage_key?: string | null;
  cookies_count: number;
  origins_count: number;
  updated_at?: string | null;
}

export interface AddFriendConfigResponse {
  pages: AddFriendPageOption[];
  templates: AddFriendTemplateOption[];
  tags: string[];
  skip_sources: string[];
  state_info: PancakeStateInfo;
}

export interface PhoneImportItem {
  raw_phone: string;
  phone: string;
  is_valid: boolean;
  validation_note: string;
  name: string;
  source: string;
  nhu_cau: string;
  is_duplicate: boolean;
  is_skipped_source: boolean;
  already_added: boolean;
  rendered_message: string;
  rendered_note: string;
}

export interface ParsePhonesParams {
  raw_text: string;
  page_name: string;
  message_template: string;
  note_template: string;
  use_source_template: boolean;
  enable_spintax: boolean;
  skip_sources: string[];
  exclude_already_added: boolean;
}

export interface ParsePhonesResponse {
  total_lines: number;
  valid_count: number;
  invalid_count: number;
  duplicate_count: number;
  skipped_source_count: number;
  already_added_count: number;
  ready_count: number;
  items: PhoneImportItem[];
}

export interface RateLimitSettings {
  preset: 'fast' | 'recommended' | 'ultra' | 'custom';
  delay_min: number;
  delay_max: number;
  batch_size: number;
  batch_pause_sec: number;
  max_retries: number;
  max_consecutive_errors: number;
  daily_limit: number;
  enable_spintax: boolean;
  exclude_already_added: boolean;
}

export interface AddFriendTargetItem {
  phone: string;
  name: string;
  source: string;
  nhu_cau: string;
  custom_message?: string;
  custom_note?: string;
}

export interface StartAddFriendParams {
  campaign_name: string;
  page_name: string;
  items: AddFriendTargetItem[];
  message_template: string;
  inbox_message_template?: string;
  use_source_template: boolean;
  send_inbox_message: boolean;
  add_note: boolean;
  note_template: string;
  tags: string[];
  rate_limit: RateLimitSettings;
  dry_run: boolean;
}

export interface AddFriendLogItem {
  index: number;
  phone: string;
  name: string;
  source: string;
  nhu_cau: string;
  page_name: string;
  message: string;
  note: string;
  tags: string[];
  status: 'ADDED' | 'DRY_RUN' | 'NOT_FOUND' | 'FAILED' | 'SERVER_ERROR' | 'AUTH_EXPIRED' | string;
  detail: string;
  attempts: number;
  time: string;
}

export interface AddFriendTaskStatus {
  task_id: string;
  campaign_name: string;
  page_name: string;
  is_running: boolean;
  dry_run: boolean;
  total: number;
  processed: number;
  added_count: number;
  not_found_count: number;
  failed_count: number;
  current_phone: string;
  current_action: string;
  started_at: string;
  finished_at?: string | null;
  logs: AddFriendLogItem[];
}

export interface AddFriendHistoryItem {
  id: number;
  campaign_name: string;
  phone: string;
  page_name: string;
  customer_info: string;
  message: string;
  status: string;
  detail: string;
  sent_at: string;
}

export const fetchAddFriendConfig = async (): Promise<AddFriendConfigResponse> => {
  const res = await apiClient.get<AddFriendConfigResponse>('/add-friend/config');
  return res.data;
};

export const fetchPancakeStateRaw = async (): Promise<{
  status: string;
  has_state: boolean;
  storage_key?: string | null;
  state_info: PancakeStateInfo;
  state_json?: string | null;
}> => {
  const res = await apiClient.get('/add-friend/state');
  return res.data;
};

export const savePancakeStateJson = async (
  stateJson: string
): Promise<{ status: string; message: string; state_info: PancakeStateInfo }> => {
  const res = await apiClient.post('/add-friend/state', { state_json: stateJson });
  return res.data;
};

export const deletePancakeState = async (): Promise<{ status: string; message: string; state_info: PancakeStateInfo }> => {
  const res = await apiClient.delete('/add-friend/state');
  return res.data;
};

export const parseBulkPhones = async (params: ParsePhonesParams): Promise<ParsePhonesResponse> => {
  const res = await apiClient.post<ParsePhonesResponse>('/add-friend/parse-phones', params);
  return res.data;
};

export const fetchLeadsWithPhonesForAddFriend = async (
  sourceChannel: string = 'all',
  limit: number = 50
): Promise<{ count: number; formatted_text: string }> => {
  const res = await apiClient.get('/add-friend/leads-phones', {
    params: { source_channel: sourceChannel, limit }
  });
  return res.data;
};

export const startAddFriendCampaign = async (
  params: StartAddFriendParams
): Promise<{ status: string; task_id: string; campaign_name: string; total: number }> => {
  const res = await apiClient.post('/add-friend/start', params);
  return res.data;
};

export const fetchAddFriendStatus = async (taskId: string): Promise<AddFriendTaskStatus> => {
  const res = await apiClient.get<AddFriendTaskStatus>(`/add-friend/status/${taskId}`);
  return res.data;
};

export const stopAddFriendCampaign = async (taskId: string): Promise<{ status: string; task_id: string }> => {
  const res = await apiClient.post(`/add-friend/stop/${taskId}`);
  return res.data;
};

export const fetchAddFriendHistory = async (limit: number = 100): Promise<{ items: AddFriendHistoryItem[] }> => {
  const res = await apiClient.get<{ items: AddFriendHistoryItem[] }>('/add-friend/history', {
    params: { limit }
  });
  return res.data;
};
