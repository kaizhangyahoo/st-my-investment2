import axios from 'axios';
import { PortfolioSummary, PortfolioHistoryResponse, CashflowItem, UserProfile, UploadResult } from '../types';

const api = axios.create({
  baseURL: '/api/v1',
  // Without this a hung backend leaves the dashboard showing sample data forever.
  timeout: 60000,
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
  // Served from user_portfolio_values.json. No accountId returns every stored account summed
  // per date; passing one (e.g. "QX2B3") returns that account's series.
  getHistory: async (accountId?: string): Promise<PortfolioHistoryResponse> =>
    (await api.get('/portfolio/history', { params: accountId ? { account_id: accountId } : {} })).data,
  // Values the uploaded trade history and writes it to user_portfolio_values.json. data_quality
  // describes this run only.
  computeHistory: async (refresh = false): Promise<PortfolioHistoryResponse> =>
    (await api.post('/portfolio/history/compute', null, { params: { refresh } })).data,
  getWaterfall: async (): Promise<CashflowItem[]> => (await api.get('/trades/waterfall')).data,
  uploadFiles: async (files: File[]): Promise<UploadResult> => {
    const formData = new FormData();
    files.forEach((file) => formData.append('files', file));
    return (await api.post('/trades/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })).data;
  },
  reset: async () => (await api.post('/trades/reset')).data,
};

export interface OhlcResponse {
  ticker: string;
  currency: string | null;
  points: { date: string; close: number }[];
}

export const marketDataApi = {
  getOhlc: async (ticker: string, startDate: string): Promise<OhlcResponse> =>
    (await api.get(`/market-data/ohlc/${encodeURIComponent(ticker)}`, { params: { start_date: startDate } })).data,
};

export const tickersApi = {
  getMappings: async (): Promise<Record<string, string>> => (await api.get('/tickers/mappings')).data,
  // Merges into the stored map. Use replaceMappings for anything that removes a key.
  updateMappings: async (mappings: Record<string, string>): Promise<Record<string, string>> =>
    (await api.put('/tickers/mappings', { mappings })).data,
  // The payload becomes the whole map -- the only way a delete or rename reaches the file.
  replaceMappings: async (mappings: Record<string, string>): Promise<Record<string, string>> =>
    (await api.put('/tickers/mappings', { mappings, replace: true })).data,
  resolve: async (marketNames: string[]): Promise<Record<string, string | null>> => 
    (await api.post('/tickers/resolve', { market_names: marketNames })).data,
};

// Prefer the backend's validation message (e.g. a duplicate name) over axios's generic status text.
export const apiErrorMessage = (err: any, fallback: string): string => {
  const detail = err?.response?.data?.detail;
  return typeof detail === 'string' ? detail : err?.message || fallback;
};

export const t212Api = {
  getOverview: async (key?: string, secret?: string) => 
    (await api.get('/trading212/overview', { headers: { 'x-t212-key': key, 'x-t212-secret': secret } })).data,
  getPositions: async (key?: string, secret?: string) => 
    (await api.get('/trading212/positions', { headers: { 'x-t212-key': key, 'x-t212-secret': secret } })).data,
};

export default api;

