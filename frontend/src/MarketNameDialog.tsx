import {useEffect,useRef,useState} from 'react';
import {api} from './api';
import type {MarketCatalog,NameUpdateResult} from './researchTypes';

interface Props {
  catalog:MarketCatalog;
  initialSymbol:string;
  onDismiss:()=>void;
  onSaved:(result:NameUpdateResult)=>void;
}

export function MarketNameDialog({catalog,initialSymbol,onDismiss,onSaved}:Props) {
  const dialog=useRef<HTMLDialogElement>(null);
  const initial=catalog.instruments.find(i=>i.symbol===initialSymbol);
  const [symbol,setSymbol]=useState(initial?.symbol??'');
  const [name,setName]=useState(initial?.name_source==='UNAVAILABLE'?'':initial?.name_zh??'');
  const [query,setQuery]=useState(''),[onlyMissing,setOnlyMissing]=useState(false);
  const [saving,setSaving]=useState(false),[error,setError]=useState('');
  useEffect(()=>{if(dialog.current&&!dialog.current.open)dialog.current.showModal();},[]);
  const target=catalog.instruments.find(i=>i.symbol===symbol);
  const terms=query.trim().toLocaleLowerCase().split(/\s+/).filter(Boolean);
  const matches=catalog.instruments.filter(i=>(!onlyMissing||i.name_source==='UNAVAILABLE')&&terms.every(t=>`${i.symbol} ${i.name_zh} ${i.base_asset}`.toLocaleLowerCase().includes(t)));
  const related=target?catalog.instruments.filter(i=>i.symbol===target.symbol||(target.underlying_type&&i.underlying_type===target.underlying_type&&i.base_asset===target.base_asset)):[];
  const valid=!!target&&/[\u3400-\u9fff]/.test(name.trim())&&name.trim()!=='中文名待补充'&&name.trim().length<=80;
  function choose(code:string) {
    setSymbol(code);setError('');
    const item=catalog.instruments.find(i=>i.symbol===code);
    setName(item?.name_source==='UNAVAILABLE'?'':item?.name_zh??'');
  }
  async function save() {
    if(!target||!valid)return;
    setSaving(true);setError('');
    try {
      onSaved(await api<NameUpdateResult>('/api/v1/market/names',{
        symbol:target.symbol,name_zh:name.trim(),expected_name:target.name_zh,
      }));
    }catch(e){setError(String(e));}finally{setSaving(false);}
  }
  return <dialog ref={dialog} className="name-dialog" aria-labelledby="name-dialog-title" onCancel={e=>{if(saving)e.preventDefault();else onDismiss();}} onClose={onDismiss}>
    <form onSubmit={e=>{e.preventDefault();void save();}}>
      <div className="section-heading"><div><h2 id="name-dialog-title">补充中文名</h2><p className="muted">填写用于行情显示和搜索的本地名称。</p></div><button type="button" aria-label="关闭中文名窗口" disabled={saving} onClick={onDismiss}>×</button></div>
      <label className="wide-label">窗口搜索合约<input type="search" placeholder="输入合约代码或已有中文名" disabled={saving} value={query} onChange={e=>{setQuery(e.target.value);choose('');}}/></label>
      <label className="name-missing"><input type="checkbox" checked={onlyMissing} disabled={saving} onChange={e=>{setOnlyMissing(e.target.checked);choose('');}}/>仅显示中文名待补充的合约</label>
      <label className="wide-label">补充名称的合约<select value={matches.some(i=>i.symbol===symbol)?symbol:''} disabled={saving||!matches.length} onChange={e=>choose(e.target.value)}><option value="" disabled>请选择合约（{matches.length} 项）</option>{matches.map(i=><option key={i.symbol} value={i.symbol}>{i.symbol} · {i.name_zh}</option>)}</select></label>
      {!matches.length&&<p className="note">没有匹配的合约，请修改搜索词或取消筛选。</p>}
      {target&&<p className="muted">正在编辑：<strong>{target.symbol}</strong><br/>当前名称：{target.name_zh}</p>}
      <label className="wide-label">中文展示名称<input maxLength={80} required disabled={saving||!target} placeholder="例如 美光科技（Micron）" value={name} onChange={e=>setName(e.target.value)}/></label>
      <p className="muted name-hint">最多 80 个字符，须包含中文；可附加英文公司名或常用别名。</p>
      {target&&<p className="note">保存后更新 {related.length} 个同资产、同类型合约：{related.map(i=>i.symbol).join('、')}。名称仅用于本地展示。</p>}
      {error&&<p role="alert" className="error">{error}</p>}
      <div className="actions"><button type="button" disabled={saving} onClick={onDismiss}>取消</button><button type="submit" className="primary" disabled={saving||!valid}>{saving?'保存中…':'保存中文名'}</button></div>
    </form>
  </dialog>;
}
