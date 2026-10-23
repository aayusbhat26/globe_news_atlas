export interface SnapshotEvent {
  id: string;
  lat: number;
  lng: number;
  cat: string;
  imp: number;
  t: string;
  at: string | null;
  oc: number;
  sp: {
    left?: number;
    centre?: number;
    right?: number;
    unrated?: number;
  };
  st: string;
  sb: number;
  ss: boolean;
  cg: boolean;
  cw: boolean;
  sum?: string;
  loc?: string;
  gp?: string;
  src?: string;
}

export interface SnapshotArc {
  id: string;
  a: string;
  b: string;
  a_lat?: number;
  a_lng?: number;
  b_lat?: number;
  b_lng?: number;
  countries?: string[];
  event_ids?: string[];
  n?: number;
  ty: 'trade' | 'talks' | 'sanctions' | 'military' | 'aid';
  dir: 'a_to_b' | 'b_to_a' | 'bidirectional';
  stg: 'proposed' | 'negotiating' | 'agreed' | 'violated' | 'active';
  imp: number;
  t?: string | null;
}

export interface SnapshotResponse {
  ts: string;
  w: string;
  n: {
    e: number;
    a: number;
    total?: number;
    capped?: boolean;
  };
  events: SnapshotEvent[];
  arcs: SnapshotArc[];
  available?: boolean;
}
