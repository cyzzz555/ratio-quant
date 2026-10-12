export interface PaperOrder {
  id:string;client_order_id:string;plan_hash:string;state:string;filled:string;closed:string;
  simulation_challenge:string;extra_simulation_challenge:string|null;
  plan:{symbol:string;direction:string;entry:string;stop:string;take_profit:string;quantity:string;
    exchange_leverage:number;reserved_risk:string;assumed_liquidation:string;expires_at:string;
    spec_version:string;fee_bps:string;slippage_bps:string;funding_budget_bps:string};
  transitions:{at:string;state:string;reason:string}[];
}
export interface PaperSnapshot {
  id:string;name:string;config:{mode:string;initial_equity:string;assumed_account_max:number};
  persistence:string;reduced_risk_latched:boolean;risk_state:{state:string;new_risk_multiplier:string};metrics:Record<string,string>;blockers:string[];permanent_locks:string[];
  orders:PaperOrder[];positions:{order_id:string;symbol:string;direction:string;quantity:string;
    average_entry:string;stop:string;take_profit:string;protected:boolean}[];
  quotes:{symbol:string;price:string;fresh:boolean;at:string;spec_version:string}[];
  fills:{id:string;kind:string;quantity:string;price:string;commission:string;realized_pnl:string;at:string}[];
  ledger:{kind:string;amount:string;at:string;reference:string}[];
  funding:{symbol:string;rate:string;amount:string;at:string}[];
  live_trading_enabled:false;allow_new_risk:false;policy_state:string;checked_at:string;
}
export interface PaperSessions {sessions:{id:string;name:string;created_at:string}[];persistence:string}
export const paperStates:Record<string,string>={AWAITING_APPROVAL:'等待模拟审批',APPROVED:'已模拟批准',
  SEND_PENDING:'等待纸面提交',RECONCILING:'正在纸面对账',ACKED:'纸面订单已受理',PARTIALLY_FILLED:'部分模拟成交',FILLED:'全部模拟成交',CANCELLED:'剩余已取消',
  REJECTED:'已拒绝',INVALIDATED:'已失效',EXPIRED:'已过期',UNKNOWN_SUBMISSION:'提交结果未知 · 待对账'};
export const paperReasons:Record<string,string>={PRINCIPAL_LOCK:'本金损失达到 40% 模拟锁定线',
  PRINCIPAL_BUDGET_BREACH:'本金损失达到或超过 50% 容忍预算',DRAWDOWN_LOCK:'最高净值回撤锁定',
  DAILY_LOCK:'单日模拟亏损锁定',RECOVERY_REQUIRED:'需人工对账恢复',UNKNOWN_SUBMISSION:'纸面订单状态未知',
  PROTECTION_FAILURE:'模拟保护单失败',HUMAN_KILL_SWITCH:'人工禁止新增模拟风险',
  PROCESS_RESTART_REQUIRES_RECONCILIATION:'服务重启，需人工对账恢复',
  PORTFOLIO_RISK_CAP:'组合计划风险超限',SIMULATED_MARKET_DATA_STALE:'模拟行情已过期，请写入新场景价',
  CANDIDATE_EFFECTIVE_LEVERAGE_CAP:'模拟候选的 2x 总有效杠杆超限',
  SIMULATED_QUOTE_STALE_OR_FUTURE:'场景价格过期，请重新写入报价',
  SINGLE_RISK_BUDGET_EXCEEDED:'指定数量超过单笔风险预算',
  ONE_ISOLATED_PLAN_PER_SYMBOL:'该合约已有持仓或未结束方案',
  EXTRA_SIMULATED_APPROVAL_REQUIRED_21_TO_25X:'21–25x 需要额外模拟审批码',
  APPROVED_PLAN_REQUIRED:'必须先完成模拟审批',RECONCILE_OLD_CLIENT_ID_FIRST:'先对账原订单，不能盲目撤销',
  REDUCE_ONLY_MUST_NOT_OVERSHOOT:'减仓数量必须大于零且不能超过持仓',
  CANDIDATE_MAX_TWO_POSITIONS:'微资金候选最多两组持仓或待执行方案',
  TOTAL_PLANNED_RISK_CAP:'全部持仓与待成交计划风险超过 5%',
  NO_KNOWN_POSITION_TO_REDUCE:'没有已确认的持仓可减',
  SIMULATED_SECOND_FACTOR_REQUIRED:'请填写公开模拟码并勾选人工确认',
};
Object.assign(paperReasons,{DAILY_WARNING:'模拟单日亏损预警',DRAWDOWN_WARNING:'最高净值回撤预警',PRINCIPAL_WARNING:'模拟本金损失预警',PRINCIPAL_REDUCE_RISK:'新增模拟风险预算减半',PERSISTED_LOCK:'已有持久财务锁',RISK_GRADE_BUDGET_EXCEEDED:'单笔风险超过当前等级预算：标准普通 0.5% / 优质 1%，微资金普通 1% / 优质 2%（模拟候选）',INVALID_DIRECTIONAL_STOP:'止损方向不正确：多头止损低于入场，空头止损高于入场',INVALID_TAKE_PROFIT:'止盈方向不正确或没有对齐价格步长',STOP_NOT_BEFORE_LIQUIDATION_WITH_BUFFER:'假设强平参考价未留出止损缓冲，请复核模拟参数',REJECT_USER_LEVERAGE_CAP:'单仓杠杆超过 25x，方案已拒绝',REJECT_ACCOUNT_MAX_NO_AUTOMATIC_DOWNGRADE:'超过本实验的假设账户杠杆上限；不会自动降低杠杆',QUOTE_MISSING:'请先写入该合约的模拟场景价',PRICE_NOT_TICK_ALIGNED:'场景价格或止损未对齐价格步长',QUANTITY_NOT_STEP_ALIGNED:'数量未对齐模拟步长',INSUFFICIENT_SIMULATED_MARGIN:'模拟保证金不足',APPROVAL_HASH_MISMATCH:'审批与当前不可变方案不一致',ORDER_NOT_AWAITING_APPROVAL:'方案已失效、过期或已经处理',BELOW_EXCHANGE_MINIMUM_NO_ROUND_UP:'数量或名义金额低于模拟最小要求，不能向上凑单',CANDIDATE_COST_RISK_RATIO:'预计成本超过模拟风险预算的 20%'});
export const paperMessage=(value:string)=>value.split(';').map(s=>paperReasons[s]??s).join('；');
