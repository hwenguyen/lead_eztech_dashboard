import axios from 'axios';

// Get API URL from env, or default to relative /api if deployed together
const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000/api';

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
  name: string | null;
  phone_number: string | null;
  page_id: string;
  first_created_at: string;
  status_tag: string | null;
  is_contacted: boolean;
}

export const fetchSummary = async (startDate: string, endDate: string, pageId?: string) => {
  const params = { start_date: startDate, end_date: endDate, ...(pageId && { page_id: pageId }) };
  const response = await apiClient.get<SummaryData>('/metrics/summary', { params });
  return response.data;
};

export const fetchTrend = async (startDate: string, endDate: string, pageId?: string) => {
  const params = { start_date: startDate, end_date: endDate, ...(pageId && { page_id: pageId }) };
  const response = await apiClient.get<{ data: TrendData[] }>('/metrics/trend', { params });
  return response.data.data;
};

export const fetchLeads = async (pageId?: string, page = 1, size = 50) => {
  const params = { page, size, ...(pageId && { page_id: pageId }) };
  const response = await apiClient.get<{ data: Lead[], total: number }>('/leads/list', { params });
  return response.data;
};
