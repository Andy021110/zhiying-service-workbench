<script setup>
import {computed,onUnmounted,ref,watch} from 'vue'
import {workbenchRequest} from '../lib/backends'
import '../styles/historical-todo.css'
import {formDraftKey,readFormDraft,writeFormDraft} from '../lib/formDrafts'
const props=defineProps({settings:Object,disabled:Boolean}),emit=defineEmits(['open'])
const expanded=ref(false),data=ref(null),busy=ref(false),error=ref(''),category=ref('all')
const current=computed(()=>data.value?.workspace_id===props.settings.workspaceId)
const unfinished=computed(()=>data.value?.items.filter(x=>x.status!=='resolved').length||0)
const shown=computed(()=>data.value?.items.filter(x=>category.value==='all'||x.key===category.value)||[])
const labels={open:'待处理',pending:'待跟进',in_progress:'处理中',resolved:'已完成'}
const orderLabels={delivered:'已送达',shipped:'已发货',canceled:'已取消',unavailable:'不可用',processing:'处理中',invoiced:'已开票',created:'已创建',approved:'已确认'}
const time=v=>v?new Date(v).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'}):'未安排'
let generation=0
async function load(){const n=++generation;busy.value=true;error.value='';try{const value=await workbenchRequest({...props.settings,workspaceId:''},'/historical-todos/ensure','POST',{user_id:props.settings.userId});if(n===generation)data.value=value}catch(e){if(n===generation)error.value=e.message}finally{if(n===generation)busy.value=false}}
watch(()=>[props.settings.userId,props.settings.backend,props.settings.workspaceId],()=>{expanded.value=!!readFormDraft(formDraftKey(props.settings,'history-catalog','expanded'))?.expanded;data.value=null;category.value='all';load()},{immediate:true})
onUnmounted(()=>generation++)
function toggleExamples(){expanded.value=!expanded.value;writeFormDraft(formDraftKey(props.settings,'history-catalog','expanded'),{expanded:expanded.value})}
function open(convId){emit('open',{workspaceId:data.value.workspace_id,convId})}
</script>
<template>
<section class="historical-todos" :aria-busy="busy" aria-label="Olist历史数据练习待办">
 <header><div><span class="history-eyebrow">Kaggle / Olist · 真实历史数据练习</span><h2>{{current?'正在处理历史数据练习':'从真实评价开始，直接处理六类问题'}}</h2><p>本地已有 {{data?.source?.imported_reviews||0}} 条低分评价。这里关联原始评价与订单，练习记录单独保存。</p></div><button v-if="data?.workspace_id&&!current" type="button" class="secondary" :disabled="busy||disabled" @click="open()">进入历史练习待办</button></header>
 <p v-if="busy" role="status" class="source-note">正在准备历史评价与待办…</p><p v-if="error" role="alert" class="form-error">{{error}} <button type="button" class="text-button" @click="load">重新读取历史待办</button></p>
 <template v-if="data&&!error"><p class="history-boundary">2016—2018 年匿名历史评价 · {{unfinished}} 条未完成 / {{data.items.length}} 条练习。中文为人工导读；处理期限从本地建立时起算，不代表历史客户承诺。</p>
  <p v-if="!data.items.length" class="source-note">{{data.scope}}</p>
  <template v-if="data.items.length&&!current"><button type="button" class="text-button history-expand" :aria-expanded="expanded" aria-controls="history-example-list" @click="toggleExamples">{{expanded?'收起历史练习案例':'展开 '+data.items.length+' 条历史练习案例'}}</button></template><template v-if="data.items.length&&!current&&expanded"><div id="history-example-list"><div class="history-filter"><label>练习类型<select v-model="category" aria-label="筛选历史练习"><option value="all">全部六类</option><option v-for="item in data.items" :key="item.key" :value="item.key">{{item.title.split(' · ')[0]}}</option></select></label><span>上方当前工作范围的筛选，不影响此独立练习列表。</span></div>
   <div class="history-task-grid"><article v-for="item in shown" :key="item.key" class="history-task" :data-history-task="item.key"><div class="history-task-meta"><span class="badge" :class="item.status">{{labels[item.status]}}</span><span>{{item.review.score}} / 5 分 · 作答 {{item.review.review_answer_timestamp?.slice(0,10)||'未收录'}}</span></div><h3>{{item.title}}</h3><p class="history-guide"><strong>中文导读</strong>{{item.guide}}</p><div class="history-next"><strong>下一步</strong><p>{{item.next_action||'进入原工单核对最新处理记录。'}}</p></div><dl><div><dt>订单最终状态</dt><dd>{{orderLabels[item.order.status]||item.order.status}}</dd></div><div><dt>订单合计</dt><dd>{{item.order.total}} {{item.order.currency}}</dd></div><div><dt>负责人</dt><dd>{{item.owner===settings.userId?'当前体验者':item.owner}}</dd></div><div><dt>本地练习期限</dt><dd>{{time(item.due_at)}}</dd></div></dl><details><summary>核对评价原文与订单时间</summary><blockquote lang="pt-BR">{{item.review.content}}</blockquote><p>原始订单号：<code>{{item.order.id}}</code></p><p>评价记录创建：{{item.review.review_creation_date||item.review.created_at}}<br/>客户评价作答：{{item.review.review_answer_timestamp||'源数据未收录'}}<br/>原始时间未转换时区。</p><p>预计送达：{{item.order.estimated_at||'源数据未记录'}}<br/>实际送达：{{item.order.delivered_at||'源数据未记录'}}</p><p>以上为历史订单最终记录，可能与评价当时状态不同。</p></details><button type="button" class="primary" :disabled="busy||disabled" @click="open(item.conv_id)">{{item.status==='resolved'?'查看处理记录':'打开事项并继续处理'}}</button></article></div>
  </div></template><p v-if="current" class="source-note">上方的工单列表就是你的历史练习待办，可继续处理、记录材料与客户结果。完成的工单可在「已解决」中查看。</p>
  <footer><span>练习基于历史事实，当前处理步骤为本地练习安排。</span><a v-if="data.source?.source_url" :href="data.source.source_url" target="_blank" rel="noreferrer">查看 Kaggle 数据来源 ↗</a></footer>
 </template>
</section>
</template>
