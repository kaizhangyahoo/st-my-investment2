import axios from 'axios';
import { PortfolioSummary, PortfolioHistoryPoint, CashflowItem, UserProfile } from '../types';

const api = axios.create({
  baseURL: '/api/v1',
  headers: {
    'Content-Type': 'application/json',
  },
});

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('access_token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

export const authApi = {
  login: async (email: string, password: string) => (await api.post('/auth/login', { email, password })).data,
  signup: async (email: string, password: string) => (await api.post('/auth/signup', { email, password })).data,
  getMe: async (): Promise<UserProfile> => (await api.get('/auth/me')).data,
  logEvent: async (event: any) => (await api.post('/auth/log-event', event)).data,
};

export const portfolioApi = {
  getSummary: async (): Promise<PortfolioSummary> => (await api.get('/trades/summary')).data,
  getHistory: async (accountId: string = 'default'): Promise<PortfolioHistoryPoint[]> => 
    (await api.get('/portfolio/history', { params: { account_id: accountId } })).data,
  getWaterfall: async (): Promise<CashflowItem[]> => (await api.get('/trades/waterfall')).data,
  uploadFiles: async (files: File[]) => {
    const formData = new FormData();
    files.forEach((file) => formData.append('files', file));
    return (await api.post('/trades/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })).data;
  },
};

export const tickersApi = {
  getMappings: async (): Promise<Record<string, string>> => (await api.get('/tickers/mappings')).data,
  updateMappings: async (mappings: Record<string, string>) => (await api.put('/tickers/mappings', { mappings })).data,
  resolve: async (marketNames: string[]): Promise<Record<string, string | null>> => 
    (await api.post('/tickers/resolve', { market_names: marketNames })).data,
};

export const t212Api = {
  getOverview: async (key?: string, secret?: string) => 
    (await api.get('/trading212/overview', { headers: { 'x-t212-key': key, 'x-t212-secret': secret } })).data,
  getPositions: async (key?: string, secret?: string) => 
    (await api.get('/trading212/positions', { headers: { 'x-t212-key': key, 'x-t212-secret': secret } })).data,
};

export default api;

