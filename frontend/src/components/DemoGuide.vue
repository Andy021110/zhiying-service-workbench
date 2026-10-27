<script setup>
import {ref,watch} from 'vue'
import {workbenchRequest} from '../lib/backends'
const props=defineProps({conversation:Object,settings:Object,disabled:Boolean}),emit=defineEmits(['prompt','examples','exit','policy'])
const promptsOpen=ref(window.matchMedia('(min-width: 801px)').matches)
const guide=ref(null),error=ref('');let generation=0
watch(()=>[props.conversation.id,props.settings.userId,props.settings.workspaceId],async()=>{const n=++generation;guide.value=null;error.value='';try{const data=await workbenchRequest(props.settings,'/demos/conversations/'+props.conversation.id+'?user_id='+encodeURIComponent(props.settings.userId));if(n===generation)guide.value=data}catch(e){if(n===generation)error.value=e.message}},{immediate:true})
</script>
<template>
<section class="demo-guide" aria-label="演示案例背景">
  <header><strong>演示案例 · 沿用已有背景继续处理</strong><div><button class="text-button" :disabled="disabled" @click="emit('examples')">返回案例目录</button><button class="text-button" :disabled="disabled" @click="emit('exit')">退出演示</button></div></header>
  <p v-if="error" role="alert">{{error}}</p>
  <template v-if="guide"><details><summary>客户背景、完整流程与下一步</summary><p>{{guide.seed_note}}</p><template v-if="guide.template"><p><strong>背景：</strong>{{guide.template.background}}</p><ol class="demo-milestones"><li v-for="s in guide.template.milestones" :key="s">{{s}}</li></ol><p><strong>下一步：</strong>{{guide.template.next_step}}</p></template><button v-for="p in guide.policies" :key="p.id" class="text-button" :disabled="disabled" @click="emit('policy',p.id)">核对 {{p.title}} · v{{p.version}}</button></details>
  <details v-if="guide.template" class="demo-prompts-menu" :open="promptsOpen"><summary>试着接着问 · {{guide.template.prompts.length}} 个建议</summary><div class="demo-prompts"><button v-for="p in guide.template.prompts" :key="p" type="button" :disabled="disabled" @click="emit('prompt',p)">{{p}}</button><small>点击填入输入框，由你决定是否发送。</small></div></details></template>
</section>
</template>
