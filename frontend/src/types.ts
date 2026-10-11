export type Capability = {
  symbol: string; capability_state: string; product_family: string;
  public_exchangeinfo_visible: boolean | null; account_trade_permission: 'UNKNOWN';
  trading_status: string | null; historical_bars_available: boolean | null;
  websocket_works: boolean | null; mark_price_available: boolean | null;
  funding_data_available: boolean | null; max_account_leverage: number | null;
  max_public_leverage: number | null; isolated_supported: boolean | null;
  reduce_only_supported: boolean | null; stop_type_supported: boolean | null;
  history_start_at: string | null; verified_at: string; notes: string[];
  evidence: {source: string; timestamp: string; result: string; raw_hash: string | null}[];
};
export type Report = { run_id: string; generated_at: string; instruments: Capability[] };
export type Health = {
  service_ready: boolean; trading_ready: false; allow_new_risk: false;
  live_trading_enabled: false; checked_at: string; reasons: string[];
};
export type ProbeJob = {
  job_id: string | null; state: 'IDLE' | 'RUNNING' | 'SUCCEEDED' | 'FAILED';
  started_at: string | null; finished_at: string | null; exit_code: number | null;
  message: string; completed_symbols: string[]; total_symbols: number; log: string;
};
export type Quality = {
  symbol: string; closed_sample: number; unclosed_sample: number;
  closed_total: number; timeliness: string; quality: string;
  gaps: unknown[]; normalization_errors: string[]; latest_closed_at: string | null;
};
