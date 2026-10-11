import {useEffect,useRef} from 'react';
import {localTime} from './api';
import type {Run} from './researchTypes';

export function RecordDeleteDialog({record,busy,error,onDismiss,onConfirm}:{record:Run;busy:boolean;error:string;onDismiss:()=>void;onConfirm:()=>void}) {
  const dialog=useRef<HTMLDialogElement>(null);
  useEffect(()=>{if(dialog.current&&!dialog.current.open)dialog.current.showModal();},[]);
  return <dialog ref={dialog} className="name-dialog" aria-labelledby="delete-title" onCancel={e=>{if(busy)e.preventDefault();else onDismiss();}} onClose={onDismiss}>
    <h2 id="delete-title">删除此回测记录？</h2><p><strong>{record.symbol}</strong> · {localTime(record.created_at)}</p><code className="hash">{record.run_id}</code>
    <p>结果报告将移入回收站，从回测记录列表中隐藏；可在回收站恢复。</p><p className="note">历史数据集、Parquet、原始响应和审计证据继续保留。</p>
    {error&&<p className="error" role="alert">{error}</p>}
    <div className="actions"><button disabled={busy} onClick={onDismiss}>取消</button><button className="danger" disabled={busy} onClick={onConfirm}>{busy?'正在删除…':'确认删除'}</button></div>
  </dialog>;
}
