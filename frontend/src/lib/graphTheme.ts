/** 节点类型 → ECharts 分类色 */
export const NODE_TYPE_COLORS: Record<string, string> = {
  军事组织: '#38bdf8',
  武器装备: '#f97316',
  地理位置: '#4ade80',
  冲突事件: '#f87171',
  行动计划: '#a78bfa',
  时间节点: '#facc15',
};

export function colorForNodeType(nodeType: string): string {
  return NODE_TYPE_COLORS[nodeType] ?? '#94a3b8';
}
