const $ = id => document.getElementById(id);
let token, catalog, busy = false, timer;
let editor, editorBusy = false;
const phases = {starting:'시작 중', waiting:'준비 확인 중', ready:'준비 완료', 'debug-ready':'Debug 가능', stopping:'종료 중'};
async function api(path, body) {
  const response = await fetch(path, body === undefined ? {} : {method:'POST', headers:{'Content-Type':'application/json', 'X-Injector-Token':token}, body:JSON.stringify(body)});
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || '요청에 실패했습니다.');
  return result;
}
function error(message) { $('result').textContent = message; $('badge').textContent = '확인 필요'; $('badge').className = 'badge failed'; }
function buttons() {
  $('prepare').disabled = busy || !$('target').value;
  for (const id of ['load','stop','project']) $(id).disabled = busy;
  for (const id of ['target','profile']) $(id).disabled = busy || !catalog;
  editorButtons();
}
async function plan() {
  $('prepare').disabled = true;
  try {
    const query = new URLSearchParams({project:$('project').value, target:$('target').value, profile:$('profile').value});
    const result = await api('/api/plan?' + query);
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
    $('prepare').disabled = busy;
  } catch(e) { error(e.message); }
}
async function targets(preferred) {
  const profile = catalog.profiles[$('profile').value];
  $('target').replaceChildren(...profile.applications.map(name => new Option(name,name)));
  if (profile.applications.includes(preferred)) $('target').value = preferred;
  else if (profile.targets.length) $('target').value = profile.targets[0];
  await plan();
}
async function load() {
  const profile = $('profile').value, target = $('target').value;
  catalog = null; buttons();
  try {
    catalog = await api('/api/project?' + new URLSearchParams({project:$('project').value}));
    $('project').value = catalog.project;
    $('profile').replaceChildren(...Object.keys(catalog.profiles).map(name => new Option(name,name)));
    if (Object.hasOwn(catalog.profiles, profile)) $('profile').value = profile;
    $('badge').textContent = '대기 중';
    $('badge').className = 'badge';
    $('result').textContent = '실행 환경을 준비할 수 있습니다.';
    buttons(); await targets($('profile').value === profile ? target : undefined);
  } catch(e) { error(e.message); }
}
async function poll() {
  const job = await api('/api/job'); busy = job.status === 'running'; buttons();
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
    $('result').textContent = result.status==='stopped' ? 'Injector가 만든 의존성을 종료했습니다. IDE에서 시작한 앱은 직접 종료하세요.' : result.runConfiguration ? `준비 완료. IntelliJ에서 Injector-${result.profile}-${result.target}를 선택하고 Debug를 누르세요.\n\n${result.runConfiguration}` : '앱과 의존성이 모두 준비되었습니다.';
  } else if(job.status==='failed') error(job.error);
  else $('result').textContent='의존성을 순서대로 준비하고 있습니다…';
  if (busy) timer=setTimeout(() => poll().catch(e => error(e.message)),700);
}
async function run(action) {
  busy=true; buttons(); clearTimeout(timer);
  try {
    await api('/api/'+action,{project:$('project').value,target:$('target').value,profile:$('profile').value});
    await poll();
  } catch(e) { busy=false; buttons(); error(e.message); }
}

function draftChanged() {
  return editor && $('registry-text').value !== editor.savedText;
}

function editorButtons() {
  $('edit-registry').disabled = !token || editorBusy || !$('project').value.trim();
  $('registry-text').disabled = editorBusy || !editor;
  $('registry-close').disabled = editorBusy;
  for (const id of ['registry-reload', 'registry-validate']) $(id).disabled = editorBusy || !editor;
  $('registry-save').disabled = busy || editorBusy || !draftChanged();
}

function registryStatus(message, state = '') {
  $('registry-status').textContent = message;
  $('registry-status').dataset.state = state;
}

function discardDraft() {
  return !draftChanged() || window.confirm('저장하지 않은 변경을 버릴까요?');
}

async function openEditor(project) {
  if (!discardDraft()) return;
  editorBusy = true;
  $('registry-editor').hidden = false;
  $('edit-registry').setAttribute('aria-expanded', 'true');
  $('registry-editor').scrollIntoView({block:'nearest'});
  editorButtons();
  registryStatus('파일을 읽는 중…');
  try {
    const result = await api('/api/registry/open', {project});
    $('registry-path').textContent = result.path;
    $('registry-text').value = result.text;
    editor = {project:result.project, revision:result.revision, savedText:$('registry-text').value};
    registryStatus('파일을 불러왔습니다.');
  } catch (e) {
    registryStatus(e.message, 'error');
  } finally {
    editorBusy = false;
    editorButtons();
    if (editor) $('registry-text').focus({preventScroll:true});
  }
}

async function checkEditor(action) {
  editorBusy = true;
  editorButtons();
  const text = $('registry-text').value;
  registryStatus(action === 'save' ? '검증 후 저장하는 중…' : '검증하는 중…');
  let location;
  try {
    const result = await api('/api/registry/' + action, {project:editor.project, text, revision:editor.revision});
    if (action === 'save') {
      editor.revision = result.revision;
      editor.savedText = text;
      if ($('project').value === result.project || catalog?.project === result.project) await load();
      registryStatus('저장했습니다.', 'success');
    } else {
      registryStatus(`검증 통과 · 스키마 ${result.schemaVersion} · 노드 ${result.nodes}개 · 프로필 ${result.profiles}개`, 'success');
    }
  } catch (e) {
    registryStatus(e.message, 'error');
    location = /line (\d+), column (\d+)/.exec(e.message);
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

$('load').onclick=load;
$('profile').onchange=() => targets();
$('target').onchange=plan;
$('project').oninput=() => {catalog=null; $('target').replaceChildren(); buttons();};
$('prepare').onclick=() => run('prepare');
$('stop').onclick=() => run('stop');
$('edit-registry').onclick = () => openEditor($('project').value.trim());
$('registry-validate').onclick = () => checkEditor('validate');
$('registry-save').onclick = () => checkEditor('save');
$('registry-reload').onclick = () => openEditor(editor.project);
$('registry-close').onclick = () => {
  if (!discardDraft()) return;
  editor = null;
  $('registry-text').value = '';
  $('registry-path').textContent = '';
  $('edit-registry').setAttribute('aria-expanded', 'false');
  $('registry-editor').hidden = true;
  editorButtons();
  $('edit-registry').focus();
};
$('registry-text').oninput = () => {
  registryStatus(draftChanged() ? '저장하지 않은 변경이 있습니다.' : '저장된 내용과 같습니다.');
  editorButtons();
};
window.addEventListener('beforeunload', event => {
  if (!draftChanged()) return;
  event.preventDefault();
  event.returnValue = true;
});
(async () => {try {const info=await api('/api/info'); token=info.token; $('project').value=info.project; await load(); await poll();} catch(e) {error(e.message);}})();
