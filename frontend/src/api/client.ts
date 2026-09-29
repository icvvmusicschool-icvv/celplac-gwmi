// Cliente mínimo da API. Substitui os geradores DEMO do protótipo página a página.
import type {
  CyclePosition, Competitor, Destination, DestinationShift, Envelope, ExportsSummary, Flow, GeoEvent,
  IndexComponent, IndexResult, NcmSearchRow, NewsItem, PulseItem, SignalState, TraceSeries,
} from "./contracts";

const BASE = (import.meta as any).env?.VITE_GWMI_API ?? "http://localhost:8000/v1";

async function get<T>(path: string, params: Record<string, unknown> = {}): Promise<Envelope<T>> {
  const q = new URLSearchParams(
    Object.entries(params).filter(([, v]) => v !== undefined && v !== null).map(([k, v]) => [k, String(v)]));
  const qs = q.toString();
  const r = await fetch(`${BASE}${path}${qs ? `?${qs}` : ""}`);
  if (!r.ok) throw new Error(`${r.status} ${path}`);
  return r.json();
}

export const api = {
  pulse: (history_months = 24) => get<PulseItem[]>("/pulse", { history_months }),
  exportsSummary: (months = 12, family?: string) => get<ExportsSummary | null>("/trade/exports/summary", { months, family }),
  destinations: (months = 12, family?: string) => get<Destination[]>("/trade/exports/destinations", { months, family }),
  shift: (months = 12) => get<DestinationShift>("/trade/exports/shift", { months }),
  flows: (months = 12) => get<Flow[]>("/trade/flows", { months }),
  ncmSearch: (p: { q?: string; family?: string; partner?: string; year?: number; month?: number }) =>
    get<NcmSearchRow[]>("/trade/ncm/search", p),
  competitors: (hs4 = "4412") => get<Competitor[]>("/trade/competitors", { hs4 }),
  events: (category?: string) => get<GeoEvent[]>("/events", { category }),
  news: (impact_class?: string) => get<NewsItem[]>("/news", { impact_class }),
  signals: () => get<SignalState[]>("/signals"),
  cycle: () => get<CyclePosition[]>("/cycle"),
  traceSeries: (code: string, geo: string, period?: string) => get<TraceSeries>(`/trace/series/${code}`, { geo, period }),
  index: async (components?: IndexComponent[]): Promise<Envelope<IndexResult | null>> => {
    const r = await fetch(`${BASE}/index`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(components ? { components } : {}),
    });
    return r.json();
  },
};
