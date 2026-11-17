class DependencyGraph {
  constructor(root, request) {
    this.request = request;
    for (const name of ['scope', 'status', 'frame', 'viewport', 'columns', 'edges', 'relations', 'direct']) {
      this[name] = root.querySelector('#graph-' + name);
    }
    this.generation = 0;
    this.nodes = new Map();
    this.links = [];
    this.scope.addEventListener('change', () => this.refresh());
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
    let apps = 0;
    // Plans list dependencies first. Reversing gives each dependency all of its callers first.
    for (const step of [...steps].reverse()) {
      const rank = ranks.get(step.node) ?? 0;
      for (const dependency of step.dependencies) {
        ranks.set(dependency, Math.max(rank + 1, ranks.get(dependency) ?? 0));
        this.links.push({from: step.node, to: dependency});
      }
      if (!columns[rank]) columns[rank] = [];
      columns[rank].push(step);
      if (step.kind === 'application') apps++;
    }
    this.columns.classList.toggle('graph-long-links', this.links.some(({from, to}) =>
      (ranks.get(to) ?? 0) - (ranks.get(from) ?? 0) > 1));
    for (const [rank, stepsInColumn] of columns.entries()) {
      const column = document.createElement('div');
      column.className = 'graph-column';
      for (const step of stepsInColumn) {
        const node = this.makeNode(step);
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
      ? `앱 ${apps}개 · 인프라 ${steps.length - apps}개 · 화살표는 의존성을 향합니다.`
      : '표시할 앱이 없습니다.';
    this.viewport.scrollTo(0, 0);
    this.scheduleDraw();
  }

  makeNode(step) {
    const application = step.kind === 'application';
    const focusable = application && !this.scope.value;
    const element = document.createElement(focusable ? 'button' : 'div');
    element.className = 'graph-node';
    element.dataset.kind = step.kind;
    if (step.node === this.scope.value) element.classList.add('graph-selected');
    const name = document.createElement('strong');
    name.textContent = step.node;
    const caption = document.createElement('span');
    caption.textContent = `${application ? '앱' : '인프라'} · ${step.variant} · ${step.runner}`;
    if (focusable) {
      element.type = 'button';
      element.setAttribute('aria-label', `${step.node} 의존성 보기`);
      element.addEventListener('click', () => {
        this.scope.value = step.node;
        this.scope.focus();
        this.refresh();
      });
    }
    element.append(name, caption);
    return element;
  }

  scheduleDraw() {
    if (this.animation !== undefined) return;
    this.animation = requestAnimationFrame(() => {
      this.animation = undefined;
      this.draw();
    });
  }

  draw() {
    if (this.frame.hidden) return;
    const width = this.viewport.clientWidth, height = this.viewport.clientHeight;
    const scale = window.devicePixelRatio || 1;
    this.edges.width = Math.round(width * scale);
    this.edges.height = Math.round(height * scale);
    this.edges.style.width = `${width}px`;
    this.edges.style.height = `${height}px`;
    const context = this.edges.getContext('2d');
    if (!context) return;
    context.scale(scale, scale);
    context.strokeStyle = context.fillStyle = '#557b6a';
    context.lineWidth = 1.6;
    const origin = this.viewport.getBoundingClientRect();
    const top = this.columns.getBoundingClientRect().top - origin.top;
    const box = new Map([...this.nodes].map(([id, {element}]) => [id, element.getBoundingClientRect()]));
    let longLink = 0;
    for (const {from, to} of this.links) {
      const source = box.get(from), target = box.get(to);
      const start = source.right - origin.left;
      const end = target.left - origin.left;
      const y1 = (source.top + source.bottom) / 2 - origin.top;
      const y2 = (target.top + target.bottom) / 2 - origin.top;
      context.beginPath();
      context.moveTo(start, y1);
      if (this.nodes.get(to).rank - this.nodes.get(from).rank > 1) {
        const lane = top + 12 + (longLink++ % 5) * 8;
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
