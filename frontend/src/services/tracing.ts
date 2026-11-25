/**
 * Browser tracing. Each API call gets a real CLIENT span that is exported, so the backend's
 * request span has a parent that actually reaches the trace store (no "missing root span").
 *
 * Spans go to the same-origin `/otlp/v1/traces` route; nginx forwards it to the OTel Collector,
 * which adds the vendor credentials. Nothing secret ships to the browser, and changing vendor
 * (Grafana -> CloudWatch / GCP) is a collector config change only.
 */
import { SpanKind, SpanStatusCode, context, propagation, trace, type Span } from '@opentelemetry/api';
import { OTLPTraceExporter } from '@opentelemetry/exporter-trace-otlp-http';
import { resourceFromAttributes } from '@opentelemetry/resources';
import { BatchSpanProcessor, WebTracerProvider } from '@opentelemetry/sdk-trace-web';
import { ATTR_SERVICE_NAME } from '@opentelemetry/semantic-conventions';

const provider = new WebTracerProvider({
  resource: resourceFromAttributes({
    [ATTR_SERVICE_NAME]: 'web-portfolio',
    'service.namespace': 'st-my-investment2',
    'deployment.environment': import.meta.env.MODE,
  }),
  spanProcessors: [
    new BatchSpanProcessor(
      new OTLPTraceExporter({ url: new URL('/otlp/v1/traces', window.location.origin).href }),
    ),
  ],
});
// Installs the W3C trace-context propagator used by startRequestSpan().
provider.register();

const tracer = trace.getTracer('web-portfolio');

/** Start a CLIENT span for an outgoing request and return the headers that continue it. */
export const startRequestSpan = (method: string, path: string) => {
  const span = tracer.startSpan(`${method} ${path}`, {
    kind: SpanKind.CLIENT,
    attributes: { 'http.request.method': method, 'url.path': path },
  });
  const headers: Record<string, string> = {};
  propagation.inject(trace.setSpan(context.active(), span), headers);
  return { span, headers };
};

export const endRequestSpan = (span: Span, status?: number, error?: string) => {
  if (status !== undefined) span.setAttribute('http.response.status_code', status);
  if (error || (status !== undefined && status >= 500)) {
    span.setStatus({ code: SpanStatusCode.ERROR, message: error });
    if (error) span.setAttribute('error.type', error);
  }
  span.end();
};
