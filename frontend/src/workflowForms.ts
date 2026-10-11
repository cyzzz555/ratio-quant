export type ViewMode = 'simple' | 'full';
export const viewModeLabel = (mode:ViewMode) => mode === 'simple' ? '简化模式' : '完整模式';

export const backtestDefaults = {
  timeframe:'5m',initial_equity:'1000',risk_pct:'1',fee_bps:'5',slippage_bps:'2',
  spread_bps:'1',participation_pct:'1',simulated_multiplier:'1',fast_window:'6',
  slow_window:'12',pullback_window:'6',stop_window:'5',max_holding_bars:'12',reward_risk:'2',
};
export const riskDefaults = {
  mode:'micro_capital',direction:'LONG',equity:'1000',principal:'1000',net_flows:'0',
  peak:'1000',entry:'100',stop:'98',risk_pct:'1',exchange_leverage:'20',
  existing_notional:'0',pending_notional:'0',extra_loss_per_unit:'0',
  step:'0.001',tick:'0.01',min_qty:'0.001',min_notional:'5',
};
export type BacktestForm = typeof backtestDefaults;
export type RiskForm = typeof riskDefaults;
export interface NumericField<K extends string> {key:K;label:string;simple:boolean;min?:number;max?:number;integer?:boolean}
export const backtestFields:NumericField<Exclude<keyof BacktestForm,'timeframe'>>[] = [
  {key:'initial_equity',label:'模拟初始权益',simple:true,min:0},
  {key:'risk_pct',label:'单笔风险 %',simple:true,min:0,max:2},
  {key:'fee_bps',label:'单边手续费 bps',simple:false,min:0,max:100},
  {key:'slippage_bps',label:'单边滑点 bps',simple:false,min:0,max:100},
  {key:'spread_bps',label:'完整价差 bps',simple:false,min:0,max:100},
  {key:'participation_pct',label:'前根成交量参与率 %',simple:false,min:0,max:10},
  {key:'simulated_multiplier',label:'假设乘数',simple:false,min:0},
  {key:'fast_window',label:'1h 快均线根数',simple:false,min:2,max:30,integer:true},
  {key:'slow_window',label:'1h 慢均线根数',simple:false,min:4,max:60,integer:true},
  {key:'pullback_window',label:'回拉均线根数',simple:false,min:2,max:30,integer:true},
  {key:'stop_window',label:'止损回看根数',simple:false,min:2,max:30,integer:true},
  {key:'max_holding_bars',label:'最长持有根数',simple:false,min:1,max:100,integer:true},
  {key:'reward_risk',label:'目标盈亏比',simple:false,min:1,max:5},
];
export const riskFields:NumericField<Exclude<keyof RiskForm,'mode'|'direction'>>[] = [
  {key:'equity',label:'净权益 USDT',simple:true,min:0},
  {key:'principal',label:'初始本金 USDT',simple:true,min:0},
  {key:'net_flows',label:'后续净入金 USDT',simple:false},
  {key:'peak',label:'资金流调整后最高权益',simple:true,min:0},
  {key:'entry',label:'计划入场价',simple:true,min:0},
  {key:'stop',label:'计划止损价',simple:true,min:0},
  {key:'risk_pct',label:'计划风险 %',simple:true,min:0,max:2},
  {key:'exchange_leverage',label:'交易所单仓杠杆',simple:true,min:1,max:100,integer:true},
  {key:'existing_notional',label:'现有仓位名义金额',simple:false,min:0},
  {key:'pending_notional',label:'待成交名义金额',simple:false,min:0},
  {key:'extra_loss_per_unit',label:'每单位额外成本损失',simple:false,min:0},
  {key:'step',label:'模拟数量步长',simple:false,min:0},
  {key:'tick',label:'模拟价格步长',simple:false,min:0},
  {key:'min_qty',label:'模拟最小数量',simple:false,min:0},
  {key:'min_notional',label:'模拟最小名义金额',simple:false,min:0},
];

// Decimal values stay as strings; changing the view never changes the submitted plan.
export function backtestBody(params:BacktestForm,datasetId:string) {
  const integers = new Set<string>(backtestFields.filter(f=>f.integer).map(f=>f.key));
  return {...Object.fromEntries(Object.entries(params).map(([k,v])=>[k,integers.has(k)?Number(v):v])),dataset_id:datasetId};
}
export function riskBody(form:RiskForm) {
  return {...form,exchange_leverage:Number(form.exchange_leverage)};
}
