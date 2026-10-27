<script setup>
defineProps({ name: { type: String, default: 'sparkles' }, size: { type: [Number, String], default: 20 } })
const paths = {
  sparkles: 'm12 3 2.3 6.7L21 12l-6.7 2.3L12 21l-2.3-6.7L3 12l6.7-2.3L12 3Z M20 2v4 M18 4h4',
  plus: 'M12 5v14 M5 12h14',
  message: 'M21 11.5a8.5 8.5 0 0 1-8.5 8.5H4l-2 2V11.5A8.5 8.5 0 0 1 10.5 3h2a8.5 8.5 0 0 1 8.5 8.5Z M7 9h10 M7 13h7',
  book: 'M3 4h6a4 4 0 0 1 3 1.5A4 4 0 0 1 15 4h6v16h-6a4 4 0 0 0-3 1.5A4 4 0 0 0 9 20H3V4Z M12 6v15',
  chart: 'M4 4v16h16 M8 15v-4 M12 15V7 M16 15v-6',
  activity: 'M3 12h4l3-7 4 14 3-7h4',
  settings: 'M9 3h6l1 3 3 1 2 5-2 5-3 1-1 3H9l-1-3-3-1-2-5 2-5 3-1 1-3Z M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z',
  database: 'M20 6c0 2-3.6 3-8 3s-8-1-8-3 3.6-3 8-3 8 1 8 3Z M4 6v12c0 2 3.6 3 8 3s8-1 8-3V6 M4 12c0 2 3.6 3 8 3s8-1 8-3',
  arrow: 'M12 19V5 M6 11l6-6 6 6',
  arrowRight: 'M5 12h14 M13 6l6 6-6 6',
  close: 'M6 6l12 12 M6 18 18 6',
  search: 'M17 10a7 7 0 1 1-14 0 7 7 0 0 1 14 0Z M15 15l6 6',
  shield: 'm12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6l8-3Z m-4 9 3 3 5-6',
  layers: 'm12 3 10 5-10 5L2 8l10-5Z M2 12l10 5 10-5 M2 16l10 5 10-5',
  menu: 'M4 6h16 M4 12h16 M4 18h16',
  chevron: 'm9 5 7 7-7 7',
  refresh: 'M20 9a8 8 0 1 0 0 7 M20 3v6h-6',
  file: 'M14 3H5v18h14V8l-5-5Z M14 3v5h5 M8 12h8 M8 16h6',
  upload: 'M12 16V3 M7 8l5-5 5 5 M4 16v5h16v-5',
  check: 'm5 12 4 4L19 6',
  code: 'm8 5-6 7 6 7 M16 5l6 7-6 7 M14 3l-4 18',
  logout: 'M9 4H4v16h5 M11 12h10 M17 8l4 4-4 4',
  headset: 'M4 14v-3a8 8 0 0 1 16 0v3 M4 12H2v7h4v-7H4Z M20 12h2v7h-4v-7h2Z M20 19c0 2-4 3-7 3',
  clock: 'M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z M12 7v5l3 2',
}
</script>
<template><svg :width="size" :height="size" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.65" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" class="ui-icon"><path :d="paths[name] || paths.sparkles" /></svg></template>
<style scoped>.ui-icon{display:inline-block;flex-shrink:0;vertical-align:middle}</style>
