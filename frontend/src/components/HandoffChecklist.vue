<script setup>
import {ref,computed,watch} from 'vue'
import {workbenchRequest} from '../lib/backends'
const props=defineProps({ticket:Object,candidate:String,settings:Object,modelValue:Object})
const emit=defineEmits(['update:modelValue'])
const data=ref(null),error=ref('')
const statuses={missing:'待收集',received:'已收到，待核验',pending:'待客户确认',disputed:'客户不认可',unreachable:'无法联系',unrecorded:'历史结案待核对'}
const outgoing=computed(()=>props.settings.workspaceId&&props.candidate&&![props.ticket.owner,props.settings.userId,'待分派'].includes(props.candidate))
const incoming=computed(()=>!!props.ticket.handoff)
const stale=computed(()=>outgoing.value&&props.modelValue?.context_hash&&data.value?.context_hash!==props.modelValue.context_hash)
const choices=computed(()=>props.modelValue?.decisions||[])
function change(key,decision){emit('update:modelValue',{context_hash:props.modelValue?.context_hash||data.value.context_hash,decisions:[...choices.value.filter(x=>x.key!==key),{key,decision}]})}
function rebase(){emit('update:modelValue',{context_hash:data.value.context_hash,decisions:choices.value.filter(x=>data.value.items.some(i=>i.key===x.key))})}
async function load(){data.value=null;error.value='';try{data.value=await workbenchRequest(props.settings,'/tickets/'+props.ticket.id+'/handoff-preview?user_id='+encodeURIComponent(props.settings.userId))}catch(e){error.value=e.message}}
watch(()=>[props.ticket.id,props.ticket.revision,props.candidate,props.settings.userId,props.settings.workspaceId],load,{immediate:true})
</script><template><section v-if="outgoing||incoming" class="handoff-checklist" :aria-busy="!data&&!error"><h3>材料与回访责任清单</h3><p v-if="error" role="alert">{{error}} <button type="button" @click="load">重读清单</button></p><p v-else-if="!data">正在核对独立待办…</p><template v-else><template v-if="outgoing"><p>工单接受后移交给 {{candidate}}。以下独立待办请逐项确认。</p><p v-if="!data.items.length">当前没有待收集材料或客户跟进。</p><label v-for="item in data.items" :key="item.key">{{item.title}} · 当前 {{item.owner}} · {{statuses[item.status]||item.status}}<select :aria-label="'交接责任：'+item.title" required :value="choices.find(x=>x.key===item.key)?.decision||''" @change="change(item.key,$event.target.value)"><option value="" disabled>请选择责任安排</option><option value="transfer">随工单移交给 {{candidate}}</option><option value="retain">仍由 {{item.owner}} 负责</option></select><small v-if="item.due_at">期限：{{new Date(item.due_at).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'})}}</small></label><p v-if="stale" role="alert">独立待办已变化，原选择保留。<button type="button" @click="rebase">已核对最新清单，继续</button></p></template><template v-else-if="incoming"><p v-for="item in ticket.handoff.tasks||[]" :key="item.key">{{item.title}}：{{item.decision==='transfer'?(ticket.handoff.state==='accepted'?'已移交给 ':'接受后由 ')+ticket.handoff.candidate+' 负责':'仍由 '+item.owner+' 负责'}} · {{statuses[item.status]||item.status}}</p><p v-if="ticket.handoff.state==='pending'&&(data.items.length&&!ticket.handoff.task_context_hash||ticket.handoff.task_context_hash&&ticket.handoff.task_context_hash!==data.context_hash)" role="alert">交接清单缺少确认或已变化。请退回，由发起人核对后重新交接；接受操作会被阻止。</p></template></template></section></template>
