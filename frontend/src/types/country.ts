export interface CountryBriefEvent {
  id: string;
  title: string;
  summary: string;
  category: string;
  importance: number;
  updated_at: string | null;
  location: string;
  source: string;
  outlet_count: number;
  source_count: number;
  severity: string;
  is_single_source: boolean;
  has_coverage_gap: boolean;
  content_warning: boolean;
}

export interface CountryBriefSection {
  key: string;
  count: number;
  events: CountryBriefEvent[];
}

export interface CountryBriefResponse {
  country: string;
  iso2: string;
  window: string;
  generated_at: string | null;
  available: boolean;
  total_events: number;
  brief_events: number;
  total_reports: number;
  total_outlets: number;
  counts: Record<string, number>;
  sections: CountryBriefSection[];
}

export interface CountryFocus {
  name: string;
  iso2?: string;
  lat: number;
  lng: number;
}
