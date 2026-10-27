// Unsaved form data is isolated by viewer, backend, workspace and record.
export const formDraftKey=(settings,kind,id)=>'echomind.form.'+JSON.stringify([settings.backend,settings.endpoints?.[settings.backend]||'',settings.userId,settings.workspaceId||'personal',kind,id])
export function readFormDraft(key){try{return JSON.parse(localStorage.getItem(key)||'null')}catch{return null}}
export function writeFormDraft(key,value){try{localStorage.setItem(key,JSON.stringify(value));return true}catch{return false}}
export function clearFormDraft(key){try{localStorage.removeItem(key)}catch{}}
export const copyForm=value=>JSON.parse(JSON.stringify(value))
export const sameForm=(a,b)=>JSON.stringify(a)===JSON.stringify(b)
