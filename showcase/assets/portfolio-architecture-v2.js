'use strict';
(() => {
  document.querySelectorAll('.architecture-section[data-architecture]').forEach(section => {
    const frame = section.querySelector('iframe');
    const buttons = [...section.querySelectorAll('button[data-architecture-src]')];
    const open = section.querySelector('[data-architecture-open]');
    const spec = section.querySelector('[data-architecture-spec]');
    const loading = section.querySelector('[role="status"]');
    if (!frame || !buttons.length || !open || !spec) return;
    let selected = buttons.find(button => button.getAttribute('aria-pressed') === 'true') || buttons[0];
    let loaded = '';
    const theme = () => document.documentElement.dataset.theme || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
    function update() {
      const url = new URL(selected.dataset.architectureSrc, location.href);
      url.searchParams.set('theme', theme());
      open.href = url.href; spec.href = selected.dataset.architectureSpec;
      frame.title = selected.dataset.architectureTitle + '：可交互架构图';
      url.searchParams.set('present', '1');
      if (loaded !== url.href) {
        if (loading) loading.hidden = false;
        frame.src = url.href; loaded = url.href;
      }
    }
    frame.addEventListener('load', () => { if (loading) loading.hidden = true; });
    buttons.forEach(button => button.addEventListener('click', () => {
      selected = button;
      buttons.forEach(item => item.setAttribute('aria-pressed', String(item === button)));
      update();
    }));
    document.getElementById('appearance')?.addEventListener('change', update);
    matchMedia('(prefers-color-scheme: dark)').addEventListener('change', update);
    update();
  });
})();
