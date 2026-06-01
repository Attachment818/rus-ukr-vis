export const API_BASE_URL = 'http://127.0.0.1:8000';
const REQUEST_TIMEOUT_MS = 190000;

async function request(path: string, init?: RequestInit): Promise<Response> {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  try {
    return await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      signal: controller.signal,
    });
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') {
      throw new Error(
        `后端接口超时：${path}。服务已连接，但该请求在 190 秒内未完成；可能是模型响应过慢、检索过程阻塞，或后端仍在处理。`,
      );
    }
    if (err instanceof TypeError) {
      throw new Error(`无法连接后端：${API_BASE_URL}${path}。请先启动 FastAPI 后端。`);
    }
    throw err;
  } finally {
    window.clearTimeout(timer);
  }
}

async function readErrorMessage(response: Response): Promise<string> {
  const text = await response.text();
  if (!text) {
    return `Request failed: ${response.status}`;
  }
  try {
    const payload = JSON.parse(text) as { detail?: string | { msg?: string }[] };
    if (typeof payload.detail === 'string') {
      return payload.detail;
    }
    if (Array.isArray(payload.detail) && payload.detail[0]?.msg) {
      return payload.detail[0].msg;
    }
  } catch {
    /* not JSON */
  }
  return text;
}

export async function fetchJson<T>(path: string): Promise<T> {
  const response = await request(path);
  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }
  return response.json() as Promise<T>;
}

export async function postJson<T>(path: string, payload: unknown): Promise<T> {
  const response = await request(path, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }
  return response.json() as Promise<T>;
}

export async function postFormData<T>(path: string, payload: FormData): Promise<T> {
  const response = await request(path, {
    method: 'POST',
    body: payload,
  });
  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }
  return response.json() as Promise<T>;
}

/** POST with empty body (e.g. trigger graph extraction). */
export async function postEmpty<T>(path: string): Promise<T> {
  const response = await request(path, { method: 'POST' });
  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }
  return response.json() as Promise<T>;
}

export async function deleteJson<T>(path: string): Promise<T> {
  const response = await request(path, { method: 'DELETE' });
  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }
  return response.json() as Promise<T>;
}
