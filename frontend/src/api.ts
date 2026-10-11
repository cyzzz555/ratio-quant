export async function api<T>(url:string, body?:unknown):Promise<T> {
  const response = await fetch(url, body === undefined ? undefined : {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : `HTTP ${response.status}：请检查输入和服务`);
  return data as T;
}
export const localTime = (value:string) => new Date(value).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false});
export const numberText = (value:string|null|undefined, digits=2) => value == null ? '—' : Number(value).toLocaleString('zh-CN',{maximumFractionDigits:digits});
