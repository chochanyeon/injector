const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const app = fs.readFileSync(path.join(__dirname, '../injector_core/web/app.js'), 'utf8');

function browser(fetch) {
  const elements = new Map();
  const timers = [];
  const element = id => {
    if (!elements.has(id)) elements.set(id, {value: '', textContent: '', children: [], addEventListener() {}, focus() {}});
    return elements.get(id);
  };
  const context = vm.createContext({
    document: {getElementById: element},
    window: {addEventListener() {}},
    DependencyGraph: class {},
    setTimeout: callback => timers.push(callback),
    fetch: (url, options) => url === '/api/info' ? new Promise(() => {}) : fetch(url, options)
  });
  vm.runInContext(app, context);
  return {element, timers, run: code => vm.runInContext(code, context)};
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
  const loadedPath = await page.run('let loaded; load = () => { loaded = selection().registry; }; pickPath("registry").then(() => loaded)');
  assert.equal(loadedPath, registry);
});
