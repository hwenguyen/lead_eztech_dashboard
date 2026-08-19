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
  contacted_leads: number;
  phone_leads: number;
  new_leads_employee_stats?: Record<string, number>;
  phone_leads_employee_stats?: Record<string, number>;
  tag_stats?: Record<string, number>;
}

export interface TrendData {
  date: string;
  new_leads: number;
  contacted_leads: number;
  phone_leads: number;
}

export interface Lead {
  id: number;
  customer_id: string;
  name?: string;
  phone_number?: string;
  page_id: string;
  first_created_at: string;
  status_tag?: string;
  assigned_users?: string;
  messages?: string;
  is_contacted: boolean;
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

export const fetchLeads = async (pageId?: string, employee?: string, startDate?: string, endDate?: string) => {
  const params: any = { page: 1, size: 50 };
  if (pageId) params.page_id = pageId;
  if (employee) params.employee = employee;
  if (startDate) params.start_date = startDate;
  if (endDate) params.end_date = endDate;
  const res = await apiClient.get<{data: Lead[]}>('/leads/list', { params });
  return res.data;
};

export const fetchEmployees = async () => {
  try {
    const res = await apiClient.get<{data: string[]}>('/employees/list');
    return res.data.data;
  } catch (error) {
    console.error("fetchEmployees failed", error);
    return [];
  }
};
