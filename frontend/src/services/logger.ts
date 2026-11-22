/**
 * Browser-side logger. Entries are batched and posted to the backend's telemetry route,
 * which re-emits them through its own pipeline (stdout + OTLP), tagged `web-portfolio`.
 *
 * Uses `fetch` rather than the shared axios instance so a failing telemetry call can never
 * trigger the axios error interceptor and log itself in a loop. Telemetry failures are dropped
 * silently on purpose: a broken page must not amplify its own traffic.
 */

type Level = 'debug' | 'info' | 'warn' | 'error';

interface Entry {
  level: Level;
  message: string;
  ts: string;
  view?: string;
  path?: string;
  request_id?: string;
  stack?: string;
  count: number;
}

const ENDPOINT = '/api/v1/telemetry/client-logs';
const MAX_BATCH = 20; // backend schema cap
const FLUSH_MS = 5000;
const MAX_QUEUE = 100;
const MAX_MESSAGE = 1000;
const MAX_STACK = 4000;

const SESSION_ID =
  typeof crypto !== 'undefined' && 'randomUUID' in crypto
    ? crypto.randomUUID().slice(0, 16)
    : Math.random().toString(36).slice(2, 18);

let queue: Entry[] = [];
let timer: ReturnType<typeof setTimeout> | null = null;
let currentView: string | undefined;

// Strip credentials a message might carry (an axios error can embed a URL with a key).
const scrub = (text: string) =>
  text.replace(/([?&](?:api_?key|apikey|api_?token|token|secret|password|access_token)=)[^&\s"']+/gi, '$1[redacted]');

const flush = (useBeacon = false) => {
  if (timer) {
    clearTimeout(timer);
    timer = null;
  }
  while (queue.length) {
    const entries = queue.splice(0, MAX_BATCH);
    const body = JSON.stringify({ entries, session_id: SESSION_ID, release: import.meta.env.MODE });
    const token = localStorage.getItem('access_token');
    fetch(ENDPOINT, {
      method: 'POST',
      // keepalive lets the final batch survive a page unload.
      keepalive: useBeacon,
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body,
    }).catch(() => undefined);
  }
};

const enqueue = (level: Level, message: string, extra: Partial<Entry> = {}) => {
  const msg = scrub(message).slice(0, MAX_MESSAGE);
  // Collapse repeats (a render loop, a polling failure) into one entry with a count.
  const last = queue[queue.length - 1];
  if (last && last.level === level && last.message === msg) {
    last.count = Math.min(last.count + 1, 1000);
    return;
  }
  if (queue.length >= MAX_QUEUE) queue.shift();
  queue.push({
    level,
    message: msg,
    ts: new Date().toISOString(),
    view: currentView,
    path: window.location.pathname.slice(0, 256),
    count: 1,
    ...extra,
    stack: extra.stack ? scrub(extra.stack).slice(0, MAX_STACK) : undefined,
  });
  if (queue.length >= MAX_BATCH) flush();
  else if (!timer) timer = setTimeout(() => flush(), FLUSH_MS);
};

const describe = (err: unknown): { message: string; stack?: string } => {
  if (err instanceof Error) return { message: `${err.name}: ${err.message}`, stack: err.stack };
  return { message: typeof err === 'string' ? err : JSON.stringify(err) ?? String(err) };
};

const emit = (level: Level, message: string, err?: unknown, extra: Partial<Entry> = {}) => {
  if (import.meta.env.DEV) {
    const fn = level === 'error' ? console.error : level === 'warn' ? console.warn : console.info;
    err === undefined ? fn(message) : fn(message, err);
  }
  if (level === 'debug') return;
  const detail = err === undefined ? undefined : describe(err);
  enqueue(level, detail ? `${message}: ${detail.message}` : message, { stack: detail?.stack, ...extra });
};

export const logger = {
  info: (message: string, extra?: Partial<Entry>) => emit('info', message, undefined, extra),
  warn: (message: string, err?: unknown, extra?: Partial<Entry>) => emit('warn', message, err, extra),
  error: (message: string, err?: unknown, extra?: Partial<Entry>) => emit('error', message, err, extra),
  /** Tag subsequent entries with the workspace tab the user is on. */
  setView: (view: string) => {
    currentView = view.slice(0, 64);
  },
};

let installed = false;

/** Capture what no try/catch saw: runtime errors and unhandled promise rejections. */
export const installGlobalErrorCapture = () => {
  if (installed) return;
  installed = true;
  window.addEventListener('error', (e) => {
    logger.error('Uncaught error', e.error ?? e.message);
  });
  window.addEventListener('unhandledrejection', (e) => {
    logger.error('Unhandled promise rejection', e.reason);
  });
  window.addEventListener('pagehide', () => flush(true));
};
