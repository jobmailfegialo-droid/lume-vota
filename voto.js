'use strict';
const el=id=>document.getElementById(id);
const uid=/^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$/i;
const createNode=(tag,text,cls)=>{const n=document.createElement(tag);n.textContent=text;if(cls)n.className=cls;return n;};
let selected=[], pollId='', owner='', voter='', pending=false, lastData=null, revision=0, confirmingClose=false;
const messages={CLOSED:'La votazione è chiusa.',TRY_LATER:'Ci sono molte nuove proposte. Riprova fra un minuto.',FULL:'La votazione ha raggiunto il limite di partecipanti.'};
async function rpc(name,body){
  const response=await fetch(LUME_API+'/rest/v1/rpc/lume_dinner_'+name,{method:'POST',headers:{apikey:LUME_PUBLIC_KEY,'Content-Type':'application/json'},body:JSON.stringify(body),signal:AbortSignal.timeout(12000)});
  const data=await response.json();
  if(!response.ok)throw Error(messages[data?.message]||'Il servizio di voto non è disponibile. Riprova.');
  return data;
}
function keyFor(key){let value=localStorage.getItem(key);if(!uid.test(value||'')){value=crypto.randomUUID();localStorage.setItem(key,value);}return value;}
// Same wording as features/menus/pollModel.js: the link preview is shared by every poll, so the text names the venues.
function inviteText(names,link){const list=names.map(n=>String(n||'').trim()).filter(Boolean);const choice=list.length>1?list.slice(0,-1).join(', ')+' o '+list[list.length-1]:list[0]||'';return (choice?'Dove mangiamo? '+choice+'. Vota su Lume: ':'Dove mangiamo? Vota il locale su Lume: ')+link;}
function shareURL(){return location.origin+location.pathname+'#'+pollId;}
function note(message){el('notice').textContent=message;}
const key=t=>String(t||'').normalize('NFKD').replace(/[̀-ͯ]/g,'').toLowerCase().replace(/[^a-z0-9]+/g,' ').trim();
let places=null, place=null, placeVenues=[], activePlace=-1;
const shards=new Map(), LIMIT=40;
async function loadJSON(url){const r=await fetch(url,{signal:AbortSignal.timeout(15000)});if(!r.ok)throw Error('La guida non è disponibile. Riprova.');return r.json();}
function showDraft(){
  el('draftLabel').hidden=!selected.length;
  el('draft').replaceChildren(...selected.map(v=>{const li=createNode('li',v.name),x=createNode('button','✕');x.type='button';x.setAttribute('aria-label','Togli '+v.name);
    x.onclick=()=>{selected=selected.filter(o=>o.id!==v.id);showDraft();renderVenues();};li.append(x);return li;}));
  el('create').disabled=pending||selected.length<2||selected.length>3;
}
function closePlaces(){el('places').hidden=true;el('place').setAttribute('aria-expanded','false');activePlace=-1;}
function suggestPlaces(){
  const k=key(el('place').value);if(!places||k.length<2){closePlaces();return;}
  const starts=[],inside=[];
  for(const p of places.localita){const n=p._k??=key(p[0]);if(n.startsWith(k))starts.push(p);else if(inside.length<8&&n.includes(' '+k))inside.push(p);if(starts.length>=8)break;}
  const found=[...starts,...inside].slice(0,8);
  el('places').replaceChildren(...found.map((p,i)=>{const li=document.createElement('li'),b=createNode('button',p[0]+' ');b.type='button';b.id='place-'+i;b.setAttribute('role','option');
    b.append(createNode('span','('+p[1]+') · '+p[2]+(p[2]===1?' locale':' locali')));b.onclick=()=>choosePlace(p);li.append(b);return li;}));
  if(!found.length)el('places').append(createNode('li','Nessuna località con questo nome.','tiny meta'));
  el('places').hidden=false;el('place').setAttribute('aria-expanded','true');activePlace=-1;
}
async function choosePlace(p){
  closePlaces();place=p;el('place').value=p[0]+' ('+p[1]+')';note('Carico i locali…');
  try{const file='guida/z/'+p[3].toString(16).padStart(2,'0')+'.json';
    if(!shards.has(file))shards.set(file,await loadJSON(file));
    if(place!==p)return;placeVenues=shards.get(file)[p[0]+'|'+p[1]]||[];note('');
  }catch(e){note(e.message||'La guida non è disponibile. Riprova.');return;}
  el('venueBox').hidden=false;el('query').value='';renderVenues();el('query').focus();
}
function asOption(v){
  return {id:v[0],name:v[1],address:[v[3],place[0]].filter(Boolean).join(', ').slice(0,320),detail:[v[2],v[5]?'menu verificato su Lume':''].filter(Boolean).join(' · '),destination:v[4]||''};
}
function renderVenues(){
  if(!place)return;const words=key(el('query').value).split(' ').filter(Boolean);
  const hits=placeVenues.filter(v=>{const text=key(v[1]+' '+v[2]+' '+v[3]);return words.every(w=>text.includes(w));});
  el('hint').textContent=!hits.length?'Nessun locale trovato. Prova con un’altra parola.':hits.length>LIMIT?'Ne mostro '+LIMIT+' su '+hits.length+': scrivi il nome per trovare gli altri.':'';
  el('choices').replaceChildren(...hits.slice(0,LIMIT).map(v=>{
    const row=createNode('label','','check'),box=document.createElement('input'),text=createNode('span',v[1]);box.type='checkbox';box.checked=selected.some(o=>o.id===v[0]);
    if(v[5])text.append(' ',createNode('span','· menu verificato','badge'));
    const meta=[v[2],v[3]].filter(Boolean).join(' · ');if(meta)text.append(createNode('small',meta));
    row.append(box,text);
    box.onchange=()=>{if(box.checked&&selected.length>=3){box.checked=false;note('Puoi scegliere fino a tre locali.');return;}
      selected=box.checked?[...selected,asOption(v)]:selected.filter(o=>o.id!==v[0]);note('');showDraft();};
    return row;}));
}
function setup(){
  el('room').hidden=true;el('setup').hidden=false;el('retry').hidden=true;note('');
  const input=location.hash.startsWith('#prepara=')?location.hash.slice(9):'';
  if(input){try{const list=JSON.parse(decodeURIComponent(input));if(!Array.isArray(list)||list.length<2||list.length>3||list.some(v=>!v?.name||!v.id))throw Error();selected=list;el('picker').hidden=true;showDraft();return;}catch{note('La proposta non è leggibile. Puoi crearne una nuova.');}}
  el('picker').hidden=false;showDraft();if(!places)loadJSON('guida/localita.json').then(d=>{places=d;if(document.activeElement===el('place'))suggestPlaces();}).catch(e=>note(e.message));
}
function event(kind){fetch(LUME_API+'/rest/v1/rpc/lume_dinner_event',{method:'POST',headers:{apikey:LUME_PUBLIC_KEY,'Content-Type':'application/json'},body:JSON.stringify({poll_id:pollId,event_kind:kind}),keepalive:true}).catch(()=>{});}
function render(data){
  lastData=data;const total=data.counts.reduce((a,b)=>a+b,0),max=Math.max(...data.counts);
  const leaders=data.options.filter((_,i)=>total&&data.counts[i]===max);
  el('title').textContent=data.closed?'Il risultato':'Dove mangiamo?';
  el('summary').textContent=(data.closed?'Votazione chiusa. ': 'Scegli il tuo locale. ')+(total===1?'1 voto':total+' voti')+
    (leaders.length===1?' · '+(data.closed?'Ha vinto ':'In testa: ')+leaders[0].name:leaders.length>1?' · Pari merito: '+leaders.map(v=>v.name).join(' e '):'');
  el('options').replaceChildren();
  data.options.forEach((v,i)=>{
    const card=createNode('article','','card'+(data.closed&&leaders.includes(v)?' lead':''));
    card.append(createNode('h2',v.name));if(v.address)card.append(createNode('p',v.address,'meta'));if(v.detail)card.append(createNode('p',v.detail,'tiny'));
    const line=createNode('div','','line'),count=createNode('span',data.counts[i]+(data.counts[i]===1?' voto':' voti'),'count');
    const bar=createNode('div','','indicator'),fill=createNode('i','');fill.style.width=(total?100*data.counts[i]/total:0)+'%';bar.append(fill);card.append(count,bar);
    if(!data.closed){const b=createNode('button',data.myChoice===i?'Il tuo voto':'Vota');b.disabled=pending||voter===''||data.myChoice===i;b.setAttribute('aria-label',(data.myChoice===i?'Hai votato ':'Vota ')+v.name);b.onclick=()=>act(async()=>{render(await rpc('vote',{poll_id:pollId,voter_key:voter,picked:i}));note('Voto registrato. Puoi cambiarlo fino alla chiusura.');});line.append(b);}
    const map=createNode('a','Indicazioni','maps');map.href='https://www.google.com/maps/dir/?api=1&destination='+encodeURIComponent(v.destination||[v.name,v.address].filter(Boolean).join(', '));map.onclick=()=>event('directions');map.target='_blank';map.rel='noopener noreferrer';line.append(map);card.append(line);el('options').append(card);
  });
  el('until').textContent=data.closed?'I risultati restano consultabili per 30 giorni dalla creazione.':'Si chiude il '+new Date(data.endsAt).toLocaleString('it-IT',{day:'numeric',month:'long',hour:'2-digit',minute:'2-digit'})+'.';
  el('close').hidden=!owner||data.closed;el('cancelClose').hidden=!confirmingClose||data.closed;el('close').textContent=confirmingClose?'Conferma chiusura':'Chiudi la votazione';el('credit').hidden=!data.options.some(v=>/^osm[-:]/.test(v.id));
  // After voting, a signed poll offers to follow the person who sent it: that is how a vote turns into a friend on Lume.
  const host=data.host&&uid.test(data.host.id||'')?data.host:null;
  el('host').hidden=!host||!!owner||(data.myChoice==null&&!data.closed);
  if(host){el('hostText').textContent='Segui '+host.nome+' su Lume: vedrai i posti che prova e le prossime cene che propone.';el('hostLink').href='app.html#profilo/'+host.id;}
  el('whatsapp').href='https://wa.me/?text='+encodeURIComponent(inviteText(data.options.map(v=>v.name),shareURL()));
}
async function refresh(){
  const seq=++revision;const data=await rpc('status',{poll_id:pollId,voter_key:voter||null});
  if(seq!==revision||pending)return;if(!data)throw Error('Questa proposta è scaduta o il link è incompleto.');
  el('retry').hidden=true;render(data);
}
async function act(fn){
  if(pending)return;pending=true;revision++;if(lastData)render(lastData);showDraft();note('');
  try{await fn();}catch(e){note(e.message||'Operazione non riuscita. Riprova.');}finally{pending=false;if(lastData)render(lastData);showDraft();}
}
async function openRoom(){
  pollId=location.hash.slice(1);el('setup').hidden=true;el('room').hidden=false;el('close').hidden=true;
  try{voter=keyFor('lume.voter.'+pollId);owner=localStorage.getItem('lume.owner.'+pollId)||'';}catch{voter='';owner='';}
  note(voter?'':'Per registrare il voto, consenti i dati locali in questo browser.');
  try{await refresh();if(!owner&&lastData)event('received');}catch(e){note(e.message);el('retry').hidden=false;}
}
function route(){confirmingClose=false;revision++;lastData=null;el('link').hidden=true;if(uid.test(location.hash.slice(1)))openRoom();else setup();}
el('place').oninput=()=>{place=null;el('venueBox').hidden=true;suggestPlaces();};
el('place').onkeydown=e=>{const items=[...el('places').querySelectorAll('button')];if(el('places').hidden||!items.length)return;
  if(e.key==='ArrowDown'||e.key==='ArrowUp'){e.preventDefault();activePlace=(activePlace+(e.key==='ArrowDown'?1:-1)+items.length)%items.length;items.forEach((b,i)=>b.setAttribute('aria-selected',i===activePlace));el('place').setAttribute('aria-activedescendant',items[activePlace].id);}
  else if(e.key==='Enter'){e.preventDefault();(items[activePlace]||items[0]).click();}else if(e.key==='Escape')closePlaces();};
el('query').oninput=renderVenues;
el('create').onclick=()=>act(async()=>{
  const draft=JSON.stringify(selected);const last=JSON.parse(localStorage.getItem('lume.dinner.draft')||'null');
  const secret=last?.draft===draft&&uid.test(last.secret)?last.secret:crypto.randomUUID();
  localStorage.setItem('lume.dinner.draft',JSON.stringify({draft,secret}));
  const id=await rpc('create',{owner_key:secret,venues:selected});if(!uid.test(id))throw Error('Link non disponibile. Riprova.');
  localStorage.setItem('lume.owner.'+id,secret);localStorage.removeItem('lume.dinner.draft');
  location.hash=id;
});
el('copy').onclick=async()=>{try{await navigator.clipboard.writeText(shareURL());note('Link copiato.');}catch{el('link').hidden=false;el('link').value=shareURL();el('link').select();}};
el('cancelClose').onclick=()=>{confirmingClose=false;render(lastData);note('');};
el('close').onclick=()=>act(async()=>{if(!confirmingClose){confirmingClose=true;note('Conferma per rendere definitivo il risultato.');return;}
  if(!await rpc('close',{poll_id:pollId,owner_key:owner}))throw Error('Può chiudere solo chi ha creato la votazione.');
  render(await rpc('status',{poll_id:pollId,voter_key:voter}));});
el('retry').onclick=openRoom;window.addEventListener('hashchange',route);
setInterval(()=>{if(pollId&&!pending&&!document.hidden&&lastData&&!lastData.closed)refresh().catch(()=>note('Aggiornamento in attesa. Controlla la connessione.'));},8000);
route();
