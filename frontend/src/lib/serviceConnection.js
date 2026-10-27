import {ref,watch,onMounted,onUnmounted} from 'vue'
import {backendMeta} from './backends'
import {REQUEST_EVENT} from './requestErrors'
export function useServiceConnection(settings,{onRecovered=()=>{}}={}){
  const online=ref(false),state=ref('checking'),checking=ref(false),recovered=ref(false)
  let timer=null,toastTimer=null,controller=null,epoch=0,failures=0,stopped=false
  const base=()=>backendMeta(settings.backend,settings).baseUrl.replace(/\/+$/,'')
  function schedule(){clearTimeout(timer);if(!stopped)timer=setTimeout(check,[1500,3000,6000,10000,15000][Math.min(failures-1,4)]||1500)}
  async function check(){
    if(checking.value||stopped)return
    checking.value=true;const token=epoch,wasUnavailable=state.value==='unavailable';const requestController=new AbortController();controller=requestController;const timeout=setTimeout(()=>requestController.abort(),3500)
    try{const response=await fetch(base()+'/health',{signal:requestController.signal,cache:'no-store'});if(!response.ok)throw Error();const data=await response.json();if(data.status!=='ok')throw Error();if(token!==epoch)return
      clearTimeout(timer);failures=0;online.value=true;state.value='online'
      if(wasUnavailable){recovered.value=true;clearTimeout(toastTimer);toastTimer=setTimeout(()=>{recovered.value=false},4000);onRecovered()}
    }catch{if(token!==epoch)return;online.value=false;state.value='unavailable';failures++;schedule()}
    finally{clearTimeout(timeout);if(token===epoch)checking.value=false}
  }
  function onRequest(event){const e=event.detail;if(e?.base!==base())return
    if(e.type==='failure'&&e.error?.transient)check()
    if(e.type==='success'&&e.path==='/health'&&state.value==='checking'){online.value=true;state.value='online'}
  }
  function onFocus(){if(state.value==='unavailable')check()}
  watch(()=>[settings.backend,settings.endpoints?.[settings.backend]],()=>{epoch++;controller?.abort();clearTimeout(timer);clearTimeout(toastTimer);checking.value=false;online.value=false;state.value='checking';recovered.value=false;failures=0;check()})
  onMounted(()=>{window.addEventListener(REQUEST_EVENT,onRequest);window.addEventListener('online',onFocus);window.addEventListener('focus',onFocus);check()})
  onUnmounted(()=>{stopped=true;epoch++;controller?.abort();clearTimeout(timer);clearTimeout(toastTimer);window.removeEventListener(REQUEST_EVENT,onRequest);window.removeEventListener('online',onFocus);window.removeEventListener('focus',onFocus)})
  return {online,state,checking,recovered,check}
}
