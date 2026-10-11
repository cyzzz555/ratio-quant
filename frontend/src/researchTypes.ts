export interface Candle {open_at:string; close_at:string; open:string; high:string; low:string; close:string; volume:string}
export interface Market {symbol:string; quote_asset:string; timeframe:string; bars:Candle[]; forming:{close:string}[]; mark_price:string; funding_rate:string; received_at:string; server_at:string; source:string;archive_used:boolean;chart_gap_count:number}
export interface Dataset {id:string; symbol:string;quote_asset?:string; count:number; days_requested:number; data_hash:string; created_at:string; gaps:unknown[]; complete_requested_range:boolean; warnings:string[]; metadata_ledger:string}
export interface Job {state:string; message:string; kind?:string; result_id?:string}
export interface ResearchStatus {database:{ready:boolean; error?:string; migration?:string}; job:Job}
export interface Metrics {initial_equity:string;final_equity:string;net_pnl:string;return_pct:string;max_drawdown_pct:string;trade_count:number;win_rate_pct:string|null;profit_factor:string|null;costs:Record<string,string>}
export interface Trade {candidate_id:string;direction:string;entry_at:string;exit_at:string;entry:string;exit:string;quantity:string;requested_quantity:string;unfilled_cancelled:string;net_pnl:string;fees:string;funding:string;reason:string}
export interface Split {first_at:string;last_at:string;bars:number;metrics:Metrics;trades:Trade[];equity_curve:{at:string;equity:string}[];candidate_count:number}
export interface Run {run_id:string;created_at:string;dataset_id:string;symbol:string;quote_asset?:string;status:string;parameters:Record<string,string|number>;parameter_hash:string;data_hash:string;code_hash:string;result_hash:string;splits:Record<string,Split>;stress:Record<string,Record<string,Metrics>>;warnings:string[];metadata_ledger:string}
export interface RiskResult {risk_budget:string;quantity:string;notional:string;theoretical_margin:string;effective_leverage:string;principal_loss_pct:string;high_water_drawdown_pct:string;simulation_passed:boolean;reasons:string[];plan_hash:string;risk_state:{state:string;policy_state:string}}

export interface MarketInstrument {symbol:string;base_asset:string;quote_asset:string;contract_type:string;underlying_type:string;name_zh:string;name_source:'LOCAL_DISPLAY_ALIAS'|'UNAVAILABLE';account_permission:'UNKNOWN'}
export interface MarketCatalog {instruments:MarketInstrument[];observed_at:string;raw_hash:string;cache_ttl_seconds:number;live_trading_enabled:false}
export interface NameUpdateResult {catalog:MarketCatalog;affected_symbols:string[];saved_at:string;storage:'LOCAL_DISPLAY_ALIAS'}

export interface TrashRun {run_id:string;symbol:string;created_at:string;deleted_at:string;result_hash:string;dataset_id:string}
