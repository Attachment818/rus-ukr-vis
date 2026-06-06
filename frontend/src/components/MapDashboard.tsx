import { useEffect, useRef, useState } from 'react';
import { API_BASE_URL } from '../lib/api';
import * as L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import 'leaflet.heat';

// --- Types ---
type MapPoint = {
  event_code: string; event_date: string | null;
  event_type: string; admin1: string; location: string;
  latitude: number; longitude: number; fatalities: number;
  actor1: string; actor2: string;
};
type DailyPoint = { date: string; count: number; fatalities: number };
type EventTypeItem = { event_type: string; count: number; fatalities: number };
type YearlyStat = { year: number; count: number; fatalities: number; regions: number };

const EVENT_COLORS: Record<string, string> = {
  'Battles': '#ef4444', 'Explosions/Remote violence': '#f97316',
  'Violence against civilians': '#ec4899', 'Protests': '#22c55e',
  'Riots': '#eab308', 'Strategic developments': '#6366f1',
};

function eventColor(et: string): string {
  for (const [k, v] of Object.entries(EVENT_COLORS)) {
    if (et.includes(k) || k.includes(et)) return v;
  }
  return '#3b82f6';
}

type FocusEvent = { lat: number; lng: number; id: string; title?: string } | null;

export default function MapDashboard({ fullscreen = true, focusEvent = null }: { fullscreen?: boolean; focusEvent?: FocusEvent }) {
  const [mapPoints, setMapPoints] = useState<MapPoint[]>([]);
  const [timeline, setTimeline] = useState<DailyPoint[]>([]);
  const [eventTypes, setEventTypes] = useState<EventTypeItem[]>([]);
  const [yearlyStats, setYearlyStats] = useState<YearlyStat[]>([]);
  const [selectedYear, setSelectedYear] = useState<number | null>(null);
  const [selectedEventType, setSelectedEventType] = useState<string | null>(null);
  const [showHeat, setShowHeat] = useState(true);
  const [showMarkers, setShowMarkers] = useState(true);
  const [showRegions, setShowRegions] = useState(true);

  // --- Animation state ---
  const [animMode, setAnimMode] = useState(false);
  const [animFrames, setAnimFrames] = useState<any[]>([]);
  const [animIndex, setAnimIndex] = useState(0);
  const [animPlaying, setAnimPlaying] = useState(false);
  const [animSpeed, setAnimSpeed] = useState(3); // frames per tick
  const animTimer = useRef<any>(null);

  // Load animation data
  useEffect(() => {
    if (!animMode || animFrames.length) return;
    fetch(`${API_BASE_URL}/dashboard/animation-frames?interval=day`)
      .then(r => r.json())
      .then(data => {
        setAnimFrames(data.frames || []);
        setAnimIndex(0);
      });
  }, [animMode]);

  // Auto-play timer
  useEffect(() => {
    if (!animPlaying || !animFrames.length) return;
    animTimer.current = setInterval(() => {
      setAnimIndex(prev => {
        const next = prev + animSpeed;
        if (next >= animFrames.length - 1) {
          setAnimPlaying(false);
          return animFrames.length - 1;
        }
        return next;
      });
    }, 80); // ~12 fps base
    return () => clearInterval(animTimer.current);
  }, [animPlaying, animSpeed, animFrames.length]);

  // Filtered points for animation
  const visiblePoints = animMode && animFrames.length
    ? (() => {
        const all: MapPoint[] = [];
        for (let i = 0; i <= animIndex && i < animFrames.length; i++) {
          for (const e of animFrames[i].events) {
            if (e.latitude && e.longitude) {
              all.push({
                event_code: e.event_code, event_date: e.event_date,
                event_type: e.event_type || 'Unknown',
                admin1: e.admin1, location: e.location,
                latitude: e.latitude, longitude: e.longitude,
                fatalities: e.fatalities || 0,
                actor1: e.actor1 || '', actor2: e.actor2 || '',
              });
            }
          }
        }
        return all;
      })()
    : mapPoints;

  // Current frame info
  const currentFrame = animMode && animFrames[animIndex]
    ? animFrames[animIndex]
    : null;
  const [ready, setReady] = useState(false);

  const mapRef = useRef<HTMLDivElement>(null);
  const mapInst = useRef<L.Map | null>(null);
  const heatLayer = useRef<L.Layer | null>(null);
  const markerLayer = useRef<L.LayerGroup | null>(null);
  const geoLayer = useRef<L.GeoJSON | null>(null);
  const timeChartRef = useRef<HTMLDivElement>(null);
  const yearChartRef = useRef<HTMLDivElement>(null);
  const pieChartRef = useRef<HTMLDivElement>(null);
  const timeInst = useRef<any>(null);
  const yearInst = useRef<any>(null);
  const pieInst = useRef<any>(null);

  // --- Init map once ---
  useEffect(() => {
    if (!mapRef.current || mapInst.current) return;

    const map = L.map(mapRef.current, {
      center: [48.38, 31.17],
      zoom: 6,
      minZoom: 4,
      maxZoom: 15,
      zoomControl: true,
    });

    L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
      maxZoom: 19,
    }).addTo(map);

    L.control.scale({ position: 'bottomleft', imperial: false }).addTo(map);
    mapInst.current = map;
    setReady(true);

    return () => {
      map.remove();
      mapInst.current = null;
      setReady(false);
    };
  }, []);

  // --- Focus on event (from parent) ---
  const focusMarker = useRef<L.CircleMarker | null>(null);

  useEffect(() => {
    const map = mapInst.current;
    if (!map || !focusEvent) return;

    // Fly to location
    map.flyTo([focusEvent.lat, focusEvent.lng], 10, { duration: 1.2 });

    // Remove previous focus marker
    if (focusMarker.current) {
      map.removeLayer(focusMarker.current);
      focusMarker.current = null;
    }

    // Add a pulsing highlight marker
    const marker = L.circleMarker([focusEvent.lat, focusEvent.lng], {
      radius: 12,
      fillColor: '#fbbf24',
      color: '#ffffff',
      weight: 3,
      fillOpacity: 0.8,
      opacity: 0.9,
    }).addTo(map);

    marker.bindPopup(
      `<b>${focusEvent.title || focusEvent.id}</b><br>📍 (${focusEvent.lat.toFixed(4)}, ${focusEvent.lng.toFixed(4)})`,
      { autoClose: false, closeOnClick: true },
    ).openPopup();

    // Pulse animation
    let growing = true;
    const pulse = setInterval(() => {
      const r = marker.getRadius();
      marker.setRadius(growing ? r + 1.5 : r - 1.5);
      if (r >= 20) growing = false;
      if (r <= 10) growing = true;
    }, 150);

    focusMarker.current = marker;

    return () => {
      clearInterval(pulse);
      if (focusMarker.current) {
        map.removeLayer(focusMarker.current);
        focusMarker.current = null;
      }
    };
  }, [focusEvent]);

  // --- Load data ---
  useEffect(() => {
    const yp = selectedYear ? `?year=${selectedYear}` : '';
    const tp = selectedEventType ? `${yp ? '&' : '?'}event_type=${encodeURIComponent(selectedEventType)}` : '';

    Promise.all([
      fetch(`${API_BASE_URL}/dashboard/map-heatmap?limit=15000${yp}${tp}`).then(r => r.json()),
      fetch(`${API_BASE_URL}/dashboard/timeline-daily${yp}`).then(r => r.json()),
      fetch(`${API_BASE_URL}/dashboard/event-type-distribution${yp}`).then(r => r.json()),
      fetch(`${API_BASE_URL}/dashboard/yearly-stats`).then(r => r.json()),
    ]).then(([mp, tl, et, ys]) => {
      setMapPoints(mp);
      setTimeline(tl);
      setEventTypes(et);
      setYearlyStats(ys);
    }).catch(e => console.error('Data load error', e));
  }, [selectedYear, selectedEventType]);

  // --- Update heat layer (canvas heatmap) ---
  useEffect(() => {
    const map = mapInst.current;
    if (!map || !ready) return;

    if (heatLayer.current) {
      map.removeLayer(heatLayer.current);
      heatLayer.current = null;
    }
    if (!showHeat || !mapPoints.length) return;

    // Build heat data: [lat, lng, intensity]
    // Higher baseline + larger radius = denser heatmap
    const heatData: [number, number, number][] = mapPoints.map(p => [
      p.latitude, p.longitude,
      1 + Math.min(p.fatalities * 0.8, 15),
    ]);

    const layer = (L as any).heatLayer(heatData, {
      radius: 28,
      blur: 16,
      maxZoom: 14,
      max: 12,
      minOpacity: 0.25,
      gradient: {
        0.15: '#2563eb',
        0.35: '#06b6d4',
        0.50: '#22c55e',
        0.65: '#eab308',
        0.80: '#f97316',
        0.95: '#ef4444',
      },
    });

    layer.addTo(map);
    heatLayer.current = layer;
  }, [mapPoints, showHeat, ready]);

  // --- Update event markers (color-coded by type) ---
  // During animation: show current frame events as bright pulsing dots
  // Normal mode: show sampled events as color-coded dots
  useEffect(() => {
    const map = mapInst.current;
    if (!map || !ready) return;

    if (markerLayer.current) {
      map.removeLayer(markerLayer.current);
      markerLayer.current = null;
    }
    if (!showMarkers) return;

    if (animMode && currentFrame) {
      // Animation mode: show CURRENT FRAME events large and bright
      if (!currentFrame.events.length) return;
      const canvas = L.canvas({ padding: 0.5 });
      const layer = L.layerGroup([], { renderer: canvas });

      for (const p of currentFrame.events) {
        if (!p.latitude || !p.longitude) continue;
        const marker = L.circleMarker([p.latitude, p.longitude], {
          radius: 5 + Math.min((p.fatalities || 0) * 0.8, 10),
          fillColor: eventColor(p.event_type || ''),
          color: '#ffffff',
          weight: 1.5,
          fillOpacity: 0.9,
        });
        marker.bindTooltip(
          `<b>${p.event_type}</b><br>📍 ${p.location || p.admin1}<br>📅 ${p.event_date || '-'}<br>⚔️ ${p.actor1 || '?'} vs ${p.actor2 || '?'}<br>💀 ${p.fatalities || 0}`,
          { direction: 'top', offset: [0, -8] },
        );
        layer.addLayer(marker);
      }

      layer.addTo(map);
      markerLayer.current = layer;
    } else if (!animMode && mapPoints.length) {
      // Normal mode: sampled overview
      const canvas = L.canvas({ padding: 0.5 });
      const layer = L.layerGroup([], { renderer: canvas });

      const sample = mapPoints.length <= 3000
        ? mapPoints
        : mapPoints.filter(() => Math.random() < (3000 / mapPoints.length));

      for (const p of sample) {
        const marker = L.circleMarker([p.latitude, p.longitude], {
          radius: 4 + Math.min(p.fatalities * 0.5, 6),
          fillColor: eventColor(p.event_type),
          color: 'rgba(255,255,255,0.3)',
          weight: 0.5,
          fillOpacity: 0.7,
        });
        marker.bindTooltip(
          `<b>${p.event_type}</b><br>📍 ${p.location || p.admin1}<br>📅 ${p.event_date || '-'}<br>⚔️ ${p.actor1 || '?'} vs ${p.actor2 || '?'}<br>💀 ${p.fatalities || 0}`,
          { direction: 'top', offset: [0, -6] },
        );
        layer.addLayer(marker);
      }

      layer.addTo(map);
      markerLayer.current = layer;
    }
  }, [mapPoints, showMarkers, ready, animMode, animIndex, currentFrame]);

  // --- Update GeoJSON regions ---
  useEffect(() => {
    const map = mapInst.current;
    if (!map || !ready) return;

    if (geoLayer.current) {
      map.removeLayer(geoLayer.current);
      geoLayer.current = null;
    }
    if (!showRegions) return;

    fetch('/ukraine-regions.json')
      .then(r => r.json())
      .then(geo => {
        if (!mapInst.current) return;
        const layer = L.geoJSON(geo, {
          style: (f: any) => ({
            fillColor: f.properties.color,
            fillOpacity: 0.1,
            color: f.properties.color,
            weight: 1.5,
            opacity: 0.4,
          }),
          onEachFeature: (f: any, l: L.Layer) => {
            l.bindTooltip(
              `<b>${f.properties.name}</b><br>事件: ${f.properties.event_count.toLocaleString()}<br>死亡: ${f.properties.fatalities.toLocaleString()}`,
              { sticky: true },
            );
          },
        }).addTo(map);
        geoLayer.current = layer;
      })
      .catch(() => {});
  }, [showRegions, ready]);

  // --- ECharts charts ---
  useEffect(() => {
    if (!timeChartRef.current || !timeline.length) return;
    let c = false;
    import('echarts').then(m => {
      if (c || !timeChartRef.current) return;
      const e = (m as any).default || m;
      const i = e.init(timeChartRef.current, 'dark');
      timeInst.current = i;
      i.setOption({
        backgroundColor: 'transparent',
        tooltip: { trigger: 'axis' },
        grid: { left: 4, right: 8, top: 8, bottom: 28 },
        xAxis: { type: 'category', data: timeline.map(d => d.date), axisLabel: { color: '#94a3b8', fontSize: 8, rotate: 20 } },
        yAxis: { type: 'value', splitLine: { lineStyle: { color: '#1e293b' } }, axisLabel: { color: '#94a3b8', fontSize: 8 } },
        dataZoom: [{ type: 'slider', height: 12, bottom: 4 }],
        series: [{ type: 'bar', data: timeline.map(d => d.count), itemStyle: { color: '#3b82f6' } }],
      });
      const r = () => i.resize();
      window.addEventListener('resize', r);
      return () => { window.removeEventListener('resize', r); };
    });
    return () => { c = true; timeInst.current?.dispose(); };
  }, [timeline]);

  useEffect(() => {
    if (!yearChartRef.current || !yearlyStats.length) return;
    let c = false;
    import('echarts').then(m => {
      if (c || !yearChartRef.current) return;
      const e = (m as any).default || m;
      const i = e.init(yearChartRef.current, 'dark');
      yearInst.current = i;
      i.setOption({
        backgroundColor: 'transparent',
        tooltip: { trigger: 'axis' },
        legend: { data: ['事件数', '死亡'], bottom: 0, textStyle: { color: '#94a3b8', fontSize: 8 } },
        grid: { left: 4, right: 8, top: 8, bottom: 28 },
        xAxis: { type: 'category', data: yearlyStats.map(y => String(y.year)), axisLabel: { color: '#94a3b8', fontSize: 9 } },
        yAxis: [
          { type: 'value', splitLine: { lineStyle: { color: '#1e293b' } }, axisLabel: { color: '#94a3b8', fontSize: 8 } },
        ],
        series: [
          { name: '事件数', type: 'bar', data: yearlyStats.map(y => y.count), itemStyle: { color: '#3b82f6', borderRadius: [3,3,0,0] } },
          { name: '死亡', type: 'line', data: yearlyStats.map(y => y.fatalities), smooth: true, lineStyle: { color: '#ef4444', width: 2 }, itemStyle: { color: '#ef4444' }, symbolSize: 4 },
        ],
      });
      i.on('click', (p: any) => {
        if (yearlyStats[p.dataIndex]) {
          const yr = yearlyStats[p.dataIndex].year;
          setSelectedYear(prev => prev === yr ? null : yr);
        }
      });
      const r = () => i.resize();
      window.addEventListener('resize', r);
      return () => { window.removeEventListener('resize', r); };
    });
    return () => { c = true; yearInst.current?.dispose(); };
  }, [yearlyStats]);

  useEffect(() => {
    if (!pieChartRef.current || !eventTypes.length) return;
    let c = false;
    import('echarts').then(m => {
      if (c || !pieChartRef.current) return;
      const e = (m as any).default || m;
      const i = e.init(pieChartRef.current, 'dark');
      pieInst.current = i;
      i.setOption({
        backgroundColor: 'transparent',
        tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
        legend: { orient: 'vertical', right: 0, top: 'center', textStyle: { color: '#94a3b8', fontSize: 8 } },
        series: [{
          type: 'pie', radius: ['40%', '70%'], center: ['38%', '50%'],
          data: eventTypes.slice(0, 7).map(et => ({
            name: et.event_type, value: et.count,
            itemStyle: { color: eventColor(et.event_type), borderColor: '#0f172a', borderWidth: 2, borderRadius: 4 },
          })),
          label: { show: false }, emphasis: { label: { show: true, color: '#f1f5f9' } },
        }],
      });
      i.on('click', (p: any) => setSelectedEventType(prev => prev === p.name ? null : p.name));
      const r = () => i.resize();
      window.addEventListener('resize', r);
      return () => { window.removeEventListener('resize', r); };
    });
    return () => { c = true; pieInst.current?.dispose(); };
  }, [eventTypes]);

  const totalEvents = yearlyStats.reduce((s, y) => s + y.count, 0);
  const totalFatalities = yearlyStats.reduce((s, y) => s + y.fatalities, 0);
  const years = Array.from(new Set(yearlyStats.map(y => y.year))).sort();

  // Cleanup all
  useEffect(() => () => {
    mapInst.current?.remove();
    timeInst.current?.dispose();
    yearInst.current?.dispose();
    pieInst.current?.dispose();
  }, []);

  return (
    <div style={fullscreen ? {
      position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, zIndex: 9999,
      display: 'flex', flexDirection: 'column',
      background: '#0f172a', color: '#e2e8f0', fontFamily: "system-ui,sans-serif",
    } : {
      height: '100%', width: '100%',
      display: 'flex', flexDirection: 'column',
      background: '#0f172a', color: '#e2e8f0', fontFamily: "system-ui,sans-serif",
      borderRadius: 12, border: '1px solid #1e293b',
    }}>
      {/* Top bar */}
      <div style={{
        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        padding: '6px 14px', background: '#0f172a', borderBottom: '1px solid #1e293b',
        flexShrink: 0, zIndex: 10000,
      }}>
        <div>
          <h1 style={{ margin: 0, fontSize: 17, fontWeight: 700 }}>🔴 俄乌冲突地理情报沙盘</h1>
          <p style={{ margin: 0, fontSize: 10, color: '#64748b' }}>OpenStreetMap · Leaflet · ACLED Data</p>
        </div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          {fullscreen && (
            <button onClick={() => window.dispatchEvent(new CustomEvent('app-navigate', { detail: 'home' }))}
              style={{ background: '#1e293b', color: '#94a3b8', border: '1px solid #334155', borderRadius: 6, padding: '4px 12px', fontSize: 12, cursor: 'pointer' }}>
              ← 返回首页
            </button>
          )}
          <select value={selectedYear || ''} onChange={e => setSelectedYear(e.target.value ? Number(e.target.value) : null)}
            style={{ background: '#1e293b', color: '#e2e8f0', border: '1px solid #334155', borderRadius: 6, padding: '4px 8px', fontSize: 12 }}>
            <option value="">全部年份</option>
            {years.map(y => <option key={y} value={y}>{y}</option>)}
          </select>
          <div style={{ display: 'flex', borderRadius: 6, overflow: 'hidden', border: '1px solid #334155' }}>
            <button onClick={() => setShowHeat(!showHeat)}
              style={{ padding: '4px 10px', fontSize: 11, cursor: 'pointer', border: 'none', background: showHeat ? '#f97316' : '#1e293b', color: showHeat ? '#fff' : '#94a3b8' }}>
              🔥 热力
            </button>
            <button onClick={() => { setAnimMode(!animMode); setAnimPlaying(!animMode); }}
              style={{ padding: '4px 10px', fontSize: 11, cursor: 'pointer', border: 'none', background: animMode ? '#22c55e' : '#1e293b', color: animMode ? '#000' : '#94a3b8' }}>
              ▶️ 回放
            </button>
            <button onClick={() => setShowMarkers(!showMarkers)}
              style={{ padding: '4px 10px', fontSize: 11, cursor: 'pointer', border: 'none', background: showMarkers ? '#3b82f6' : '#1e293b', color: showMarkers ? '#fff' : '#94a3b8' }}>
              📍 事件
            </button>
            <button onClick={() => setShowRegions(!showRegions)}
              style={{ padding: '4px 10px', fontSize: 11, cursor: 'pointer', border: 'none', background: showRegions ? '#8b5cf6' : '#1e293b', color: showRegions ? '#fff' : '#94a3b8' }}>
              🗺️ 区域
            </button>
          </div>
          {(selectedEventType || selectedYear) && (
            <button onClick={() => { setSelectedYear(null); setSelectedEventType(null); }}
              style={{ background: '#fbbf24', color: '#0f172a', border: 'none', borderRadius: 6, padding: '4px 10px', fontSize: 11, cursor: 'pointer', fontWeight: 600 }}>
              ✕ 重置
            </button>
          )}
        </div>
      </div>

      {/* Map */}
      <div style={{ flex: 1, position: 'relative', minHeight: 0 }}>
        <div ref={mapRef} style={{ width: '100%', height: '100%' }} />

        {/* KPI overlay — fullscreen only */}
        {fullscreen ? (
        <div style={{ position: 'absolute', top: 10, right: 10, zIndex: 1000, display: 'flex', gap: 8 }}>
          {[
            ['事件总数', totalEvents.toLocaleString(), '#3b82f6'],
            ['死亡人数', totalFatalities.toLocaleString(), '#ef4444'],
            ['事件类型', eventTypes.length, '#22c55e'],
          ].map(([label, val, color]) => (
            <div key={label as string} style={{
              background: 'rgba(15,23,42,0.88)', backdropFilter: 'blur(6px)',
              borderRadius: 8, padding: '8px 14px', border: `1px solid ${(color as string)}44`,
            }}>
              <div style={{ fontSize: 10, color: '#94a3b8' }}>{label}</div>
              <div style={{ fontSize: 22, fontWeight: 700, color: color as string }}>{val}</div>
            </div>
          ))}
        </div>
        ) : null}

        {/* Legend — fullscreen only */}
        {fullscreen ? (
        <div style={{
          position: 'absolute', bottom: 8, left: 8, zIndex: 1000,
          background: 'rgba(15,23,42,0.88)', backdropFilter: 'blur(6px)',
          borderRadius: 8, padding: '6px 10px', display: 'flex', gap: 10, flexWrap: 'wrap',
          border: '1px solid #1e293b',
        }}>
          {Object.entries(EVENT_COLORS).map(([k, v]) => (
            <div key={k} style={{ display: 'flex', alignItems: 'center', gap: 3, fontSize: 9, color: '#94a3b8' }}>
              <div style={{ width: 8, height: 8, borderRadius: 2, background: v }} />{k}
            </div>
          ))}
        </div>
        ) : null}
      </div>

      {/* Animation player bar — fullscreen only */}
      {fullscreen && animMode && animFrames.length > 0 && (
        <div style={{
          flexShrink: 0, padding: '6px 14px', background: '#0f172a',
          borderTop: '2px solid #22c55e', borderBottom: '1px solid #1e293b',
          display: 'flex', alignItems: 'center', gap: 10,
        }}>
          {/* Play/Pause */}
          <button onClick={() => setAnimPlaying(!animPlaying)}
            style={{ background: animPlaying ? '#ef4444' : '#22c55e', color: '#fff', border: 'none', borderRadius: 20, padding: '4px 14px', fontSize: 13, cursor: 'pointer', fontWeight: 700, minWidth: 60 }}>
            {animPlaying ? '⏸ 暂停' : '▶ 播放'}
          </button>

          {/* Speed */}
          <select value={animSpeed} onChange={e => setAnimSpeed(Number(e.target.value))}
            style={{ background: '#1e293b', color: '#e2e8f0', border: '1px solid #334155', borderRadius: 4, padding: '3px 6px', fontSize: 11 }}>
            <option value={1}>1x 天</option>
            <option value={2}>2x</option>
            <option value={3}>3x</option>
            <option value={5}>5x</option>
            <option value={10}>10x</option>
            <option value={30}>30x (月)</option>
          </select>

          {/* Timeline slider */}
          <input type="range" min={0} max={animFrames.length - 1} value={animIndex}
            onChange={e => { setAnimIndex(Number(e.target.value)); setAnimPlaying(false); }}
            style={{ flex: 1, accentColor: '#22c55e', height: 4 }}
          />

          {/* Frame info */}
          <div style={{ fontSize: 12, color: '#f1f5f9', fontWeight: 600, minWidth: 80, textAlign: 'right' }}>
            📅 {currentFrame?.date || '-'}
          </div>
          <div style={{ fontSize: 11, color: '#3b82f6', minWidth: 50, textAlign: 'right' }}>
            ⚡ {currentFrame?.day_count || 0} 事件
          </div>
          <div style={{ fontSize: 11, color: '#ef4444', minWidth: 50, textAlign: 'right' }}>
            💀 {currentFrame?.day_fatalities || 0} 死亡
          </div>
          <div style={{ fontSize: 11, color: '#94a3b8', minWidth: 60, textAlign: 'right' }}>
            累计 {currentFrame?.cumulative_count?.toLocaleString() || 0}
          </div>

          {/* Close */}
          <button onClick={() => { setAnimMode(false); setAnimPlaying(false); }}
            style={{ background: '#1e293b', color: '#94a3b8', border: '1px solid #334155', borderRadius: 4, padding: '3px 10px', fontSize: 11, cursor: 'pointer' }}>
            ✕ 退出回放
          </button>
        </div>
      )}

      {/* Bottom charts — fullscreen only */}
      {fullscreen && (
        <div style={{
          height: 170, flexShrink: 0, display: 'grid', gridTemplateColumns: '2fr 1fr 1fr',
          gap: 4, padding: '4px 8px', background: '#0f172a', borderTop: '1px solid #1e293b',
        }}>
          <div style={{ background: '#0f172a', borderRadius: 8, border: '1px solid #1e293b', overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
            <div style={{ padding: '2px 8px', fontSize: 10, color: '#64748b', flexShrink: 0 }}>📈 每日冲突时间线</div>
            <div ref={timeChartRef} style={{ flex: 1 }} />
          </div>
          <div style={{ background: '#0f172a', borderRadius: 8, border: '1px solid #1e293b', overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
            <div style={{ padding: '2px 8px', fontSize: 10, color: '#64748b', flexShrink: 0 }}>📊 年度趋势 (点击筛选)</div>
            <div ref={yearChartRef} style={{ flex: 1 }} />
          </div>
          <div style={{ background: '#0f172a', borderRadius: 8, border: '1px solid #1e293b', overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
            <div style={{ padding: '2px 8px', fontSize: 10, color: '#64748b', flexShrink: 0 }}>🎯 事件类型 (点击筛选)</div>
            <div ref={pieChartRef} style={{ flex: 1 }} />
          </div>
        </div>
      )}
    </div>
  );
}
