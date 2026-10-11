import {useEffect,useRef,useState} from 'react';
import type {NumericField,ViewMode} from './workflowForms';
import {viewModeLabel} from './workflowForms';

interface Props {title:string;mode:ViewMode;simpleDescription:string;disabled?:boolean;onChange:(mode:ViewMode)=>void}

export function WorkflowMode({title,mode,simpleDescription,disabled=false,onChange}:Props) {
  const [open,setOpen]=useState(false);
  return <div className="workflow-mode"><span className="badge">{viewModeLabel(mode)}</span><button type="button" disabled={disabled} onClick={()=>setOpen(true)}>选择{title}模式</button>
    {open&&<ModeDialog title={title} mode={mode} simpleDescription={simpleDescription} onDismiss={()=>setOpen(false)} onApply={next=>{onChange(next);setOpen(false);}}/>}
  </div>;
}

function ModeDialog({title,mode,simpleDescription,onDismiss,onApply}:Omit<Props,'disabled'|'onChange'>&{onDismiss:()=>void;onApply:(mode:ViewMode)=>void}) {
  const dialog=useRef<HTMLDialogElement>(null);
  const [choice,setChoice]=useState<ViewMode>(mode);
  const titleId=`mode-${title}`;
  useEffect(()=>{
    const node=dialog.current,previousFocus=document.activeElement;
    node?.showModal();
    return()=>{if(node?.open)node.close();if(previousFocus instanceof HTMLElement)previousFocus.focus();};
  },[]);
  return <dialog ref={dialog} className="mode-dialog" aria-labelledby={titleId} onCancel={onDismiss} onClose={onDismiss}>
    <form onSubmit={e=>{e.preventDefault();onApply(choice);}}>
      <div className="section-heading"><h2 id={titleId}>{title} · 选择操作模式</h2><button type="button" aria-label="关闭模式窗口" onClick={onDismiss}>×</button></div>
      <fieldset className="mode-choices"><legend className="sr-only">操作模式</legend>
        <label className={choice==='simple'?'selected':''}><input type="radio" name="view-mode" value="simple" checked={choice==='simple'} onChange={()=>setChoice('simple')}/><span><strong>简化模式</strong><small>{simpleDescription}</small></span></label>
        <label className={choice==='full'?'selected':''}><input type="radio" name="view-mode" value="full" checked={choice==='full'} onChange={()=>setChoice('full')}/><span><strong>完整模式</strong><small>展开全部已有参数，适合详细研究和复核。</small></span></label>
      </fieldset>
      <p className="note">切换保留当前填写的全部数值。这里仅调整界面，不会启动任务、批准参数或执行订单。</p>
      <div className="actions"><button type="button" onClick={onDismiss}>取消</button><button type="submit" className="primary">使用{viewModeLabel(choice)}</button></div>
    </form>
  </dialog>;
}

export function NumericInputs<K extends string>({fields,values,disabled,onChange,quote}:{fields:NumericField<K>[];values:Record<K,string>;disabled:boolean;onChange:(key:K,value:string)=>void;quote?:string}) {
  return <>{fields.map(field=><label key={field.key}>{field.label}{field.key==='initial_equity'?` ${quote??'USDT'}`:''}<input type="number" required step={field.integer?'1':'any'} min={field.min} max={field.max} inputMode={field.integer?'numeric':'decimal'} value={values[field.key]} disabled={disabled} onChange={e=>onChange(field.key,e.target.value)}/></label>)}</>;
}

export function AssumptionSummary<K extends string>({fields,values}:{fields:NumericField<K>[];values:Record<K,string>}) {
  return <p className="muted assumption-summary">当前附加参数：{fields.map(f=>`${f.label} ${values[f.key]||'未填写'}`).join(' · ')}。展开下方可修改。</p>;
}
