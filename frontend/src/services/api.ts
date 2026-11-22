import axios from 'axios';
import {
  BenchmarkResponse,
  CashflowItem,
  MatchedBenchmarkResponse,
  PortfolioHistoryResponse,
  PortfolioMetricsResponse,
  PortfolioSummary,
  UploadResult,
  UserProfile,
} from '../types';
import { logger } from './logger';

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

// One log entry per failed API call, carrying the backend's X-Request-ID so the browser entry
// and the server's access line can be joined. Path only: params can carry tickers or keys, and
// headers are never read (the Trading 212 routes send credentials in them).
api.interceptors.response.use(
  (response) => response,
  (error) => {
    const status: number | undefined = error?.response?.status;
    const method = (error?.config?.method ?? 'get').toUpperCase();
    const path = `${error?.config?.baseURL ?? ''}${error?.config?.url ?? ''}`.split('?')[0];
    const requestId: string | undefined = error?.response?.headers?.['x-request-id'];
    const outcome = status ? `HTTP ${status}` : error?.code === 'ECONNABORTED' ? 'timeout' : 'network error';
    const message = `${method} ${path} failed: ${outcome}`;
    if (!status || status >= 500) logger.error(message, undefined, { request_id: requestId });
    else logger.warn(message, undefined, { request_id: requestId });
    return Promise.reject(error);
  },
);

export const authApi = {
  login: async (email: string, password: string) => (await api.post('/auth/login', { email, password })).data,
  signup: async (email: string, password: string) => (await api.post('/auth/signup', { email, password })).data,
  getMe: async (): Promise<UserProfile> => (await api.get('/auth/me')).data,
  logEvent: async (event: any) => (await api.post('/auth/log-event', event)).data,
};

export const portfolioApi = {
  getSummary: async (): Promise<PortfolioSummary> => (await api.get('/trades/summary')).data,
  // Served from user_portfolio_values.json. Always one account's series: omitting accountId
  // lets the backend fall back to the caller's own key, it does not aggregate (KAN-46).
  getHistory: async (accountId?: string): Promise<PortfolioHistoryResponse> =>
    (await api.get('/portfolio/history', { params: accountId ? { account_id: accountId } : {} })).data,
  // Values the uploaded trade history and writes it to user_portfolio_values.json. data_quality
  // describes this run only.
  computeHistory: async (refresh = false): Promise<PortfolioHistoryResponse> =>
    (await api.post('/portfolio/history/compute', null, { params: { refresh } })).data,
  // Risk statistics for one stored series, keyed by timeframe. Separate from getHistory so the
  // tiles and the chart share one window definition (the server's) without a second fetch.
  getMetrics: async (accountId?: string): Promise<PortfolioMetricsResponse> =>
    (await api.get('/portfolio/metrics', { params: accountId ? { account_id: accountId } : {} })).data,
  // Raw index closes, not portfolio units and not normalised server-side: rebase them onto the
  // portfolio's own first visible value so the comparison holds for whichever window is shown.
  // One call per symbol; omitting `symbol` leaves the server's default in place.
  getBenchmark: async (startDate?: string, symbol?: string): Promise<BenchmarkResponse> =>
    (
      await api.get('/portfolio/benchmark', {
        params: { ...(startDate ? { start_date: startDate } : {}), ...(symbol ? { symbol } : {}) },
      })
    ).data,
  // The index bought with the account's own deposits, valued in GBP. Takes no start date: the
  // series begins at the first deposit, and trimming it to a window is the caller's job. These
  // points are absolute, so rebasing them would undo the thing that makes them comparable.
  getMatchedBenchmark: async (
    symbol?: string,
    accountId?: string,
  ): Promise<MatchedBenchmarkResponse> =>
    (
      await api.get('/portfolio/benchmark/matched', {
        params: { ...(symbol ? { symbol } : {}), ...(accountId ? { account_id: accountId } : {}) },
      })
    ).data,
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
  getOrders: async (key?: string, secret?: string) =>
    (await api.get('/trading212/orders', { headers: { 'x-t212-key': key, 'x-t212-secret': secret } })).data,
  getDividends: async (key?: string, secret?: string) =>
    (await api.get('/trading212/dividends', { headers: { 'x-t212-key': key, 'x-t212-secret': secret } })).data,
};

export default api;

