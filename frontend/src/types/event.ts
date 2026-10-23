export interface SpectrumBar {
  left: number;
  centre: number;
  right: number;
  unrated: number;
}

export interface HoverCardData {
  id: string;
  title: string;
  summary: string;
  category: string;
  status: string;
  updated_at: string | null;
  updated_relative: string;
  outlet_count: number;
  spectrum: SpectrumBar;
  is_single_source: boolean;
  has_coverage_gap: boolean;
  social_buzz: number;
  content_warning?: string | null;
  summary_method: string;
  location_name?: string;
  geo_precision?: string;
}

export interface SampleHeadline {
  title: string;
  outlet: string;
  url: string;
}

export interface CoverageColumn {
  camp: 'left' | 'centre' | 'right' | 'unrated' | string;
  outlet_count: number;
  article_count: number;
  framing_note: string;
  sample_headlines: SampleHeadline[];
  sentiment?: number | null;
}

export interface TimelineEntry {
  timestamp: string;
  description: string;
  source_count: number;
}

export interface CitedSource {
  outlet_name: string;
  url: string;
  alignment: string;
  title: string;
  snippet?: string;
  published_at?: string | null;
}

export interface SearchApiResult {
  id: string;
  title: string;
  category: string;
  lat: number;
  lng: number;
  importance: number;
  status: string;
  outlet_count: number;
  summary: string;
  location_name: string;
  updated_at: string | null;
}

export interface EventDetailData {
  id: string;
  title: string;
  status: string;
  category: string;
  severity: string;
  first_reported: string | null;
  last_updated: string | null;
  summary: string;
  summary_method: string;
  confidence: number;
  excerpt: string;
  timeline: TimelineEntry[];
  coverage: CoverageColumn[];
  lat: number | null;
  lng: number | null;
  geo_precision: string;
  location_name: string;
  reddit_threads: number;
  bluesky_posts: number;
  outlet_count: number;
  article_count: number;
  source_count: number;
  is_single_source: boolean;
  has_coverage_gap: boolean;
  has_official_source: boolean;
  content_warning?: string | null;
  revision: number;
  countries: string[];
  spectrum: SpectrumBar;
  sources: CitedSource[];
  related_event_ids: string[];
  related_relation_ids: string[];
  corrections: Array<{ timestamp: string; description: string }>;
}
