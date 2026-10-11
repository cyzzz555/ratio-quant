import {useCallback,useEffect,useState} from 'react';
import {api,localTime,numberText} from './api';
import {ContractSearch} from './ContractSearch';
import type {MarketCatalog} from './researchTypes';
import type {RealtimeSnapshot} from './realtimeTypes';
import {qualityLabel,signalLabel} from './realtimeTypes';

export function RealtimeDesk() {
  const [snapshot,setSnapshot]=useState<RealtimeSnapshot|null>(null);
  const [symbol,setSymbol]=useState('BTCUSDT'),[watchlist,setWatchlist]=useState<string[]>(['BTCUSDT']);
  const [catalog,setCatalog]=useState<MarketCatalog|null>(null),[available,setAvailable]=useState(false);
  const [discovery,setDiscovery]=useState(false),[timeframe,setTimeframe]=useState('5m');
  const [busy,setBusy]=useState(false),[error,setError]=useState(''),[channel,setChannel]=useState('正在连接页面');
  const onCatalog=useCallback((value:MarketCatalog)=>setCatalog(value),[]);
  const onAvailable=useCallback((value:boolean)=>setAvailable(value),[]);
  const active=snapshot?.worker_active??false;
  useEffect(()=>{
    let closed=false,stream:WebSocket|null=null,poll:ReturnType<typeof setInterval>|undefined;
    const refresh=async()=>{try{const value=await api<RealtimeSnapshot>('/api/v1/realtime');
      if(!closed){setSnapshot(value);setChannel('页面定时更新');}}catch{if(!closed)setChannel('本机服务不可用');}};
    const startPolling=()=>{if(closed)return;if(!poll){void refresh();poll=setInterval(()=>void refresh(),2000);}};
    queueMicrotask(()=>{if(closed)return;
    stream=new WebSocket(`${location.protocol==='https:'?'wss':'ws'}://${location.host}/api/v1/stream`);
    stream.onmessage=event=>{if(!closed){setSnapshot(JSON.parse(event.data) as RealtimeSnapshot);setChannel('页面实时连接');}};
    stream.onerror=startPolling;stream.onclose=startPolling;
    });
    return()=>{closed=true;stream?.close();if(poll)clearInterval(poll);};
  },[]);
  async function action(path:string,body:unknown) {
    setBusy(true);setError('');
    try{setSnapshot(await api<RealtimeSnapshot>(path,body));}catch(e){setError(String(e));}
    finally{setBusy(false);}
  }
  const name=(s:string)=>catalog?.instruments.find(i=>i.symbol===s)?.name_zh??'中文名待补充';
  return <>
    <div className="two-columns"><section className="panel">
      <p className="eyebrow">P2 · PUBLIC REALTIME RESEARCH</p><h2>实时关注池</h2>
      <p>选择关注合约，启动后持续接收公共行情。修改关注池请先停止采集。</p>
      <ContractSearch id="realtime-search" symbol={symbol} disabled={active||busy} onCatalog={onCatalog}
        onChoose={setSymbol} onSelectionAvailable={onAvailable}/>
      <button disabled={active||busy||!available||watchlist.includes(symbol)||watchlist.length>=4}
        onClick={()=>setWatchlist([...watchlist,symbol])}>添加到关注池</button>
      <ul className="realtime-watchlist">{watchlist.map(s=><li key={s}><strong>{s}</strong> · {name(s)}
        <button aria-label={`移除 ${s}`} disabled={active||busy||watchlist.length===1}
          onClick={()=>setWatchlist(watchlist.filter(x=>x!==s))}>移除</button></li>)}</ul>
      <div className="realtime-controls"><label>研究信号周期<select aria-label="实时信号周期" value={timeframe}
        disabled={active||busy} onChange={e=>setTimeframe(e.target.value)}>
        <option value="5m">5 分钟</option><option value="15m">15 分钟</option></select></label>
        <label>发现池<select aria-label="实时发现池" value={discovery?'on':'off'} disabled={active||busy}
          onChange={e=>setDiscovery(e.target.value==='on')}><option value="off">关闭</option>
          <option value="on">启动时选取 USDT 成交额前 2 名</option></select></label></div>
      <p className="muted">最多 4 个关注合约；发现池额外最多 2 个，按启动时滚动 24 小时成交额选取，同一会话不自动换池。</p>
      <div className="actions"><button className="primary" disabled={active||busy||!catalog}
        onClick={()=>void action('/api/v1/realtime/start',{watchlist,discovery,timeframe})}>
        {busy?'处理中…':'启动实时采集'}</button><button disabled={!active||busy||snapshot?.state==='STOPPING'}
        onClick={()=>void action('/api/v1/realtime/stop',{})}>停止采集</button></div>
      {error&&<p role="alert" className="error">{error}</p>}
    </section><section className="panel" aria-live="polite">
      <h2>实时运行状态</h2><span className="badge">{snapshot?qualityLabel[snapshot.state]??snapshot.state:'正在读取'}</span>
      <dl className="facts"><div><dt>交易所连接</dt><dd>{snapshot?.connected?'已连接 · 逐品种质量另行检查':'未连接'}</dd></div>
        <div><dt>页面更新</dt><dd>{channel}</dd></div><div><dt>最新处理时间</dt><dd>{snapshot?.checked_at?localTime(snapshot.checked_at):'—'}</dd></div>
        <div><dt>真实订单执行</dt><dd>关闭 · LIVE=false</dd></div><div><dt>账户权限</dt><dd>未核验</dd></div>
        <div><dt>归档状态</dt><dd>本机可回放 · PostgreSQL 验收待完成</dd></div></dl>
      {snapshot?.failure&&<p role="alert" className="error">采集错误：{snapshot.failure}。查看通知后重新启动。</p>}
      <p>预热约 13 小时闭合分钟数据。未闭合 K 线只更新展示；断线、延迟、缺口和冲突都会阻止研究确认。</p>
      <details><summary>研究参数与本阶段限制</summary><p>研究窗口：1h 均线 6 / 12，回拉 6，下一根闭合低周期 K 线延续方向确认；候选最长观察 2 根。评分 60 为研究规则分，不能解释为胜率。</p>
        <p>这些参数尚未获得实盘批准。均值回归与事件驱动当前显示未完成，不生成虚构评分。</p>
        <ul>{snapshot?.limitations.map(s=><li key={s}>{s}</li>)}</ul>
        <p className="mono">{snapshot?.journal??'启动后生成会话归档'}</p></details>
    </section></div>
    <section className="panel"><h2>逐合约行情与质量</h2><div className="table-wrap"><table>
      <thead><tr><th>合约 / 来源池</th><th>最新成交 / 标记价</th><th>分钟归档 / 缺口</th><th>行情质量</th><th>研究市场状态</th><th>独立策略评分</th></tr></thead>
      <tbody>{snapshot?.instruments.map(i=><tr key={i.symbol}><th scope="row">{i.symbol}<small>{name(i.symbol)==='中文名待补充'?i.name_zh:name(i.symbol)} · {i.pool==='WATCHLIST'?'关注池':'发现池'}</small></th>
        <td>{numberText(i.latest_price,6)}<small>标记价 {numberText(i.mark_price,6)}</small></td>
        <td>{i.closed_minutes} 根<small>{i.gaps.reduce((n,g)=>n+g.missing_count,0)} 分钟缺口</small></td>
        <td><span className={i.quality==='HEALTHY'?'badge':'muted'}>{qualityLabel[i.quality]??i.quality}</span>
          <small>最新闭合 {i.latest_closed_at?localTime(i.latest_closed_at):'—'}</small></td>
        <td>{{UPTREND:'上涨趋势',DOWNTREND:'下跌趋势',FLAT:'均线持平',UNKNOWN:'样本不足'}[i.regime]??i.regime}
          <small>优先级 {i.strategy_priority==='UNRESOLVED'?'待判定':i.strategy_priority}</small></td>
        <td>TrendPullback 最近规则分：{i.scores.TrendPullback.value??'暂无候选'}<small>MeanReversion：待实现</small><small>EventDriven：事件源待核验</small></td>
      </tr>)}</tbody></table></div>{!snapshot?.instruments.length&&<p className="empty">启动实时采集后，这里显示逐品种公共核验和行情质量。</p>}</section>
    <div className="two-columns"><section className="panel"><h2>两阶段研究信号</h2>
      <p className="muted">观察 → 下一根闭合 K 线确认。所有信号均不可执行，质量失效后不会恢复旧候选。</p>
      {!snapshot?.signals.length&&<p className="empty">暂无满足研究条件的信号。采集中不代表必然出现信号。</p>}
      <div className="realtime-feed">{[...(snapshot?.signals??[])].reverse().map(s=><article className="realtime-event" key={s.id}>
        <strong>{s.symbol} · {s.direction==='LONG'?'多头':'空头'} · {signalLabel[s.state]??s.state}</strong>
        <p>{qualityLabel[s.reason]??s.reason}</p><small>{localTime(s.updated_at)} · 独立规则分 {s.score} · 不可执行</small></article>)}</div>
    </section><section className="panel"><h2>分级通知</h2><p className="muted">仅本机页面显示；不向外部账户或消息渠道发送。</p>
      {!snapshot?.notifications.length&&<p className="empty">暂无通知。</p>}
      <div className="realtime-feed">{[...(snapshot?.notifications??[])].reverse().map(n=><article className={`realtime-event ${n.severity==='CRITICAL'?'error':''}`} key={n.id}>
        <strong>{{INFO:'信息',WARNING:'注意',CRITICAL:'阻断'}[n.severity]} · {n.symbol??'会话'}</strong>
        <p>{qualityLabel[n.message]??n.message}</p><small>{localTime(n.at)} · {n.code}</small></article>)}</div>
    </section></div>
  </>;
}
