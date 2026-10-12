import React, { useCallback, useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import type { Capability, Health, ProbeJob, Quality, Report } from './types';
import './style.css';
import {MarketDesk,ResearchDesk,RiskDesk} from './ResearchDesk';
import {RealtimeDesk} from './RealtimeDesk';
import {PaperDesk} from './PaperDesk';

const pages = [
  {id: 'paper', title: '纸面交易', icon: '⊡', hint: 'P3 场景模拟、审批、订单与持仓台账'},
  {id: 'realtime', title: '实时监控', icon: '◉', hint: 'P2 公共行情、质量与研究信号'},
  {id: 'market', title: '合约行情', icon: '↗', hint: '真实闭合 K 线与标记价'},
  {id: 'research', title: '历史与回测', icon: '⌁', hint: '采集历史、运行研究回测并复查结果'},
  {id: 'risk', title: '交易准备', icon: '⊞', hint: '仓位与风控试算，交易执行进度'},
  {id: 'overview', title: '运行总览', icon: '◫', hint: '本机服务与最近一次探测'},
  {id: 'instruments', title: '合约能力', icon: '▦', hint: '逐品种证据、账户权限与详情'},
  {id: 'probe', title: '只读探测', icon: '▷', hint: '运行公共接口核验并查看进度'},
  {id: 'reports', title: '数据与报告', icon: '≡', hint: '样本质量、闭合归档与报告下载'},
  {id: 'safety', title: '安全与阶段', icon: '◇', hint: '当前边界与待核验事项'},
] as const;
type Page = typeof pages[number]['id'];
function currentPage(): Page {
  const id = location.hash.slice(1);
  return pages.find(p => p.id === id)?.id ?? 'market';
}
const fact = (v: boolean | null) => v === true ? '已观测' : v === false ? '未观测' : '未核验';
const time = (v: string | null | undefined) => v
  ? new Date(v).toLocaleString('zh-CN', {timeZone: 'Asia/Shanghai', hour12: false}) : '—';
const jobNames = {IDLE: '尚未运行', RUNNING: '正在探测', SUCCEEDED: '探测完成', FAILED: '探测失败'};
async function request<T>(url: string, options?: RequestInit, allow503 = false): Promise<T> {
  const response = await fetch(url, options);
  const result = await response.json();
  if (!response.ok && !(allow503 && response.status === 503)) {
    throw new Error(typeof result.detail === 'string' ? result.detail : `请求失败：HTTP ${response.status}`);
  }
  return result as T;
}

function InstrumentDialog({cap, close}: {cap: Capability; close: () => void}) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => { dialog.current?.showModal(); }, []);
  return <dialog ref={dialog} aria-labelledby="instrument-title" onCancel={close}>
    <div className="dialog-head"><div><p className="eyebrow">INSTRUMENT EVIDENCE</p>
      <h2 id="instrument-title">{cap.symbol}</h2></div><button onClick={close} autoFocus>关闭详情</button></div>
    <p className="muted">核验时间：{time(cap.verified_at)} · 北京时间</p>
    <dl className="facts">
      <div><dt>产品族 / 状态</dt><dd>{cap.product_family} / {cap.trading_status ?? '未知'}</dd></div>
      <div><dt>账户交易权限</dt><dd>{cap.account_trade_permission}</dd></div>
      <div><dt>账户最大杠杆</dt><dd>{cap.max_account_leverage ?? '未核验'}</dd></div>
      <div><dt>逐仓 / reduceOnly / 保护单</dt><dd>{fact(cap.isolated_supported)} / {fact(cap.reduce_only_supported)} / {fact(cap.stop_type_supported)}</dd></div>
      <div><dt>首个历史返回时间</dt><dd>{time(cap.history_start_at)}</dd></div>
      <div><dt>资金费率样本</dt><dd>{fact(cap.funding_data_available)}</dd></div>
    </dl>
    <h3>原始请求证据</h3><div className="evidence-list">{cap.evidence.map((e, i) => <article key={i}>
      <strong>{e.source}</strong><p>{time(e.timestamp)} · {e.result}</p>
      <code>{e.raw_hash ?? '没有响应哈希'}</code></article>)}</div>
    <h3>核验限制与错误</h3>{cap.notes.map((note, i) => <p className="note" key={i}>{note}</p>)}
  </dialog>;
}

function App() {
  const [page, setPage] = useState<Page>(currentPage);
  const [report, setReport] = useState<Report | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [quality, setQuality] = useState<Quality[]>([]);
  const [job, setJob] = useState<ProbeJob | null>(null);
  const [errors, setErrors] = useState<string[]>([]);
  const [actionError, setActionError] = useState('');
  const [loading, setLoading] = useState(false);
  const [starting, setStarting] = useState(false);
  const [query, setQuery] = useState('');
  const [filter, setFilter] = useState('all');
  const [selected, setSelected] = useState<Capability | null>(null);
  const wasRunning = useRef(false);
  useEffect(() => { window.scrollTo({top: 0, behavior: 'auto'}); }, [page]);
  const loadSnapshot = useCallback(async () => {
    setLoading(true);
    const results = await Promise.allSettled([
      request<Report>('/api/v1/instruments').then(r => {
        if (!Array.isArray(r.instruments)) throw new Error('能力报告格式无效');
        setReport(r);
      }),
      request<Health>('/health/ready', undefined, true).then(setHealth),
      request<Quality[]>('/api/v1/data-quality').then(setQuality),
    ]);
    setErrors(results.flatMap((r, i) => r.status === 'rejected'
      ? [`${['能力报告', '服务状态', '数据质量'][i]}：${String(r.reason.message ?? r.reason)}`] : []));
    setLoading(false);
  }, []);
  const refreshJob = useCallback(async () => {
    try {
      const next = await request<ProbeJob>('/api/v1/probe');
      setJob(next);
      if (wasRunning.current && next.state !== 'RUNNING') await loadSnapshot();
      wasRunning.current = next.state === 'RUNNING';
    } catch (e) { setActionError(`任务状态不可用：${String(e)}`); }
  }, [loadSnapshot]);
  useEffect(() => {
    const onHash = () => setPage(currentPage());
    window.addEventListener('hashchange', onHash);
    void loadSnapshot(); void refreshJob();
    return () => window.removeEventListener('hashchange', onHash);
  }, [loadSnapshot, refreshJob]);
  useEffect(() => {
    if (job?.state !== 'RUNNING') return;
    const interval = window.setInterval(() => void refreshJob(), 2000);
    return () => window.clearInterval(interval);
  }, [job?.state, refreshJob]);
  useEffect(() => {
    const interval = window.setInterval(() => {
      void request<Health>('/health/ready', undefined, true).then(setHealth).catch(() => setHealth(null));
    }, 15000);
    return () => window.clearInterval(interval);
  }, []);
  async function startProbe() {
    setStarting(true); setActionError('');
    try {
      const next = await request<ProbeJob>('/api/v1/probe', {
        method: 'POST', headers: {'Content-Type': 'application/json'}, body: '{}',
      });
      wasRunning.current = true; setJob(next);
    } catch (e) { setActionError(String(e)); }
    finally { setStarting(false); }
  }
  const caps = report?.instruments ?? [];
  const filtered = caps.filter(c => c.symbol.toLowerCase().includes(query.trim().toLowerCase())
    && (filter === 'all' || (filter === 'ws' && c.websocket_works !== true)
      || (filter === 'public' && c.public_exchangeinfo_visible !== true)));
  const active = pages.find(p => p.id === page)!;
  return <div className="app-shell">
    <aside className="sidebar"><a className="brand" href="#overview"><span className="brand-mark">Q</span><span>QUANT SYSTEM<small>V1.2 / P3 PAPER</small></span></a>
      <p className="nav-label">本地研究控制台</p><nav aria-label="功能导航">{pages.map(p =>
        <a key={p.id} href={`#${p.id}`} aria-current={page === p.id ? 'page' : undefined}>
          <span aria-hidden="true">{p.icon}</span>{p.title}</a>)}</nav>
      <div className="sidebar-foot"><span className="status-dot"/> 只读环境<small>Mac 本地 · Binance 公共接口</small></div>
    </aside>
    <main><header className="topbar"><div><p className="eyebrow">WORKSPACE / {active.id.toUpperCase()}</p>
      <h1>{active.title}</h1><p className="muted">{active.hint}</p></div>
      <button disabled={loading} onClick={() => { void loadSnapshot(); void refreshJob(); }}>{loading ? '正在刷新…' : '刷新报告'}</button></header>
      <div className="safety-banner"><span className="badge">LIVE=false</span><span>账户权限未核验 · 禁止新增风险 · P3 模拟交易开发中 · 真实订单执行禁用</span></div>
      {[...errors, ...(actionError ? [actionError] : [])].map((error, i) => <p role="alert" className="error" key={i}>{error}</p>)}
      {page === 'paper' && <PaperDesk/>}
      {page === 'realtime' && <RealtimeDesk/>}
      {page === 'market' && <MarketDesk/>}
      {page === 'research' && <ResearchDesk/>}
      {page === 'risk' && <RiskDesk/>}
      {page === 'overview' && <>
        <section className="metrics" aria-label="核验汇总">
          <article><p>公共规格已观测</p><strong>{caps.filter(c => c.public_exchangeinfo_visible).length}<small> / {caps.length}</small></strong><span>逐品种证据</span></article>
          <article><p>WebSocket 有效样本</p><strong>{caps.filter(c => c.websocket_works === true).length}<small> / {caps.length}</small></strong><span>未收到帧的项目保留未知</span></article>
          <article><p>账户交易权限</p><strong className="text-value">UNKNOWN</strong><span>公共可见性不代表账户资格</span></article>
          <article><p>证据缓存状态</p><strong className="text-value">{health ? health.service_ready ? '时效内' : '待更新' : '不可用'}</strong><span>15 分钟服务检查窗口</span></article>
        </section>
        <div className="two-columns"><section className="panel"><h2>从这里开始</h2><p>进入行情查看真实价格，在研究工作台采集历史并运行回测。接口证据与数据质量仍可单独检查。</p>
          <div className="actions"><a className="button primary" href="#realtime">打开实时监控</a><a className="button" href="#market">打开行情</a><a className="button" href="#research">运行研究回测</a><a className="button" href="#instruments">查看合约能力</a></div>
          <div className="info-strip"><span>最近报告</span><strong>{time(report?.generated_at)}</strong><small>北京时间 · 静态快照，手动探测更新</small></div></section>
          <section className="panel"><h2>本机服务</h2><dl className="facts"><div><dt>后端连接</dt><dd>{health ? '已连接' : '不可用'}</dd></div>
            <div><dt>交易就绪</dt><dd>禁止（研究阶段）</dd></div><div><dt>最近控制台任务</dt><dd>{job ? jobNames[job.state] : '未取得状态'}</dd></div>
            <div><dt>执行适配配置</dt><dd>PAPER_BROKER · 无订单适配器</dd></div></dl><a href="http://127.0.0.1:8000/docs" target="_blank" rel="noreferrer">打开 FastAPI 文档 ↗</a></section></div>
        <section className="panel"><h2>阶段进度</h2><div className="roadmap"><article><span className="badge">P0 证据核验</span><h3>能力与数据核验</h3><p>公共接口、样本归档、可追溯证据</p></article>
          <article><span className="muted">P1 开发中 · 数据库验收待完成</span><h3>研究与回测</h3><p>持续数据、策略研究、成本与验证</p></article>
          <article><span className="badge">P2 · 首批功能</span><h3>实时监控</h3><p>实时公共行情、断线补数与研究信号</p><a href="#realtime">打开实时监控 ↗</a></article>
          <article><span className="badge">当前 P3 · 场景模拟</span><h3>纸面交易</h3><p>审批、订单、风险预占与持仓台账</p><a href="#paper">打开纸面交易 ↗</a></article>
          <article><span className="muted">后续阶段 · 未实现</span><h3>人审与执行</h3><p>账户核验、2FA、纸面交易及实盘授权</p></article></div></section>
      </>}
      {page === 'instruments' && <section className="panel">
        <div className="section-heading"><div><h2>候选合约</h2><p className="muted">{filtered.length} 个结果 · 点击详情查看请求证据</p></div>
          <div className="filters"><input aria-label="搜索合约" placeholder="搜索符号，例如 NVDA" value={query} onChange={e => setQuery(e.target.value)}/>
            <select aria-label="能力筛选" value={filter} onChange={e => setFilter(e.target.value)}><option value="all">全部合约</option><option value="ws">WS 待核验</option><option value="public">公共规格待核验</option></select></div></div>
        <div className="table-wrap"><table><caption className="sr-only">逐品种公共能力</caption><thead><tr><th>合约</th><th>公共规格</th><th>历史 K 线</th><th>WS 样本</th><th>标记价</th><th>账户权限 / 杠杆</th><th>操作</th></tr></thead>
          <tbody>{filtered.map(c => <tr key={c.symbol}><th scope="row"><button className="symbol-button" aria-label={`打开 ${c.symbol} 证据`} onClick={() => setSelected(c)}>{c.symbol} ↗</button><small>{c.trading_status ?? '未知'} · {c.product_family}</small></th>
            <td>{fact(c.public_exchangeinfo_visible)}</td><td>{fact(c.historical_bars_available)}</td><td>{fact(c.websocket_works)}</td><td>{fact(c.mark_price_available)}</td>
            <td>{c.account_trade_permission}<small>最大杠杆：{c.max_account_leverage ?? '未核验'}</small></td><td><button aria-label={`查看 ${c.symbol} 详情`} onClick={() => setSelected(c)}>详情 ↗</button></td></tr>)}</tbody></table></div>
        {!filtered.length && <p className="empty">没有匹配的合约。可以清空搜索或更换筛选条件。</p>}
      </section>}
      {page === 'probe' && <><div className="two-columns"><section className="panel"><p className="eyebrow">PUBLIC READ-ONLY PROBE</p><h2>运行 Binance 只读核验</h2>
        <p>检查配置中的候选合约：公共规格、历史 K 线、标记价、资金费率和短窗口 WebSocket 样本。</p>
        <p className="muted">无需 API key。通常约 1–2 分钟，任务上限 180 秒。两次启动至少间隔 60 秒，禁止并发采集。</p>
        <button className="primary" disabled={starting || job?.state === 'RUNNING'} onClick={() => void startProbe()}>{starting ? '正在启动…' : job?.state === 'RUNNING' ? '探测运行中…' : '运行只读探测'}</button>
      </section><section className="panel" aria-live="polite"><h2>任务进度</h2><span className="badge">{job ? jobNames[job.state] : '正在读取状态'}</span><p>{job?.message}</p>
        {job?.job_id && <><progress max={job.total_symbols || 1} value={job.completed_symbols.length}/><p>{job.completed_symbols.length} / {job.total_symbols} 个合约已有处理日志</p></>}
        <dl className="facts"><div><dt>开始</dt><dd>{time(job?.started_at)}</dd></div><div><dt>结束</dt><dd>{time(job?.finished_at)}</dd></div><div><dt>退出码</dt><dd>{job?.exit_code ?? '—'}</dd></div></dl></section></div>
        <section className="panel"><div className="section-heading"><h2>运行日志</h2><button onClick={() => void refreshJob()}>刷新任务状态</button></div>
          <p className="muted">运行时每 2 秒更新；显示日志末尾最多 16 KB。进程完成不代表每项交易能力已获核验。</p><pre className="terminal" aria-label="运行日志">{job?.log || '尚无日志。点击「运行只读探测」开始。'}</pre>
          {job?.job_id && <p className="muted mono">任务 ID：{job.job_id}</p>}</section></>}
      {page === 'reports' && <><section className="panel"><h2>报告下载</h2><p className="muted">当前探测快照：{time(report?.generated_at)} · 下载文件中的未知状态保留原值。</p><div className="downloads">
        {[['capabilities_json', '能力报告', 'JSON / 完整证据'], ['capabilities_csv', '能力汇总', 'CSV / 逐品种'], ['quality_md', '数据质量说明', 'Markdown / 异常与限制'], ['quality_json', '数据质量明细', 'JSON / 样本统计']].map(([id, label, hint]) =>
          <a key={id} href={`/api/v1/reports/${id}`} download><strong>{label} ↓</strong><span>{hint}</span></a>)}</div></section>
        <section className="panel"><h2>最近一次样本质量</h2><p className="muted">时效标签反映采集时刻；小样本不能证明持续可用性。闭合归档按来源去重。</p>
          <div className="table-wrap"><table><thead><tr><th>合约</th><th>闭合样本</th><th>未闭合样本</th><th>累计归档</th><th>缺口段数</th><th>采集时质量 / 时效</th></tr></thead><tbody>{quality.map(q => <tr key={q.symbol}>
            <th scope="row">{q.symbol}</th><td>{q.closed_sample}</td><td>{q.unclosed_sample}</td><td>{q.closed_total}</td><td>{q.gaps.length}</td><td>{q.quality} / {q.timeliness}</td></tr>)}</tbody></table></div>
          {!quality.length && <p className="empty">没有可用的质量报告，请运行只读探测。</p>}
          <p className="muted mono">报告 ID：{report?.run_id ?? '—'}</p></section></>}
      {page === 'safety' && <><section className="panel"><h2>当前运行边界</h2><dl className="facts"><div><dt>实盘开关</dt><dd>LIVE_TRADING_ENABLED=false</dd></div><div><dt>审批模式</dt><dd>HUMAN</dd></div><div><dt>账户凭证</dt><dd>P0 不接入密钥</dd></div><div><dt>真实订单执行</dt><dd>尚未实现</dd></div></dl>
        <p>行情、历史研究回测与风险试算已接入；P1 数据库验收待完成。P3 离线纸面交易已接入，数据库验收待完成；认证账户核验在 P4，真实执行在独立授权后的 P5。</p></section>
        <div className="two-columns"><section className="panel"><h2>已确认的设计要求</h2><dl className="facts"><div><dt>微资金本金亏损容忍</dt><dd>50%</dd></div><div><dt>常规交易所单仓杠杆</dt><dd>10–20x</dd></div><div><dt>单仓杠杆上限偏好</dt><dd>25x</dd></div></dl><p className="muted">这是设计要求。实际账户与合约能力尚未核验；50% 为容忍预算，不保证最大亏损。</p></section>
          <section className="panel"><h2>仍待核验或批准</h2><ul><li>逐品种账户权限和地区适用性</li><li>账户最大杠杆、逐仓、reduceOnly 和保护单</li><li>其他微资金风险阈值：研究/模拟候选</li><li>持续行情稳定性、完整历史与时段映射</li></ul><p className="muted">当前健康接口返回 503 是交易未就绪的预期状态。</p></section></div></>}
      <footer>Quant System V1.2 · P3 纸面模拟（开发中）<span>时间展示：Asia/Shanghai · 存储：UTC</span></footer>
    </main>{selected && <InstrumentDialog cap={selected} close={() => setSelected(null)}/>}
  </div>;
}
createRoot(document.getElementById('root')!).render(<React.StrictMode><App/></React.StrictMode>);
