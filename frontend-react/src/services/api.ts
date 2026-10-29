import axios from 'axios';

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

// Bắt lỗi 401 Unauthorized để yêu cầu đăng nhập lại
apiClient.interceptors.response.use(
  (response) => response,
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

// ==========================================
// DEAL WIN (Google Sheet / Form Học Viên)
// ==========================================

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
  time_filter?: string;
  days_ago?: number;
  phone_filter?: string;
  limit?: number;
  template: string;
  exclude_already_sent?: boolean;
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
  time_filter?: string;
  days_ago?: number;
  phone_filter?: string;
  limit: number;
  delay: number;
  dry_run: boolean;
  exclude_already_sent: boolean;
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
