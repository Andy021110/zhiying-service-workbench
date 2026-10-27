import {createApp,h} from 'vue'
import TaskMapView from './components/TaskMapView.vue'
import map from './data/task-map.json'
import './styles/task-map-offline.css'
const requested=window.location.hash.slice(1)
createApp({render:()=>h(TaskMapView,{map,standalone:true,initialTask:map.tasks.some(t=>t.id===requested)?requested:'',onNavigate:({view})=>window.open('http://127.0.0.1:5175/#'+view,'_blank','noopener,noreferrer')})}).mount('#map-root')
