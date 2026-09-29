// Contratos da API v1 — CELPLAC GWMI (Fase 2).
// Espelham backend/app (envelope.py + routers). A fonte da verdade é o OpenAPI em /openapi.json;
// estes tipos servem o frontend React enquanto a geração automática (openapi-typescript) não é ligada.

export type Status = "ok" | "DADO INDISPONÍVEL";
export type Kind = "data" | "indicator" | "analysis" | "hypothesis" | "signal" | "alert";

export interface SourceRef {
  source_id: string;
  name: string;
  url: string | null;
  source_type: string;
  periodicity: string;
  methodology: string | null;
  license_note: string | null;
  reliability: "ALTA" | "MÉDIA" | "BAIXA" | null;
}

export interface Envelope<T> {
  status: Status;
  data: T;
  meta: {
    is_simulated: boolean;          // true ⇒ exibir selo DEMO / SIMULATED DATA
    kind: Kind;
    sources: SourceRef[];
    period: Record<string, unknown> | null;
    notes: string[];
    generated_at: string;
  };
}

export interface PulseItem {
  indicator_code: string; geo_iso3: string; name_pt: string; unit: string; category: string;
  polarity: -1 | 0 | 1; pulse_key: string; kind: "data" | "indicator";
  period: string; value: number; prev_period: string | null; prev_value: number | null;
  chg_mom: number | null; chg_yoy: number | null; avg60: number | null; vs_avg60: number | null;
  mom_6m: number | null; trend: "↑" | "↓" | "→" | null;
  source_id: string; collected_at: string; run_id: number; is_simulated: boolean;
  history: { period: string; value: number }[];
}

export interface ExportsSummary {
  period_start: string; period_end: string;
  value_usd: number; value_usd_prev: number | null; value_var: number | null;
  net_kg: number | null; net_kg_prev: number | null; qty_m3: number | null; qty_m3_prev: number | null;
  m3_var: number | null; price_usd_m3: number | null; price_usd_m3_prev: number | null;
  destinations: number; is_simulated: boolean; sources: string[];
  prev_months_available: number; prev_window_complete: boolean;   // false ⇒ variações = null (EVIDÊNCIA INSUFICIENTE)
}

export interface Destination {
  rank: number; iso3: string; name_pt: string; region: string; lat: number | null; lon: number | null;
  value_usd: number; value_usd_prev: number | null; value_var: number | null;
  share: number; share_prev: number | null; share_delta: number | null;
  qty_m3: number | null; net_kg: number | null; price_usd_m3: number | null;
  is_new: boolean | null; trend: "↑" | "↓" | "→" | null; is_simulated: boolean; prev_window_complete: boolean;
}

export interface DestinationShift {
  gaining: Destination[]; losing: Destination[]; new_markets: Destination[]; contracting: Destination[];
}

export interface Flow { uf: string; port_name: string; region: string; value_usd: number; qty_m3: number | null; is_simulated: boolean }

export interface Competitor {
  rank: number; iso3: string; name_pt: string; value_usd: number; value_usd_prev: number | null;
  growth: number | null; share: number; qty_m3: number | null; price_usd_m3: number | null; is_simulated: boolean;
}

export interface NcmSearchRow {
  ncm8: string; hs6: string; description_pt: string; family: string | null; value_usd: number;
  net_kg: number | null; qty_m3: number | null; price_usd_m3: number | null; months: number; is_simulated: boolean;
}

export interface GeoEvent {
  event_id: string; category: string; title: string; event_date: string; countries: string[];
  hs6_affected: string[]; products_text: string | null; routes: string | null;
  potential_impact: "ALTO" | "MÉDIO" | "BAIXO" | "INDETERMINADO"; confidence: "ALTA" | "MÉDIA" | "BAIXA";
  evidence: string; source_name: string; source_url: string | null;
  impact_class: "direto" | "indireto" | "contexto" | "monitoramento"; status: string; is_simulated: boolean;
}

export interface NewsItem {
  news_id: number; published_at: string; title: string; source_name: string; url: string | null;
  country_iso3: string[]; category: string; summary: string | null; products_text: string | null;
  impact_class: GeoEvent["impact_class"]; potential_impact: GeoEvent["potential_impact"];
  event_id: string | null; is_simulated: boolean;
}

export type SignalResult = "SINAL" | "INDICAÇÃO" | "SEM SINAL" | "EVIDÊNCIA INSUFICIENTE";
export interface SignalState {
  rule_id: string; rule_name: string; tone: "pos" | "neg" | "warn"; market_iso3: string; market_name: string;
  as_of: string; conditions_met: number; conditions_total: number; result: SignalResult; is_simulated: boolean;
  detail: { label: string; indicator: string; geo: string; test: string; met: boolean | null;
            observed: number | null; threshold: number | null; n_obs: number; is_simulated: boolean | null }[];
}

export interface CyclePosition {
  indicator_code: string; geo_iso3: string; label: string; level_vs_avg: number | null; momentum_6m: number | null;
  phase: "EXPANSÃO" | "PICO" | "DESACELERAÇÃO" | "CONTRAÇÃO" | "RECUPERAÇÃO" | "EVIDÊNCIA INSUFICIENTE";
  period: string; is_simulated: boolean;
}

export interface IndexComponent { indicator: string; geo: string; weight: number; invert?: boolean }
export interface IndexResult {
  config: { config_id: number | null; name: string; note?: string };
  periods: string[]; values: number[];
  components_used: IndexComponent[]; components_missing: (IndexComponent & { reason: string })[];
  total_weight: number;
}

export interface TraceSeries {
  obs_id: number; indicator_code: string; geo_iso3: string; period: string; value: number | null;
  obs_status: "A" | "P" | "E" | "M"; name_pt: string; unit: string; formula: string | null; kind: string;
  source_id: string; source_name: string; source_url: string | null; methodology: string | null;
  run_id: number; job: string; run_finished_at: string; collected_at: string; version: number; is_simulated: boolean;
  raw_files: { uri: string; sha256: string; bytes: number; fetched_at: string }[] | null;
  versions: { version: number; value: number | null; collected_at: string; superseded_at: string | null }[];
}
