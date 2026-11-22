'use strict';
const el=id=>document.getElementById(id);
const uid=/^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$/i;
const createNode=(tag,text,cls)=>{const n=document.createElement(tag);n.textContent=text;if(cls)n.className=cls;return n;};
let selected=[], pollId='', owner='', voter='', pending=false, lastData=null, revision=0;
const messages={CLOSED:'La votazione è chiusa.',TRY_LATER:'Ci sono molte nuove proposte. Riprova fra un minuto.',FULL:'La votazione ha raggiunto il limite di partecipanti.'};
async function rpc(name,body){
  const response=await fetch(LUME_API+'/rest/v1/rpc/lume_dinner_'+name,{method:'POST',headers:{apikey:LUME_PUBLIC_KEY,'Content-Type':'application/json'},body:JSON.stringify(body),signal:AbortSignal.timeout(12000)});
  const data=await response.json();
  if(!response.ok)throw Error(messages[data?.message]||'Il servizio di voto non è disponibile. Riprova.');
  return data;
}
function keyFor(key){let value=localStorage.getItem(key);if(!uid.test(value||'')){value=crypto.randomUUID();localStorage.setItem(key,value);}return value;}
function shareURL(){return location.origin+location.pathname+'#'+pollId;}
function note(message){el('notice').textContent=message;}
function showDraft(){
  el('draft').textContent=selected.length?selected.map(x=>x.name).join(' · '):'';
  el('create').disabled=pending||selected.length<2||selected.length>3;
}
function chooseCity(){
  selected=[];el('choices').replaceChildren();
  for(const v of LUME_VENUES.filter(v=>v.city===el('city').value)){
    const row=createNode('label','','check'),box=document.createElement('input');box.type='checkbox';
    row.append(box,document.createTextNode(v.name));el('choices').append(row);
    box.onchange=()=>{if(box.checked&&selected.length>=3){box.checked=false;note('Puoi scegliere fino a tre locali.');return;}
      selected=box.checked?[...selected,v]:selected.filter(o=>o.id!==v.id);note('');showDraft();};
  }showDraft();
}
function setup(){
  el('room').hidden=true;el('setup').hidden=false;el('retry').hidden=true;note('');
  const input=location.hash.startsWith('#prepara=')?location.hash.slice(9):'';
  if(input){try{const list=JSON.parse(decodeURIComponent(input));if(!Array.isArray(list)||list.length<2||list.length>3||list.some(v=>!v?.name||!v.id))throw Error();selected=list;el('picker').hidden=true;showDraft();return;}catch{note('La proposta non è leggibile. Puoi crearne una nuova.');}}
  el('picker').hidden=false;el('city').replaceChildren(...[...new Set(LUME_VENUES.map(v=>v.city))].sort().map(c=>new Option(c,c)));chooseCity();
}
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
    const map=createNode('a','Indicazioni','maps');map.href='https://www.google.com/maps/dir/?api=1&destination='+encodeURIComponent(v.destination||[v.name,v.address].filter(Boolean).join(', '));map.target='_blank';map.rel='noopener noreferrer';line.append(map);card.append(line);el('options').append(card);
  });
  el('until').textContent=data.closed?'I risultati restano consultabili per 30 giorni dalla creazione.':'Si chiude il '+new Date(data.endsAt).toLocaleString('it-IT',{day:'numeric',month:'long',hour:'2-digit',minute:'2-digit'})+'.';
  el('close').hidden=!owner||data.closed;el('credit').hidden=!data.options.some(v=>/^osm[-:]/.test(v.id));
  el('whatsapp').href='https://wa.me/?text='+encodeURIComponent('Dove mangiamo? Vota su Lume: '+shareURL());
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
  try{await refresh();}catch(e){note(e.message);el('retry').hidden=false;}
}
function route(){revision++;lastData=null;el('link').hidden=true;if(uid.test(location.hash.slice(1)))openRoom();else setup();}
el('city').onchange=chooseCity;
el('create').onclick=()=>act(async()=>{
  const draft=JSON.stringify(selected);const last=JSON.parse(localStorage.getItem('lume.dinner.draft')||'null');
  const secret=last?.draft===draft&&uid.test(last.secret)?last.secret:crypto.randomUUID();
  localStorage.setItem('lume.dinner.draft',JSON.stringify({draft,secret}));
  const id=await rpc('create',{owner_key:secret,venues:selected});if(!uid.test(id))throw Error('Link non disponibile. Riprova.');
  localStorage.setItem('lume.owner.'+id,secret);localStorage.removeItem('lume.dinner.draft');
  location.hash=id;
});
el('copy').onclick=async()=>{try{await navigator.clipboard.writeText(shareURL());note('Link copiato.');}catch{el('link').hidden=false;el('link').value=shareURL();el('link').select();}};
el('close').onclick=()=>act(async()=>{if(!window.confirm('Chiudere la votazione? Il gruppo potrà leggere il risultato finale.'))return;
  if(!await rpc('close',{poll_id:pollId,owner_key:owner}))throw Error('Può chiudere solo chi ha creato la votazione.');
  render(await rpc('status',{poll_id:pollId,voter_key:voter}));});
el('retry').onclick=openRoom;window.addEventListener('hashchange',route);
setInterval(()=>{if(pollId&&!pending&&!document.hidden&&lastData&&!lastData.closed)refresh().catch(()=>note('Aggiornamento in attesa. Controlla la connessione.'));},8000);
route();
