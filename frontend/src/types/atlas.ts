import type { SnapshotArc, SnapshotEvent } from './snapshot';

export interface WatchlineEntry {
  id: string;
  kind: 'place' | 'arc';
  key: string;
  label: string;
  created_at: string | null;
}

export interface MatchedDesk {
  kind: 'place' | 'arc';
  key: string;
  label: string;
}

export interface WatchlineEvent extends SnapshotEvent {
  matched: MatchedDesk[];
  fresh: boolean;
}

export interface FollowedArc {
  id: string;
  arc_id: string;
  label: string;
  countries: string[];
  type: string;
  direction: string;
  stage: string;
  importance: number;
  total_events: number;
  window_events: number;
  latest_at: string | null;
  event_ids: string[];
}

export interface WatchlineFeed {
  available: boolean;
  public: boolean;
  signed_in: boolean;
  window: string;
  generated_at: string | null;
  entries: WatchlineEntry[];
  feed: WatchlineEvent[];
  feed_total: number;
  matched_total: number;
  shown: number;
  new_count: number;
  last_seen: string | null;
  arcs: FollowedArc[];
  capacity: number;
}

export interface ThinItem {
  id: string;
  title: string;
  category: string;
  importance: number;
  outlet_count: number;
  source_count: number;
  revision: number;
  has_official_source: boolean;
  location_name: string;
  updated_at: string | null;
  source: string;
  reasons: string[];
  reason_labels: string[];
}

export interface ThinFile {
  window: string;
  generated_at: string | null;
  total_events: number;
  thin_total: number;
  shown: number;
  counts: Record<string, number>;
  items: ThinItem[];
}

export interface StorylinePreview {
  id: string;
  title: string;
  category: string;
  updated_at: string | null;
  outlet_count: number;
}

export interface Storyline {
  id: string;
  countries: string[];
  a: string;
  b: string;
  type: string;
  direction: string;
  stage: string;
  importance: number;
  total_events: number;
  window_events: number;
  a_lat?: number;
  a_lng?: number;
  b_lat?: number;
  b_lng?: number;
  events: StorylinePreview[];
}

export interface StorylinesResponse {
  window: string;
  generated_at: string | null;
  total_storylines: number;
  storylines: Storyline[];
  available: boolean;
}

export interface PulseItem {
  id: string;
  title: string;
  category: string;
  location_name: string;
  importance: number;
  outlet_count: number;
  previous_outlets: number | null;
  outlet_delta: number;
  is_new: boolean;
  previous_at: string | null;
  updated_at: string | null;
  score: number;
}

export interface PulseResponse {
  available: boolean;
  window: string;
  generated_at: string | null;
  basis: {
    frames: number;
    from: string | null;
    to: string | null;
  };
  items: PulseItem[];
  has_momentum: boolean;
}

export interface RewindFrame {
  run_id: string;
  ts: string;
  counts: { e?: number; a?: number };
  events: SnapshotEvent[];
  arcs: SnapshotArc[];
}

export interface RewindResponse {
  available: boolean;
  generated_at: string | null;
  source_window: string;
  history_days: number | null;
  available_runs?: number;
  from: string | null;
  to: string | null;
  count: number;
  frames: RewindFrame[];
}

export interface Citation {
  event_id: string;
  title: string;
  url: string;
  accessed_at: string;
  outlet: string;
  apa: string;
  bibtex: string;
  plain: string;
}
