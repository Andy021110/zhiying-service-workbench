<script setup>
import {ref,watch} from 'vue'
import {workbenchRequest} from '../lib/backends'
const props=defineProps({conversationId:String,settings:Object,ticketId:String,refreshToken:Number,expanded:Boolean})
const emit=defineEmits(['action','loading','ready'])
const state=ref(null),loading=ref(false),error=ref('');let generation=0
async function load(){const n=++generation;state.value=null;if(!props.conversationId)return;emit('loading');loading.value=true;error.value='';try{const q=new URLSearchParams({user_id:props.settings.userId,...(props.ticketId?{ticket_id:props.ticketId}:{})});const r=await workbenchRequest(props.settings,'/conversations/'+props.conversationId+'/readiness?'+q);if(n===generation)state.value=r}catch(e){if(n===generation)error.value=e.message}finally{if(n===generation){loading.value=false;emit('ready')}}}
watch(()=>[props.conversationId,props.settings.userId,props.settings.workspaceId,props.ticketId,props.refreshToken],load,{immediate:true})
defineExpose({load})
</script>
<template>
<section class="case-progress" :aria-busy="loading" aria-label="当前阶段与下一步">
 <p v-if="loading" class="source-note">正在核对当前阶段与欠缺条件…</p><p v-if="error" role="alert" class="form-error">{{error}} <button type="button" class="text-button" @click="load">重新核对</button></p>
 <template v-if="state"><div class="case-progress-head"><strong>当前阶段：{{state.phase}}</strong><button v-if="state.blocks.length" type="button" class="text-button" @click="emit('action',{...state.blocks[0],conv_id:conversationId})">{{state.blocks[0].action}}</button><button v-else-if="state.notices.length" type="button" class="text-button" @click="emit('action',{kind:'customer',conv_id:conversationId})">查看客户跟进</button></div>
 <details :open="expanded"><summary>查看欠缺条件与下一步 · {{state.blocks.length}} 项待办<span v-if="state.requires_exception"> · 客户尚未确认</span></summary><ul v-if="state.blocks.length"><li v-for="b in state.blocks" :key="b.kind+b.id"><span>{{b.title}}</span><button type="button" class="text-button" @click="emit('action',{...b,conv_id:conversationId})">{{b.action}}</button></li></ul><p v-else class="source-note">必要材料和当前交接没有阻塞项；提交时会再次核对最新记录。</p><div v-for="(n,i) in state.notices" :key="i" class="case-result-warning"><p>{{n.title}}</p><button type="button" class="text-button" @click="emit('action',{kind:'customer',conv_id:conversationId})">{{n.action}}</button><button v-if="expanded&&!state.internally_resolved" type="button" class="text-button" @click="emit('action',{kind:'exception',conv_id:conversationId})">填写内部结案例外原因</button></div></details></template>
</section>
</template>
