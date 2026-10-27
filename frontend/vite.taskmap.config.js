import {defineConfig} from 'vite'
import vue from '@vitejs/plugin-vue'
export default defineConfig({plugins:[vue()],base:'./',build:{outDir:'dist-task-map',cssCodeSplit:false,rollupOptions:{input:'task-map.html',output:{inlineDynamicImports:true}}}})
