const $ = id => document.getElementById(id);
let token, catalog, busy = false, timer;
let editor, completion, editorBusy = false, pickerBusy = false;
let variants = {}, planReady = false, planRequest = 0, loadRequest = 0;
let checking = false, suiteChecking = false, activeAction, selectionWarning = '';
let historyRequest = 0, savedSuite;
let serverStopped = false;
const phases = {starting:'시작 중', waiting:'준비 확인 중', ready:'준비 완료', 'debug-ready':'Debug 가능', stopping:'종료 중'};
const runners = {process:'로컬 프로세스', compose:'Docker Compose', intellij:'IntelliJ', external:'외부 서비스'};
const sides = {baseline:'기준', candidate:'후보'};
const verdicts = {PASS:'통과', FAIL:'실패', INCONCLUSIVE:'판정 보류', NOT_RUN:'미실행'};
const changeTypes = {added:'추가', removed:'삭제', changed:'변경'};
async function api(path, body) {
  const endpoint = path.split('?')[0];
  let response, result;
  try {
    response = await fetch(path, body === undefined ? {} : {method:'POST', headers:{'Content-Type':'application/json', 'X-Injector-Token':token}, body:JSON.stringify(body)});
  } catch {
    connection(false);
    throw new Error(`Injector 서버에 연결할 수 없습니다 (${endpoint}).`);
  }
  try {
    result = await response.json();
  } catch {
    throw new Error(`Injector 서버 응답이 비어 있거나 읽을 수 없습니다 (${endpoint}, HTTP ${response.status}).`);
  }
  if (!result || typeof result !== 'object' || Array.isArray(result)) {
    throw new Error(`Injector 서버 응답 형식이 올바르지 않습니다 (${endpoint}).`);
  }
  connection(true);
  if (!response.ok) throw new Error(result.error || '요청에 실패했습니다.');
  return result;
}
const dependencyGraph = new DependencyGraph($('dependency-graph'), api);
const registryDialog = $('registry-editor');
function selection() {
  return {project:$('project').value.trim(), registry:$('registry').value.trim()};
}
function feedback(id, message, state = '') {
  $(id).textContent = message;
  $(id).dataset.state = state;
}
function badge(id, message, state = '') {
  $(id).textContent = message;
  $(id).className = `badge ${state}`.trim();
}
function connection(online) {
  if (serverStopped) return;
  $('connection').dataset.state = online ? 'online' : 'offline';
  $('connection').textContent = online ? '로컬 연결됨' : '연결 확인 필요';
}

async function shutdownServer() {
  const draft = draftChanged() ? '\n저장하지 않은 Registry 초안이 있습니다.' : '';
  if (!window.confirm(`Injector 웹 서버를 종료할까요? 실행 중인 의존성은 계속 실행됩니다.${draft}`)) return;
  const button = $('shutdown-server');
  button.disabled = true;
  feedback('shutdown-feedback', '서버를 종료하는 중…', 'pending');
  try {
    await api('/api/shutdown', {});
    serverStopped = true;
    clearTimeout(timer);
    feedback('shutdown-feedback', '');
    $('dashboard').inert = true;
    $('connection').dataset.state = 'offline';
    $('connection').textContent = '서버 종료됨';
  } catch (e) {
    feedback('shutdown-feedback', e.message, 'error');
    button.disabled = false;
    button.focus();
  }
}
function error(message) { feedback('result', message, 'error'); badge('badge', '확인 필요', 'failed'); }
function suiteSelection() {
  return {...selection(), suite:$('suite-file').value.trim(), candidate:$('suite-candidate').value.trim()};
}
function suiteButtons(locked) {
  const pending = locked || suiteChecking;
  const input = suiteSelection();
  for (const id of ['suite-candidate','suite-file']) $(id).disabled = pending;
  for (const id of ['suite-pick-candidate','suite-pick-file']) $(id).disabled = pending || editorBusy || !token;
  for (const id of ['suite-check','suite-run']) $(id).disabled = pending || !catalog || !input.candidate || !input.suite;
}
function buttons() {
  const locked = busy || pickerBusy;
  $('prepare').disabled = locked || !planReady;
  $('check').disabled = locked || checking || !planReady;
  $('variant-options').disabled = locked;
  for (const id of ['load','project','registry']) $(id).disabled = locked;
  $('stop').disabled = locked || !selection().project;
  for (const id of ['target','profile']) $(id).disabled = locked || !catalog;
  $('pick-project').disabled = locked || editorBusy || !token;
  $('pick-registry').disabled = $('pick-project').disabled;
  suiteButtons(locked);
  editorButtons();
}
function clearPlan(message) {
  $('progress').hidden = $('execution-log').hidden = $('ide-hint').hidden = true;
  $('plan').replaceChildren();
  $('summary').textContent = message;
}
async function plan() {
  const generation = ++planRequest;
  planReady = false;
  feedback('check-result', '');
  clearPlan('계획을 읽는 중…');
  badge('badge', '계획을 읽는 중');
  feedback('result', selectionWarning, selectionWarning ? 'pending' : '');
  buttons();
  try {
    const query = new URLSearchParams({...selection(), target:$('target').value, profile:$('profile').value});
    for (const [node, variant] of Object.entries(variants)) query.append('variant', node + '=' + variant);
    const result = await api('/api/plan?' + query);
    if (generation !== planRequest) return;
    $('plan').replaceChildren();
    result.steps.forEach((step,index) => {
      const item = document.createElement('li'); item.dataset.node = step.node;
      const number = document.createElement('span'); number.className='number'; number.textContent=String(index+1).padStart(2,'0');
      const name = document.createElement('span'); name.className='node'; name.textContent=step.node;
      const runner = document.createElement('span'); runner.className='runner'; runner.textContent=(runners[step.runner] || step.runner) + ' · ' + step.variant; name.append(runner);
      const phase = document.createElement('span'); phase.className='phase'; phase.textContent='대기';
      item.append(number,name,phase); $('plan').append(item);
    });
    $('summary').textContent = `${result.order.length}개 노드`;
    $('ide-hint').hidden = result.steps.at(-1)?.runner !== 'intellij';
    badge('badge', '실행 대기');
    if (!selectionWarning) feedback('result', '실행 환경을 준비할 수 있습니다.');
    planReady = true;
    buttons();
  } catch(e) {
    if (generation !== planRequest) return;
    $('plan').replaceChildren();
    $('summary').textContent = '실행 계획을 확인할 수 없습니다.';
    error(e.message);
  }
}
function refreshPlan() {
  const name = $('profile').value;
  if (!catalog?.profiles[name]) return;
  return Promise.all([plan(),
    dependencyGraph.update(catalog.project, name, catalog.profiles[name].applications, variants, catalog.registry, $('target').value)]);
}
async function checkRequirements() {
  const generation = planRequest;
  const result = $('check-result');
  checking = true;
  feedback('check-result', '실행 조건을 확인하는 중…', 'pending');
  buttons();
  try {
    const check = await api('/api/check', {...selection(), target:$('target').value, profile:$('profile').value, variants});
    if (generation === planRequest) {
      result.textContent = check.intellij
        ? `IDE 확인 필요 · 등록된 실행 조건을 확인했습니다. IntelliJ에서 모듈 ${check.intellij.module}과 메인 클래스 ${check.intellij.mainClass}를 확인하세요.`
        : `통과 · 선택한 앱과 의존성 ${check.order.length}개 노드의 등록된 실행 조건을 확인했습니다.`;
      result.dataset.state = 'success';
    }
  } catch(e) {
    if (generation === planRequest) feedback('check-result', `확인 필요 · ${e.message}`, 'error');
  } finally {
    checking = false;
    buttons();
  }
}
async function targets(preferred) {
  const profile = catalog.profiles[$('profile').value];
  $('target').replaceChildren(...profile.applications.map(name => new Option(name,name)));
  if (profile.applications.includes(preferred)) $('target').value = preferred;
  else if (profile.targets.length) $('target').value = profile.targets[0];
  variants = {};
  const options = $('variant-options');
  options.replaceChildren();
  for (const [node, choice] of Object.entries(profile.variantChoices ?? {})) {
    const label = document.createElement('label');
    label.textContent = node;
    const select = document.createElement('select');
    select.append(...choice.options.map(value => new Option(value, value)));
    select.value = choice.default;
    select.onchange = () => {
      if (select.value === choice.default) delete variants[node];
      else variants[node] = select.value;
      refreshPlan();
    };
    label.append(select);
    options.append(label);
  }
  $('variant-picker').hidden = !options.children.length;
  await refreshPlan();
}
async function load(remember = false) {
  const generation = ++loadRequest;
  const profile = $('profile').value, target = $('target').value;
  catalog = null; planReady = false; planRequest++; $('variant-picker').hidden = true; buttons();
  badge('project-state', '불러오는 중', 'running');
  clearPlan('프로젝트를 읽는 중…');
  selectionWarning = '';
  feedback('check-result', '');
  suiteChanged();
  resetHistory();
  try {
    const paths = selection();
    let result;
    if (remember) {
      try { result = await api('/api/project', paths); }
      catch { /* A read-only preview may reject the save request. */ }
    }
    if (generation !== loadRequest) return;
    if (!result) {
      result = await api('/api/project?' + new URLSearchParams(paths));
      if (remember) result.remembered = false;
    }
    if (generation !== loadRequest) return;
    catalog = result;
    $('project').title = $('project').value = catalog.project;
    $('registry').title = $('registry').value = catalog.registry;
    $('profile').replaceChildren(...Object.keys(catalog.profiles).map(name => new Option(name,name)));
    if (Object.hasOwn(catalog.profiles, profile)) $('profile').value = profile;
    badge('project-state', '불러옴', 'succeeded');
    if (result.remembered === false) selectionWarning = '경로를 불러왔습니다. 이 선택이 저장됐는지는 확인할 수 없습니다.';
    feedback('result', selectionWarning || '실행 환경을 준비할 수 있습니다.', selectionWarning ? 'pending' : '');
    $('suite-baseline').textContent = `기준 워크트리 · ${catalog.project}`;
    buttons(); await targets($('profile').value === profile ? target : undefined);
    if ($('suite-history').open) await loadSuiteHistory();
  } catch(e) {
    if (generation !== loadRequest) return;
    dependencyGraph.reset();
    badge('project-state', '불러오기 실패', 'failed');
    clearPlan('프로젝트 경로와 Registry 파일을 확인하세요.');
    error(e.message);
  }
}

async function pickPath(kind, inEditor = false, field = kind, buttonId = inEditor ? 'registry-pick-project' : 'pick-' + kind) {
  if (busy || editorBusy || pickerBusy) return;
  const button = $(buttonId);
  const caption = button.textContent;
  let project;
  pickerBusy = true;
  button.textContent = '선택 중…';
  buttons();
  try {
    ({project} = await api('/api/project/pick', {kind, project:(inEditor && editor?.project) || $(field).value.trim()}));
  } catch (e) {
    if (inEditor) registryStatus(e.message, 'error');
    else if (field.startsWith('suite-')) feedback('suite-result', e.message, 'error');
    else error(e.message);
    return;
  } finally {
    pickerBusy = false;
    button.textContent = caption;
    buttons();
    button.focus();
  }
  if (!project) return;
  if (inEditor) {
    await openEditor(project);
    if (editor?.project !== project) return;
  }
  $(field).value = project;
  if (field.startsWith('suite-')) return suiteChanged();
  await load(true);
}
async function poll(restore = false) {
  if (serverStopped) return;
  let job;
  try {
    job = await api('/api/job');
    connection(true);
  } catch(e) {
    if (serverStopped) return;
    connection(false);
    feedback(activeAction === 'suite' ? 'suite-result' : 'result', `${e.message} 작업 상태를 다시 확인합니다…`, 'error');
    timer = setTimeout(() => poll(restore), 1500);
    return;
  }
  if (restore && job.action === 'suite' && job.context?.project === selection().project
      && job.context.registry === selection().registry && !suiteSelection().suite && !suiteSelection().candidate) {
    $('suite-file').value = job.context.suite;
    $('suite-candidate').value = job.context.candidate;
  }
  busy = job.status === 'running'; buttons();
  if (job.status === 'idle') return;
  activeAction = job.action;
  if (matchesJob(job)) {
    if (job.action === 'suite') {
      if (job.status === 'succeeded') {
        showSuiteResult(job.result);
        if (job.result.report && $('suite-history').open) await loadSuiteHistory();
      }
      else if (job.status === 'failed') {
        badge('suite-badge', '실행 실패', 'failed');
        feedback('suite-result', job.error, 'error');
      } else {
        const current = job.events.at(-1);
        badge('suite-badge', '검증 중', 'running');
        feedback('suite-result', current ? `${current.case} · ${sides[current.side]} 워크트리 실행 중` : '실행 조건을 확인하는 중…', 'pending');
      }
    } else showExecution(job);
  } else if (busy) feedback('result', '다른 실행 대상의 작업이 진행 중입니다.', 'pending');
  if (busy) timer=setTimeout(poll, 700);
}
function matchesJob(job) {
  const context = job.context;
  if (!context) return true;
  const current = job.action === 'suite' ? suiteSelection() : selection();
  if (current.project !== context.project || current.registry !== context.registry) return false;
  if (job.action === 'suite') return current.suite === context.suite && current.candidate === context.candidate;
  if (job.action !== 'prepare') return true;
  const prepared = context.variants || {};
  return $('target').value === context.target && $('profile').value === context.profile
    && Object.keys(variants).length === Object.keys(prepared).length
    && Object.entries(variants).every(([node, variant]) => prepared[node] === variant);
}
function showExecution(job) {
  badge('badge', ({running:'진행 중', succeeded:job.action === 'stop' ? '종료됨' : '준비 완료', failed:'실패'})[job.status], job.status);
  const events = job.events || [];
  $('execution-log').hidden = !events.length;
  $('events').textContent = events.map(event => event.order ? event.order.join(' → ')
    : [event.node, phases[event.phase] || event.phase].filter(Boolean).join(' · ')).join('\n');
  const states = new Map(events.filter(event => event.node).map(event => [event.node, event.phase]));
  let ready = 0;
  for (const row of $('plan').children) {
    const state = states.get(row.dataset.node);
    const phase = row.querySelector('.phase');
    phase.textContent = job.status === 'succeeded' && job.action === 'stop' ? '대기' : phases[state] || state || '대기';
    phase.className = 'phase ' + (state || '');
    if (['ready', 'debug-ready'].includes(state)) ready++;
  }
  const progress = $('progress');
  progress.max = Math.max(1, $('plan').children.length);
  progress.value = ready;
  progress.hidden = job.status !== 'running' || job.action === 'stop' || !$('plan').children.length;
  if (job.status==='succeeded') {
    const result=job.result;
    const instruction = result.externalRunConfiguration
      ? 'IntelliJ에서 아래 실행 구성을 가져온 뒤 Debug를 누르세요.'
      : `IntelliJ에서 Injector-${result.profile}-${result.target}를 선택하고 Debug를 누르세요.`;
    const message = result.status==='stopped' ? 'Injector가 시작한 자원을 종료했습니다.'
      : result.runConfiguration ? `${instruction}\n${result.runConfiguration}` : '앱과 의존성이 준비됐습니다.';
    feedback('result', message, 'success');
  } else if(job.status==='failed') error(job.error);
  else {
    const current = events.filter(event => event.node).at(-1);
    const message = current ? `${current.node} · ${phases[current.phase] || current.phase}`
      : job.action === 'stop' ? '의존성을 종료하는 중…' : '의존성을 준비하는 중…';
    feedback('result', message, 'pending');
  }
}
async function run(action) {
  activeAction = action;
  const suite = action === 'suite';
  if (suite) {
    suiteChanged();
    badge('suite-badge', '시작 중', 'running');
    feedback('suite-result', '실행 조건을 확인하는 중…', 'pending');
  } else {
    badge('badge', '시작 중', 'running');
    feedback('result', action === 'stop' ? '종료 요청 중…' : '준비 요청 중…', 'pending');
  }
  busy=true; buttons(); clearTimeout(timer);
  try {
    const inputs = suite ? suiteSelection() : {...selection(),target:$('target').value,profile:$('profile').value,variants};
    await api(suite ? '/api/suite/run' : '/api/'+action, inputs);
    await poll();
  } catch(e) {
    busy=false; buttons();
    if (!suite) error(e.message);
    else {
      badge('suite-badge', '확인 필요', 'failed');
      feedback('suite-result', e.message, 'error');
    }
  }
}

function suiteChanged() {
  badge('suite-badge', '대기 중');
  feedback('suite-result', '');
  $('suite-entries').replaceChildren();
  $('suite-entries').hidden = $('suite-evidence').hidden = true;
  buttons();
}
function showSuiteResult(report) {
  const preflight = report.phase === 'preflight';
  const success = preflight ? report.status === 'READY' : report.verdict === 'PASS';
  const label = preflight ? success ? '실행 가능' : '실행 조건 확인 필요' : verdicts[report.verdict];
  const state = success ? 'success' : report.verdict === 'INCONCLUSIVE' ? 'pending' : 'error';
  const cases = report.cases || [];
  badge('suite-badge', label, success ? 'succeeded' : state === 'pending' ? 'running' : 'failed');
  feedback('suite-result', `${label}${report.suite ? ` · ${report.suite}` : ''}${cases.length ? ` · 시나리오 ${cases.length}개` : ''}`, state);
  const rows = (preflight && !success ? report.diagnostics.map(entry => [
    sides[entry.side], entry.case ? `시나리오 ${entry.case}` : '', entry.node, entry.variable,
    entry.message
  ].filter(Boolean).join(' · ')) : cases.map(entry => [entry.scenario || entry.file,
    entry.verdict ? verdicts[entry.verdict] || entry.verdict : '', entry.reason].filter(Boolean).join(' · ')));
  $('suite-entries').replaceChildren(...rows.map(text => {
    const item = document.createElement('li'); item.textContent = text; return item;
  }));
  $('suite-entries').hidden = !rows.length;
  $('suite-evidence').hidden = !report.report;
  $('suite-report').textContent = report.report || '';
  $('suite-copy').textContent = '보고서 경로 복사';
}

async function copySuiteReport() {
  const path = $('suite-report');
  try {
    await navigator.clipboard.writeText(path.textContent);
    $('suite-copy').textContent = '복사됨';
  } catch {
    const range = document.createRange();
    range.selectNodeContents(path);
    const selected = window.getSelection();
    selected.removeAllRanges();
    selected.addRange(range);
    $('suite-copy').textContent = '경로 선택됨';
  }
}

function resetHistory() {
  historyRequest++;
  savedSuite = null;
  $('history-run').replaceChildren();
  $('history-run').disabled = $('history-cases').hidden = true;
  feedback('history-status', '먼저 기준 프로젝트를 불러오세요.');
}

async function loadSuiteHistory() {
  const previous = $('history-run').value;
  resetHistory();
  if (!catalog) return;
  const generation = historyRequest;
  feedback('history-status', '저장된 검증 기록을 읽는 중…', 'pending');
  try {
    const {runs} = await api('/api/suite/history', {project:catalog.project});
    if (generation !== historyRequest) return;
    if (!runs.length) {
      feedback('history-status', '이 프로젝트의 저장된 검증 기록이 없습니다.');
      return;
    }
    $('history-run').replaceChildren(...runs.map(run => new Option(
      `${verdicts[run.verdict]} · ${run.suite} · ${new Date(run.modified * 1000).toLocaleString()}`, run.id)));
    if (runs.some(run => run.id === previous)) $('history-run').value = previous;
    $('history-run').disabled = false;
    await openSavedSuite();
  } catch (e) {
    if (generation === historyRequest) feedback('history-status', e.message, 'error');
  }
}

async function openSavedSuite() {
  const generation = ++historyRequest;
  const run = $('history-run').value;
  $('history-cases').hidden = true;
  savedSuite = null;
  feedback('history-status', '보고서를 읽는 중…', 'pending');
  try {
    const report = await api('/api/suite/history', {project:catalog.project, run});
    if (generation !== historyRequest) return;
    savedSuite = report;
    feedback('history-status', `${verdicts[report.verdict]} · ${report.targetApp} · ${report.profile}`,
             report.verdict === 'PASS' ? 'success' : report.verdict === 'FAIL' ? 'error' : 'pending');
    const cases = report.cases;
    $('history-case').replaceChildren(...cases.map((entry, index) => new Option(
      `${entry.scenario} · ${verdicts[entry.verdict]}`, String(index + 1))));
    const failed = cases.findIndex(entry => entry.verdict !== 'PASS' && entry.report);
    if (failed >= 0) $('history-case').value = String(failed + 1);
    $('history-cases').hidden = false;
    await openSavedCase();
  } catch (e) {
    if (generation === historyRequest) feedback('history-status', e.message, 'error');
  }
}

async function openSavedCase() {
  const generation = ++historyRequest;
  const index = Number($('history-case').value);
  const entry = savedSuite?.cases[index - 1];
  const changes = $('history-changes');
  $('history-detail').hidden = changes.hidden = true;
  if (!entry?.report) {
    feedback('history-case-status', '이 시나리오에는 저장된 증거가 없습니다.');
    return;
  }
  feedback('history-case-status', '시나리오 증거를 읽는 중…', 'pending');
  try {
    const report = await api('/api/suite/history', {project:catalog.project, run:$('history-run').value, case:index});
    if (generation !== historyRequest) return;
    const statuses = {recorded:'기록 완료', failed:'실행 실패', interrupted:'중단', 'not-run':'미실행'};
    feedback('history-case-status', [verdicts[report.verdict], report.reason].filter(Boolean).join(' · '),
             report.verdict === 'PASS' ? 'success' : report.verdict === 'FAIL' ? 'error' : 'pending');
    for (const [side, label] of Object.entries(sides)) {
      const run = report.runs?.[side];
      const status = statuses[run?.status];
      $(`history-${side}-title`).textContent = status ? `${label} · ${status}` : label;
      const reason = $(`history-${side}-reason`);
      reason.textContent = run?.reason || '';
      reason.hidden = !reason.textContent;
      $(`history-${side}-details`).textContent = report[side] || '관측 기록 없음';
    }
    changes.replaceChildren(...(report.changes || []).map(({path, kind, baseline, candidate}) => {
      const item = document.createElement('li');
      item.textContent = `${changeTypes[kind]} · ${path}`;
      const values = document.createElement('p');
      values.className = 'hint';
      values.textContent = `기준 ${baseline ?? '없음'} → 후보 ${candidate ?? '없음'}`;
      item.append(values);
      return item;
    }));
    changes.hidden = !changes.children.length;
    $('history-detail').hidden = false;
  } catch (e) {
    if (generation === historyRequest) feedback('history-case-status', e.message, 'error');
  }
}
async function checkSuite() {
  const input = suiteSelection();
  suiteChanged();
  suiteChecking = true;
  buttons();
  badge('suite-badge', '점검 중', 'running');
  feedback('suite-result', '워크트리와 시나리오의 실행 조건을 확인하는 중…', 'pending');
  const unchanged = () => JSON.stringify(input) === JSON.stringify(suiteSelection());
  try {
    const report = await api('/api/suite/check', input);
    if (unchanged()) showSuiteResult(report);
  } catch(e) {
    if (unchanged()) {
      badge('suite-badge', '확인 필요', 'failed');
      feedback('suite-result', e.message, 'error');
    }
  } finally {
    suiteChecking = false;
    buttons();
  }
}

function draftChanged() {
  return editor && $('registry-text').value !== editor.savedText;
}

function editorButtons() {
  const locked = editorBusy || pickerBusy;
  $('edit-registry').disabled = !token || locked || !$('project').value.trim();
  $('registry-pick-project').disabled = busy || locked || !token;
  $('registry-file').disabled = locked;
  $('registry-text').disabled = locked || !editor;
  $('completion-controls').disabled = locked || !editor;
  $('registry-fold').disabled = $('registry-close').disabled = locked;
  for (const id of ['registry-reload', 'registry-validate']) $(id).disabled = locked || !editor;
  $('registry-save').disabled = busy || locked || !draftChanged();
}

function registryStatus(message, state = '') {
  $('registry-status').textContent = message;
  $('registry-status').dataset.state = state;
}

function discardDraft() {
  return !draftChanged() || window.confirm('저장하지 않은 변경을 버릴까요?');
}

function resetCompletion(message = '') {
  completion = null;
  $('completion-path').hidden = $('completion-node').hidden = $('completion-apply').hidden = true;
  $('completion-status').textContent = message;
}

function completionOptions(id, options) {
  const select = $(id), previous = select.value;
  select.replaceChildren(...options.map(value => new Option(value, value)));
  if (options.includes(previous)) select.value = previous;
}

function completionVariant() {
  return completion.variants.find(variant => variant.id === $('completion-variant').value);
}

function completionSourceChoices(source = {}) {
  const sources = completionVariant().sources;
  completionOptions('completion-source', sources.map(item => item.id));
  if (source.node) $('completion-source').value = source.node;
  const endpoints = sources.find(item => item.id === $('completion-source').value)?.endpoints || [];
  completionOptions('completion-endpoint', endpoints.map(item => item.id));
  if (source.endpoint) $('completion-endpoint').value = source.endpoint;
  const contexts = endpoints.find(item => item.id === $('completion-endpoint').value)?.contexts || [];
  completionOptions('completion-context', contexts.map(item => item.id));
  if (source.context) $('completion-context').value = source.context;
  completionOptions('completion-component', contexts.find(item => item.id === $('completion-context').value)?.components || []);
  if (source.component) $('completion-component').value = source.component;
  $('completion-apply').disabled = !$('completion-component').value;
}

function showInjectionRule() {
  const index = $('completion-rule').value;
  const rule = index === '' ? null : completionVariant().injections[Number(index)];
  $('completion-remove-rule').hidden = !rule;
  $('completion-key').value = rule?.key || '';
  if (rule) $('completion-channel').value = rule.channel;
  completionSourceChoices(rule?.source);
}

function completionRunnerFields() {
  const runner = completion.runners.find(item => item.id === $('completion-runner').value);
  const existing = completionVariant().execution;
  $('completion-runner-fields').replaceChildren(...runner.fields.map(({name, array}) => {
    const label = document.createElement('label');
    const input = document.createElement(array ? 'textarea' : 'input');
    label.textContent = name;
    input.name = name;
    input.required = true;
    if (array) {
      input.rows = 2;
      input.placeholder = '["java", "-jar", "app.jar"]';
    }
    if (existing.type === runner.id) input.value = array ? JSON.stringify(existing[name]) : existing[name];
    label.append(input);
    return label;
  }));
}

function showCompletionFields() {
  const variant = completionVariant(), field = $('completion-field').value;
  const status = $('completion-status');
  status.textContent = '선택한 variant의 초안을 편집합니다.';
  $('completion-dependency-field').hidden = field !== 'dependencies';
  $('completion-injection').hidden = field !== 'injections';
  $('completion-execution').hidden = field !== 'execution';
  if (field === 'dependencies') {
    completionOptions('completion-dependency', variant.dependencies);
    $('completion-apply').disabled = !variant.dependencies.length;
    if (!variant.dependencies.length) status.textContent = '추가할 등록 서비스가 없습니다.';
  } else if (field === 'injections') {
    $('completion-rule').replaceChildren(new Option('새 규칙 추가', ''), ...variant.injections.map((rule, index) =>
      new Option(`${rule.channel} · ${rule.key} ← ${rule.source.node}/${rule.source.endpoint}`, String(index))));
    showInjectionRule();
    if (!variant.sources.length) status.textContent = '주입에 사용할 의존 서비스의 엔드포인트가 없습니다.';
  } else {
    if (variant.execution.type) $('completion-runner').value = variant.execution.type;
    completionRunnerFields();
    $('completion-apply').disabled = false;
  }
}

async function loadCompletion(edit) {
  if (!editor || editorBusy) return;
  editorBusy = true;
  editorButtons();
  const request = {project:editor.project, registry:editor.registry, file:editor.file, text:$('registry-text').value};
  const status = $('completion-status');
  status.textContent = '후보를 읽는 중…';
  try {
    if (edit) {
      const draft = await api('/api/registry/complete', {...request, edit});
      $('registry-text').value = request.text = draft.text;
      registryStatus('초안에 반영했습니다.');
    }
    resetCompletion('후보를 읽는 중…');
    completion = await api('/api/registry/complete', request);
    if (editor.file) {
      $('completion-node').hidden = false;
      completionOptions('completion-variant', completion.variants.map(item => item.id));
      completionOptions('completion-runner', completion.runners.map(item => item.id));
      completionOptions('completion-channel', completion.channels);
      showCompletionFields();
      if (edit?.field === 'injections' && Number.isInteger(edit.index)) {
        $('completion-rule').value = String(edit.index);
        showInjectionRule();
      }
      $('completion-apply').hidden = false;
    } else {
      $('completion-path').hidden = $('completion-apply').hidden = !completion.paths.length;
      $('completion-apply').disabled = false;
      $('completion-file').value = '';
      $('completion-files').replaceChildren(...completion.paths.map(item => {
        const option = new Option(item.id, item.path);
        option.label = item.id;
        return option;
      }));
      const description = completion.paths.length ? `미등록 노드 파일 ${completion.paths.length}개` : '등록할 노드 파일이 없습니다.';
      status.textContent = completion.limited ? `${description} · 검색 범위 한도에 도달했습니다.` : description;
    }
  } catch (e) {
    status.textContent = e.message;
  } finally {
    editorBusy = false;
    editorButtons();
  }
}

async function applyCompletion() {
  if (!completion) return;
  if (!editor.file) {
    const path = $('completion-file').value;
    if (!completion.paths.some(item => item.path === path)) {
      $('completion-status').textContent = '목록에 있는 노드 파일을 선택하세요.';
      return;
    }
    return loadCompletion({path});
  }
  const field = $('completion-field').value;
  let value;
  if (field === 'dependencies') {
    value = $('completion-dependency').value;
  } else if (field === 'injections') {
    value = {channel:$('completion-channel').value, key:$('completion-key').value.trim(), source:{
      node:$('completion-source').value, endpoint:$('completion-endpoint').value,
      context:$('completion-context').value, component:$('completion-component').value}};
    if (!$('completion-key').reportValidity()) return;
  } else {
    value = {type:$('completion-runner').value};
    for (const input of $('completion-runner-fields').querySelectorAll('input, textarea')) {
      if (!input.reportValidity()) return;
      try {
        value[input.name] = input.tagName === 'TEXTAREA' ? JSON.parse(input.value) : input.value;
      } catch {
        $('completion-status').textContent = 'command를 JSON 문자열 배열로 입력하세요.';
        return;
      }
    }
  }
  const edit = {field, value, variant:$('completion-variant').value};
  if (field === 'injections' && $('completion-rule').value !== '') edit.index = Number($('completion-rule').value);
  return loadCompletion(edit);
}

function updateEditorFiles() {
  const files = editor?.files ?? [];
  const selector = $('registry-file');
  const rootName = editor?.registry.split(/[\\/]/).pop() || 'registry.json';
  selector.replaceChildren(new Option(rootName, ''), ...files.map(file => new Option(file, file)));
  selector.value = editor?.file ?? '';
  $('registry-file-picker').hidden = !files.length;
}

async function openEditor(project, {filename, reload = false, registry = selection().registry} = {}) {
  if (editorBusy) return;
  const sameProject = editor && (registry === editor.registry || registry === editor.sourceRegistry)
    && (project === editor.project || project === editor.source);
  const file = filename ?? (sameProject ? editor.file : '');
  if (!reload && sameProject && file === editor.file) {
    if (!registryDialog.open) registryDialog.showModal();
    if (!window.matchMedia?.('(pointer: coarse)').matches) $('registry-text').focus({preventScroll:true});
    return;
  }
  if (!discardDraft()) {
    $('registry-file').value = editor.file;
    return;
  }
  const source = sameProject ? editor.source : project;
  const sourceRegistry = sameProject ? editor.sourceRegistry : registry;
  editorBusy = true;
  if (!registryDialog.open) registryDialog.showModal();
  editorButtons();
  registryStatus('파일을 읽는 중…');
  try {
    const result = await api('/api/registry/open', {project, registry, file});
    $('registry-path').textContent = result.path;
    $('registry-text').value = result.text;
    editor = {project:result.project, registry:result.registry, source, sourceRegistry, file, files:result.files,
              revision:result.revision, savedText:$('registry-text').value};
    $('registry-completion').open = false;
    $('registry-completion').hidden = false;
    resetCompletion();
    registryStatus('파일을 불러왔습니다.');
  } catch (e) {
    registryStatus(e.message, 'error');
  } finally {
    editorBusy = false;
    updateEditorFiles();
    editorButtons();
    if (editor && !window.matchMedia?.('(pointer: coarse)').matches) $('registry-text').focus({preventScroll:true});
  }
}

function hideEditor(discard) {
  if (editorBusy || pickerBusy || (discard && !discardDraft())) return;
  if (discard) {
    editor = null;
    $('registry-completion').hidden = true;
    resetCompletion();
    $('registry-text').value = '';
    $('registry-path').textContent = '';
    updateEditorFiles();
  }
  registryDialog.close();
  editorButtons();
  $('edit-registry').focus();
}

async function checkEditor(action) {
  editorBusy = true;
  editorButtons();
  const text = $('registry-text').value;
  registryStatus(action === 'save' ? '검증 후 저장하는 중…' : '검증하는 중…');
  let location;
  try {
    const result = await api('/api/registry/' + action, {project:editor.project, registry:editor.registry, file:editor.file, text, revision:editor.revision});
    if (action === 'save') {
      editor.revision = result.revision;
      editor.savedText = text;
      editor.files = result.files;
      updateEditorFiles();
      const current = selection();
      if ((current.project === result.project || current.project === editor.source)
          && (current.registry === result.registry || current.registry === editor.sourceRegistry)) await load(true);
      registryStatus('저장했습니다.', 'success');
    } else {
      registryStatus(`검증 통과 · 스키마 ${result.schemaVersion} · 노드 ${result.nodes}개 · 프로필 ${result.profiles}개`, 'success');
    }
  } catch (e) {
    registryStatus(e.message, 'error');
    location = /^invalid JSON at line (\d+), column (\d+)/.exec(e.message);
  } finally {
    editorBusy = false;
    editorButtons();
  }
  if (location) {
    const lines = text.split('\n'), line = Number(location[1]) - 1;
    const start = lines.slice(0, line).reduce((offset, row) => offset + row.length + 1, 0);
    const column = Array.from(lines[line] || '').slice(0, Number(location[2]) - 1).join('').length;
    $('registry-text').focus();
    $('registry-text').setSelectionRange(start + column, start + column + 1);
  }
}

function clearObservationComparison() {
  $('observation-details').hidden = $('observation-changes').hidden = true;
  $('observation-status').textContent = '';
  dependencyGraph.showComparison(null);
}

async function compareObservations() {
  const baseline = $('observation-baseline');
  const candidate = $('observation-candidate');
  const button = $('observation-compare');
  const status = $('observation-status');
  const details = $('observation-details');
  const changes = $('observation-changes');
  clearObservationComparison();
  for (const control of [baseline, candidate, button]) control.disabled = true;
  try {
    const files = [baseline.files[0], candidate.files[0]];
    if (files.some(file => !file || file.size > 2 * 1024 * 1024)) {
      throw new Error('2 MiB 이하의 관측 JSON 파일을 두 개 선택하세요.');
    }
    const [before, after] = await Promise.all(files.map(async file =>
      new TextDecoder('utf-8', {fatal:true}).decode(await file.arrayBuffer())));
    const report = await api('/api/observations/compare', {baseline:before, candidate:after});
    const verdict = {PASS:'일치', FAIL:'차이 발견', INCONCLUSIVE:'판정 보류'}[report.verdict];
    const scope = report.edge ? `${report.edge.caller} → ${report.edge.dependency}` : report.targetNode;
    status.textContent = `${verdict}${scope ? ' · ' + scope + ' · ' + report.profile : ''}${report.reason ? ' · ' + report.reason : ''}`;
    if (report.baseline && report.candidate) {
      $('observation-before').textContent = report.baseline;
      $('observation-after').textContent = report.candidate;
      details.hidden = false;
    }
    const entries = report.changes || [];
    changes.replaceChildren(...entries.map(({path, kind}) => {
      const item = document.createElement('li');
      item.textContent = `${changeTypes[kind]} · ${path}`;
      return item;
    }));
    changes.hidden = !changes.children.length;
    if (report.changeCount > entries.length) status.textContent += ` · 차이 ${report.changeCount}개 중 50개 표시`;
    dependencyGraph.showComparison(report);
  } catch (e) {
    status.textContent = e.message;
  } finally {
    for (const control of [baseline, candidate, button]) control.disabled = false;
  }
}

$('observation-compare').onclick = compareObservations;
$('observation-baseline').onchange = $('observation-candidate').onchange = clearObservationComparison;
$('project-form').onsubmit = $('load').onclick = event => { event?.preventDefault(); return load(true); };
$('pick-project').onclick=() => pickPath('project');
$('pick-registry').onclick=() => pickPath('registry');
$('profile').onchange=() => targets();
$('target').onchange=refreshPlan;
$('project').oninput=$('registry').oninput=() => {
  catalog=null; planReady=false; planRequest++; loadRequest++;
  feedback('check-result', ''); feedback('result', '바뀐 경로를 불러오세요.');
  badge('project-state', '불러오기 필요'); badge('badge', '대기 중');
  $('variant-picker').hidden=true;
  $('project').title = $('project').value;
  $('registry').title = $('registry').value;
  $('target').replaceChildren(new Option('프로젝트를 불러오세요', ''));
  $('suite-baseline').textContent = '기준 워크트리는 위에서 선택한 프로젝트입니다.';
  clearPlan('실행 대상을 선택하세요.'); dependencyGraph.reset(); suiteChanged();
  resetHistory();
};
$('check').onclick=checkRequirements;
$('prepare').onclick=() => run('prepare');
$('stop').onclick=() => run('stop');
$('shutdown-server').onclick = shutdownServer;
$('suite-pick-candidate').onclick = () => pickPath('project', false, 'suite-candidate', 'suite-pick-candidate');
$('suite-pick-file').onclick = () => pickPath('suite', false, 'suite-file', 'suite-pick-file');
$('suite-candidate').oninput = $('suite-file').oninput = suiteChanged;
$('suite-check').onclick = checkSuite;
$('suite-run').onclick = () => run('suite');
$('suite-copy').onclick = copySuiteReport;
$('suite-history').addEventListener('toggle', () => { if ($('suite-history').open) loadSuiteHistory(); });
$('history-refresh').onclick = loadSuiteHistory;
$('history-run').onchange = openSavedSuite;
$('history-case').onchange = openSavedCase;
$('edit-registry').onclick = () => openEditor($('project').value.trim());
$('registry-pick-project').onclick = () => pickPath('project', true);
$('registry-file').onchange = () => openEditor(editor.project, {filename:$('registry-file').value, registry:editor.registry});
$('registry-validate').onclick = () => checkEditor('validate');
$('registry-save').onclick = () => checkEditor('save');
$('registry-reload').onclick = () => openEditor(editor.project, {reload:true, registry:editor.registry});
$('registry-fold').onclick = () => hideEditor(false);
$('registry-close').onclick = () => hideEditor(true);
registryDialog.addEventListener('cancel', event => {
  event.preventDefault();
  hideEditor(true);
});
$('registry-text').oninput = () => {
  registryStatus(draftChanged() ? '저장하지 않은 변경이 있습니다.' : '저장된 내용과 같습니다.');
  resetCompletion('JSON을 수정했습니다. 후보를 다시 읽으세요.');
  editorButtons();
};
$('registry-completion').addEventListener('toggle', () => {
  if ($('registry-completion').open && !completion) loadCompletion();
});
$('completion-reload').onclick = () => loadCompletion();
$('completion-apply').onclick = applyCompletion;
$('completion-variant').onchange = $('completion-field').onchange = showCompletionFields;
$('completion-source').onchange = $('completion-endpoint').onchange = $('completion-context').onchange = completionSourceChoices;
$('completion-runner').onchange = completionRunnerFields;
$('completion-rule').onchange = showInjectionRule;
$('completion-remove-rule').onclick = () => loadCompletion({field:'removeInjection',
  variant:$('completion-variant').value, index:Number($('completion-rule').value)});
window.addEventListener('beforeunload', event => {
  if (serverStopped || !draftChanged()) return;
  event.preventDefault();
  event.returnValue = true;
});
(async () => {
  try {
    const info=await api('/api/info');
    connection(true);
    token=info.token;
    $('shutdown-server').disabled = false;
    $('project').value=info.project;
    $('registry').value=info.registry;
    $('registries').replaceChildren(...info.registries.map(path => new Option(path, path)));
    await load();
    await poll(true);
  } catch(e) {connection(false); error(e.message);}
})();
