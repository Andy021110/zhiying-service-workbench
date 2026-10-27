<script setup>
import {ref,watch} from 'vue'
import {workbenchRequest} from '../lib/backends'
import taskMap from '../data/task-map.json'
import DemoProject from './DemoProject.vue'
import '../styles/demo-cases.css'
const props=defineProps({settings:Object,disabled:Boolean}),emit=defineEmits(['open','exit'])
const catalog=ref(null),busy=ref(false),error=ref('')
const statusLabels={open:'待处理',pending:'待跟进',resolved:'已解决'}
const taskName=id=>taskMap.tasks.find(t=>t.id===id)?.title||id
const api=(p,m='GET',b)=>workbenchRequest(props.settings,p,m,b)
let generation=0
async function load(){const n=++generation;busy.value=true;error.value='';try{const data=await api('/demos/ensure','POST',{user_id:props.settings.userId});if(n===generation)catalog.value=data}catch(e){if(n===generation)error.value=e.message}finally{if(n===generation)busy.value=false}}
watch(()=>props.settings.userId,load,{immediate:true})
function open(c,id=c.conv_id){emit('open',{workspaceId:catalog.value.workspace_id,convId:id})}
async function newRound(c){if(busy.value||props.disabled)return;busy.value=true;error.value='';try{catalog.value=await api('/demos/'+c.id+'/new-round','POST',{user_id:props.settings.userId,expected_generation:c.generation});open(catalog.value.cases.find(item=>item.id===c.id))}catch(e){error.value=e.message}finally{busy.value=false}}
</script>
<template>
<section class="page demo-hub" :aria-busy="busy">
  <header class="demo-heading"><div><span class="demo-eyebrow">先浏览完整示例，再继续处理</span><h1>一个项目，看清业务全过程</h1><p>项目、进展、待办、审批和来源已经关联。可以直接浏览，也可以进入原事项，沿着已有背景继续操作。</p></div><button v-if="settings.workspaceId?.startsWith('demo-space-')" class="secondary" :disabled="busy||disabled" @click="emit('exit')">返回之前的工作范围</button></header>
  <div class="demo-scope"><strong>3 个合成案例 · 每位体验者独立保存</strong><span>预置对话、合成订单和演示规则已标识；练习记录保存在独立空间。</span></div>
  <p v-if="error" role="alert" class="form-error">{{error}} <button class="text-button" @click="load">重新加载案例</button></p>
  <p v-if="busy&&!catalog" role="status">正在准备完整案例…</p>
  <DemoProject v-if="catalog" :settings="settings" :workspace-id="catalog.workspace_id" :disabled="disabled||busy" @open="emit('open',$event)"/>
  <h2 v-if="catalog" class="demo-case-section-title">单个业务案例</h2><p v-if="catalog" class="demo-case-section-note">也可以从一条客户事项开始试用；新建一轮会保留原有对话与审批记录。</p>
  <div v-if="catalog" class="demo-grid">
    <article v-for="(c,index) in catalog.cases" :key="c.id" class="demo-card" :data-demo="c.id">
      <div class="demo-card-top"><span>案例 0{{index+1}}</span><span>第 {{c.generation}} 轮 · {{c.message_count}} 条消息</span></div>
      <h2>{{c.title}}</h2><span class="demo-current-state">当前：{{statusLabels[c.status]||c.status}}</span><p class="demo-goal">{{c.goal}}</p>
      <dl><dt>事情的起因</dt><dd>{{c.background}}</dd><dt>预置的处理阶段</dt><dd>{{c.progress}}</dd><dt>接下来可以做</dt><dd>{{c.next_step}}</dd></dl>
      <details><summary>查看流程与对应任务</summary><ol class="demo-milestones"><li v-for="step in c.milestones" :key="step">{{step}}</li></ol><p class="source-note">以下是相关用户任务；此案例呈现本地演示部分。</p><ul class="demo-task-list"><li v-for="id in c.tasks" :key="id">{{id}} · {{taskName(id)}}</li></ul></details>
      <div class="demo-card-actions"><button class="primary" :disabled="busy||disabled" @click="open(c)">查看并继续对话</button><button class="text-button" :disabled="busy||disabled" @click="newRound(c)">新建一轮体验</button></div>
      <p class="demo-retention">“继续”打开上次记录；新一轮保留旧记录。</p>
      <details v-if="c.history.length" class="demo-previous"><summary>之前的体验记录 · {{c.history.length}}</summary><button v-for="h in c.history" :key="h.id" class="text-button" :disabled="busy||disabled" @click="open(c,h.id)">{{h.title}}</button></details>
    </article>
  </div>
</section>
</template>
