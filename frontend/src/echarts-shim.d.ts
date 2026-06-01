/** ECharts：依赖在 package.json 中声明；本地请执行 `npm install`。 */
declare module 'echarts' {
  interface ECharts {
    setOption(option: unknown): void;
    dispose(): void;
    resize(): void;
    on(event: string, handler: (params: { data?: { id?: string } }) => void): void;
    off(event: string): void;
  }
  function init(dom: HTMLElement): ECharts;
}
