/* Dependency-free, read-only architecture walkthrough for the public portfolio. */
(() => {
  'use strict';
  const ns = 'http://www.w3.org/2000/svg';
  const el = (tag, cls, text) => {
    const item = document.createElement(tag);
    if (cls) item.className = cls;
    if (text !== undefined) item.textContent = text;
    return item;
  };
  async function mount(root) {
    const response = await fetch(root.dataset.architecture);
    if (!response.ok) throw new Error('Architecture data unavailable');
    const data = await response.json();
    const nodes = new Map(data.nodes.map(node => [node.id, node]));
    const ui = el('div', 'ax-explorer');
    let scenario = data.scenarios[0], step = 0, selected = scenario.steps[0].node;
    let timer = null, frame = 0;
    const id = root.id;
    const controls = el('div', 'ax-controls');
    const field = el('div', 'ax-field');
    const label = el('label', '', '选择业务场景');
    label.htmlFor = id + '-scenario';
    const select = el('select'); select.id = label.htmlFor;
    for (const item of data.scenarios) {
      const option = el('option', '', item.title); option.value = item.id; select.append(option);
    }
    field.append(label, select);
    const transport = el('div', 'ax-transport');
    const previous = el('button', '', '上一步'), play = el('button', '', '自动播放'), next = el('button', '', '下一步');
    for (const button of [previous, play, next]) button.type = 'button';
    play.setAttribute('aria-pressed', 'false');
    transport.append(previous, play, next); controls.append(field, transport);
    const question = el('p', 'ax-question');
    const evidence = el('div', 'ax-evidence');
    const status = el('p', 'ax-status'); status.setAttribute('aria-live', 'polite'); status.setAttribute('aria-atomic', 'true');
    const body = el('div', 'ax-body');
    const compact = window.matchMedia('(max-width: 680px)');
    const graph = el('div', 'ax-graph');
    const legend = el('p', 'ax-legend', '数字表示讲解顺序；高亮表示本场景的主路径。点击任意模块查看职责。');
    const board = el('div', 'ax-board');
    const svg = document.createElementNS(ns, 'svg');
    svg.classList.add('ax-wires'); svg.setAttribute('aria-hidden', 'true');
    const defs = document.createElementNS(ns, 'defs');
    const marker = document.createElementNS(ns, 'marker');
    marker.id = id + '-arrow'; marker.setAttribute('viewBox', '0 0 8 8');
    marker.setAttribute('refX', '7'); marker.setAttribute('refY', '4');
    marker.setAttribute('markerWidth', '5'); marker.setAttribute('markerHeight', '5'); marker.setAttribute('orient', 'auto');
    const tip = document.createElementNS(ns, 'path'); tip.setAttribute('d', 'M1 1 L7 4 L1 7');
    tip.classList.add('ax-arrow'); marker.append(tip); defs.append(marker); svg.append(defs);
    const lanes = el('div', 'ax-lanes');
    const buttons = new Map();
    for (const [laneIndex, lane] of data.lanes.entries()) {
      const group = el('div', 'ax-lane');
      const heading = el('h4', '', lane);
      const list = el('div', 'ax-module-list');
      for (const node of data.nodes.filter(node => node.lane === laneIndex)) {
        const button = el('button', 'ax-node'); button.type = 'button';
        button.dataset.node = node.id; button.setAttribute('aria-pressed', 'false');
        const number = el('span', 'ax-number'); number.setAttribute('aria-hidden', 'true');
        button.append(number, el('b', '', node.title), el('small', '', node.subtitle));
        button.addEventListener('click', () => {
          stop(); selected = node.id;
          const index = scenario.steps.findIndex(item => item.node === node.id);
          if (index !== -1) step = index;
          render();
          if (compact.matches) {
            details.querySelector('h3').focus({preventScroll: true});
            details.scrollIntoView({block: 'start', behavior: 'auto'});
          }
        });
        buttons.set(node.id, button); list.append(button);
      }
      group.append(heading, list); lanes.append(group);
    }
    board.append(svg, lanes); graph.append(legend, board);
    const details = el('div', 'ax-details'); details.setAttribute('role', 'region');
    details.setAttribute('aria-label', '当前模块详情');
    body.append(graph, details); ui.append(controls, question, evidence, status, body);
    root.replaceChildren(ui);
    function stop() {
      if (timer !== null) clearInterval(timer);
      timer = null; play.textContent = '自动播放'; play.setAttribute('aria-pressed', 'false');
    }
    function draw() {
      svg.querySelectorAll('.ax-edge').forEach(path => path.remove());
      if (window.matchMedia('(max-width: 680px)').matches) return;
      const box = board.getBoundingClientRect();
      svg.setAttribute('viewBox', `0 0 ${box.width} ${box.height}`);
      const active = new Set(scenario.steps.map(item => item.node));
      for (const [from, to] of data.edges) {
        if (!active.has(from) || !active.has(to)) continue;
        const a = buttons.get(from).getBoundingClientRect(), b = buttons.get(to).getBoundingClientRect();
        const sameLane = nodes.get(from).lane === nodes.get(to).lane;
        let d;
        if (sameLane) {
          const x = (a.left + a.right) / 2 - box.left;
          const start = a.bottom - box.top + 2, end = b.top - box.top - 3;
          if (end - start > 45) {
            const edge = a.right - box.left + 10;
            const y1 = (a.top + a.bottom) / 2 - box.top, y2 = (b.top + b.bottom) / 2 - box.top;
            d = `M${a.right-box.left+2},${y1} L${edge},${y1} L${edge},${y2} L${b.right-box.left+3},${y2}`;
          } else d = `M${x},${start} L${x},${end}`;
        } else if (Math.abs(nodes.get(from).lane - nodes.get(to).lane) > 1) {
          const x1 = (a.left+a.right)/2-box.left, x2 = (b.left+b.right)/2-box.left;
          const y = Math.max(a.bottom,b.bottom)-box.top+12;
          d = `M${x1},${a.bottom-box.top+2} L${x1},${y} L${x2},${y} L${x2},${b.bottom-box.top+3}`;
        } else {
          const x1 = a.right - box.left + 2, y1 = (a.top + a.bottom) / 2 - box.top;
          const x2 = b.left - box.left - 3, y2 = (b.top + b.bottom) / 2 - box.top;
          const mid = (x1 + x2) / 2;
          d = `M${x1},${y1} C${mid},${y1} ${mid},${y2} ${x2},${y2}`;
        }
        const path = document.createElementNS(ns, 'path');
        path.classList.add('ax-edge'); path.setAttribute('d', d);
        path.setAttribute('marker-end', `url(#${id}-arrow)`); svg.append(path);
      }
    }
    function scheduleDraw() { cancelAnimationFrame(frame); frame = requestAnimationFrame(draw); }
    function render() {
      const current = scenario.steps[step];
      question.textContent = scenario.question;
      evidence.replaceChildren(el('span', 'ax-kind', scenario.kind), el('span', '', scenario.evidence));
      const evidenceLink = el('a', '', '查看依据'); evidenceLink.href = scenario.evidenceUrl;
      evidenceLink.target = '_blank'; evidenceLink.rel = 'noopener'; evidence.append(evidenceLink);
      status.textContent = `第 ${step + 1} / ${scenario.steps.length} 步 · ${nodes.get(current.node).title}：${current.note}`;
      previous.disabled = step === 0; next.disabled = step === scenario.steps.length - 1;
      for (const [nodeId, button] of buttons) {
        const index = scenario.steps.findIndex(item => item.node === nodeId);
        button.classList.toggle('ax-on-path', index !== -1);
        button.classList.toggle('ax-current', nodeId === current.node);
        button.setAttribute('aria-pressed', String(nodeId === selected));
        button.querySelector('.ax-number').textContent = index !== -1 ? index + 1 : '·';
        button.setAttribute('aria-label', nodes.get(nodeId).title + (index === -1 ? '，当前主路径未展开' : `，路径第 ${index + 1} 步`));
      }
      const node = nodes.get(selected);
      const inPath = scenario.steps.some(item => item.node === selected);
      details.replaceChildren(el('p', 'ax-detail-state', inPath ? '当前主路径中的模块' : '当前主路径未展开此模块'), el('h3', '', node.title), el('p', 'ax-description', node.description));
      details.querySelector('h3').tabIndex = -1;
      const dl = el('dl');
      for (const [term, value] of [['输入', node.input], ['输出', node.output], ['边界', node.boundary]]) {
        const row = el('div'); row.append(el('dt', '', term), el('dd', '', value)); dl.append(row);
      }
      details.append(dl, el('h4', '', '对应实现'));
      const files = el('ul', 'ax-files');
      for (const file of node.files) {
        const li = el('li'), a = el('a', '', file.split('/').pop());
        a.href = data.repo + '/blob/main/' + file; a.target = '_blank'; a.rel = 'noopener'; a.title = file;
        li.append(a); files.append(li);
      }
      const back = el('button', 'ax-back', '返回模块图'); back.type = 'button';
      back.addEventListener('click', () => {
        const button = buttons.get(selected);
        button.focus({preventScroll: true}); button.scrollIntoView({block: 'center', behavior: 'auto'});
      });
      details.append(files, back); scheduleDraw();
    }
    select.addEventListener('change', () => {
      stop(); scenario = data.scenarios.find(item => item.id === select.value);
      step = 0; selected = scenario.steps[0].node; render();
    });
    previous.addEventListener('click', () => { stop(); step = Math.max(0, step - 1); selected = scenario.steps[step].node; render(); });
    next.addEventListener('click', () => { stop(); step = Math.min(scenario.steps.length - 1, step + 1); selected = scenario.steps[step].node; render(); });
    play.addEventListener('click', () => {
      if (timer !== null) { stop(); return; }
      if (step === scenario.steps.length - 1) step = 0;
      selected = scenario.steps[step].node; render();
      play.textContent = '暂停'; play.setAttribute('aria-pressed', 'true');
      timer = setInterval(() => {
        step++; selected = scenario.steps[step].node; render();
        if (step === scenario.steps.length - 1) stop();
      }, 2400);
    });
    document.addEventListener('visibilitychange', () => { if (document.hidden) stop(); });
    function arrange() {
      if (compact.matches) body.prepend(details);
      else body.append(details);
      scheduleDraw();
    }
    compact.addEventListener('change', arrange); arrange();
    const observer = new ResizeObserver(scheduleDraw); observer.observe(board);
    render();
  }
  document.querySelectorAll('[data-architecture]').forEach(root => {
    mount(root).catch(() => {
      const note = el('p', 'ax-fallback', '交互图暂未加载，可先查看静态架构说明；刷新页面后重试。');
      root.prepend(note);
    });
  });
})();
