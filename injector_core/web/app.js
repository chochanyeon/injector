const $ = id => document.getElementById(id);
let token, catalog, busy = false, timer;
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
async function targets() {
  const profile = catalog.profiles[$('profile').value];
  $('target').replaceChildren(...profile.applications.map(name => new Option(name,name)));
  if (profile.targets.length) $('target').value = profile.targets[0];
  await plan();
}
async function load() {
  catalog = null; buttons();
  try {
    catalog = await api('/api/project?' + new URLSearchParams({project:$('project').value}));
    $('project').value = catalog.project;
    $('profile').replaceChildren(...Object.keys(catalog.profiles).map(name => new Option(name,name)));
    buttons(); await targets();
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
$('load').onclick=load;
$('profile').onchange=targets;
$('target').onchange=plan;
$('project').oninput=() => {catalog=null; $('target').replaceChildren(); buttons();};
$('prepare').onclick=() => run('prepare');
$('stop').onclick=() => run('stop');
(async () => {try {const info=await api('/api/info'); token=info.token; $('project').value=info.project; await load(); await poll();} catch(e) {error(e.message);}})();
