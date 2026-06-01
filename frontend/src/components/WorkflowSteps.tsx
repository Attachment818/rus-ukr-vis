type Step = { id: string; label: string; detail: string; done: boolean; active: boolean };

type Props = {
  hasDocument: boolean;
  hasGraph: boolean;
  hasQa: boolean;
};

export function WorkflowSteps({ hasDocument, hasGraph, hasQa }: Props) {
  const steps: Step[] = [
    {
      id: 'parse',
      label: '上传并解析',
      detail: hasDocument ? '文本块已入库' : '上传 PDF / DOCX / TXT',
      done: hasDocument,
      active: !hasDocument,
    },
    {
      id: 'graph',
      label: '抽取知识图谱',
      detail: hasGraph ? '实体关系已构建' : '需配置 LLM API',
      done: hasGraph,
      active: hasDocument && !hasGraph,
    },
    {
      id: 'qa',
      label: '图辅助问答',
      detail: hasQa ? '已完成溯源问答' : '基于图谱 + chunk 检索',
      done: hasQa,
      active: hasGraph && !hasQa,
    },
  ];

  return (
    <ol className="workflow-steps">
      {steps.map((step, index) => (
        <li key={step.id} className={`workflow-step${step.done ? ' is-done' : ''}${step.active ? ' is-active' : ''}`}>
          <span className="workflow-index">{step.done ? '✓' : index + 1}</span>
          <div className="workflow-copy">
            <strong>{step.label}</strong>
            <span>{step.detail}</span>
          </div>
        </li>
      ))}
    </ol>
  );
}
