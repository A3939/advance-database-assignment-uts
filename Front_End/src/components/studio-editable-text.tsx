"use client";
import {createContext,useContext,useEffect,useLayoutEffect,useRef,useState,useReducer} from 'react';
import {StudioFieldDrafts} from '@/services/studio-edit-buffer';
import styles from './studio.module.css';
export const StudioDraftContext=createContext<{fields:StudioFieldDrafts;changed:()=>void;discard:(key:string)=>Promise<void>}|null>(null);
export function EditableText({value,label,onSave,single=false,max=6000,onDirty,fieldKey,disabled=false,placeholder,className,rows=3,autoSize=true}: {
 value:string;label:string;onSave:(text:string)=>Promise<void>;single?:boolean;max?:number;onDirty:()=>void;fieldKey:string;disabled?:boolean;placeholder?:string;className?:string;rows?:number;autoSize?:boolean;
}) {
 const session=useContext(StudioDraftContext);
 const [,refresh]=useReducer(n=>n+1,0);
 const text=session?.fields.get(fieldKey)??value;
 const textarea=useRef<HTMLTextAreaElement>(null);
 useLayoutEffect(()=>{
  const element=textarea.current;
  if(!element||!autoSize)return;
  const resize=()=>{
   // Size only this field. Saved text and its receipt identity remain owned by the draft buffer.
   element.style.height='auto';
   const border=element.offsetHeight-element.clientHeight;
   element.style.height=`${element.scrollHeight+border}px`;
  };
  resize();
  let lastWidth=element.clientWidth;
  const observer=new ResizeObserver(()=>{
   if(element.clientWidth!==lastWidth){lastWidth=element.clientWidth;resize();}
  });
  observer.observe(element);
  return()=>observer.disconnect();
 },[text,autoSize,single]);
 const timer=useRef<ReturnType<typeof setTimeout>|null>(null), saveRef=useRef(onSave),flight=useRef<{token:number,promise:Promise<void>}|null>(null), failedAttempt=useRef<{token:number,error:unknown}|null>(null);
 useEffect(()=>{saveRef.current=onSave;},[onSave]);
 useEffect(()=>()=>{if(timer.current)clearTimeout(timer.current);},[]);
 const save=(next:string,token:number|undefined):Promise<void>=>{
  if(timer.current)clearTimeout(timer.current);timer.current=null;
  if(token===undefined||session?.fields.token(fieldKey)!==token)return Promise.resolve();
  if(flight.current?.token===token)return flight.current.promise;
  // Blur and a read-only recovery review must not silently retry a failed write.
  // A new edit resets this; explicit reviewed reapply is owned by the parent queue.
  if(failedAttempt.current?.token===token)return Promise.reject(failedAttempt.current.error);
  const promise=saveRef.current(next).then(()=>{failedAttempt.current=null;session?.changed();refresh();}).catch(error=>{failedAttempt.current={token,error};throw error;}).finally(()=>{if(flight.current?.promise===promise)flight.current=null;});
  flight.current={token,promise};return promise;
 };
 const props={"aria-label":label,placeholder:placeholder??(label==='Report caption (optional)'?'Add a caption…':undefined),value:text,maxLength:max,disabled,
 onChange:(e:React.ChangeEvent<HTMLInputElement|HTMLTextAreaElement>)=>{const next=e.target.value;failedAttempt.current=null;onDirty();const token:number|undefined=session?.fields.set(fieldKey,next,():Promise<void>=>save(next,token));refresh();session?.changed();if(timer.current)clearTimeout(timer.current);timer.current=setTimeout(()=>void save(next,token).catch(()=>{}),500);},
 onBlur:()=>void save(text,session?.fields.token(fieldKey)).catch(()=>{})};
 return single?<input className={[styles.editTitle,className].filter(Boolean).join(' ')} {...props}/>:<textarea ref={textarea} className={[styles.editText,className].filter(Boolean).join(' ')} rows={rows} {...props}/>;
}

/** Explicit-save forms retain dirty values across panels; clean forms follow restored host snapshots. */
export function useStudioFormDraft<T>(fieldKey:string,saved:T,label:string) {
 const session=useContext(StudioDraftContext), serialized=JSON.stringify(saved);
 const [,refresh]=useReducer(n=>n+1,0), [base,setBase]=useState(serialized);
 const held=session?.fields.get(fieldKey),dirty=held!==undefined,draft:T=dirty?JSON.parse(held):saved;
 const change=(next:T)=>{if(!dirty)setBase(serialized);session?.fields.set(fieldKey,JSON.stringify(next),()=>Promise.reject(Error(`Save or discard ${label} before leaving or exporting.`)));refresh();session?.changed();};
 const commit=async(save:(next:T)=>Promise<void>)=>{const text=JSON.stringify(draft);await save(draft);setBase(text);refresh();session?.changed();};
 const discard=async()=>{await session?.discard(fieldKey);setBase(serialized);refresh();session?.changed();};
 return {draft,dirty,conflicted:dirty&&base!==serialized,change,commit,discard};
}
