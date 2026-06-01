import { useEffect, useRef, type MutableRefObject } from 'react';
import type { DocumentGraphResponse, GraphNode } from '../types';
import { colorForNodeType } from '../lib/graphTheme';

type EChartsInstance = {
  setOption: (o: unknown) => void;
  dispose: () => void;
  resize: () => void;
  on: (event: string, handler: (params: { data?: { id?: string } }) => void) => void;
  off: (event: string) => void;
};

type Props = {
  graph: DocumentGraphResponse | null;
  graphHint: string | null;
  modeLabel: string;
  selectedNodeId: string | null;
  onNodeSelect: (node: GraphNode | null) => void;
};

export function GraphPanel({ graph, graphHint, modeLabel, selectedNodeId, onNodeSelect }: Props) {
  const chartRef = useRef<HTMLDivElement | null>(null);
  const chartInstance = useRef<EChartsInstance | null>(null);
  const nodeMapRef = useRef<Map<string, GraphNode>>(new Map());
  const onNodeSelectRef = useRef(onNodeSelect) as MutableRefObject<(node: GraphNode | null) => void>;
  onNodeSelectRef.current = onNodeSelect;

  useEffect(() => {
    let cancelled = false;
    let resizeHandler: (() => void) | null = null;

    chartInstance.current?.dispose();
    chartInstance.current = null;
    nodeMapRef.current = new Map();

    if (!graph?.nodes.length || !chartRef.current) {
      return () => {
        cancelled = true;
      };
    }

    const snapshot = graph;
    const nodeMap = new Map(snapshot.nodes.map((node) => [node.id, node]));
    nodeMapRef.current = nodeMap;

    void import('echarts').then((echartsModule) => {
      if (cancelled || !chartRef.current) {
        return;
      }
      const echarts = echartsModule as {
        init: (dom: HTMLElement) => EChartsInstance;
      };
      const chart = echarts.init(chartRef.current);
      if (cancelled) {
        chart.dispose();
        return;
      }
      chartInstance.current = chart;

      const categories = Array.from(new Set(snapshot.nodes.map((node) => node.node_type))).map((name) => ({
        name,
        itemStyle: { color: colorForNodeType(name) },
      }));
      const categoryIndex = new Map(categories.map((item, index) => [item.name, index]));

      const nodes = snapshot.nodes.map((node) => ({
        id: node.id,
        name: node.label,
        category: categoryIndex.get(node.node_type) ?? 0,
        symbolSize: selectedNodeId === node.id ? 36 : 18 + Math.min(22, (node.chunk_ids?.length ?? 0) * 2),
        value: node.label,
        itemStyle:
          selectedNodeId && selectedNodeId !== node.id
            ? { opacity: 0.35 }
            : { opacity: 1, borderColor: selectedNodeId === node.id ? '#fff' : undefined, borderWidth: selectedNodeId === node.id ? 2 : 0 },
      }));

      const links = snapshot.edges.map((edge) => ({
        source: edge.source,
        target: edge.target,
        value: edge.relation_type,
        label: { show: true, formatter: edge.relation_type, fontSize: 10, color: '#9fb1c8' },
        lineStyle: { opacity: selectedNodeId ? 0.35 : 0.85 },
      }));

      chart.setOption({
        backgroundColor: 'transparent',
        tooltip: {
          trigger: 'item',
          formatter: (params: { dataType?: string; data?: { id?: string; name?: string } }) => {
            if (params.dataType !== 'node' || !params.data?.id) {
              return '';
            }
            const full = nodeMap.get(params.data.id);
            if (!full) {
              return params.data.name ?? '';
            }
            return `<strong>${full.label}</strong><br/>类型：${full.node_type}<br/>溯源 chunk：${full.chunk_ids.join(', ') || '无'}`;
          },
        },
        legend: { data: categories.map((c) => c.name), textStyle: { color: '#9fb1c8' }, bottom: 0 },
        series: [
          {
            type: 'graph',
            layout: 'force',
            roam: true,
            draggable: true,
            categories,
            data: nodes,
            links,
            label: { show: true, position: 'right', color: '#e8eef7', fontSize: 11 },
            lineStyle: { color: 'source', curveness: 0.12 },
            emphasis: { focus: 'adjacency', lineStyle: { width: 4 } },
            force: { repulsion: 380, edgeLength: [90, 180], gravity: 0.08, friction: 0.35 },
          },
        ],
      });

      const handleClick = (params: { data?: { id?: string } }) => {
        if (!params.data?.id) {
          onNodeSelect(null);
          return;
        }
        const node = nodeMap.get(params.data.id) ?? null;
        onNodeSelectRef.current(node);
      };
      chart.on('click', handleClick);

      if (cancelled) {
        chart.off('click');
        chart.dispose();
        chartInstance.current = null;
        return;
      }
      resizeHandler = () => chart.resize();
      window.addEventListener('resize', resizeHandler);
    });

    return () => {
      cancelled = true;
      if (resizeHandler) {
        window.removeEventListener('resize', resizeHandler);
      }
      chartInstance.current?.off('click');
      chartInstance.current?.dispose();
      chartInstance.current = null;
    };
  }, [graph, selectedNodeId]);

  return (
    <div className="graph-panel">
      <div className="graph-panel-toolbar">
        <span className="graph-mode-tag">{modeLabel}</span>
        {graph && (
          <span className="muted">
            {graph.nodes.length} 节点 · {graph.edges.length} 关系
          </span>
        )}
      </div>
      {graphHint && !graph?.nodes.length && <div className="inline-hint">{graphHint}</div>}
      <div ref={chartRef} className="graph-canvas" />
      {!graph?.nodes.length && !graphHint && <div className="graph-empty">解析文档并抽取图谱后，将在此展示力导向图</div>}
    </div>
  );
}
