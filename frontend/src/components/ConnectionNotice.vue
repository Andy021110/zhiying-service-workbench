<script setup>
defineProps({state:String,checking:Boolean,recovered:Boolean,readError:Object,busy:Boolean})
defineEmits(['check','reload'])
</script><template>
<section v-if="state==='unavailable'" class="connection-notice" role="status" aria-live="polite"><div><strong>暂时无法连接本地服务</strong><p>正在自动重新连接。可继续保留当前填写内容；提交操作不会自动重试。</p></div><button type="button" class="secondary" :disabled="checking" @click="$emit('check')">{{checking?'正在检查连接…':'重新连接'}}</button></section>
<section v-else-if="readError" class="connection-notice" role="status" aria-live="polite"><div><strong>部分内容暂时未能读取</strong><p>{{readError.message}}</p></div><button type="button" class="secondary" :disabled="busy" @click="$emit('reload')">重新读取当前页面</button></section>
<section v-else-if="recovered" class="connection-notice recovered" role="status" aria-live="polite"><strong>本地服务连接已恢复</strong><span>如有提交结果待确认，请先核对对应记录。</span></section>
</template><style scoped>
.connection-notice{display:flex;align-items:center;justify-content:space-between;gap:18px;margin:0;padding:16px 28px;background:#fff8e9;border-bottom:1px solid #eadbb7;color:#725526;font-size:13px;line-height:1.7}.connection-notice strong{font-size:14px}.connection-notice p{margin:3px 0 0}.connection-notice button{flex-shrink:0;min-height:40px}.connection-notice.recovered{justify-content:flex-start;background:#eff7f1;color:#336347;border-color:#d6e7d9}@media(max-width:650px){.connection-notice{padding:14px 16px;align-items:flex-start;flex-wrap:wrap;gap:10px}.connection-notice button{min-height:44px}.connection-notice.recovered span{display:block}}
</style>
