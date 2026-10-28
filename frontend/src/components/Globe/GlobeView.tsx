import React, { useRef, useEffect, useMemo, useState } from 'react';
import Globe from 'globe.gl';
import { X } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import type { SnapshotEvent, SnapshotArc } from '../../types/snapshot';
import type { CountryFocus } from '../../types/country';
import { CATEGORY_COLORS, CATEGORY_COLORS_LIGHT, RELATION_COLORS } from '../../utils/colors';
import './GlobeView.css';

interface GlobeViewProps {
  events: SnapshotEvent[];
  arcs: SnapshotArc[];
  onEventHover: (event: SnapshotEvent | null, x: number, y: number) => void;
  onEventClick: (eventId: string) => void;
  onLocationClick: (events: SnapshotEvent[]) => void;
  onCountryClick?: (country: CountryFocus) => void;
  activeCountry?: string | null;
  targetCoords?: { lat: number; lng: number; altitude?: number } | null;
  isDark: boolean;
  onWebGLError?: () => void;
  onWebGLRestored?: () => void;
  legendInitiallyOpen?: boolean;
  /** Pixels of fixed Atlas chrome above the canvas. */
  insetTop?: number;
}

type GroupedEvent = SnapshotEvent & {
  _stackSize: number;
  _group: SnapshotEvent[];
  kind: 'event';
};

interface GeoLabel {
  id?: string;
  name: string;
  lat: number;
  lng: number;
  minLabel: number;
  level: 'country' | 'state';
  admin?: string;
  iso2?: string;
}

type GeoLabelItem = GeoLabel & { kind: 'label' };
type MapItem = GroupedEvent | GeoLabelItem;

interface GlobeHandlers {
  onEventHover: GlobeViewProps['onEventHover'];
  onEventClick: GlobeViewProps['onEventClick'];
  onLocationClick: GlobeViewProps['onLocationClick'];
  onCountryClick: GlobeViewProps['onCountryClick'];
}

const ARC_VISIBLE_ALTITUDE = 1.15;
const MIN_ALTITUDE = 0.32;
const GLOBE_RADIUS = 100;

/**
 * Events sharing an exact coordinate become one numbered marker. We never
 * displace a story geographically just to make room for another pin.
 */
function groupEventsByLocation(events: SnapshotEvent[]): GroupedEvent[] {
  const groups = new Map<string, SnapshotEvent[]>();
  for (const event of events) {
    if (!Number.isFinite(event.lat) || !Number.isFinite(event.lng)) continue;
    const key = `${event.lat.toFixed(3)},${event.lng.toFixed(3)}`;
    const existing = groups.get(key);
    if (existing) {
      existing.push(event);
    } else {
      groups.set(key, [event]);
    }
  }

  return Array.from(groups.values()).map((group) => {
    const ordered = [...group].sort((left, right) => {
      const importance = (right.imp || 0) - (left.imp || 0);
      return importance || (right.at || '').localeCompare(left.at || '');
    });
    return { ...ordered[0], _stackSize: ordered.length, _group: ordered, kind: 'event' as const };
  });
}

function pickBoundaryTextureSize(): '8k' | '4k' {
  try {
    const canvas = document.createElement('canvas');
    const gl = canvas.getContext('webgl');
    const max = gl?.getParameter(gl.MAX_TEXTURE_SIZE) || 4096;
    return max >= 8192 ? '8k' : '4k';
  } catch {
    return '4k';
  }
}

function angularDistance(lat1: number, lng1: number, lat2: number, lng2: number): number {
  const toRad = Math.PI / 180;
  const dLat = (lat2 - lat1) * toRad;
  const dLng = (lng2 - lng1) * toRad;
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(lat1 * toRad) * Math.cos(lat2 * toRad) * Math.sin(dLng / 2) ** 2;
  return 2 * Math.atan2(Math.sqrt(a), Math.sqrt(Math.max(0, 1 - a))) / toRad;
}

function countryLabelLimit(altitude: number): number {
  if (altitude >= 2.0) return 3.0;
  if (altitude >= 1.6) return 4.0;
  if (altitude >= 1.25) return 5.0;
  return 6.1;
}

function stateLabelLimit(altitude: number): number {
  if (altitude >= 0.72) return 0;
  if (altitude >= 0.6) return 7.0;
  if (altitude >= 0.48) return 8.7;
  if (altitude >= 0.4) return 10.5;
  if (altitude >= 0.34) return 12.0;
  return 18.0;
}

function stateLabelRadius(altitude: number): number {
  if (altitude >= 0.6) return 20;
  if (altitude >= 0.48) return 19;
  if (altitude >= 0.4) return 18;
  return 17;
}

function countryFocusRadius(altitude: number): number {
  if (altitude >= 2.0) return 68;
  if (altitude >= 1.5) return 56;
  if (altitude >= 1.15) return 42;
  if (altitude >= 0.9) return 30;
  if (altitude >= 0.6) return 24;
  return 18;
}

function countryLabelSpacing(altitude: number): number {
  if (altitude >= 2.0) return 5.5;
  if (altitude >= 1.5) return 3.8;
  if (altitude >= 1.15) return 2.8;
  if (altitude >= 0.9) return 2.2;
  if (altitude >= 0.6) return 1.3;
  return 0.8;
}

function stateLabelSpacing(altitude: number): number {
  if (altitude >= 0.6) return 1.2;
  if (altitude >= 0.48) return 0.8;
  if (altitude >= 0.4) return 0.55;
  if (altitude >= 0.34) return 0.38;
  return 0.22;
}

function declutterLabels(labels: GeoLabelItem[], spacing: number): GeoLabelItem[] {
  if (spacing <= 0) return labels;
  const accepted: GeoLabelItem[] = [];
  const ordered = [...labels].sort(
    (left, right) => left.minLabel - right.minLabel || left.name.localeCompare(right.name),
  );
  for (const label of ordered) {
    if (
      accepted.every(
        (other) => angularDistance(label.lat, label.lng, other.lat, other.lng) >= spacing,
      )
    ) {
      accepted.push(label);
    }
  }
  return accepted;
}

function asLabelItems(labels: GeoLabel[]): GeoLabelItem[] {
  return labels.map((label) => ({
    ...label,
    id: `${label.level}-${label.iso2 || 'xx'}-${label.lat}-${label.lng}-${label.name}`,
    kind: 'label' as const,
  }));
}

function buildGeoLabel(
  label: GeoLabelItem,
  handlers: React.MutableRefObject<GlobeHandlers>,
  activeCountry: string | null | undefined,
): HTMLElement {
  if (label.level === 'country' && handlers.current.onCountryClick) {
    const active = Boolean(activeCountry) && label.name === activeCountry;
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'geo-label geo-label--country';
    if (active) button.classList.add('geo-label--active');
    button.textContent = label.name;
    button.title = label.name;
    button.setAttribute('aria-label', label.name);
    button.setAttribute('aria-haspopup', 'dialog');
    if (active) button.setAttribute('aria-current', 'true');
    button.dataset.iso2 = label.iso2 || '';
    button.dataset.country = label.name;
    button.addEventListener('click', (event) => {
      event.stopPropagation();
      handlers.current.onCountryClick?.({
        name: label.name,
        iso2: label.iso2,
        lat: label.lat,
        lng: label.lng,
      });
    });
    return button;
  }

  const span = document.createElement('span');
  span.className = `geo-label geo-label--${label.level}`;
  if (label.level === 'country') span.classList.add('geo-label--static');
  span.textContent = label.name;
  span.title = label.admin ? `${label.name} · ${label.admin}` : label.name;
  span.setAttribute('aria-hidden', 'true');
  span.dataset.iso2 = label.iso2 || '';
  return span;
}

function markerInk(hex: string): string {
  const clean = hex.replace('#', '');
  const value = clean.length === 3
    ? clean.split('').map((character) => character + character).join('')
    : clean;
  const red = parseInt(value.slice(0, 2), 16);
  const green = parseInt(value.slice(2, 4), 16);
  const blue = parseInt(value.slice(4, 6), 16);
  const luminance = (0.299 * red + 0.587 * green + 0.114 * blue) / 255;
  return luminance > 0.58 ? '#17191c' : '#faf6ed';
}

function buildMarker(
  group: GroupedEvent,
  isDark: boolean,
  handlers: React.MutableRefObject<GlobeHandlers>,
): HTMLButtonElement {
  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'globe-marker';
  if ((group.imp || 0) >= 0.55 || group._stackSize >= 3) {
    button.classList.add('globe-marker--key');
  }
  const color = (isDark ? CATEGORY_COLORS : CATEGORY_COLORS_LIGHT)[group.cat] || '#6F8FA9';
  const stacked = group._stackSize > 1;
  const size = stacked
    ? Math.min(24, 17 + String(group._stackSize).length * 2)
    : 9 + Math.round((group.imp || 0.4) * 5);
  button.style.setProperty('--marker-color', color);
  button.style.setProperty('--marker-ink', markerInk(color));
  button.style.setProperty('--marker-size', `${size}px`);

  const extra = stacked ? `, ${group._stackSize} stories at this location` : '';
  button.setAttribute('aria-label', `${group.t}${extra}`);
  button.title = group.t;

  const dot = document.createElement('span');
  dot.className = `globe-marker__dot${stacked ? ' globe-marker__dot--count' : ''}`;
  if (stacked) {
    dot.textContent = String(group._stackSize);
  }
  button.appendChild(dot);

  const show = () => handlers.current.onEventHover(group, 0, 0);
  const hide = () => handlers.current.onEventHover(null, 0, 0);
  button.addEventListener('mouseenter', show);
  button.addEventListener('mouseleave', hide);
  button.addEventListener('focus', show);
  button.addEventListener('blur', hide);
  button.addEventListener('click', (event) => {
    event.stopPropagation();
    hide();
    if (group._stackSize > 1) {
      handlers.current.onLocationClick(group._group);
    } else {
      handlers.current.onEventClick(group.id);
    }
  });

  return button;
}

const GlobeViewComponent: React.FC<GlobeViewProps> = ({
  events,
  arcs,
  onEventHover,
  onEventClick,
  onLocationClick,
  onCountryClick,
  activeCountry,
  targetCoords,
  isDark,
  onWebGLError,
  onWebGLRestored,
  legendInitiallyOpen,
  insetTop = 0,
}) => {
  const { t } = useTranslation();
  const containerRef = useRef<HTMLDivElement>(null);
  const globeRef = useRef<any>(null);
  const boundaryTextureSize = useMemo(() => pickBoundaryTextureSize(), []);
  const [legendOpen, setLegendOpen] = useState<boolean>(() => {
    if (legendInitiallyOpen === true) return true;
    if (legendInitiallyOpen === false) return false;
    try {
      // Collapsed on a first visit; a previous dismissal is remembered.
      return localStorage.getItem('gna_map_key_open') === '0';
    } catch {
      return false;
    }
  });

  const openLegend = () => {
    setLegendOpen(true);
    try {
      localStorage.setItem('gna_map_key_open', '0');
    } catch {
      /* storage may be unavailable */
    }
  };

  const closeLegend = () => {
    setLegendOpen(false);
    try {
      localStorage.setItem('gna_map_key_open', '1');
    } catch {
      /* storage may be unavailable */
    }
  };

  const initialView = useMemo(() => {
    const params = new URLSearchParams(window.location.search);
    const latParam = params.get('lat');
    const lngParam = params.get('lng');
    const altParam = params.get('alt');
    const lat = latParam ? Number(latParam) : NaN;
    const lng = lngParam ? Number(lngParam) : NaN;
    const altitude = altParam ? Number(altParam) : NaN;
    return {
      lat: Number.isFinite(lat) ? Math.max(-85, Math.min(85, lat)) : 20,
      lng: Number.isFinite(lng) ? ((lng + 540) % 360) - 180 : 20,
      altitude: Number.isFinite(altitude)
        ? Math.max(MIN_ALTITUDE, Math.min(4, altitude))
        : 2.2,
      fixed: Boolean(latParam || lngParam || altParam),
    };
  }, []);

  const [view, setView] = useState({
    lat: initialView.lat,
    lng: initialView.lng,
    altitude: initialView.altitude,
  });
  const viewRef = useRef(view);

  const groupedEvents = useMemo(() => groupEventsByLocation(events), [events]);
  const groupedRef = useRef(groupedEvents);
  const arcsRef = useRef(arcs);
  const visibleArcsRef = useRef(initialView.altitude >= ARC_VISIBLE_ALTITUDE);

  const handlersRef = useRef<GlobeHandlers>({
    onEventHover,
    onEventClick,
    onLocationClick,
    onCountryClick,
  });
  const errorHandlerRef = useRef(onWebGLError);
  const restoredHandlerRef = useRef(onWebGLRestored);

  useEffect(() => {
    errorHandlerRef.current = onWebGLError;
  }, [onWebGLError]);

  useEffect(() => {
    restoredHandlerRef.current = onWebGLRestored;
  }, [onWebGLRestored]);

  useEffect(() => {
    handlersRef.current = { onEventHover, onEventClick, onLocationClick, onCountryClick };
  }, [onEventHover, onEventClick, onLocationClick, onCountryClick]);

  const [countryLabels, setCountryLabels] = useState<GeoLabelItem[]>([]);
  const [stateLabels, setStateLabels] = useState<GeoLabelItem[]>([]);
  const stateLabelsRequested = useRef(false);

  useEffect(() => {
    let active = true;
    fetch('/data/country_labels.json?v=1')
      .then((response) => (response.ok ? response.json() : Promise.reject(new Error('country labels unavailable'))))
      .then((data: GeoLabel[]) => {
        if (active) setCountryLabels(asLabelItems(data));
      })
      .catch(() => {
        // the map remains usable without labels
      });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (view.altitude >= 0.72 || stateLabelsRequested.current) return;
    stateLabelsRequested.current = true;
    let active = true;
    fetch('/data/admin1_labels.json?v=1')
      .then((response) => (response.ok ? response.json() : Promise.reject(new Error('state labels unavailable'))))
      .then((data: GeoLabel[]) => {
        if (active) setStateLabels(asLabelItems(data));
      })
      .catch(() => {
        stateLabelsRequested.current = false;
      });
    return () => {
      active = false;
    };
  }, [view.altitude]);

  const visibleCountryLabels = useMemo(() => {
    const limit = countryLabelLimit(view.altitude);
    const focus = countryFocusRadius(view.altitude);
    const candidates = countryLabels.filter(
      (label) =>
        label.minLabel <= limit &&
        angularDistance(view.lat, view.lng, label.lat, label.lng) <= focus,
    );
    return declutterLabels(candidates, countryLabelSpacing(view.altitude));
  }, [countryLabels, view]);

  const visibleStateLabels = useMemo(() => {
    const limit = stateLabelLimit(view.altitude);
    if (!limit || stateLabels.length === 0) return [];
    const radius = stateLabelRadius(view.altitude);
    const candidates = stateLabels.filter(
      (label) =>
        label.minLabel <= limit &&
        angularDistance(view.lat, view.lng, label.lat, label.lng) <= radius,
    );
    return declutterLabels(candidates, stateLabelSpacing(view.altitude));
  }, [stateLabels, view]);

  const mapItems = useMemo<MapItem[]>(
    () => [...groupedEvents, ...visibleCountryLabels, ...visibleStateLabels],
    [groupedEvents, visibleCountryLabels, visibleStateLabels],
  );
  const mapItemsRef = useRef(mapItems);
  const activeCountryRef = useRef(activeCountry);
  const previousCountryRef = useRef<string | null>(null);

  useEffect(() => {
    const previous = previousCountryRef.current;
    previousCountryRef.current = activeCountry ?? null;
    activeCountryRef.current = activeCountry;

    if (!activeCountry && previous) {
      const focused = document.activeElement as HTMLElement | null;
      const lostFocus =
        !focused ||
        focused === document.body ||
        !document.contains(focused) ||
        focused.closest('.country-desk') !== null;
      if (lostFocus) {
        window.requestAnimationFrame(() => {
          const label = Array.from(
            document.querySelectorAll<HTMLElement>('.globe-canvas-wrapper .geo-label--country'),
          ).find((element) => element.dataset.country === previous);
          label?.focus();
        });
      }
    }

    const frame = window.requestAnimationFrame(() => {
      document
        .querySelectorAll<HTMLElement>('.globe-canvas-wrapper .geo-label--country')
        .forEach((element) => {
          const active = Boolean(activeCountry) && element.dataset.country === activeCountry;
          element.classList.toggle('geo-label--active', active);
          if (active) {
            element.setAttribute('aria-current', 'true');
          } else {
            element.removeAttribute('aria-current');
          }
        });
    });
    return () => window.cancelAnimationFrame(frame);
  }, [activeCountry]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    let globe: any = null;
    try {
      globe = new Globe(container);
    } catch (err) {
      console.warn('Globe WebGL initialization error:', err);
      errorHandlerRef.current?.();
      return;
    }

    let controls: any = null;
    let arcVisibilityHandler: (() => void) | null = null;
    let viewUpdateHandler: (() => void) | null = null;
    let viewTimer: number | undefined;
    let contextCanvas: HTMLCanvasElement | null = null;
    let resizeObserver: ResizeObserver | null = null;

    const handleContextLost = (event: Event) => {
      event.preventDefault();
      errorHandlerRef.current?.();
    };
    const handleContextRestored = () => {
      restoredHandlerRef.current?.();
    };
    const applySize = () => {
      const container = containerRef.current;
      if (!globe || !container) return;
      const width = container.clientWidth;
      const height = container.clientHeight;
      if (width > 0 && height > 0) {
        globe.width(width);
        globe.height(height);
      }
    };

    try {
      const renderer = globe.renderer?.();
      if (renderer) {
        renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
        contextCanvas = renderer.domElement as HTMLCanvasElement;
        contextCanvas.addEventListener('webglcontextlost', handleContextLost, false);
        contextCanvas.addEventListener('webglcontextrestored', handleContextRestored, false);
      }
      applySize();

      const validArcs = (items: SnapshotArc[]) =>
        items.filter((arc) => arc.a_lat !== undefined && arc.b_lat !== undefined);

      globe
        .globeImageUrl(
          isDark
            ? `/data/earth-dark-boundaries-${boundaryTextureSize}.webp?v=3`
            : `/data/earth-light-boundaries-${boundaryTextureSize}.webp?v=3`,
        )
        .backgroundColor('rgba(0, 0, 0, 0)')
        .atmosphereColor(isDark ? '#7E8C86' : '#8B7C66')
        .atmosphereAltitude(0.14)
        .htmlLat((item: MapItem) => item.lat)
        .htmlLng((item: MapItem) => item.lng)
        .htmlAltitude((item: MapItem) =>
          item.kind === 'event' ? 0.012 : item.level === 'country' ? 0.006 : 0.004,
        )
        .htmlElement((item: MapItem) =>
          item.kind === 'event'
            ? buildMarker(item, isDark, handlersRef)
            : buildGeoLabel(item, handlersRef, activeCountryRef.current),
        )
        .htmlElementVisibilityModifier((element: HTMLElement, visible: boolean) => {
          element.classList.toggle('is-hidden', !visible);
        })
        .htmlTransitionDuration(0)
        .htmlElementsData(mapItemsRef.current)
        .arcsData(visibleArcsRef.current ? validArcs(arcsRef.current) : [])
        .arcStartLat((arc: any) => arc.a_lat)
        .arcStartLng((arc: any) => arc.a_lng)
        .arcEndLat((arc: any) => arc.b_lat)
        .arcEndLng((arc: any) => arc.b_lng)
        .arcColor((arc: any) => {
          const color = RELATION_COLORS[arc.ty] || '#6F8FA9';
          return [color, color];
        })
        .arcAltitude((arc: any) => 0.06 + (arc.imp || 0.5) * 0.09)
        .arcStroke(0.3)
        .arcDashLength(0.55)
        .arcDashGap(0.25)
        .arcDashAnimateTime(12000)
        .arcDashInitialGap(() => 0);

      controls = globe.controls();
      if (controls) {
        controls.autoRotate = false;
        controls.autoRotateSpeed = 0.3;
        controls.enableDamping = true;
        controls.dampingFactor = 0.05;
        controls.minDistance = GLOBE_RADIUS * (1 + MIN_ALTITUDE);
        controls.maxDistance = GLOBE_RADIUS * 5;
        controls.addEventListener('start', () => {
          controls.autoRotate = false;
        });

        arcVisibilityHandler = () => {
          const distance = globe.camera?.()?.position?.length?.() || 0;
          if (!distance) return;
          const altitude = distance / GLOBE_RADIUS - 1;
          const visible = altitude >= ARC_VISIBLE_ALTITUDE;
          if (visible === visibleArcsRef.current) return;
          visibleArcsRef.current = visible;
          try {
            globe.arcsData(visible ? validArcs(arcsRef.current) : []);
          } catch {
            // keep the globe usable if the arc layer is unavailable
          }
        };
        controls.addEventListener('change', arcVisibilityHandler);

        viewUpdateHandler = () => {
          const point = globe.pointOfView?.();
          if (!point || !Number.isFinite(point.altitude)) return;
          const next = { lat: point.lat, lng: point.lng, altitude: point.altitude };
          viewRef.current = next;
          if (viewTimer) window.clearTimeout(viewTimer);
          viewTimer = window.setTimeout(() => setView(next), 240);
        };
        controls.addEventListener('change', viewUpdateHandler);
        controls.addEventListener('end', viewUpdateHandler);
      }

      globe.pointOfView(viewRef.current || initialView);
      viewUpdateHandler?.();
      globeRef.current = globe;
    } catch (renderErr) {
      console.warn('WebGL rendering setup failed:', renderErr);
      errorHandlerRef.current?.();
      return;
    }

    // Size from the panel, not window.innerWidth/Height: Rewind's 62vh globe
    // and mobile orientation changes need the container's real dimensions.
    if (typeof ResizeObserver !== 'undefined') {
      resizeObserver = new ResizeObserver(applySize);
      resizeObserver.observe(container);
    } else {
      window.addEventListener('resize', applySize);
    }
    window.addEventListener('orientationchange', applySize);
    applySize();

    return () => {
      resizeObserver?.disconnect();
      window.removeEventListener('resize', applySize);
      window.removeEventListener('orientationchange', applySize);
      if (contextCanvas) {
        contextCanvas.removeEventListener('webglcontextlost', handleContextLost);
        contextCanvas.removeEventListener('webglcontextrestored', handleContextRestored);
      }
      if (viewTimer) window.clearTimeout(viewTimer);
      if (controls && arcVisibilityHandler) {
        controls.removeEventListener('change', arcVisibilityHandler);
      }
      if (controls && viewUpdateHandler) {
        controls.removeEventListener('change', viewUpdateHandler);
        controls.removeEventListener('end', viewUpdateHandler);
      }
      if (globeRef.current) {
        try {
          const renderer = globeRef.current.renderer?.();
          if (renderer) {
            renderer.dispose();
            renderer.forceContextLoss?.();
            const dom = renderer.domElement;
            if (dom && dom.parentNode) {
              dom.parentNode.removeChild(dom);
            }
          }
          globeRef.current._destructor?.();
        } catch {
          // ignore teardown errors
        }
      }
      if (container) {
        container.innerHTML = '';
      }
      globeRef.current = null;
    };
  }, [isDark, boundaryTextureSize, initialView]);

  useEffect(() => {
    groupedRef.current = groupedEvents;
    arcsRef.current = arcs;
    mapItemsRef.current = mapItems;
    if (!globeRef.current) return;
    try {
      globeRef.current.htmlElementsData(mapItems);
      globeRef.current.arcsData(
        visibleArcsRef.current
          ? arcs.filter((arc) => arc.a_lat !== undefined && arc.b_lat !== undefined)
          : [],
      );
    } catch {
      // ignore layer update errors
    }
  }, [groupedEvents, mapItems, arcs]);

  useEffect(() => {
    if (!globeRef.current || !targetCoords) return;
    try {
      const current = globeRef.current.pointOfView?.();
      const requested = targetCoords.altitude ?? 1.1;
      const altitude = Number.isFinite(current?.altitude)
        ? Math.max(MIN_ALTITUDE, Math.min(requested, current.altitude))
        : requested;
      globeRef.current.pointOfView(
        {
          lat: targetCoords.lat,
          lng: targetCoords.lng,
          altitude,
        },
        1400,
      );
    } catch {
      // ignore camera errors
    }
  }, [targetCoords]);

  const categories = Object.entries(isDark ? CATEGORY_COLORS : CATEGORY_COLORS_LIGHT);

  return (
    <div
      className="globe-container"
      style={insetTop ? ({ '--globe-inset-top': `${insetTop}px` } as React.CSSProperties) : undefined}
    >
      <div ref={containerRef} className="globe-canvas-wrapper" />

      {legendOpen ? (
        <aside className="globe-legend" aria-label={t('map_key')}>
          <div className="globe-legend__head">
            <span className="globe-legend__heading">{t('map_key')}</span>
            <button
              type="button"
              className="globe-legend__close"
              onClick={closeLegend}
              aria-label={t('hide_map_key')}
            >
              <X size={12} />
            </button>
          </div>

          <div className="globe-legend__title">{t('legend_categories')}</div>
          <div className="globe-legend__categories">
            {categories.map(([category, color]) => (
              <div key={category} className="globe-legend__item">
                <span className="globe-legend__dot" style={{ backgroundColor: color }} />
                <span>{t(`category.${category}`, category)}</span>
              </div>
            ))}
          </div>
          <div className="globe-legend__marker-row">
            <span className="globe-legend__marker-sample">
              <span className="globe-legend__marker-dot">3</span>
            </span>
            <span>{t('legend_marker_note')}</span>
          </div>

          <div className="globe-legend__title">{t('legend_arcs')}</div>
          <div className="globe-legend__items">
            {Object.entries(RELATION_COLORS).map(([type, color]) => (
              <div key={type} className="globe-legend__item">
                <span className="globe-legend__arc-line" style={{ backgroundColor: color }} />
                <span>{t(`arc_type.${type}`, type)}</span>
              </div>
            ))}
          </div>
          <div className="globe-legend__note">{t('legend_arcs_note')}</div>

          <div className="globe-legend__title">{t('legend_map')}</div>
          <div className="globe-legend__items">
            <div className="globe-legend__item">
              <span className="globe-legend__border-line globe-legend__border-line--country" />
              <span>{t('legend_country_border')}</span>
            </div>
            <div className="globe-legend__item">
              <span className="globe-legend__border-line globe-legend__border-line--state" />
              <span>{t('legend_state_border')}</span>
            </div>
            <div className="globe-legend__item">
              <span className="globe-legend__border-line globe-legend__border-line--disputed" />
              <span>{t('legend_disputed_boundary')}</span>
            </div>
            <div className="globe-legend__item">
              <span className="globe-legend__swatch" />
              <span>{t('legend_disputed_area')}</span>
            </div>
          </div>
          <div className="globe-legend__note">{t('legend_boundary_note')}</div>
        </aside>
      ) : (
        <button
          type="button"
          className="globe-legend-toggle"
          onClick={openLegend}
          aria-expanded="false"
        >
          {t('map_key')}
        </button>
      )}
    </div>
  );
};

export const GlobeView = React.memo(GlobeViewComponent);
