import React from 'react';
import { logger } from '../../services/logger';

interface State {
  error: Error | null;
}

/** Catches render-time crashes, logs them, and shows a fallback instead of a blank page. */
export class ErrorBoundary extends React.Component<{ children: React.ReactNode }, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    logger.error('React render error', error, {
      stack: `${error.stack ?? ''}\nComponent stack:${info.componentStack ?? ''}`,
    });
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div role="alert" className="min-h-screen flex items-center justify-center bg-surface text-on-surface p-8">
        <div className="max-w-md text-center space-y-3">
          <p className="font-semibold">Something went wrong rendering this page.</p>
          <p className="text-xs text-outline">The error has been logged. Reload to try again.</p>
          <button
            type="button"
            onClick={() => window.location.reload()}
            className="px-3 py-1.5 rounded border border-surface-container text-xs font-mono"
          >
            RELOAD
          </button>
        </div>
      </div>
    );
  }
}
