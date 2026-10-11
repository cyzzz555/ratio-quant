import {useEffect,useRef,useState} from 'react';
import {api,localTime} from './api';
import {MarketNameDialog} from './MarketNameDialog';
import type {MarketCatalog,MarketInstrument} from './researchTypes';

export function matchingContracts(catalog:MarketCatalog|null,query:string):MarketInstrument[] {
  const terms=query.trim().toLocaleLowerCase().split(/\s+/).filter(Boolean);
  return (catalog?.instruments??[]).filter(i=>terms.every(t=>`${i.symbol} ${i.base_asset} ${i.name_zh}`.toLocaleLowerCase().includes(t)));
}

export function ContractSearch({id,symbol,disabled,onCatalog,onChoose,onSelectionAvailable}:{id:string;symbol:string;disabled:boolean;onCatalog:(catalog:MarketCatalog)=>void;onChoose:(symbol:string)=>void;onSelectionAvailable:(available:boolean)=>void}) {
  const [catalog,setCatalog]=useState<MarketCatalog|null>(null),[query,setQuery]=useState('');
  const [busy,setBusy]=useState(false),[error,setError]=useState('');
  const [nameOpen,setNameOpen]=useState(false),[message,setMessage]=useState('');
  const initialized=useRef(false);
  async function load(refresh=false) {
    setBusy(true);setError('');
    try {const next=await api<MarketCatalog>('/api/v1/market/catalog',{refresh});setCatalog(next);onCatalog(next);}
    catch(e){setError(String(e));}finally{setBusy(false);}
  }
  useEffect(()=>{if(!initialized.current){initialized.current=true;void load();}},[]);
  const matches=matchingContracts(catalog,query);
  useEffect(()=>{onSelectionAvailable(matchingContracts(catalog,query).some(i=>i.symbol===symbol));},[catalog,query,symbol,onSelectionAvailable]);
  return <><div className="market-search"><label htmlFor={id}>搜索合约代码或中文名称<input id={id} type="search" placeholder="例如 BTC、比特币、美光、SPCX" value={query} onChange={e=>setQuery(e.target.value)} aria-describedby={`${id}-count`}/></label><button disabled={!query} onClick={()=>setQuery('')}>清空搜索</button><button disabled={busy||disabled} onClick={()=>void load(true)}>{busy?'读取目录…':'刷新合约目录'}</button><button disabled={!catalog||busy||disabled} onClick={()=>{setMessage('');setNameOpen(true);}}>补充中文名</button></div>
    <p id={`${id}-count`} className="muted market-count" aria-live="polite">{catalog?`匹配 ${matches.length} / ${catalog.instruments.length} 个当前合约 · 目录核验 ${localTime(catalog.observed_at)}`:busy?'正在读取交易所合约目录…':'目录尚未加载，请刷新合约目录。'}</p>
    {error&&<p role="alert" className="error">{error}{catalog?'；仍显示上次目录，请重试。':''}</p>}
    {message&&<p role="status" className="info-strip">{message}</p>}
    <label className="wide-label">{id==='market-search'?'行情合约':'研究合约'}<select aria-label={id==='market-search'?'行情合约':'研究合约'} disabled={disabled||!matches.length} value={matches.some(i=>i.symbol===symbol)?symbol:''} onChange={e=>onChoose(e.target.value)}><option value="" disabled>{matches.length?'选择搜索结果':'没有匹配的合约'}</option>{matches.map(i=><option key={i.symbol} value={i.symbol}>{i.symbol} · {i.name_zh}</option>)}</select></label>
    {catalog&&!matches.length&&<p className="empty">没有匹配的合约，请修改关键词或清空搜索。</p>}
    {nameOpen&&catalog&&<MarketNameDialog catalog={catalog} initialSymbol={symbol} onDismiss={()=>setNameOpen(false)} onSaved={result=>{setCatalog(result.catalog);onCatalog(result.catalog);setNameOpen(false);setMessage(`中文名已保存，更新 ${result.affected_symbols.length} 个合约；行情与历史采集共用此名称。`);}}/>}
    <p className="muted">中文为本地展示别名，目录与行情页共用；公共数据可见不代表账户权限。目录缓存 5 分钟。</p>
  </>;
}
