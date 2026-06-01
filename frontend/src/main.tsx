import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import './app.css';

function renderBootError(title: string, detail: unknown) {
  const root = document.getElementById('root');
  if (!root) return;
  const message = detail instanceof Error ? detail.stack || detail.message : String(detail);
  root.innerHTML = `
    <main style="max-width: 920px; margin: 32px auto; padding: 24px; font-family: Segoe UI, sans-serif;">
      <h1 style="margin: 0 0 12px; font-size: 22px;">${title}</h1>
      <pre style="white-space: pre-wrap; background: #fef2f2; border: 1px solid #fca5a5; color: #991b1b; padding: 16px; border-radius: 8px;">${message}</pre>
      <p style="color: #475569;">请把这段错误发给维护者，或打开浏览器 DevTools Console 查看更完整堆栈。</p>
    </main>
  `;
}

window.addEventListener('error', (event) => {
  renderBootError('前端运行时错误', event.error || event.message);
});

window.addEventListener('unhandledrejection', (event) => {
  renderBootError('前端异步错误', event.reason);
});

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
