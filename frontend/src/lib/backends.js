import {requestError,publishRequest} from './requestErrors'
const DEFAULT_BACKENDS = {
  python: {
    id: 'python',
    label: 'Python',
    baseUrl: import.meta.env.VITE_PYTHON_API_URL || '/api/python',
    port: '8010'
  },
  java: {
    id: 'java',
    label: 'Java',
    baseUrl: import.meta.env.VITE_JAVA_API_URL || '/api/java',
    port: '8080'
  }
}

export function createInitialSettings() {
  const saved = readSettings()
  return {
    backend: saved.backend || 'python',
    workspaceId:saved.workspaceId||'',
    demoReturn:saved.demoReturn||null,
    practiceReturn:saved.practiceReturn||null,
    userId: saved.userId || 'u1001',
    conversationId: saved.conversationId || '',
    endpoints: {
      python: saved.endpoints?.python || DEFAULT_BACKENDS.python.baseUrl,
      java: saved.endpoints?.java || DEFAULT_BACKENDS.java.baseUrl
    }
  }
}

export function saveSettings(settings) {
  localStorage.setItem('echomind.frontend.settings', JSON.stringify(settings))
}

export function backendMeta(type, settings) {
  const meta = DEFAULT_BACKENDS[type] || DEFAULT_BACKENDS.java
  return {
    ...meta,
    baseUrl: normalizeBaseUrl(settings.endpoints[type] || meta.baseUrl)
  }
}

export async function requestHealth(type, settings) {
  return requestJson(backendMeta(type, settings).baseUrl, '/health')
}

export async function requestMonitor(type, settings) {
  return requestJson(backendMeta(type, settings).baseUrl, '/monitor')
}

export async function requestKnowledgeStats(type, settings) {
  return requestJson(backendMeta(type, settings).baseUrl, '/knowledge/stats')
}

export async function requestSearch(type, settings, query, topK = 5) {
  const params = new URLSearchParams({ query, [type === 'python' ? 'top_k' : 'topK']: String(topK) })
  return requestJson(backendMeta(type, settings).baseUrl, `/search?${params}`, { method: 'POST' })
}

export async function requestChat(type, settings, message) {
  const meta = backendMeta(type, settings)
  const payload = buildChatPayload(type, settings, message)
  const raw = await requestJson(meta.baseUrl, '/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  })
  return normalizeChatResponse(type, raw)
}

export async function addKnowledge(type, settings, documents) {
  return requestJson(backendMeta(type, settings).baseUrl, '/knowledge/add', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ documents })
  })
}

export async function uploadKnowledge(type,settings,file,scope="business") {
  const form = new FormData()
  form.append('file', file)
  return requestJson(backendMeta(type,settings).baseUrl, '/knowledge/upload?scope='+encodeURIComponent(scope), {
    method: 'POST',
    body: form
  })
}

function buildChatPayload(type, settings, message) {
  if (type === 'python') {
    return {
      message,
      user_id: settings.userId || 'anonymous',
      conv_id: settings.conversationId || undefined,
      workspace_id:settings.workspaceId||undefined,
      request_id:settings.replyRequestId||undefined,
      input_kind:settings.inputKind||'customer_input',
      action:settings.replyAction||undefined
    }
  }
  return {
    message,
    user_id: settings.userId || 'anonymous',
    conversation_id: settings.conversationId || undefined
  }
}

function normalizeChatResponse(type, raw) {
  return {
    backend: type,
    conversationId: raw.conversation_id || raw.conversationId || raw.conv_id || '',
    response: raw.response || '',
    intent: raw.intent || 'other',
    agentType: raw.agent_type || raw.agentType || '',
    escalated: Boolean(raw.escalated),
    latencyMs: Number(raw.latency_ms ?? raw.latencyMs ?? 0),
    knowledgeUsed: Boolean(raw.knowledge_used ?? raw.knowledgeUsed),
    verified: raw.verified,
    grounded: raw.grounded,
    raw
  }
}

async function requestJson(baseUrl, path, options = {}) {
  const base=normalizeBaseUrl(baseUrl),url=base+path,method=(options.method||'GET').toUpperCase()
  let response,text
  try{response=await fetch(url,options);text=await response.text()}
  catch(cause){const error=requestError({path,method,network:true});publishRequest({type:'failure',base,error});throw error}
  let data=null
  try{data=text?JSON.parse(text):null}catch{data=text}
  if(!response.ok){const error=requestError({path,method,status:response.status,detail:data?.detail});publishRequest({type:'failure',base,error});throw error}
  publishRequest({type:'success',base,path,method})
  return data
}

function normalizeBaseUrl(value) {
  return String(value || '').replace(/\/+$/, '')
}

function readSettings() {
  try {
    return JSON.parse(localStorage.getItem('echomind.frontend.settings') || '{}')
  } catch {
    return {}
  }
}

export function workbenchRequest(settings,path,method='GET',body) {
  const scoped=/^\/(conversations|tickets|operations|demos|orders|knowledge\/(gaps|rechecks))(\/|\?|$)/.test(path)||/^\/feedback\/[^/]+\/case$/.test(path)
  if(scoped&&settings.workspaceId){
    if(method==='GET')path+=(path.includes('?')?'&':'?')+'workspace_id='+encodeURIComponent(settings.workspaceId)
    else if(body&&typeof body==='object')body={...body,workspace_id:settings.workspaceId}
  }
  return requestJson(backendMeta(settings.backend,settings).baseUrl,path,{
    method,...(body===undefined?{}:{headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})
  })
}

export async function uploadCaseEvidence(settings,convId,file,fields) {
  const body=new FormData();body.append('file',file)
  for(const [key,value] of Object.entries({...fields,user_id:settings.userId,...(settings.workspaceId?{workspace_id:settings.workspaceId}:{})}))body.append(key,value)
  return requestJson(backendMeta(settings.backend,settings).baseUrl,'/conversations/'+convId+'/attachments',{method:'POST',body})
}

export async function getCaseEvidence(settings,convId,id) {
  const query=new URLSearchParams({user_id:settings.userId,...(settings.workspaceId?{workspace_id:settings.workspaceId}:{})})
  const response=await fetch(backendMeta(settings.backend,settings).baseUrl+'/conversations/'+convId+'/attachments/'+id+'?'+query)
  if(!response.ok)throw new Error('凭证读取失败：'+response.status+'，请确认当前事项权限后重试')
  return response.blob()
}
