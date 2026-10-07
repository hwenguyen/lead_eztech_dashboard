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
