const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const app = fs.readFileSync(path.join(__dirname, '../injector_core/web/app.js'), 'utf8');

function browser(fetch) {
  const elements = new Map();
  const timers = [];
  const comparisons = [];
  const element = id => {
    if (!elements.has(id)) elements.set(id, {
      value: '', textContent: '', children: [], addEventListener() {}, focus() {},
      replaceChildren(...children) { this.children = children; }
    });
    return elements.get(id);
  };
  const context = vm.createContext({
    document: {getElementById: element, createElement: () => ({textContent: ''})},
    window: {addEventListener() {}},
    DependencyGraph: class { showComparison(report) { comparisons.push(report); } },
    URLSearchParams,
    TextDecoder,
    setTimeout: callback => timers.push(callback),
    fetch: (url, options) => url === '/api/info' ? new Promise(() => {}) : fetch(url, options)
  });
  vm.runInContext(app, context);
  return {element, timers, comparisons, run: code => vm.runInContext(code, context)};
}

test('a failed status request is retried without starting another job', async () => {
  let requests = 0;
  const page = browser(async url => {
    assert.equal(url, '/api/job');
    requests++;
    if (requests === 2) throw new Error('connection lost');
    return {ok: true, json: async () => requests === 1
      ? {status: 'running', events: []}
      : {status: 'succeeded', events: [], result: {status: 'ready'}}};
  });

  await page.run('planReady = true; poll()');
  await page.timers.shift()();
  assert.equal(page.element('stop').disabled, true);
  assert.equal(page.timers.length, 1);
  await page.timers.shift()();
  assert.equal(page.element('stop').disabled, false);
  assert.equal(page.element('prepare').disabled, false);
  assert.equal(page.timers.length, 0);
  assert.equal(requests, 3);
});

test('IntelliJ results identify the module and main class for IDE confirmation', async () => {
  const page = browser(async url => {
    assert.equal(url, '/api/check');
    return {ok: true, json: async () => ({order: ['main'],
      intellij: {module: 'missing-module', mainClass: 'example.Absent'}})};
  });
  await page.run('checkRequirements()');
  assert.match(page.element('check-result').textContent, /^IDE 확인 필요 .*missing-module.*example\.Absent/);
});

test('registry selection loads the exact path returned by the picker', async () => {
  const registry = 'C:\\registries\\app\\local settings.json';
  const page = browser(async url => {
    assert.equal(url, '/api/project/pick');
    return {ok: true, json: async () => ({project: registry})};
  });
  const selection = await page.run('let loaded; load = remember => { loaded = [selection().registry, remember]; }; pickPath("registry").then(() => loaded)');
  assert.deepEqual(Array.from(selection), [registry, true]);
});

test('manual load saves both paths while startup loads them without saving', async () => {
  const paths = {project: 'C:\\source tree', registry: 'C:\\registries\\local.json'};
  const requests = [];
  const page = browser(async (url, options) => {
    requests.push({url, options});
    return {ok: true, json: async () => ({...paths, profiles: {}})};
  });
  page.element('project').value = paths.project;
  page.element('registry').value = paths.registry;
  await page.run('token = "secret"; targets = () => {}; load()');
  await page.element('load').onclick();
  assert.equal(requests[0].url, '/api/project?' + new URLSearchParams(paths));
  assert.equal(requests[1].url, '/api/project');
  assert.equal(requests[1].options.headers['X-Injector-Token'], 'secret');
  assert.deepEqual(JSON.parse(requests[1].options.body), paths);
});

test('blocked persistence still allows loading the selection read-only', async () => {
  const paths = {project: 'C:\\source', registry: 'C:\\registry.json'};
  const requests = [];
  const page = browser(async (url, options) => {
    requests.push(url);
    return options.method === 'POST'
      ? {ok: false, json: async () => ({error: 'local control token required'})}
      : {ok: true, json: async () => ({...paths, profiles: {}})};
  });
  page.element('project').value = paths.project;
  page.element('registry').value = paths.registry;
  await page.run('targets = () => {}; load(true)');
  assert.deepEqual(requests, ['/api/project', '/api/project?' + new URLSearchParams(paths)]);
  assert.match(page.element('result').textContent, /경로를 불러왔습니다/);
});

test('observation comparison displays both recordings and highlights the reported edge', async () => {
  const before = '{"id":9007199254740992}';
  const after = '{"id":9007199254740993}';
  const edge = {caller:'orders', dependency:'catalog', endpoint:'http'};
  const page = browser(async (url, options) => {
    assert.equal(url, '/api/observations/compare');
    assert.deepEqual(JSON.parse(options.body), {baseline:before, candidate:after});
    return {ok:true, json:async () => ({verdict:'FAIL', profile:'local', edge, baseline:before, candidate:after,
      changes:[{kind:'changed', path:'/target/fields/~1id'}], changeCount:1})};
  });
  const file = text => ({size:text.length, arrayBuffer:async () => new TextEncoder().encode(text)});
  page.element('observation-baseline').files = [file(before)];
  page.element('observation-candidate').files = [file(after)];
  await page.element('observation-compare').onclick();
  assert.equal(page.element('observation-details').hidden, false);
  assert.equal(page.element('observation-after').textContent, after);
  assert.match(page.element('observation-status').textContent, /orders → catalog/);
  assert.match(page.element('observation-changes').children[0].textContent, /~1id/);
  assert.deepEqual(page.comparisons.at(-1).edge, edge);
});
