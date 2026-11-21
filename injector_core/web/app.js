const $ = id => document.getElementById(id);
let token, catalog, busy = false, timer;
let editor, editorBusy = false, pickerBusy = false;
let variants = {}, planReady = false, planRequest = 0, loadRequest = 0;
let checking = false;
const phases = {starting:'시작 중', waiting:'준비 확인 중', ready:'준비 완료', 'debug-ready':'Debug 가능', stopping:'종료 중'};
async function api(path, body) {
  const endpoint = path.split('?')[0];
  let response, result;
  try {
    response = await fetch(path, body === undefined ? {} : {method:'POST', headers:{'Content-Type':'application/json', 'X-Injector-Token':token}, body:JSON.stringify(body)});
  } catch {
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
  if (!response.ok) throw new Error(result.error || '요청에 실패했습니다.');
  return result;
}
const dependencyGraph = new DependencyGraph($('dependency-graph'), api);
const registryDialog = $('registry-editor');
function selection() {
  return {project:$('project').value.trim(), registry:$('registry').value.trim()};
}
function error(message) { $('result').textContent = message; $('badge').textContent = '확인 필요'; $('badge').className = 'badge failed'; }
function buttons() {
  const locked = busy || pickerBusy;
  $('prepare').disabled = locked || !planReady;
  $('check').disabled = locked || checking || !planReady;
  $('variant-options').disabled = locked;
  for (const id of ['load','stop','project','registry']) $(id).disabled = locked;
  for (const id of ['target','profile']) $(id).disabled = locked || !catalog;
  $('pick-project').disabled = locked || editorBusy || !token;
  $('pick-registry').disabled = $('pick-project').disabled;
  editorButtons();
}
async function plan() {
  const generation = ++planRequest;
  planReady = false;
  $('check-result').textContent = '';
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
      const runner = document.createElement('span'); runner.className='runner'; runner.textContent=step.runner.toUpperCase() + ' / ' + step.variant; name.append(runner);
      const phase = document.createElement('span'); phase.className='phase'; phase.textContent='대기';
      item.append(number,name,phase); $('plan').append(item);
    });
    $('summary').textContent = `${result.order.length}개 노드 · 아래 순서로 의존성을 준비합니다.`;
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
  return Promise.all([plan(),
    dependencyGraph.update(catalog.project, name, catalog.profiles[name].applications, variants, catalog.registry)]);
}
async function checkRequirements() {
  const generation = planRequest;
  const result = $('check-result');
  checking = true;
  result.textContent = 'Registry 실행 조건을 검사하고 있습니다…';
  buttons();
  try {
    const check = await api('/api/check', {...selection(), target:$('target').value, profile:$('profile').value, variants});
    if (generation === planRequest) {
      result.textContent = check.intellij
        ? `IDE 확인 필요 · 등록된 실행 조건을 확인했습니다. IntelliJ에서 모듈 ${check.intellij.module}과 메인 클래스 ${check.intellij.mainClass}를 확인하세요.`
        : `통과 · 선택한 앱과 의존성 ${check.order.length}개 노드의 등록된 실행 조건을 확인했습니다.`;
    }
  } catch(e) {
    if (generation === planRequest) result.textContent = `확인 필요 · ${e.message}`;
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
      if ($('badge').classList.contains('failed')) {
        $('badge').className = 'badge';
        $('badge').textContent = '대기 중';
        $('result').textContent = '실행 환경을 준비할 수 있습니다.';
      }
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
  $('check-result').textContent = '';
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
    $('project').value = catalog.project;
    $('registry').value = catalog.registry;
    $('profile').replaceChildren(...Object.keys(catalog.profiles).map(name => new Option(name,name)));
    if (Object.hasOwn(catalog.profiles, profile)) $('profile').value = profile;
    $('badge').textContent = '대기 중';
    $('badge').className = 'badge';
    $('result').textContent = result.remembered === false
      ? '경로를 불러왔습니다. 이 선택이 저장됐는지는 확인할 수 없습니다.'
      : '실행 환경을 준비할 수 있습니다.';
    buttons(); await targets($('profile').value === profile ? target : undefined);
  } catch(e) {
    if (generation !== loadRequest) return;
    dependencyGraph.reset();
    error(e.message);
  }
}

async function pickPath(kind, inEditor = false) {
  if (busy || editorBusy || pickerBusy) return;
  const button = $(inEditor ? 'registry-pick-project' : 'pick-' + kind);
  const caption = button.textContent;
  let project;
  pickerBusy = true;
  button.textContent = '선택 중…';
  buttons();
  try {
    ({project} = await api('/api/project/pick', {kind, project:(inEditor && editor?.project) || selection()[kind]}));
  } catch (e) {
    if (inEditor) registryStatus(e.message, 'error');
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
  $(kind).value = project;
  await load(true);
}
async function poll() {
  let job;
  try {
    job = await api('/api/job');
  } catch(e) {
    error(`${e.message} 작업 상태를 다시 확인합니다…`);
    timer = setTimeout(poll, 1500);
    return;
  }
  busy = job.status === 'running'; buttons();
  if (job.status === 'idle') return;
  $('badge').className='badge '+job.status;
  $('badge').textContent=({running:'진행 중', succeeded:'완료', failed:'실패'})[job.status];
  $('events').textContent=job.events.map(event => event.order ? '계획: '+event.order.join(' → ') : [event.node, phases[event.phase] || event.phase].filter(Boolean).join(' · ')).join('\n');
  job.events.forEach(event => {
    const row = [...$('plan').children].find(item => item.dataset.node === event.node);
    if (row) { const phase=row.querySelector('.phase'); phase.textContent=phases[event.phase] || event.phase; phase.className='phase '+event.phase; }
  });
  if (job.status==='succeeded') {
    const result=job.result;
    const instruction = result.externalRunConfiguration
      ? 'IntelliJ에서 아래 실행 구성을 가져온 뒤 Debug를 누르세요.'
      : `IntelliJ에서 Injector-${result.profile}-${result.target}를 선택하고 Debug를 누르세요.`;
    $('result').textContent = result.status==='stopped' ? 'Injector가 만든 의존성을 종료했습니다. IDE에서 시작한 앱은 직접 종료하세요.' : result.runConfiguration ? `준비 완료. ${instruction}\n\n${result.runConfiguration}` : '앱과 의존성이 모두 준비되었습니다.';
  } else if(job.status==='failed') error(job.error);
  else $('result').textContent='의존성을 순서대로 준비하고 있습니다…';
  if (busy) timer=setTimeout(poll, 700);
}
async function run(action) {
  busy=true; buttons(); clearTimeout(timer);
  try {
    await api('/api/'+action,{...selection(),target:$('target').value,profile:$('profile').value,variants});
    await poll();
  } catch(e) { busy=false; buttons(); error(e.message); }
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
    $('registry-text').focus({preventScroll:true});
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
    registryStatus('파일을 불러왔습니다.');
  } catch (e) {
    registryStatus(e.message, 'error');
  } finally {
    editorBusy = false;
    updateEditorFiles();
    editorButtons();
    if (editor) $('registry-text').focus({preventScroll:true});
  }
}

function hideEditor(discard) {
  if (editorBusy || pickerBusy || (discard && !discardDraft())) return;
  if (discard) {
    editor = null;
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
    const edge = report.edge ? ` · ${report.edge.caller} → ${report.edge.dependency} · ${report.profile}` : '';
    status.textContent = `${verdict}${edge}${report.reason ? ' · ' + report.reason : ''}`;
    if (report.baseline && report.candidate) {
      $('observation-before').textContent = report.baseline;
      $('observation-after').textContent = report.candidate;
      details.hidden = false;
    }
    const entries = report.changes || [];
    changes.replaceChildren(...entries.map(({path, kind}) => {
      const item = document.createElement('li');
      item.textContent = `${{added:'추가', removed:'삭제', changed:'변경'}[kind]} · ${path}`;
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
$('load').onclick=() => load(true);
$('pick-project').onclick=() => pickPath('project');
$('pick-registry').onclick=() => pickPath('registry');
$('profile').onchange=() => targets();
$('target').onchange=plan;
$('project').oninput=$('registry').oninput=() => {catalog=null; planReady=false; planRequest++; loadRequest++; $('check-result').textContent=''; $('variant-picker').hidden=true; $('target').replaceChildren(); dependencyGraph.reset(); buttons();};
$('check').onclick=checkRequirements;
$('prepare').onclick=() => run('prepare');
$('stop').onclick=() => run('stop');
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
  editorButtons();
};
window.addEventListener('beforeunload', event => {
  if (!draftChanged()) return;
  event.preventDefault();
  event.returnValue = true;
});
(async () => {
  try {
    const info=await api('/api/info');
    token=info.token;
    $('project').value=info.project;
    $('registry').value=info.registry;
    $('registries').replaceChildren(...info.registries.map(path => new Option(path, path)));
    await load();
    await poll();
  } catch(e) {error(e.message);}
})();
