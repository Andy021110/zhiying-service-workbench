<script setup>
import {computed,nextTick,ref,watch} from 'vue'
import {workbenchRequest} from '../lib/backends'
import '../styles/service-followup.css'
const props=defineProps({settings:Object}),emit=defineEmits(['openConversation'])
const items=ref([]),busy=ref(false),error=ref(''),notice=ref(''),showAll=ref(false),edits=ref({}),errorBox=ref(null)
const labels={pending:'待回查',reviewed:'已回查',not_applicable:'不适用',superseded:'已转新版'}
const shown=computed(()=>items.value.filter(r=>showAll.value||r.status==='pending'))
const api=(p,m='GET',b)=>workbenchRequest(props.settings,p,m,b),scope=()=>props.settings.userId+':'+props.settings.workspaceId
let generation=0
async function load(){const n=++generation;try{const data=await api('/knowledge/rechecks?user_id='+encodeURIComponent(props.settings.userId));if(n!==generation)return;items.value=data;edits.value=Object.fromEntries(data.map(r=>[r.id,{status:r.status==='superseded'?'pending':r.status,note:''}]))}catch(e){if(n===generation)error.value=e.message}}
watch(()=>[props.settings.userId,props.settings.workspaceId],()=>{items.value=[];notice.value='';error.value='';load()},{immediate:true})
async function run(fn,message){if(busy.value)return;const key=scope();busy.value=true;error.value='';notice.value='';try{await fn();if(key!==scope())return;await load();notice.value=message}catch(e){if(key===scope()){error.value=e.message;await nextTick();errorBox.value?.focus()}}finally{busy.value=false}}
function refresh(){return run(()=>api('/knowledge/rechecks/refresh','POST',{user_id:props.settings.userId}),'已核对明确关联的缺口与业务引用，原事项保持原记录')}
function save(r){return run(()=>api('/knowledge/rechecks/'+r.id,'PATCH',{user_id:props.settings.userId,...edits.value[r.id],expected_revision:r.revision}),'回查结论已保存；原回复与事项状态保留')}
defineExpose({load})
</script>
<template>
<section :aria-busy="busy" class="recheck-panel"><header><div><h2>知识生效后的影响事项</h2><p class="source-note">仅包含缺口或业务回复引用明确关联的事项，不代表所有语义相关问题。逐项核对，不自动重开或改写已采用回复。</p></div><button class="secondary" :disabled="busy" @click="refresh">刷新影响事项</button></header><p v-if="error" ref="errorBox" role="alert" tabindex="-1" class="form-error">{{error}}</p><p v-if="notice" role="status" class="source-note">{{notice}}</p><label class="inline-check"><input v-model="showAll" type="checkbox"/>显示已回查、不适用与旧版本</label><p v-if="!shown.length" class="source-note">当前范围暂无待回查事项。缺口关联生效文档或新版本审核通过后生成；历史关联可点击刷新补齐。</p><div class="recheck-list"><article v-for="r in shown" :key="r.id"><h3>{{r.case_title}}</h3><p>{{r.document_title}} · v{{r.document_version}} · {{labels[r.status]}}</p><small>回查负责人：{{r.current_owner}}<br/>依据：关联 {{r.references.filter(x=>x.startsWith('gap:')).length}} 个缺口、{{r.references.filter(x=>x.startsWith('citation:')).length}} 条业务引用</small><button class="text-button" :disabled="busy" @click="emit('openConversation',r.conv_id)">打开受影响事项</button><p v-if="!r.document_current" class="form-error">依据已变化或失效，请刷新清单并核对当前版本。</p><form v-if="r.document_current&&r.status!=='superseded'" @submit.prevent="save(r)"><label>事项回查结论<select aria-label="事项回查结论" v-model="edits[r.id].status"><option value="pending">待回查</option><option value="reviewed">已回查</option><option value="not_applicable">不适用</option></select></label><label>回查说明<textarea v-model.trim="edits[r.id].note" required maxlength="2000" rows="2"/></label><button class="secondary" :disabled="busy||!edits[r.id].note.trim()">保存回查结论</button></form><details v-if="r.history.length"><summary>回查历史</summary><p v-for="(h,i) in r.history" :key="i">{{h.actor}} · {{h.note}} · {{labels[h.status]||''}} · v{{h.document_version||r.document_version}}</p></details></article></div></section>
</template>
