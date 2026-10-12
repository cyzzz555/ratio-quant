import type {Candle} from './researchTypes';
import {localTime,numberText} from './api';

export function Candles({bars}:{bars:Candle[]}) {
  if (!bars.length) return <p className="empty">当前范围没有完整闭合的这个周期。请选择 1m / 5m / 15m，较长周期将在历史研究中聚合。</p>;
  const rows=bars.slice(-90), low=Math.min(...rows.map(b=>Number(b.low))),high=Math.max(...rows.map(b=>Number(b.high)));
  const span=high-low || high*.001, y=(p:string)=>22+(high-Number(p))/span*206;
  const width=620/rows.length;
  return <div className="chart-frame"><svg viewBox="0 0 720 280" role="img" aria-label={`${rows.length} 根 Binance 已闭合 K 线`}>
    {[0,1,2,3,4].map(i=><g key={i}><line x1="16" x2="646" y1={22+i*51.5} y2={22+i*51.5} stroke="var(--chart-grid)"/><text x="654" y={26+i*51.5} fontSize="11" fill="var(--chart-label)">{numberText(String(high-span*i/4))}</text></g>)}
    {rows.map((b,i)=>{const x=20+i*width, color=Number(b.close)>=Number(b.open)?'var(--up)':'var(--down)';return <g key={b.open_at}><title>{localTime(b.open_at)} 开 {b.open} 高 {b.high} 低 {b.low} 收 {b.close} 量 {b.volume}</title><line x1={x+width/2} x2={x+width/2} y1={y(b.high)} y2={y(b.low)} stroke={color}/><rect x={x+width*.15} y={Math.min(y(b.open),y(b.close))} width={Math.max(1,width*.7)} height={Math.max(1,Math.abs(y(b.open)-y(b.close)))} fill={color}/></g>})}
    <text x="18" y="265" fontSize="11" fill="var(--chart-label)">{localTime(rows[0].open_at)}</text><text x="440" y="265" fontSize="11" fill="var(--chart-label)">{localTime(rows.at(-1)!.close_at)}</text>
  </svg></div>;
}

export function EquityCurve({points}:{points:{at:string;equity:string}[]}) {
  if(!points.length) return null;
  const low=Math.min(...points.map(p=>Number(p.equity))),high=Math.max(...points.map(p=>Number(p.equity)));
  const span=high-low || 1;
  const path=points.map((p,i)=>`${i?'L':'M'} ${20+i/(points.length-1 || 1)*620} ${25+(high-Number(p.equity))/span*130}`).join(' ');
  return <div className="chart-frame"><svg viewBox="0 0 720 190" role="img" aria-label="模拟净权益曲线"><line x1="20" x2="640" y1="155" y2="155" stroke="var(--chart-grid)"/><path d={path} fill="none" stroke="var(--accent)" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"/><text x="650" y="30" fontSize="11">{numberText(String(high))}</text><text x="650" y="157" fontSize="11">{numberText(String(low))}</text><text x="20" y="180" fontSize="11">{localTime(points[0].at)}</text></svg></div>;
}
