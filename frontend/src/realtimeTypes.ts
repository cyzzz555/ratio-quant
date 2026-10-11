export interface RealtimeInstrument {
  symbol:string;name_zh:string;pool:string;quality:string;closed_minutes:number;
  latest_price:string|null;mark_price:string|null;last_kline_event_at:string|null;
  latest_closed_at:string|null;regime:string;strategy_priority:string;
  gaps:{after:string;before:string;missing_count:number}[];
  scores:Record<string,{value:number|null;state:string}>;
}
export interface RealtimeSignal {
  id:string;symbol:string;strategy:string;direction:string;score:number;state:string;
  discovered_at:string;updated_at:string;expires_at:string;reason:string;executable:false;
}
export interface RealtimeSnapshot {
  phase:string;state:string;session_id:string|null;connected:boolean;worker_active:boolean;
  instruments:RealtimeInstrument[];signals:RealtimeSignal[];checked_at:string|null;
  failure:string|null;journal:string|null;live_trading_enabled:false;allow_new_risk:false;
  notifications:{id:string;at:string;severity:string;code:string;symbol:string|null;message:string}[];
  limitations:string[];parameters:Record<string,unknown>;
}
export const qualityLabel:Record<string,string> = {
  STARTING:'正在预热',STOPPED:'已停止',STOPPING:'正在停止',FAILED:'采集失败',
  WARMING:'正在预热',HEALTHY:'行情新鲜',DISCONNECTED:'连接中断',
  KLINE_STALE:'K 线等待或延迟',MARK_STALE:'标记价等待或延迟',
  GAP_UNVERIFIED:'分钟缺口 · 原因待核验',CLOSED_BAR_STALE:'闭合 K 线延迟',
  BAR_CONFLICT:'同分钟价格冲突',SPEC_CHANGED:'合约规格已变化',SPEC_STALE:'规格核验过期',
  WRONG_PRODUCT_FAMILY:'产品类型不匹配',STREAMING:'实时接收中',
};
export const signalLabel:Record<string,string> = {
  WATCHING:'观察中',CONFIRMED:'研究确认',INVALIDATED:'已失效',EXPIRED:'已过期',
};
