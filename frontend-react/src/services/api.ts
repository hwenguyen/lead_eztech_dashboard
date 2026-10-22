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
  source_channel?: string;
  note?: string;
  course_name?: string;
  payment_status?: string;
  care_by?: string;
  is_student?: boolean;
  lead_tag?: string;
  dim_lead_id?: number;
  raw_data?: Record<string, any>;
  created_at?: string;
}

export interface DealWinSummary {
  total_deals: number;
  paid_deals: number;
  top_sales_person?: string;
  top_product?: string;
  sales_person_stats: Record<string, number>;
  product_stats: Record<string, number>;
  source_stats: Record<string, number>;
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
  products: string[];
}

export const fetchDealWinSummary = async (
  startDate?: string,
  endDate?: string,
  salesPerson?: string,
  productName?: string,
  onlyStudent: boolean = true
): Promise<DealWinSummary> => {
  const params: any = { only_student: onlyStudent };
  if (startDate) params.start_date = startDate;
  if (endDate) params.end_date = endDate;
  if (salesPerson) params.sales_person = salesPerson;
  if (productName) params.product_name = productName;
  const res = await apiClient.get<DealWinSummary>('/deals/summary', { params });
  return res.data;
};

export const fetchDealWinList = async (
  page: number = 1,
  size: number = 20,
  startDate?: string,
  endDate?: string,
  salesPerson?: string,
  productName?: string,
  search?: string,
  onlyStudent: boolean = true
): Promise<DealWinListResponse> => {
  const params: any = { page, size, only_student: onlyStudent };
  if (startDate) params.start_date = startDate;
  if (endDate) params.end_date = endDate;
  if (salesPerson) params.sales_person = salesPerson;
  if (productName) params.product_name = productName;
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
