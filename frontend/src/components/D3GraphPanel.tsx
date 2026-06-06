import { useEffect, useRef, useState, useCallback } from 'react';
import * as d3 from 'd3';
import { API_BASE_URL } from '../lib/api';

// --- Types ---
type GraphNode = { id: string; type: string; name: string; degree: number };
type GraphEdge = { source: string; target: string; relation_type: string };
type GraphData = { nodes: GraphNode[]; edges: GraphEdge[] };

// --- Colors / Visual config ---
const TYPE_COLORS: Record<string, string> = {
  ConflictEvent: '#ef4444',
  ConflictActor: '#3b82f6',
  ConflictLocation: '#22c55e',
  ConflictSource: '#8b5cf6',
  IntelEntity: '#f97316',
};
const DEFAULT_COLOR = '#94a3b8';

function typeColor(t: string) { return TYPE_COLORS[t] || DEFAULT_COLOR; }

// --- Component ---
export default function D3GraphPanel() {
  const svgRef = useRef<SVGSVGElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [data, setData] = useState<GraphData | null>(null);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<string | null>(null);
  const [search, setSearch] = useState('');

  // Load data
  useEffect(() => {
    setLoading(true);
    const params = new URLSearchParams();
    if (filter) params.set('entity_type', filter);
    params.set('node_limit', '400');
    params.set('edge_limit', '800');

    fetch(`${API_BASE_URL}/graph/full-graph?${params}`)
      .then(r => r.json())
      .then(d => { setData(d); setLoading(false); })
      .catch(() => setLoading(false));
  }, [filter]);

  // D3 render
  useEffect(() => {
    if (!data || !svgRef.current || !containerRef.current) return;

    const container = containerRef.current;
    const W = container.clientWidth;
    const H = container.clientHeight;

    // Clear
    const svg = d3.select(svgRef.current);
    svg.selectAll('*').remove();
    svg.attr('width', W).attr('height', H);

    // Filter out orphan nodes (no edges referencing them)
    const edgeSourceSet = new Set(data.edges.map(e => e.source));
    const edgeTargetSet = new Set(data.edges.map(e => e.target));
    const connectedIds = new Set([...edgeSourceSet, ...edgeTargetSet]);

    const nodes: (GraphNode & { x?: number; y?: number; fx?: number | null; fy?: number | null })[] = data.nodes
      .filter(n => connectedIds.has(n.id))
      .map(n => ({ ...n, x: W / 2 + (Math.random() - 0.5) * 200, y: H / 2 + (Math.random() - 0.5) * 200 }));

    const links: (GraphEdge & { source: any; target: any })[] = data.edges
      .filter(e => connectedIds.has(e.source) && connectedIds.has(e.target))
      .map(e => ({
        ...e,
        source: e.source,
        target: e.target,
      }));

    // Scales
    const maxDegree = d3.max(nodes, d => d.degree) || 1;
    const radiusScale = d3.scaleSqrt().domain([0, maxDegree]).range([4, 22]);
    const linkOpacity = d3.scaleLinear().domain([0, nodes.length]).range([0.08, 0.35]);

    // Zoom
    const g = svg.append('g');
    const zoom = d3.zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.15, 6])
      .on('zoom', (event) => g.attr('transform', event.transform));
    svg.call(zoom);

    // Arrow marker
    svg.append('defs').selectAll('marker')
      .data(['arrow']).enter().append('marker')
      .attr('id', 'arrow')
      .attr('viewBox', '0 -5 10 10').attr('refX', 20).attr('refY', 0)
      .attr('markerWidth', 4).attr('markerHeight', 4).attr('orient', 'auto')
      .append('path')
      .attr('d', 'M0,-5L10,0L0,5').attr('fill', '#475569');

    // Links
    const link = g.append('g').selectAll('line')
      .data(links).enter().append('line')
      .attr('stroke', '#334155')
      .attr('stroke-width', 1)
      .attr('stroke-opacity', d => linkOpacity(nodes.length))
      .attr('marker-end', 'url(#arrow)');

    // Nodes
    const node = g.append('g').selectAll('g')
      .data(nodes).enter().append('g')
      .attr('cursor', 'pointer')
      .call(d3.drag<SVGGElement, GraphNode>()
        .on('start', (event, d) => {
          if (!event.active) sim.alphaTarget(0.3).restart();
          d.fx = d.x; d.fy = d.y;
        })
        .on('drag', (event, d) => { d.fx = event.x; d.fy = event.y; })
        .on('end', (event, d) => {
          if (!event.active) sim.alphaTarget(0);
          d.fx = null; d.fy = null;
        }) as any);

    // Circles
    node.append('circle')
      .attr('r', d => radiusScale(d.degree))
      .attr('fill', d => typeColor(d.type))
      .attr('stroke', '#0f172a')
      .attr('stroke-width', 1.5)
      .attr('opacity', 0.85);

    // Labels
    node.append('text')
      .text(d => d.name.length > 18 ? d.name.slice(0, 18) + '…' : d.name)
      .attr('x', d => radiusScale(d.degree) + 5)
      .attr('y', 3)
      .attr('fill', '#cbd5e1')
      .attr('font-size', 9)
      .attr('font-family', 'system-ui, sans-serif')
      .attr('pointer-events', 'none');

    // Hover behavior
    node.on('mouseenter', function (_event, d) {
      const neighbors = new Set<string>();
      links.forEach(l => {
        const s = typeof l.source === 'object' ? l.source.id : l.source;
        const t = typeof l.target === 'object' ? l.target.id : l.target;
        if (s === d.id) neighbors.add(t);
        if (t === d.id) neighbors.add(s);
      });
      node.select('circle').attr('opacity', n => neighbors.has(n.id) || n.id === d.id ? 1 : 0.1);
      link.attr('stroke-opacity', l => {
        const s = typeof l.source === 'object' ? l.source.id : l.source;
        const t = typeof l.target === 'object' ? l.target.id : l.target;
        return s === d.id || t === d.id ? 0.8 : 0.02;
      }).attr('stroke', l => {
        const s = typeof l.source === 'object' ? l.source.id : l.source;
        const t = typeof l.target === 'object' ? l.target.id : l.target;
        return s === d.id || t === d.id ? '#fbbf24' : '#334155';
      }).attr('stroke-width', l => {
        const s = typeof l.source === 'object' ? l.source.id : l.source;
        const t = typeof l.target === 'object' ? l.target.id : l.target;
        return s === d.id || t === d.id ? 2.5 : 1;
      });
    });

    node.on('mouseleave', () => {
      node.select('circle').attr('opacity', 0.85);
      link.attr('stroke', '#334155').attr('stroke-opacity', d => linkOpacity(nodes.length)).attr('stroke-width', 1);
    });

    // Tooltip on click
    node.on('click', (_event, d) => {
      d3.select('#graph-tooltip').remove();
      const tip = d3.select('body').append('div')
        .attr('id', 'graph-tooltip')
        .style('position', 'fixed')
        .style('top', `${_event.clientY - 10}px`)
        .style('left', `${_event.clientX + 15}px`)
        .style('background', 'rgba(15,23,42,0.95)')
        .style('color', '#e2e8f0')
        .style('padding', '10px 14px')
        .style('border-radius', '8px')
        .style('border', '1px solid #334155')
        .style('font-size', '12px')
        .style('z-index', '99999')
        .style('pointer-events', 'none')
        .html(`<b style="color:${typeColor(d.type)}">${d.type}</b><br/>${d.name}<br/>连接数: ${d.degree}`);
      setTimeout(() => tip.remove(), 3000);
    });

    // Simulation
    const sim = d3.forceSimulation(nodes as any)
      .force('link', d3.forceLink(links).id((d: any) => d.id).distance(80))
      .force('charge', d3.forceManyBody().strength(-200))
      .force('center', d3.forceCenter(W / 2, H / 2))
      .force('collision', d3.forceCollide().radius(d => radiusScale((d as GraphNode).degree) + 3))
      .on('tick', () => {
        link
          .attr('x1', d => (d.source as any).x)
          .attr('y1', d => (d.source as any).y)
          .attr('x2', d => (d.target as any).x)
          .attr('y2', d => (d.target as any).y);
        node.attr('transform', d => `translate(${d.x},${d.y})`);
      });

    return () => { sim.stop(); };
  }, [data]);

  // Resize
  useEffect(() => {
    const handler = () => {
      if (containerRef.current && svgRef.current) {
        const w = containerRef.current.clientWidth;
        const h = containerRef.current.clientHeight;
        d3.select(svgRef.current).attr('width', w).attr('height', h);
      }
    };
    window.addEventListener('resize', handler);
    return () => window.removeEventListener('resize', handler);
  }, []);

  // Search highlight
  const filteredNodes = data?.nodes.filter(n =>
    !search || n.name.toLowerCase().includes(search.toLowerCase())
  ) || [];

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      {/* Toolbar */}
      <div style={{
        display: 'flex', gap: 8, padding: '8px 12px', flexWrap: 'wrap',
        background: '#0f172a', borderBottom: '1px solid #1e293b',
      }}>
        <input
          type="text" placeholder="🔍 搜索节点..."
          value={search} onChange={e => setSearch(e.target.value)}
          style={{
            background: '#1e293b', color: '#e2e8f0', border: '1px solid #334155',
            borderRadius: 6, padding: '4px 10px', fontSize: 12, width: 180,
          }}
        />
        {['ConflictEvent', 'ConflictActor', 'ConflictLocation', 'ConflictSource'].map(t => (
          <button key={t}
            onClick={() => setFilter(filter === t ? null : t)}
            style={{
              background: filter === t ? typeColor(t) : '#1e293b',
              color: filter === t ? '#0f172a' : '#94a3b8',
              border: `1px solid ${filter === t ? typeColor(t) : '#334155'}`,
              borderRadius: 6, padding: '4px 10px', fontSize: 11, cursor: 'pointer',
              fontWeight: filter === t ? 600 : 400,
            }}
          >
            {t === 'ConflictEvent' ? '🔥 事件' : t === 'ConflictActor' ? '👤 行为体' : t === 'ConflictLocation' ? '📍 地点' : '📰 来源'}
          </button>
        ))}
        <span style={{ fontSize: 11, color: '#64748b', marginLeft: 'auto' }}>
          {data ? `${data.nodes.length} 节点 · ${data.edges.length} 关系` : '加载中...'}
        </span>
      </div>

      {/* Chart */}
      <div ref={containerRef} style={{ flex: 1, position: 'relative', background: '#0f172a' }}>
        {loading && (
          <div style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#64748b', zIndex: 10 }}>
            加载中...
          </div>
        )}
        <svg ref={svgRef} style={{ width: '100%', height: '100%' }} />
      </div>
    </div>
  );
}
