import axios from 'axios';

// Client In-Memory & Session Cache: Chuyển tab & F5 tức thì (<0.01s), giảm 95% request, tiết kiệm tối đa Neon Egress
const _CLIENT_CACHE = new Map<string, { time: number; data: any }>();
const _INFLIGHT_REQUESTS = new Map<string, Promise<any>>();
const CLIENT_CACHE_TTL = 5 * 60 * 1000; // 5 phút
const SESSION_CACHE_PREFIX = 'ez_cache_';

// Các endpoint realtime / nhạy cảm (cookie/token) tuyệt đối KHÔNG cache phía client
const NO_CACHE_SUBSTRINGS = [
  '/broadcast/status',
  '/broadcast/active',
  '/add-friend/status',
  '/add-friend/active',
  '/add-friend/state',
  '/add-friend/leads-phones',
  '/add-friend/history',
  '/admin/backfill/status',
  '/ai/',
  '/bulletin/',
  '/auth/me',
  '/auth/login',
  '/auth/logout',
  '/auth/users',
  '/auth/change-password',
  '/health',
];

// Các POST chỉ đọc / không làm bẩn dữ liệu dashboard -> không xóa cache toàn app
const READONLY_POST_SUBSTRINGS = [
  '/ai/chat',
  '/broadcast/preview',
  '/add-friend/parse-phones',
  '/auth/login',
  '/auth/logout',
];

export const clearClientApiCache = (urlPrefix?: string) => {
  if (!urlPrefix) {
    _CLIENT_CACHE.clear();
  } else {
    for (const k of Array.from(_CLIENT_CACHE.keys())) {
      if (k.includes(urlPrefix)) _CLIENT_CACHE.delete(k);
    }
  }
  try {
    const keysToRemove: string[] = [];
    for (let i = 0; i < sessionStorage.length; i++) {
      const k = sessionStorage.key(i);
      if (k && k.startsWith(SESSION_CACHE_PREFIX) && (!urlPrefix || k.includes(urlPrefix))) {
        keysToRemove.push(k);
      }
    }
    keysToRemove.forEach(k => sessionStorage.removeItem(k));
  } catch {
    // ignore storage error
  }
};

export interface RequestOptions {
  signal?: AbortSignal;
  skipCache?: boolean;
}

export const isAbortError = (err: unknown): boolean => {
  return axios.isCancel(err) || (err instanceof Error && (err.name === 'CanceledError' || err.name === 'AbortError'));
};

// Get API URL from env, or default to relative /api if deployed together
let API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000/api';
// Đảm bảo URL luôn có đuôi /api
if (import.meta.env.VITE_API_URL && !API_BASE_URL.endsWith('/api')) {
  API_BASE_URL = `${API_BASE_URL.replace(/\/$/, '')}/api`;
}

const apiClient = axios.create({
  baseURL: API_BASE_URL,
  timeout: 60000,
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

// Bắt lỗi 401 Unauthorized để yêu cầu đăng nhập lại & Tự động xóa cache khi có ghi dữ liệu thật
apiClient.interceptors.response.use(
  (response) => {
    const method = response.config.method?.toLowerCase();
    const reqUrl = response.config.url || '';
    if (method && ['post', 'put', 'delete', 'patch'].includes(method) && !reqUrl.includes('/data-export/')) {
      const isReadOnlyPost = method === 'post' && READONLY_POST_SUBSTRINGS.some(sub => reqUrl.includes(sub));
      if (!isReadOnlyPost) {
        clearClientApiCache();
      }
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


// Bọc apiClient.get với in-memory + session cache và in-flight deduplication
const originalGet = apiClient.get.bind(apiClient);
apiClient.get = (async (url: string, config?: any): Promise<any> => {
  const isNoCache =
    Boolean(config?.skipCache) ||
    Boolean(config?.params?.bypass_cache) ||
    Boolean(config?.params?.force) ||
    Boolean(config?.params?.refresh) ||
    config?.headers?.['Cache-Control'] === 'no-cache';
  const shouldSkip = isNoCache || NO_CACHE_SUBSTRINGS.some(sub => url.includes(sub));

  const paramEntries = Object.entries(config?.params || {}).filter(([_, v]) => v !== undefined && v !== null);
  paramEntries.sort(([a], [b]) => a.localeCompare(b));
  const paramStr = paramEntries.map(([k, v]) => `${k}=${v}`).join('&');
  let userScopePrefix = 'anon';
  try {
    const rawU = localStorage.getItem('eztech_auth_user') || sessionStorage.getItem('eztech_auth_user');
    if (rawU) {
      const parsedU = JSON.parse(rawU);
      if (parsedU?.username) userScopePrefix = String(parsedU.username);
    }
  } catch {
    // ignore
  }
  const cacheKey = `${userScopePrefix}:${url}?${paramStr}`;

  if (shouldSkip) {
    const res = await originalGet(url, config);
    // Nếu là refresh thủ công cho endpoint có thể cache (không thuộc NO_CACHE_SUBSTRINGS), cập nhật cache mới
    if (
      res &&
      res.status === 200 &&
      !NO_CACHE_SUBSTRINGS.some(sub => url.includes(sub)) &&
      !config?.params?.force &&
      !config?.params?.refresh
    ) {
      const entry = { time: Date.now(), data: res.data };
      _CLIENT_CACHE.set(cacheKey, entry);
      try {
        sessionStorage.setItem(SESSION_CACHE_PREFIX + cacheKey, JSON.stringify(entry));
      } catch {
        // ignore
      }
    }
    return res;
  }

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

  // 2. Kiểm tra sessionStorage (giữ cache ngay cả khi F5 reload)
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
  } catch {
    // ignore
  }

  // 3. Chặn gọi trùng đồng thời (StrictMode / double click) khi không truyền AbortSignal riêng
  if (!config?.signal && _INFLIGHT_REQUESTS.has(cacheKey)) {
    return _INFLIGHT_REQUESTS.get(cacheKey)!;
  }

  const reqPromise = originalGet(url, config).then((res) => {
    if (res && res.status === 200) {
      const entry = { time: Date.now(), data: res.data };
      _CLIENT_CACHE.set(cacheKey, entry);
      try {
        sessionStorage.setItem(SESSION_CACHE_PREFIX + cacheKey, JSON.stringify(entry));
      } catch {
        // ignore quota errors
      }
    }
    return res;
  }).finally(() => {
    _INFLIGHT_REQUESTS.delete(cacheKey);
  });

  if (!config?.signal) {
    _INFLIGHT_REQUESTS.set(cacheKey, reqPromise);
  }
  return reqPromise;
}) as any;

export interface PreviousSummaryData {
  start_date: string;
  end_date: string;
  total_leads: number;
  new_leads: number;
  recontact_leads: number;
  phone_leads: number;
  new_phone_leads: number;
  recontact_phone_leads: number;
}

export interface SummaryData {
  new_leads: number;
  recontact_leads: number;
  ratio_new_leads?: number;
  ratio_recontact_leads?: number;
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
  previous_period?: PreviousSummaryData;
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

export interface OverviewCrossFilters {
  selectedDate?: string | null;
  leadType?: 'new' | 'recontact' | null;
  tagCategory?: string | null;
  hasPhone?: boolean | null;
  primaryEmployee?: string | null;
}

const applyCrossFilterParams = (params: Record<string, any>, filters?: OverviewCrossFilters, includeDate: boolean = true) => {
  if (!filters) return;
  if (includeDate && filters.selectedDate) params.selected_date = filters.selectedDate;
  if (filters.leadType) params.lead_type = filters.leadType;
  if (filters.tagCategory) params.tag_category = filters.tagCategory;
  if (filters.hasPhone === true) params.has_phone = 'true';
  else if (filters.hasPhone === false) params.has_phone = 'false';
  if (filters.primaryEmployee) params.primary_employee = filters.primaryEmployee;
};

export const fetchSummary = async (
  startDate: string,
  endDate: string,
  pageId?: string,
  employee?: string,
  filters?: OverviewCrossFilters,
  opts?: RequestOptions
) => {
  const params: any = { start_date: startDate, end_date: endDate };
  if (pageId) params.page_id = pageId;
  if (employee) params.employee = employee;
  applyCrossFilterParams(params, filters, true);
  const res = await apiClient.get<SummaryData>('/metrics/summary', { params, ...(opts || {}) } as any);
  return res.data;
};

export const fetchTrend = async (
  startDate: string,
  endDate: string,
  pageId?: string,
  employee?: string,
  filters?: OverviewCrossFilters,
  opts?: RequestOptions
) => {
  const params: any = { start_date: startDate, end_date: endDate };
  if (pageId) params.page_id = pageId;
  if (employee) params.employee = employee;
  applyCrossFilterParams(params, filters, false);
  const res = await apiClient.get<{data: TrendData[]}>('/metrics/trend', { params, ...(opts || {}) } as any);
  return res.data.data;
};

export const fetchLeads = async (
  pageId?: string,
  employee?: string,
  startDate?: string,
  endDate?: string,
  page: number = 1,
  size: number = 50,
  filters?: OverviewCrossFilters,
  opts?: RequestOptions
) => {
  const params: any = { page, size };
  if (pageId) params.page_id = pageId;
  if (employee) params.employee = employee;
  if (startDate) params.start_date = startDate;
  if (endDate) params.end_date = endDate;
  applyCrossFilterParams(params, filters, true);
  const res = await apiClient.get<{data: Lead[], total: number, page: number, size: number}>('/leads/list', { params, ...(opts || {}) } as any);
  return res.data;
};

export const fetchEmployees = async (startDate?: string, endDate?: string, pageId?: string, opts?: RequestOptions): Promise<string[]> => {
  const params: any = {};
  if (startDate) params.start_date = startDate;
  if (endDate) params.end_date = endDate;
  if (pageId) params.page_id = pageId;
  const response = await apiClient.get<{data: string[]}>('/employees/list', { params, ...(opts || {}) } as any);
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
  size: number = 20,
  opts?: RequestOptions
): Promise<RemindLeadResponse> => {
  const params: any = { page, size, sort_order: sortOrder };
  if (employee) params.employee = employee;
  if (pageId) params.page_id = pageId;
  if (tag && tag !== 'all') params.tag = tag;
  if (search) params.search = search;
  if (daysBucket && daysBucket !== 'all') params.days_bucket = daysBucket;
  const res = await apiClient.get<RemindLeadResponse>('/leads/remind', { params, ...(opts || {}) } as any);
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
  source_page?: string;
  is_student?: boolean;
  lead_tag?: string;
  dim_lead_id?: number;
  is_manually_edited?: boolean;
  edited_by?: string;
  edited_at?: string;
  raw_data?: Record<string, any>;
  created_at?: string;
}

export interface DealWinUpdatePayload {
  full_name?: string | null;
  phone_number?: string | null;
  email?: string | null;
  birth_year?: string | null;
  address?: string | null;
  industry?: string | null;
  job_title?: string | null;
  expectation?: string | null;
  care_by?: string | null;
  page_id?: string | null;
  source_page?: string | null;
  is_student?: boolean;
  lead_tag?: string | null;
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
  sources?: string[];
}

export const fetchDealWinSummary = async (
  startDate?: string,
  endDate?: string,
  salesPerson?: string,
  onlyStudent: boolean = true,
  pageId?: string,
  sourcePage?: string,
  opts?: RequestOptions
): Promise<DealWinSummary> => {
  const params: any = { only_student: onlyStudent };
  if (startDate) params.start_date = startDate;
  if (endDate) params.end_date = endDate;
  if (salesPerson) params.sales_person = salesPerson;
  if (pageId) params.page_id = pageId;
  if (sourcePage) params.source_page = sourcePage;
  const res = await apiClient.get<DealWinSummary>('/deals/summary', { params, ...(opts || {}) } as any);
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
  pageId?: string,
  sourcePage?: string,
  opts?: RequestOptions
): Promise<DealWinListResponse> => {
  const params: any = { page, size, only_student: onlyStudent };
  if (startDate) params.start_date = startDate;
  if (endDate) params.end_date = endDate;
  if (salesPerson) params.sales_person = salesPerson;
  if (pageId) params.page_id = pageId;
  if (sourcePage) params.source_page = sourcePage;
  if (search) params.search = search;
  const res = await apiClient.get<DealWinListResponse>('/deals/list', { params, ...(opts || {}) } as any);
  return res.data;
};

export const fetchDealWinOptions = async (onlyStudent: boolean = true, opts?: RequestOptions): Promise<DealWinOptions> => {
  const res = await apiClient.get<DealWinOptions>('/deals/options', { params: { only_student: onlyStudent }, ...(opts || {}) } as any);
  return res.data;
};

export const fetchDealWinDetail = async (dealId: number, opts?: RequestOptions): Promise<DealWinItem> => {
  const res = await apiClient.get<DealWinItem>(`/deals/${dealId}`, { ...(opts || {}) } as any);
  return res.data;
};

export const updateDealWinItem = async (dealId: number, payload: DealWinUpdatePayload): Promise<DealWinItem> => {
  const res = await apiClient.put<DealWinItem>(`/deals/${dealId}`, payload);
  clearClientApiCache('/deals/');
  clearClientApiCache('/deal-entry/');
  return res.data;
};

export const syncDealsWithLeads = async (): Promise<{ status: string; total_deals: number; students_count: number; care_by_updated: number; message: string }> => {
  const res = await apiClient.post('/deals/sync-leads');
  clearClientApiCache('/deals/');
  clearClientApiCache('/deal-entry/');
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

export interface BroadcastImageItem {
  filename: string;
  content_type: string;
  data_base64: string;
}

export interface BroadcastStartParams {
  campaign_name: string;
  template: string;
  images?: BroadcastImageItem[];
  send_mode?: 'text_then_images' | 'images_then_text' | 'images_only';
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

export const fetchBroadcastHistory = async (campaignName?: string, limit: number = 100, opts?: RequestOptions): Promise<{ campaigns: BroadcastCampaignSummary[]; logs: BroadcastHistoryItem[] }> => {
  const params: any = { limit };
  if (campaignName && campaignName !== 'all') params.campaign_name = campaignName;
  const res = await apiClient.get<{ campaigns: BroadcastCampaignSummary[]; logs: BroadcastHistoryItem[] }>('/broadcast/history', { params, ...(opts || {}) } as any);
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
  department?: string;
  is_default_password?: boolean;
  allowed_tabs?: string[];
  default_tab?: string;
  module_scopes?: Record<string, 'all' | 'personal'>;
  scope_summary?: string;
  last_login_at?: string;
}

export interface EmployeeLoginOption {
  id: number;
  username: string;
  full_name: string;
  department: string;
  role: string;
}

export interface LoginResponse {
  access_token: string;
  token_type: string;
  expires_in_hours: number;
  user: AuthUser;
}

export const fetchLoginEmployees = async (): Promise<EmployeeLoginOption[]> => {
  const res = await apiClient.get<EmployeeLoginOption[]>('/auth/employees');
  return res.data;
};

export const updateStoredUser = (user: AuthUser): void => {
  if (localStorage.getItem('eztech_auth_token')) {
    localStorage.setItem('eztech_auth_user', JSON.stringify(user));
  } else if (sessionStorage.getItem('eztech_auth_token')) {
    sessionStorage.setItem('eztech_auth_user', JSON.stringify(user));
  } else {
    localStorage.setItem('eztech_auth_user', JSON.stringify(user));
  }
};

export const loginApi = async (username: string, password: string, rememberMe: boolean = true): Promise<LoginResponse> => {
  const res = await apiClient.post<LoginResponse>('/auth/login', {
    username,
    password,
    remember_me: rememberMe
  });
  const token = res.data.access_token;
  const user = res.data.user;
  clearClientApiCache();
  localStorage.removeItem('eztech_auth_token');
  localStorage.removeItem('eztech_auth_user');
  sessionStorage.removeItem('eztech_auth_token');
  sessionStorage.removeItem('eztech_auth_user');
  if (rememberMe) {
    localStorage.setItem('eztech_auth_token', token);
    localStorage.setItem('eztech_auth_user', JSON.stringify(user));
  } else {
    sessionStorage.setItem('eztech_auth_token', token);
    sessionStorage.setItem('eztech_auth_user', JSON.stringify(user));
  }
  // Ghi nhớ nhân viên đăng nhập gần nhất vào localStorage (giữ lại cả sau khi Logout)
  localStorage.setItem('last_login_employee', user.username);
  return res.data;
};

export const fetchCurrentUser = async (): Promise<AuthUser> => {
  const res = await apiClient.get<AuthUser>('/auth/me');
  return res.data;
};

export const changePasswordApi = async (
  oldPassword: string,
  newPassword: string,
  confirmPassword?: string
): Promise<{ status: string; message: string; user?: AuthUser }> => {
  const res = await apiClient.post('/auth/change-password', {
    old_password: oldPassword,
    new_password: newPassword,
    confirm_password: confirmPassword ?? newPassword,
  });
  if (res.data?.user) {
    updateStoredUser(res.data.user);
  }
  return res.data;
};

export const logoutApi = async (): Promise<void> => {
  try {
    await apiClient.post('/auth/logout');
  } catch (e) {
    // ignore
  } finally {
    clearClientApiCache();
    localStorage.removeItem('eztech_auth_token');
    sessionStorage.removeItem('eztech_auth_token');
    localStorage.removeItem('eztech_auth_user');
    sessionStorage.removeItem('eztech_auth_user');
  }
};

export const fetchAdminUsers = async (): Promise<AuthUser[]> => {
  const res = await apiClient.get<AuthUser[]>('/auth/users');
  return res.data;
};

export const createAdminUser = async (payload: {
  full_name: string;
  department: string;
  password?: string;
}): Promise<AuthUser> => {
  const res = await apiClient.post<AuthUser>('/auth/users', payload);
  return res.data;
};

export const updateAdminUser = async (
  userId: number,
  payload: { full_name?: string; department?: string; reset_password?: boolean }
): Promise<AuthUser> => {
  const res = await apiClient.put<AuthUser>(`/auth/users/${userId}`, payload);
  return res.data;
};

export const deleteAdminUser = async (userId: number): Promise<{ status: string; message: string }> => {
  const res = await apiClient.delete(`/auth/users/${userId}`);
  return res.data;
};

export const syncAdminUsersFromDb = async (): Promise<{ status: string; added_count: number; message: string }> => {
  const res = await apiClient.post('/auth/users/sync-from-db');
  return res.data;
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

export const fetchDealEntryInit = async (force: boolean = false, opts?: RequestOptions): Promise<DealEntryInitResponse> => {
  const res = await apiClient.get<DealEntryInitResponse>('/deal-entry/init', {
    params: force ? { force: true } : undefined,
    skipCache: force || opts?.skipCache,
    signal: opts?.signal,
  } as any);
  return res.data;
};

export const lookupDealPhone = async (sdt: string, excludeId?: string, opts?: RequestOptions): Promise<PhoneLookupResponse> => {
  const params: Record<string, string> = { sdt };
  if (excludeId) params.exclude_id = excludeId;
  const res = await apiClient.get<PhoneLookupResponse>('/deal-entry/lookup-phone', { params, ...(opts || {}) } as any);
  return res.data;
};

export const saveSalesDeal = async (payload: Partial<SalesDealRecord> & { actor?: string }) => {
  const res = await apiClient.post('/deal-entry/deals', payload, { params: { compact: true } });
  return res.data;
};

export const updateSalesDealClasses = async (dealId: string, lop: string[], actor?: string) => {
  const res = await apiClient.put(`/deal-entry/deals/${dealId}/classes`, { lop, actor }, { params: { compact: true } });
  return res.data;
};

export const deleteSalesDeal = async (dealId: string, actor?: string) => {
  const res = await apiClient.delete(`/deal-entry/deals/${dealId}`, { params: { actor, compact: true } });
  return res.data;
};

export const batchDeleteSalesDeals = async (dealIds: string[], actor?: string) => {
  const res = await apiClient.post('/deal-entry/deals/batch-delete', { deal_ids: dealIds, actor }, { params: { compact: true } });
  return res.data;
};

export const saveDealEntryLists = async (lists: DealEntryLists, actor?: string) => {
  const res = await apiClient.put('/deal-entry/lists', { lists, actor });
  return res.data;
};

export const fetchDealEntryLogs = async (limit: number = 100, opts?: RequestOptions): Promise<{ ok: boolean; logs: DealAuditLogItem[] }> => {
  const res = await apiClient.get('/deal-entry/logs', { params: { limit }, ...(opts || {}) } as any);
  return res.data;
};

export interface DealSheetSyncConfig {
  ok?: boolean;
  configured?: boolean;
  webhook_url: string;
  sheet_url: string;
  only_students: boolean;
  auto_sync: boolean;
}

export const fetchDealSheetConfig = async (): Promise<DealSheetSyncConfig> => {
  const res = await apiClient.get('/deal-entry/sheet-sync/config');
  return res.data;
};

export const saveDealSheetConfig = async (payload: DealSheetSyncConfig): Promise<DealSheetSyncConfig> => {
  const res = await apiClient.put('/deal-entry/sheet-sync/config', payload);
  return res.data;
};

export const pushAllDealsToGoogleSheet = async (): Promise<{ ok: boolean; synced_count: number; message: string }> => {
  const res = await apiClient.post('/deal-entry/sheet-sync/push-all');
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
  ad_name?: string;
  campaign_id?: string;
  campaign_name?: string;
  image_url?: string;
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
  share_count?: number;
  view_count?: number;
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
  pageId?: string,
  opts?: RequestOptions
): Promise<FacebookMetricsResponse> => {
  const params: any = {};
  if (startDate) params.start_date = startDate;
  if (endDate) params.end_date = endDate;
  if (pageId) params.page_id = pageId;
  const res = await apiClient.get<FacebookMetricsResponse>('/facebook/metrics', { params, ...(opts || {}) } as any);
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
  pageId?: string,
  opts?: RequestOptions
): Promise<FacebookMetricsResponse> => {
  const params: any = {};
  if (startDate) params.start_date = startDate;
  if (endDate) params.end_date = endDate;
  if (pageId) params.page_id = pageId;
  const res = await apiClient.get<FacebookMetricsResponse>('/tiktok/metrics', { params, ...(opts || {}) } as any);
  return res.data;
};

export const syncTikTokViews = async (
  daysBack: number = 30,
  maxVideos: number = 25,
  pageId?: string
): Promise<{ status: string; checked: number; updated: number; failed: number; message: string }> => {
  const params: any = { days_back: daysBack, max_videos: maxVideos };
  if (pageId) params.page_id = pageId;
  const res = await apiClient.post('/tiktok/sync-views', null, { params, timeout: 90000 });
  clearClientApiCache('/tiktok/');
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
  employee?: string,
  opts?: RequestOptions
): Promise<WorkReportResponse> => {
  const params: any = {};
  if (startDate) params.start_date = startDate;
  if (endDate) params.end_date = endDate;
  if (employee) params.employee = employee;
  const res = await apiClient.get<WorkReportResponse>('/work-report', { params, ...(opts || {}) } as any);
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

export interface AddFriendLeadFilters {
  employees: string[];
  source_pages: string[];
  lead_tags: string[];
}

export interface AddFriendConfigResponse {
  pages: AddFriendPageOption[];
  templates: AddFriendTemplateOption[];
  tags: string[];
  tags_by_page?: Record<string, string[]>;
  lead_filters?: AddFriendLeadFilters;
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
  status: 'ADDED' | 'ALREADY_FRIEND' | 'PARTIAL' | 'DRY_RUN' | 'NOT_FOUND' | 'FAILED' | 'SERVER_ERROR' | 'AUTH_EXPIRED' | string;
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
  already_friend_count?: number;
  partial_count?: number;
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

export interface LeadsPhonesFilterParams {
  sourceChannel?: string;
  employee?: string;
  sourcePage?: string;
  tag?: string;
  excludeAddedTag?: boolean;
  limit?: number;
}

export interface LeadsPhonesResultItem {
  phone: string;
  name: string;
  source: string;
  employee?: string;
  tags?: string[];
  nhu_cau: string;
  line: string;
}

export const fetchLeadsWithPhonesForAddFriend = async (
  filters: LeadsPhonesFilterParams = {}
): Promise<{ count: number; items: LeadsPhonesResultItem[]; formatted_text: string }> => {
  const res = await apiClient.get('/add-friend/leads-phones', {
    params: {
      source_channel: filters.sourceChannel || 'all',
      ...(filters.employee ? { employee: filters.employee } : {}),
      ...(filters.sourcePage ? { source_page: filters.sourcePage } : {}),
      ...(filters.tag ? { tag: filters.tag } : {}),
      exclude_added_tag: filters.excludeAddedTag ?? true,
      limit: filters.limit ?? 50,
    },
  });
  return res.data;
};

export const startAddFriendCampaign = async (
  params: StartAddFriendParams
): Promise<{ status: string; task_id: string; campaign_name: string; total: number }> => {
  const res = await apiClient.post('/add-friend/start', params);
  return res.data;
};

export const fetchActiveAddFriendTask = async (): Promise<{ active: AddFriendTaskStatus | null }> => {
  const res = await apiClient.get<{ active: AddFriendTaskStatus | null }>('/add-friend/active');
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

// ───────────────────────── AI RAG Assistant API ─────────────────────────

export interface AiAssistantProfile {
  id: 'sale' | 'ke_toan' | 'quy_trinh';
  name: string;
  badge: string;
  description: string;
  categories: string[];
  sample_questions: string[];
  doc_count: number;
}

export interface AiAssistantsResponse {
  assistants: AiAssistantProfile[];
  total_chunks: number;
  masked_api_key: string;
  has_api_key: boolean;
}

export interface AiDocumentItem {
  doc_id: string;
  doc_name: string;
  category: string;
  chunk_count: number;
  preview: string;
  has_embedding: boolean;
  created_at: string;
}

export interface AiChatResponse {
  assistant_id: string;
  assistant_name: string;
  answer: string;
  model: string;
  sources: { doc_name: string; category: string; score: number }[];
  tools_used: string[];
}

export const fetchAiAssistants = async (): Promise<AiAssistantsResponse> => {
  const res = await apiClient.get<AiAssistantsResponse>('/ai/assistants');
  return res.data;
};

export const fetchAiDocuments = async (category?: string): Promise<{ documents: AiDocumentItem[] }> => {
  const res = await apiClient.get<{ documents: AiDocumentItem[] }>('/ai/documents', {
    params: category ? { category } : undefined,
  });
  return res.data;
};

export const ingestAiDocument = async (payload: {
  doc_name: string;
  category: string;
  content: string;
}): Promise<{ status: string; chunks_added: number; doc_name: string }> => {
  const res = await apiClient.post('/ai/documents', payload);
  return res.data;
};

export const deleteAiDocument = async (docId: string): Promise<{ status: string; deleted_chunks: number }> => {
  const res = await apiClient.delete(`/ai/documents/${docId}`);
  return res.data;
};

export const seedAiDocuments = async (): Promise<{ status: string; chunks_added: number; message: string }> => {
  const res = await apiClient.post('/ai/seed');
  return res.data;
};

export const updateAiApiKey = async (apiKey: string): Promise<{ status: string; masked_api_key: string }> => {
  const res = await apiClient.post('/ai/config', { api_key: apiKey });
  return res.data;
};

export const sendAiChatMessage = async (payload: {
  assistant_id: string;
  question: string;
  history: { role: 'user' | 'assistant'; content: string }[];
}, opts?: RequestOptions): Promise<AiChatResponse> => {
  const res = await apiClient.post<AiChatResponse>('/ai/chat', payload, { timeout: 120000, signal: opts?.signal });
  return res.data;
};

export interface AiDailyReviewData {
  date: string;
  generated_at: string;
  period_label: string;
  model: string;
  sources: string[];
  summary_status: 'good' | 'warning' | 'critical';
  headline: string;
  overview: string[];
  customer_insight: string[];
  process_sla: string[];
  actions: string[];
}

export interface AiDailyReviewResponse {
  review: AiDailyReviewData | null;
  is_today: boolean;
  generating: boolean;
  has_api_key: boolean;
}

export const fetchAiDailyReview = async (): Promise<AiDailyReviewResponse> => {
  const res = await apiClient.get<AiDailyReviewResponse>('/ai/daily-review');
  return res.data;
};

export const refreshAiDailyReview = async (): Promise<AiDailyReviewResponse> => {
  const res = await apiClient.post<AiDailyReviewResponse>('/ai/daily-review/refresh', undefined, {
    timeout: 60000,
  });
  return res.data;
};

// ==============================================================================
// QUERY & KẾT XUẤT DỮ LIỆU EXCEL (PROTECTED + EGRESS OPTIMIZED)
// ==============================================================================

export interface DataExportColumnMeta {
  key: string;
  label: string;
  default: boolean;
  db_field_count: number;
}

export interface DataExportOptions {
  columns: DataExportColumnMeta[];
  pages: string[];
  zalo_pages: string[];
  source_pages: string[];
  employees: string[];
  tags: string[];
  tags_by_page?: Record<string, string[]>;
  max_export_rows: number;
}

export interface DataExportFilterPayload {
  columns: string[];
  channel_group: 'all' | 'zalo' | 'source';
  pages: string[];
  employees: string[];
  employee_match_mode: 'any' | 'exact';
  student_filter: 'all' | 'non_student' | 'student';
  tags: string[];
  phone_filter: 'all' | 'has_phone' | 'no_phone';
  date_field: 'contacted_at' | 'first_created_at';
  date_from?: string | null;
  date_to?: string | null;
  search?: string | null;
  exclude_zalo_groups: boolean;
  dedupe_phone: boolean;
  sort_by: 'contacted_at' | 'first_created_at' | 'message_count' | 'name';
  sort_dir: 'desc' | 'asc';
}

export interface DataExportPreviewPayload extends DataExportFilterPayload {
  page: number;
  page_size: number;
}

export interface DataExportPreviewResponse {
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
  columns: { key: string; label: string }[];
  projected_db_fields: string[];
  rows: Record<string, string | number>[];
  query_ms: number;
  cached: boolean;
}

export const fetchDataExportOptions = async (): Promise<DataExportOptions> => {
  const res = await apiClient.get<DataExportOptions>('/data-export/options');
  return res.data;
};

export const previewDataExport = async (payload: DataExportPreviewPayload): Promise<DataExportPreviewResponse> => {
  const res = await apiClient.post<DataExportPreviewResponse>('/data-export/preview', payload);
  return res.data;
};

export const downloadDataExportExcel = async (
  payload: DataExportFilterPayload & { max_rows?: number; filename?: string }
): Promise<{ filename: string; rowCount: number; projectedDbCols: number }> => {
  const res = await apiClient.post('/data-export/export', payload, {
    responseType: 'blob',
  });

  const contentDisposition = String(res.headers['content-disposition'] || '');
  const match = contentDisposition.match(/filename="?([^"]+)"?/i);
  const filename = match?.[1] || `EzTech_Query_Export_${new Date().toISOString().slice(0, 10)}.xlsx`;
  const rowCount = Number(res.headers['x-export-row-count'] || 0);
  const projectedDbCols = Number(res.headers['x-projected-db-columns'] || 0);

  const blob = new Blob([res.data], {
    type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);

  return { filename, rowCount, projectedDbCols };
};

// ==============================================================================
// BẢNG TIN NỘI BỘ, NHẮC HẸN, CHECKLIST HÀNG NGÀY & ZALO NHẮC VIỆC
// ==============================================================================

export interface BulletinAttachment {
  type: string;
  url?: string | null;
  link?: string | null;
  title?: string | null;
  description?: string | null;
}

export interface BulletinReaderInfo {
  user_id: number;
  full_name: string;
  read_at: string | null;
}

export interface BulletinPostItem {
  id: number;
  pancake_message_id: string;
  group_name?: string | null;
  boss_key: string;
  boss_display_name: string;
  sender_name: string;
  title?: string | null;
  content: string;
  attachments: BulletinAttachment[];
  posted_at: string;
  is_pinned: boolean;
  is_read: boolean;
  read_at?: string | null;
  read_count: number;
  my_reminder_count: number;
  my_checklist_count: number;
  readers?: BulletinReaderInfo[] | null;
}

export interface BulletinPostsResponse {
  total: number;
  page: number;
  size: number;
  total_pages: number;
  summary: {
    total_all: number;
    unread_count: number;
    boss_counts: Record<string, number>;
  };
  items: BulletinPostItem[];
}

export interface WorkReminderItem {
  id: number;
  title: string;
  description?: string | null;
  remind_at: string;
  remind_at_display: string;
  due_date: string;
  priority: 'low' | 'normal' | 'high' | 'urgent';
  recurrence_rule?: 'none' | 'daily' | 'weekly' | 'monthly';
  status: 'pending' | 'completed' | 'snoozed' | 'cancelled';
  completed_at?: string | null;
  source_post_id?: number | null;
  source_post_title?: string | null;
  source_post_boss?: string | null;
  owner_user_id: number;
  owner_name?: string | null;
  notify_11h: boolean;
  notify_15h: boolean;
  notify_exact_time: boolean;
  exact_notified_at?: string | null;
  created_at?: string | null;
  created_count?: number;
  next_reminder?: WorkReminderItem | null;
}

export interface BulletinAiExtractResponse {
  post_id: number;
  model: string;
  summary: string;
  checklist_title: string;
  checklist_items: string[];
  suggested_reminder: {
    title: string;
    description: string;
    remind_at: string;
    priority: 'low' | 'normal' | 'high' | 'urgent';
  } | null;
}

export interface PendingRolloverItem {
  id: number;
  content: string;
  from_date: string;
  from_checklist_title: string;
}

export interface DailyChecklistTaskItem {
  id: number;
  checklist_id: number;
  content: string;
  is_done: boolean;
  done_at?: string | null;
  sort_order: number;
  note?: string | null;
  is_assigned?: boolean;
}

export interface DailyChecklistItemGroup {
  id: number;
  checklist_date: string;
  title: string;
  owner_user_id: number;
  owner_name?: string | null;
  source_post_id?: number | null;
  source_post_title?: string | null;
  source_post_boss?: string | null;
  is_recurring_daily: boolean;
  recurring_template_id?: number | null;
  admin_note?: string | null;
  admin_note_by?: string | null;
  is_assigned?: boolean;
  done_count: number;
  total_count: number;
  progress_pct: number;
  items: DailyChecklistTaskItem[];
  created_at?: string | null;
}

export interface DailyChecklistsResponse {
  checklist_date: string;
  is_admin: boolean;
  pending_reminders_count?: number;
  summary: {
    total_checklists: number;
    total_items: number;
    done_items: number;
    pending_items: number;
  };
  items: DailyChecklistItemGroup[];
}

export interface StaffZaloMapping {
  user_id: number;
  username: string;
  full_name: string;
  department: string;
  role: string;
  staff_id?: number | null;
  phone_number?: string | null;
  zalo_conversation_id?: string | null;
  zalo_display_name?: string | null;
  receive_daily_digest: boolean;
  is_active: boolean;
}

export interface ConsultantZaloContact {
  conversation_id: string;
  display_name: string;
  phone_number?: string | null;
  updated_at?: string | null;
}

export interface ZaloReminderLogItem {
  id: number;
  dispatch_date: string;
  slot: string;
  user_id?: number | null;
  staff_name: string;
  conversation_id?: string | null;
  message_text?: string;
  done_count: number;
  pending_count: number;
  status: string;
  error_message?: string | null;
  sent_at?: string | null;
}

export const fetchBulletinUnreadCount = async (): Promise<{ unread_count: number; total_posts: number }> => {
  const res = await apiClient.get<{ unread_count: number; total_posts: number }>('/bulletin/unread-count');
  return res.data;
};

export const fetchBulletinPosts = async (
  params: {
    boss_key?: string;
    read_status?: string;
    search?: string;
    start_date?: string;
    end_date?: string;
    page?: number;
    size?: number;
  },
  options?: RequestOptions
): Promise<BulletinPostsResponse> => {
  const res = await apiClient.get<BulletinPostsResponse>('/bulletin/posts', {
    params,
    signal: options?.signal,
  });
  return res.data;
};

export const fetchBulletinPostReaders = async (
  postId: number
): Promise<{ post_id: number; items: BulletinReaderInfo[] }> => {
  const res = await apiClient.get<{ post_id: number; items: BulletinReaderInfo[] }>(
    `/bulletin/posts/${postId}/readers`
  );
  return res.data;
};

export const markBulletinPostRead = async (postId: number): Promise<{ status: string; is_read: boolean }> => {
  const res = await apiClient.post(`/bulletin/posts/${postId}/read`);
  return res.data;
};

export const markAllBulletinPostsRead = async (
  bossKey = 'all'
): Promise<{ status: string; marked_count: number }> => {
  const res = await apiClient.post('/bulletin/posts/read-all', null, { params: { boss_key: bossKey } });
  return res.data;
};

export const unmarkBulletinPostRead = async (postId: number): Promise<{ status: string; is_read: boolean }> => {
  const res = await apiClient.delete(`/bulletin/posts/${postId}/read`);
  return res.data;
};

export const togglePinBulletinPost = async (postId: number): Promise<{ status: string; is_pinned: boolean }> => {
  const res = await apiClient.post(`/bulletin/posts/${postId}/pin`);
  return res.data;
};

export const syncBulletinPosts = async (force = false): Promise<{ success: boolean; inserted: number; merged?: number; message: string }> => {
  const res = await apiClient.post('/bulletin/sync', null, { params: { max_pages: force ? 10 : 3, force } });
  return res.data;
};

export const aiExtractBulletinPost = async (postId: number): Promise<BulletinAiExtractResponse> => {
  const res = await apiClient.post<BulletinAiExtractResponse>(`/bulletin/posts/${postId}/ai-extract`, null, { timeout: 60000 });
  return res.data;
};

export const fetchWorkReminders = async (params: {
  status?: string;
  due_date?: string;
  date_from?: string;
  date_to?: string;
  owner_user_id?: number;
  search?: string;
}): Promise<{ items: WorkReminderItem[]; total: number; is_admin: boolean }> => {
  const res = await apiClient.get('/bulletin/reminders', { params });
  return res.data;
};

export const createWorkReminder = async (payload: {
  title: string;
  description?: string;
  remind_at: string;
  priority?: string;
  recurrence_rule?: string;
  source_post_id?: number | null;
  owner_user_id?: number | null;
  owner_user_ids?: number[] | null;
  notify_11h?: boolean;
  notify_15h?: boolean;
  notify_exact_time?: boolean;
}): Promise<WorkReminderItem> => {
  const res = await apiClient.post<WorkReminderItem>('/bulletin/reminders', payload);
  return res.data;
};

export const updateWorkReminder = async (
  id: number,
  payload: Partial<{
    title: string;
    description: string;
    remind_at: string;
    priority: string;
    recurrence_rule: string;
    status: string;
    notify_11h: boolean;
    notify_15h: boolean;
    notify_exact_time: boolean;
  }>
): Promise<WorkReminderItem> => {
  const res = await apiClient.patch<WorkReminderItem>(`/bulletin/reminders/${id}`, payload);
  return res.data;
};

export const deleteWorkReminder = async (id: number): Promise<void> => {
  await apiClient.delete(`/bulletin/reminders/${id}`);
};

export const fetchDailyChecklists = async (params: {
  checklist_date?: string;
  owner_user_id?: number;
}): Promise<DailyChecklistsResponse> => {
  const res = await apiClient.get<DailyChecklistsResponse>('/bulletin/checklists', { params });
  return res.data;
};

export interface ClassScheduleEvent {
  id: string;
  date: string;
  time_range: string;
  course_code: string;
  course_type: string;
  course_name: string;
  session_label: string;
  schedule_days: string;
  status: string;
  instructor: string;
  assistants: string[];
  note: string;
  is_planned: boolean;
}

export interface ClassScheduleResponse {
  sheet_url: string;
  auto_sync_enabled?: boolean;
  sync_interval_minutes?: number;
  last_synced_at: string | null;
  events: ClassScheduleEvent[];
  total: number;
}

export const fetchChecklistsMonthSummary = async (params: {
  date_from: string;
  date_to: string;
  owner_user_id?: number;
}): Promise<{ days: Record<string, { total_items: number; done_items: number }> }> => {
  const res = await apiClient.get('/bulletin/checklists/month-summary', { params });
  return res.data;
};

export const fetchClassSchedule = async (params?: {
  date_from?: string;
  date_to?: string;
}): Promise<ClassScheduleResponse> => {
  const res = await apiClient.get<ClassScheduleResponse>('/bulletin/class-schedule', { params });
  return res.data;
};

export const syncClassSchedule = async (payload: {
  sheet_url?: string;
  csv_text?: string;
  auto_sync_enabled?: boolean;
  sync_interval_minutes?: number;
}): Promise<ClassScheduleResponse & { success: boolean }> => {
  const res = await apiClient.post('/bulletin/class-schedule/sync', payload, { timeout: 30000 });
  return res.data;
};

export const uploadClassScheduleFile = async (
  file: File
): Promise<ClassScheduleResponse & { success: boolean }> => {
  const formData = new FormData();
  formData.append('file', file);
  const res = await apiClient.post('/bulletin/class-schedule/upload', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 30000,
  });
  return res.data;
};

export const fetchPendingRolloverItems = async (
  targetDate?: string
): Promise<{ target_date: string; count: number; items: PendingRolloverItem[] }> => {
  const res = await apiClient.get('/bulletin/checklists/pending-rollover', {
    params: targetDate ? { target_date: targetDate } : undefined,
  });
  return res.data;
};

export const rolloverPendingChecklistItems = async (payload: {
  target_date?: string;
  item_ids?: number[];
  title?: string;
}): Promise<{ status: string; moved_count: number; message: string }> => {
  const res = await apiClient.post('/bulletin/checklists/rollover', payload);
  return res.data;
};

export const createDailyChecklist = async (payload: {
  title: string;
  checklist_date?: string;
  items: string[];
  source_post_id?: number | null;
  owner_user_id?: number | null;
  owner_user_ids?: number[] | null;
  is_recurring_daily?: boolean;
  admin_note?: string | null;
}): Promise<DailyChecklistItemGroup & { created_count?: number }> => {
  const res = await apiClient.post('/bulletin/checklists', payload);
  return res.data;
};

export const updateDailyChecklist = async (
  checklistId: number,
  payload: Partial<{ title: string; is_recurring_daily: boolean; admin_note: string }>
): Promise<DailyChecklistItemGroup> => {
  const res = await apiClient.patch<DailyChecklistItemGroup>(`/bulletin/checklists/${checklistId}`, payload);
  return res.data;
};

export const deleteDailyChecklist = async (checklistId: number): Promise<void> => {
  await apiClient.delete(`/bulletin/checklists/${checklistId}`);
};

export const addChecklistTaskItem = async (
  checklistId: number,
  content: string
): Promise<DailyChecklistTaskItem> => {
  const res = await apiClient.post<DailyChecklistTaskItem>(`/bulletin/checklists/${checklistId}/items`, { content });
  return res.data;
};

export const updateChecklistTaskItem = async (
  itemId: number,
  payload: Partial<{ content: string; is_done: boolean; note: string }>
): Promise<DailyChecklistTaskItem> => {
  const res = await apiClient.patch<DailyChecklistTaskItem>(`/bulletin/checklists/items/${itemId}`, payload);
  return res.data;
};

export const deleteChecklistTaskItem = async (itemId: number): Promise<void> => {
  await apiClient.delete(`/bulletin/checklists/items/${itemId}`);
};

export const fetchAdminBulletinStaff = async (): Promise<{ items: StaffZaloMapping[] }> => {
  const res = await apiClient.get('/bulletin/admin/staff');
  return res.data;
};

export const updateAdminBulletinStaff = async (
  userId: number,
  payload: {
    full_name?: string;
    phone_number?: string | null;
    zalo_conversation_id?: string | null;
    zalo_display_name?: string | null;
    receive_daily_digest: boolean;
    is_active: boolean;
  }
): Promise<{ status: string }> => {
  const res = await apiClient.put(`/bulletin/admin/staff/${userId}`, payload);
  return res.data;
};

export const syncConsultantZaloContacts = async (
  autoApply = true
): Promise<{ success: boolean; contacts: ConsultantZaloContact[]; auto_matched: number; message: string }> => {
  const res = await apiClient.post('/bulletin/admin/staff/sync-zalo-contacts', { auto_apply: autoApply, max_convs: 300 });
  return res.data;
};

export const testStaffZaloMessage = async (
  userId: number,
  message?: string
): Promise<{ success: boolean; message: string }> => {
  const res = await apiClient.post(`/bulletin/admin/staff/${userId}/test-zalo`, { message });
  return res.data;
};

export const fetchBulletinConfig = async (): Promise<Record<string, any>> => {
  const res = await apiClient.get('/bulletin/admin/config');
  return res.data;
};

export const updateBulletinConfig = async (payload: Record<string, any>): Promise<Record<string, any>> => {
  const res = await apiClient.put('/bulletin/admin/config', payload);
  return res.data;
};

export const dispatchBulletinReminders = async (payload: {
  slot: '11h' | '15h' | 'exact' | 'manual';
  target_date?: string;
  user_id?: number;
  dry_run?: boolean;
  force?: boolean;
}): Promise<any> => {
  const res = await apiClient.post('/bulletin/admin/dispatch', payload, { timeout: 120000 });
  return res.data;
};

export const fetchBulletinZaloLogs = async (limit = 50): Promise<{ items: ZaloReminderLogItem[] }> => {
  const res = await apiClient.get('/bulletin/admin/logs', { params: { limit } });
  return res.data;
};


// ==========================================
// CLASS LIST (Danh sách lớp học)
// ==========================================
export interface ClassStudentItem {
  id: string;
  hoTen: string;
  sdt: string;
  linkPancake: string;
  linkSupport: string;
  lop: string[];
  nvCS: string;
}

export interface ClassListResponse {
  ok: boolean;
  classes: string[];
  class_counts: Record<string, number>;
  unassigned_class_count: number;
  staff_list: string[];
  total: number;
  students: ClassStudentItem[];
}

export const fetchClassListStudents = async (
  params?: {
    class_name?: string;
    staff?: string;
    search?: string;
    force?: boolean;
  },
  opts?: RequestOptions
): Promise<ClassListResponse> => {
  const query: Record<string, any> = {};
  if (params?.class_name) query.class_name = params.class_name;
  if (params?.staff) query.staff = params.staff;
  if (params?.search) query.search = params.search;
  if (params?.force) query.force = true;
  const res = await apiClient.get<ClassListResponse>('/class-list/students', {
    params: query,
    ...(opts || {}),
  } as any);
  return res.data;
};



