class DependencyGraph {
  constructor(root, request) {
    this.panel = root;
    this.request = request;
    for (const name of ['scope', 'status', 'frame', 'viewport', 'columns', 'edges', 'inspector', 'relations', 'direct']) {
      this[name] = root.querySelector('#graph-' + name);
    }
    this.generation = 0;
    this.nodes = new Map();
    this.links = [];
    this.active = null;
    this.scope.addEventListener('change', () => this.refresh());
    root.addEventListener('toggle', () => this.scheduleDraw());
    this.viewport.addEventListener('scroll', () => this.scheduleDraw());
    this.observer = new ResizeObserver(() => this.scheduleDraw());
    this.observer.observe(this.viewport);
    this.observer.observe(this.columns);
  }

  reset() {
    this.generation++;
    this.project = null;
    this.scope.replaceChildren(new Option('전체 앱', ''));
    this.scope.disabled = true;
    this.clear();
    this.status.textContent = '프로젝트를 불러오세요.';
  }

  update(project, profile, apps) {
    const active = this.project === project ? this.scope.value : '';
    this.project = project;
    this.profile = profile;
    this.scope.replaceChildren(new Option('전체 앱', ''), ...apps.map(app => new Option(app, app)));
    this.scope.value = apps.includes(active) ? active : '';
    this.scope.disabled = false;
    return this.refresh();
  }

  clear() {
    this.frame.hidden = this.relations.hidden = true;
    this.columns.replaceChildren();
    this.direct.replaceChildren();
    this.nodes.clear();
    this.links = [];
    this.select(null);
  }

  async refresh() {
    const generation = ++this.generation;
    const query = new URLSearchParams({project: this.project, profile: this.profile});
    if (this.scope.value) query.set('target', this.scope.value);
    this.clear();
    this.status.textContent = '의존성을 읽는 중…';
    try {
      const graph = await this.request('/api/graph?' + query);
      if (generation === this.generation) this.render(graph.steps);
    } catch (error) {
      if (generation === this.generation) this.status.textContent = error.message;
    }
  }

  render(steps) {
    const ranks = new Map();
    const columns = [];
    const parents = new Map();
    let apps = 0;
    // Plans list dependencies first. Reversing gives each dependency all of its callers first.
    for (const step of [...steps].reverse()) {
      const rank = ranks.get(step.node) ?? 0;
      for (const dependency of step.dependencies) {
        ranks.set(dependency, Math.max(rank + 1, ranks.get(dependency) ?? 0));
        if (!parents.has(dependency)) parents.set(dependency, []);
        parents.get(dependency).push(step.node);
        this.links.push({from: step.node, to: dependency});
      }
      if (!columns[rank]) columns[rank] = [];
      columns[rank].push(step);
      if (step.kind === 'application') apps++;
    }
    this.columns.classList.toggle('graph-long-links', this.links.some(({from, to}) =>
      (ranks.get(to) ?? 0) - (ranks.get(from) ?? 0) > 1));
    const positions = new Map();
    for (const [rank, stepsInColumn] of columns.entries()) {
      const column = document.createElement('div');
      column.className = 'graph-column';
      const heading = document.createElement('div');
      heading.className = 'graph-layer';
      heading.textContent = rank ? `의존성 · ${rank}단계` : '진입 노드';
      column.append(heading);
      // Place dependencies near their callers to reduce crossings between columns.
      const groups = new Map();
      for (const step of stepsInColumn) {
        const callers = parents.get(step.node) ?? [];
        const sum = callers.reduce((total, caller) => total + positions.get(caller), 0);
        groups.set(step.node, callers.length ? sum / callers.length : 0);
      }
      stepsInColumn.sort((a, b) => groups.get(a.node) - groups.get(b.node));
      for (const step of stepsInColumn) {
        const node = this.makeNode(step);
        positions.set(step.node, column.children.length - 1);
        this.nodes.set(step.node, {element: node, rank});
        column.append(node);
        const item = document.createElement('li');
        item.textContent = `${step.node} → ${step.dependencies.join(', ') || '없음'}`;
        this.direct.append(item);
      }
      this.columns.append(column);
    }
    this.frame.hidden = this.relations.hidden = steps.length === 0;
    this.status.textContent = steps.length
      ? `앱 ${apps}개 · 인프라 ${steps.length - apps}개. 노드를 선택하면 연결을 강조합니다.`
      : '표시할 앱이 없습니다.';
    this.viewport.scrollTo(0, 0);
    this.scheduleDraw();
  }

  makeNode(step) {
    const application = step.kind === 'application';
    const element = document.createElement('button');
    element.type = 'button';
    element.setAttribute('aria-pressed', 'false');
    element.className = 'graph-node';
    element.dataset.kind = step.kind;
    const name = document.createElement('strong');
    name.textContent = step.node;
    const caption = document.createElement('span');
    caption.textContent = `${application ? '앱' : '인프라'} · ${step.variant} · ${step.runner}`;
    element.addEventListener('click', () => this.select(this.active === step.node ? null : step.node));
    element.append(name, caption);
    return element;
  }

  select(id) {
    this.active = id;
    const incoming = [], outgoing = [];
    for (const {from, to} of this.links) {
      if (to === id) incoming.push(from);
      if (from === id) outgoing.push(to);
    }
    const connected = new Set([id, ...incoming, ...outgoing]);
    for (const [node, {element}] of this.nodes) {
      element.setAttribute('aria-pressed', String(node === id));
      element.classList.toggle('graph-muted', id !== null && !connected.has(node));
    }
    this.inspector.hidden = id === null;
    this.inspector.replaceChildren();
    if (id !== null) {
      for (const value of [id, `의존 대상: ${outgoing.join(', ') || '없음'}`,
                           `사용하는 노드: ${incoming.join(', ') || '없음'}`]) {
        const item = document.createElement('div');
        item.textContent = value;
        this.inspector.append(item);
      }
    }
    this.scheduleDraw();
  }

  scheduleDraw() {
    if (this.animation !== undefined) return;
    this.animation = requestAnimationFrame(() => {
      this.animation = undefined;
      this.draw();
    });
  }

  draw() {
    if (!this.panel.open || this.frame.hidden) return;
    const width = this.viewport.clientWidth, height = this.viewport.clientHeight;
    const scale = window.devicePixelRatio || 1;
    this.edges.width = Math.round(width * scale);
    this.edges.height = Math.round(height * scale);
    this.edges.style.width = `${width}px`;
    this.edges.style.height = `${height}px`;
    const context = this.edges.getContext('2d');
    if (!context) return;
    context.scale(scale, scale);
    const origin = this.viewport.getBoundingClientRect();
    const top = this.columns.getBoundingClientRect().top - origin.top;
    const box = new Map([...this.nodes].map(([id, {element}]) => [id, element.getBoundingClientRect()]));
    const isActive = ({from, to}) => from === this.active || to === this.active;
    const ports = (node, peer) => {
      const groups = new Map();
      for (const link of this.links) {
        const key = link[node];
        if (!groups.has(key)) groups.set(key, []);
        groups.get(key).push(link);
      }
      const offsets = new Map();
      for (const [id, links] of groups) {
        links.sort((a, b) => box.get(a[peer]).top - box.get(b[peer]).top);
        const step = Math.min(9, (box.get(id).height - 14) / links.length);
        links.forEach((link, index) => offsets.set(link, (index - (links.length - 1) / 2) * step));
      }
      return offsets;
    };
    const outputs = ports('from', 'to'), inputs = ports('to', 'from');
    const lanes = new Map();
    for (const link of this.links) {
      if (this.nodes.get(link.to).rank - this.nodes.get(link.from).rank > 1) {
        lanes.set(link, top + 12 + (lanes.size % 5) * 8);
      }
    }
    const ordered = [...this.links].sort((a, b) => Number(isActive(a)) - Number(isActive(b)));
    for (const link of ordered) {
      const {from, to} = link;
      context.strokeStyle = context.fillStyle = isActive(link) ? '#12644f' : this.active ? '#cad7d0' : '#587a6b';
      context.lineWidth = isActive(link) ? 2.5 : 1.5;
      const source = box.get(from), target = box.get(to);
      const start = source.right - origin.left;
      const end = target.left - origin.left;
      const y1 = (source.top + source.bottom) / 2 - origin.top + outputs.get(link);
      const y2 = (target.top + target.bottom) / 2 - origin.top + inputs.get(link);
      context.beginPath();
      context.moveTo(start, y1);
      if (lanes.has(link)) {
        const lane = lanes.get(link);
        context.bezierCurveTo(start + 22, y1, start + 10, lane, start + 30, lane);
        context.lineTo(end - 30, lane);
        context.bezierCurveTo(end - 10, lane, end - 22, y2, end - 6, y2);
      } else {
        const middle = (start + end) / 2;
        context.bezierCurveTo(middle, y1, middle, y2, end - 6, y2);
      }
      context.stroke();
      context.beginPath();
      context.moveTo(end - 1, y2);
      context.lineTo(end - 8, y2 - 4);
      context.lineTo(end - 8, y2 + 4);
      context.fill();
    }
  }
}
