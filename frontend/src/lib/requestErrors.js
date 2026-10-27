export const REQUEST_EVENT='echomind:request-status'
export function resourceName(path){
  if(path.startsWith('/health'))return '本地服务'
  if(path.startsWith('/tickets'))return '工单记录'
  if(path.startsWith('/conversations'))return '会话记录'
  if(path.startsWith('/workspaces'))return '工作范围'
  if(path.startsWith('/knowledge'))return '知识资料'
  if(path.startsWith('/feedback'))return '客户评价'
  if(path.startsWith('/task-map'))return '任务地图'
  if(path.startsWith('/operations'))return '待办与统计'
  return '当前内容'
}
export function requestError({path,method='GET',status=0,detail,network=false}){
  const mutation=!['GET','HEAD'].includes(method.toUpperCase()),transient=network||status>=500
  const name=resourceName(path)
  let message
  if(transient)message=mutation?name+'的提交结果暂未确认，请先核对当前记录，避免重复提交。':name+'暂时无法读取，请恢复连接后重新读取。'
  else message=typeof detail==='string'?detail:Array.isArray(detail)?'请检查必填项、时间格式和文字长度后重新提交。':status===404?'记录不存在或不在当前工作范围，请重新选择。':status===409?'记录已变化，请核对当前版本后再提交。':'提交未通过，请检查内容后重新提交。'
  const error=new Error(message)
  Object.assign(error,{status,detail,path,method:method.toUpperCase(),mutation,transient,kind:network?'network':status>=500?'service':status===409?'conflict':status===422?'validation':'request',outcome:mutation&&transient?'unknown':mutation?'rejected':'read_failed'})
  return error
}
export function publishRequest(event){if(typeof window!=='undefined')window.dispatchEvent(new CustomEvent(REQUEST_EVENT,{detail:event}))}
