import {useCallback,useEffect,useRef,useState} from 'react';
import {api,localTime,numberText} from './api';
import {ContractSearch} from './ContractSearch';
import {WorkflowMode} from './WorkflowMode';
import type {ViewMode} from './workflowForms';
import type {MarketCatalog} from './researchTypes';
import type {PaperOrder,PaperSnapshot,PaperSessions} from './paperTypes';
import {paperStates,paperMessage} from './paperTypes';

type Pending={url:string;body:unknown};
export function PaperDesk() {
  const [sessions,setSessions]=useState<PaperSessions|null>(null),[id,setId]=useState('');
  const [snapshot,setSnapshot]=useState<PaperSnapshot|null>(null),[busy,setBusy]=useState(false);
  const [error,setError]=useState(''),[notice,setNotice]=useState('');
  const [pending,setPending]=useState<Pending|null>(null),[approval,setApproval]=useState<PaperOrder|null>(null);
  const [mode,setMode]=useState<ViewMode>('simple');
  const [name,setName]=useState('我的纸面实验'),[equity,setEquity]=useState('1000');
  const [profile,setProfile]=useState('micro_capital'),[maxLeverage,setMaxLeverage]=useState('20');
  const [symbol,setSymbol]=useState('XAUUSDT'),[catalog,setCatalog]=useState<MarketCatalog|null>(null);
  const [price,setPrice]=useState('100'),[direction,setDirection]=useState('LONG');
  const [stop,setStop]=useState('98'),[tp,setTp]=useState('104'),[liquidation,setLiquidation]=useState('90');
  const [risk,setRisk]=useState('1'),[leverage,setLeverage]=useState('20'),[grade,setGrade]=useState('NORMAL');
  const [fee,setFee]=useState('5'),[slip,setSlip]=useState('2'),[fundingBudget,setFundingBudget]=useState('2');
  const [step,setStep]=useState('0.001'),[tick,setTick]=useState('0.01');
  const [scenario,setScenario]=useState('NORMAL'),[fillQuantities,setFillQuantities]=useState<Record<string,string>>({});
  const [reductions,setReductions]=useState<Record<string,string>>({});
  const [fundingRate,setFundingRate]=useState('0.0001'),[flow,setFlow]=useState('100');
  const disabled=busy||!!pending;
  const onCatalog=useCallback((value:MarketCatalog)=>setCatalog(value),[]);
  const onAvailable=useCallback(()=>{},[]);
  const label=(s:string)=>`${s} · ${catalog?.instruments.find(i=>i.symbol===s)?.name_zh??'中文名待补充'}`;
  const loadList=useCallback(async()=>{const value=await api<PaperSessions>('/api/v1/paper/sessions');setSessions(value);setId(old=>old||value.sessions[0]?.id||'');},[]);
  useEffect(()=>{void loadList().catch(e=>setError(String(e)));},[loadList]);
  useEffect(()=>{
    if(!id){setSnapshot(null);return;}
    let closed=false;
    const refresh=async()=>{try{const value=await api<PaperSnapshot>(`/api/v1/paper/sessions/${id}`);if(!closed)setSnapshot(value);}catch(e){if(!closed)setError(String(e));}};
    void refresh();const timer=setInterval(()=>void refresh(),3000);
    return()=>{closed=true;clearInterval(timer);};
  },[id]);
  async function mutate(attempt:Pending) {
    setBusy(true);setError('');setNotice('');setPending(attempt);
    try{
      const response=await fetch(attempt.url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(attempt.body)});
      const result=await response.json();
      if(!response.ok){if(response.status<500)setPending(null);throw new Error(typeof result.detail==='string'?paperMessage(result.detail):'请检查模拟参数格式');}
      setSnapshot(result as PaperSnapshot);setId(result.id);setPending(null);setApproval(null);
      setNotice('操作已写入模拟台账；没有向交易所发送订单。');await loadList();
    }catch(e){setError(String(e));}finally{setBusy(false);}
  }
  function command(action:string,args:unknown={}) {
    if(!id||disabled)return;
    void mutate({url:'/api/v1/paper/commands',body:{session_id:id,command_id:crypto.randomUUID(),action,args}});
  }
  return <>
    <section className="panel"><div className="section-heading"><div><p className="eyebrow">P3 · OFFLINE PAPERBROKER</p><h2>纸面交易 · 场景模拟</h2></div><WorkflowMode title="纸面交易" mode={mode} disabled={disabled} onChange={setMode} simpleDescription="创建模拟实验、写入场景价格、生成方案并逐步审批与模拟成交。"/></div>
      <p className="note">使用虚拟 USDT、手动场景价格和假设合约规则，公开模拟码不是真实 2FA。此页面不接入真实账户、实时自动成交或实盘订单。</p>
      <label>选择已有模拟实验<select value={id} disabled={disabled} onChange={e=>{setId(e.target.value);setError('');setNotice('');}}>
        <option value="">尚未创建实验</option>{sessions?.sessions.map(s=><option key={s.id} value={s.id}>{s.name} · {s.id.slice(0,8)}</option>)}</select></label>
      <details open={!id} className="advanced-parameters"><summary>创建独立模拟实验</summary><p className="muted">新实验有独立台账，不重置任何旧实验的亏损或持久锁。1000 USDT 示例不是人民币实验本金的换算。</p>
        <form onSubmit={e=>{e.preventDefault();void mutate({url:'/api/v1/paper/sessions',body:{command_id:crypto.randomUUID(),name,initial_equity:equity,mode:profile,assumed_account_max:Number(maxLeverage)}});}}>
          <div className="research-form"><label>实验名称<input required maxLength={60} value={name} disabled={disabled} onChange={e=>setName(e.target.value)}/></label>
            <label>模拟初始权益 USDT<input type="number" required step="any" min="0.01" value={equity} disabled={disabled} onChange={e=>setEquity(e.target.value)}/></label>
            <label>风险规则<select value={profile} disabled={disabled} onChange={e=>setProfile(e.target.value)}><option value="micro_capital">微资金 · 候选模拟规则</option><option value="standard">标准 · 已确认设计规则</option></select></label>
            <label>假设账户杠杆上限<select value={maxLeverage} disabled={disabled} onChange={e=>setMaxLeverage(e.target.value)}><option value="20">20x · 仅假设</option><option value="25">25x · 仍需订单额外模拟审批</option></select></label></div>
          <button className="primary" disabled={disabled}>创建模拟实验</button></form></details>
      {sessions&&<p className="muted">{sessions.persistence==='OFFLINE_FILE_JOURNAL_NOT_POSTGRESQL'?'存储：本机离线模拟文件；PostgreSQL 验收未完成':'存储：PostgreSQL 纸面台账'} · 实盘始终关闭</p>}
      {error&&<p role="alert" className="error">{error}</p>}{notice&&<p role="status" className="info-strip">{notice}</p>}
      {pending&&!busy&&<div className="note"><p>上次请求结果未能确认。请使用原请求标识重试，防止重复记录；其他操作暂时锁定。</p><button onClick={()=>void mutate(pending)}>按原标识重试上次操作</button></div>}
    </section>
    {snapshot&&<>
      <section className="metrics">{[['净权益 USDT','equity'],['现金 USDT','cash'],['本金损失 %','principal_loss_pct'],['最高净值回撤 %','high_water_drawdown_pct'],['单日亏损 %','daily_loss_pct'],['资金流调整后权益','adjusted_equity'],['持仓计划风险','position_risk'],['待成交预占风险','pending_risk'],['总有效杠杆','effective_leverage'],['理论保证金','theoretical_margin']].map(([title,key])=><article key={key}><p>{title}</p><strong>{numberText(snapshot.metrics[key],4)}</strong><span>模拟值 · {key==='effective_leverage'?'所有多空名义金额绝对值合计':'USDT 记账口径'}</span></article>)}</section>
      <section className="panel"><div className="section-heading"><h2>风控与恢复</h2><span className="badge">{snapshot.blockers.length?'禁止新增模拟风险':'账户层模拟预审可用'}</span></div>
        {snapshot.risk_state.state!=='NORMAL'&&<p className="note">当前风险状态：{paperMessage(snapshot.risk_state.state)}</p>}
        {snapshot.reduced_risk_latched&&<p className="note">此前本金损失已达 30% 模拟线，新增风险预算保持减半；盈利或恢复操作不会自动重置。</p>}
        {snapshot.blockers.map(r=><p className="note" key={r}>{paperMessage(r)}</p>)}
        <p className="muted">微资金：50% 为本金亏损容忍预算；40% 锁定、35% 高水位回撤、5% 单日、2x 总有效杠杆等仍为模拟候选。风险日暂用 UTC 日界；追加资金、重启和对账不会解除本金或日内持久锁。</p>
        <div className="actions"><button className="danger" disabled={disabled} onClick={()=>command('KILL')}>禁止新增模拟风险</button><button disabled={disabled} onClick={()=>command('RECOVER')}>核对台账并恢复模拟运行</button></div>
      </section>
      <section className="panel"><h2>1 · 场景价格与方案</h2>
        <ContractSearch id="paper-search" symbol={symbol} disabled={disabled} onCatalog={onCatalog} onChoose={setSymbol} onSelectionAvailable={onAvailable}/>
        {!symbol.endsWith('USDT')&&<p className="error">本阶段仅支持 USDT 记账的模拟合约，不进行未经核验的跨币种换算。</p>}
        <div className="research-form"><label>手动模拟场景价<input type="number" required min="0.01" step="any" value={price} disabled={disabled} onChange={e=>setPrice(e.target.value)}/></label>
          <label>方向<select value={direction} disabled={disabled} onChange={e=>setDirection(e.target.value)}><option value="LONG">多头</option><option value="SHORT">空头</option></select></label>
          <label>止损价<input type="number" min="0.01" step="any" value={stop} disabled={disabled} onChange={e=>setStop(e.target.value)}/></label>
          <label>止盈价<input type="number" min="0.01" step="any" value={tp} disabled={disabled} onChange={e=>setTp(e.target.value)}/></label>
          <label>计划等级（仅模拟标签）<select value={grade} disabled={disabled} onChange={e=>setGrade(e.target.value)}><option value="NORMAL">普通</option><option value="QUALIFIED">优质 · 模拟假设</option></select></label>
          <label>单笔风险 %<input type="number" min="0.01" max="2" step="any" value={risk} disabled={disabled} onChange={e=>setRisk(e.target.value)}/></label>
          <label>单仓杠杆<input type="number" min="1" max="100" step="1" value={leverage} disabled={disabled} onChange={e=>setLeverage(e.target.value)}/></label>
          <label>假设强平参考价<input type="number" min="0.01" step="any" value={liquidation} disabled={disabled} onChange={e=>setLiquidation(e.target.value)}/></label></div>
        <details open={mode==='full'} className="advanced-parameters"><summary>模拟合约规则与成本假设</summary><div className="research-form">
          <label>数量步长<input type="number" step="any" value={step} disabled={disabled} onChange={e=>setStep(e.target.value)}/></label><label>价格步长<input type="number" step="any" value={tick} disabled={disabled} onChange={e=>setTick(e.target.value)}/></label>
          <label>单边手续费 bps<input type="number" step="any" min="0" max="100" value={fee} disabled={disabled} onChange={e=>setFee(e.target.value)}/></label><label>退出滑点 bps<input type="number" step="any" min="0" max="100" value={slip} disabled={disabled} onChange={e=>setSlip(e.target.value)}/></label>
          <label>资金费预算 bps<input type="number" step="any" min="0" max="100" value={fundingBudget} disabled={disabled} onChange={e=>setFundingBudget(e.target.value)}/></label></div></details>
        <p className="muted">场景价有效期 120 秒，审批有效期 5 分钟。写入新价格或合约假设会使未提交的旧审批失效；持仓达到保护价时，按场景价和滑点模拟退出。缺口退出可能超过计划风险。所有规则均是假设，没有账户权限或真实强平核验。</p>
        <div className="actions"><button disabled={disabled||!symbol.endsWith('USDT')} onClick={()=>command('QUOTE',{symbol,price,step,tick})}>写入模拟场景价</button>
          <button className="primary" disabled={disabled||!!snapshot.blockers.length||!symbol.endsWith('USDT')} onClick={()=>command('PREPARE',{symbol,direction,grade,stop,take_profit:tp,risk_pct:risk,exchange_leverage:Number(leverage),assumed_liquidation:liquidation,fee_bps:fee,slippage_bps:slip,funding_budget_bps:fundingBudget})}>生成待审批方案</button></div>
        <p>{snapshot.quotes.find(q=>q.symbol===symbol)?`已写入 ${symbol}：${snapshot.quotes.find(q=>q.symbol===symbol)?.price} · ${snapshot.quotes.find(q=>q.symbol===symbol)?.fresh?'时效内':'已过期'}`:'先写入该合约的模拟价格，再生成方案。'}</p>
      </section>
      <section className="panel"><h2>2 · 审批与纸面订单</h2><details><summary>故障演练设置</summary>
        <label>下一次提交场景<select value={scenario} disabled={disabled} onChange={e=>setScenario(e.target.value)}><option value="NORMAL">正常受理</option><option value="LOST_ACK_ACCEPTED">受理且部分成交，但响应丢失</option><option value="LOST_ACK_REJECTED">未受理，但响应丢失</option><option value="PROTECTION_FAILURE">成交后保护单失败</option></select></label>
        <p className="muted">响应丢失场景保持同一 client order id，禁止盲目重发；对账后仍需人工恢复。保护单失败后可减仓，不能继续增加风险。</p></details>
        {!snapshot.orders.length&&<p className="empty">生成方案后，在这里复核数量、风险与不可变 hash。</p>}
        {[...snapshot.orders].reverse().map(o=><article className="paper-order" key={o.id}>
          <div className="section-heading"><h3>{label(o.plan.symbol)} · {o.plan.direction==='LONG'?'多头':'空头'}</h3><span className="badge">{paperStates[o.state]??o.state}</span></div>
          <p>入场 {o.plan.entry} · 止损 {o.plan.stop} · 止盈 {o.plan.take_profit} · 数量 {o.plan.quantity} · 杠杆 {o.plan.exchange_leverage}x · 预占风险 {numberText(o.plan.reserved_risk,4)} USDT</p>
          <p className="muted">模拟成交 {o.filled} · 已退出 {o.closed} · 审批到期 {localTime(o.plan.expires_at)}</p>
          <code className="hash">{o.plan_hash}</code><small className="mono">{o.client_order_id}</small>
          <div className="actions">
            {o.state==='AWAITING_APPROVAL'&&<><button className="primary" disabled={disabled} onClick={()=>setApproval(o)}>模拟审批</button><button disabled={disabled} onClick={()=>command('REJECT',{order_id:o.id})}>拒绝方案</button></>}
            {o.state==='APPROVED'&&<button className="primary" disabled={disabled} onClick={()=>command('SUBMIT',{order_id:o.id,scenario,unknown_fill_pct:scenario==='LOST_ACK_ACCEPTED'?'50':'0'})}>提交纸面订单</button>}
            {['ACKED','PARTIALLY_FILLED'].includes(o.state)&&<><label>本次模拟成交数量<input aria-label={`模拟成交数量 ${o.id.slice(0,8)}`} type="number" step="any" min="0" value={fillQuantities[o.id]??'1'} disabled={disabled} onChange={e=>setFillQuantities({...fillQuantities,[o.id]:e.target.value})}/></label><button disabled={disabled} onClick={()=>command('FILL',{order_id:o.id,fill_id:crypto.randomUUID(),quantity:fillQuantities[o.id]??'1'})}>记录模拟成交</button></>}
            {['AWAITING_APPROVAL','APPROVED','ACKED','PARTIALLY_FILLED'].includes(o.state)&&<button disabled={disabled} onClick={()=>command('CANCEL',{order_id:o.id})}>取消未成交部分</button>}
            {o.state==='UNKNOWN_SUBMISSION'&&<button disabled={disabled} onClick={()=>command('RECONCILE',{order_id:o.id})}>按原订单标识对账</button>}
          </div><details><summary>订单状态轨迹</summary>{o.transitions.map((t,i)=><p className="muted" key={i}>{localTime(t.at)} · {paperStates[t.state]??t.state} · {t.reason}</p>)}</details>
        </article>)}
      </section>
      <section className="panel"><h2>3 · 模拟持仓与减仓</h2>{!snapshot.positions.length&&<p className="empty">当前无模拟持仓。</p>}
        {snapshot.positions.map(p=><article className="paper-order" key={p.order_id}><h3>{label(p.symbol)} · {p.direction==='LONG'?'多头':'空头'} · {p.quantity}</h3>
          <p>均价 {p.average_entry} · 止损 {p.stop} · 止盈 {p.take_profit} · {p.protected?'模拟保护已设置':'模拟保护失败'}</p>
          <div className="actions"><label>模拟减仓数量<input aria-label={`减仓数量 ${p.symbol}`} type="number" step="any" min="0" value={reductions[p.order_id]??p.quantity} disabled={disabled} onChange={e=>setReductions({...reductions,[p.order_id]:e.target.value})}/></label>
            <button disabled={disabled} onClick={()=>command('REDUCE',{order_id:p.order_id,quantity:reductions[p.order_id]??p.quantity})}>确认模拟减仓</button>
            {!p.protected&&<button disabled={disabled} onClick={()=>command('RESTORE_PROTECTION',{order_id:p.order_id})}>重新设置模拟保护</button>}</div></article>)}
      </section>
      <div className="two-columns"><section className="panel"><h2>模拟资金费结算</h2><p>结算当前所选 {symbol} 的已核对持仓；正费率时多头支付、空头收取。费率不是百分数。</p>
        <label>本次模拟费率<input type="number" step="any" min="-0.1" max="0.1" value={fundingRate} disabled={disabled} onChange={e=>setFundingRate(e.target.value)}/></label>
        <button disabled={disabled} onClick={()=>command('FUNDING',{event_id:crypto.randomUUID(),symbol,rate:fundingRate})}>记录一次模拟资金费</button></section>
        <section className="panel"><h2>模拟外部资金流</h2><p>正数为追加虚拟资金，负数为提取。资金流不会重置旧亏损和锁。</p><label>模拟资金流 USDT<input type="number" step="any" value={flow} disabled={disabled} onChange={e=>setFlow(e.target.value)}/></label>
        <button disabled={disabled} onClick={()=>command('FLOW',{amount:flow})}>记录模拟资金流</button></section></div>
      <section className="panel"><h2>成交与现金台账</h2><div className="table-wrap"><table><thead><tr><th>时间</th><th>模拟成交类型</th><th>数量 / 价格</th><th>手续费</th><th>已实现毛损益</th></tr></thead><tbody>{[...snapshot.fills].reverse().map(f=><tr key={f.id}><td>{localTime(f.at)}</td><td>{{OPEN:'开仓',REDUCE:'人工减仓',STOP:'保护止损',TAKE_PROFIT:'保护止盈'}[f.kind]??f.kind}</td><td>{f.quantity} / {f.price}</td><td>{f.commission}</td><td>{f.realized_pnl}</td></tr>)}</tbody></table></div>
        <details><summary>全部现金变动（最近 100 条）</summary>{[...snapshot.ledger].reverse().map((l,i)=><p className="mono" key={i}>{localTime(l.at)} · {l.kind} · {l.amount} USDT</p>)}</details></section>
    </>}
    {approval&&<ApprovalDialog order={approval} error={error} busy={disabled} onDismiss={()=>setApproval(null)} onApprove={(code,extra)=>command('APPROVE',{order_id:approval.id,plan_hash:approval.plan_hash,simulation_code:code,exception_code:extra||null,human_confirmed:true})}/>}
  </>;
}

function ApprovalDialog({order,error,busy,onDismiss,onApprove}:{order:PaperOrder;error:string;busy:boolean;onDismiss:()=>void;onApprove:(code:string,extra:string)=>void}) {
  const ref=useRef<HTMLDialogElement>(null),[code,setCode]=useState(''),[extra,setExtra]=useState(''),[confirmed,setConfirmed]=useState(false);
  useEffect(()=>{const node=ref.current,previous=document.activeElement;node?.showModal();return()=>{if(node?.open)node.close();if(previous instanceof HTMLElement)previous.focus();};},[]);
  return <dialog ref={ref} className="paper-approval" aria-labelledby="paper-approval-title" onCancel={onDismiss}>
    <form onSubmit={e=>{e.preventDefault();onApprove(code,extra);}}><div className="section-heading"><h2 id="paper-approval-title">模拟审批 · 不授权真实交易</h2><button type="button" disabled={busy} onClick={onDismiss}>关闭</button></div>
      <p>{order.plan.symbol} · 入场 {order.plan.entry} · 止损 {order.plan.stop} · 数量 {order.plan.quantity} · {order.plan.exchange_leverage}x</p><code className="hash">{order.plan_hash}</code>
      <p className="note">这是公开的流程演练码，不是真实二次验证。无需输入账户密码、真实验证码或 API 密钥。</p>
      {error&&<p role="alert" className="error">{error}</p>}
      <p>公开模拟码：<strong className="mono">{order.simulation_challenge}</strong></p><label>输入公开模拟码<input required inputMode="numeric" pattern="[0-9]{6}" maxLength={6} value={code} disabled={busy} onChange={e=>setCode(e.target.value)}/></label>
      {order.extra_simulation_challenge&&<><p>21–25x 额外模拟审批码：<strong className="mono">{order.extra_simulation_challenge}</strong></p><label>输入额外模拟审批码<input required inputMode="numeric" pattern="[0-9]{6}" maxLength={6} value={extra} disabled={busy} onChange={e=>setExtra(e.target.value)}/></label></>}
      <label className="paper-confirm"><input type="checkbox" checked={confirmed} disabled={busy} onChange={e=>setConfirmed(e.target.checked)}/>我已复核该不可变方案，仅确认本次模拟实验</label>
      <div className="actions"><button type="button" disabled={busy} onClick={onDismiss}>取消</button><button className="primary" disabled={busy||!confirmed}>确认模拟审批</button></div></form></dialog>;
}
