/**
 * Type declarations for 'plotly.js-dist-min'.
 *
 * NOTE (KAN-36):
 * We intentionally import 'plotly.js-dist-min' directly via imperative Plotly.react/relayout/purge
 * calls in PriceTradeChart.tsx rather than using the 'react-plotly.js' wrapper. The imperative API
 * is needed for custom behaviors like reset view (relayout + purge) and fine-grained ref control.
 *
 * 'react-plotly.js' remains listed in package.json to avoid breaking offline/Artifactory npm installs
 * caused by package-lock.json regeneration.
 *
 * The shim acts as an allowlist for the methods actively used in this codebase.
 */
declare module 'plotly.js-dist-min' {
  const Plotly: {
    react: (el: HTMLElement, data: unknown[], layout?: unknown, config?: unknown) => Promise<unknown>;
    relayout: (el: HTMLElement, update: Record<string, unknown>) => Promise<unknown>;
    purge: (el: HTMLElement) => void;
  };
  export default Plotly;
}
