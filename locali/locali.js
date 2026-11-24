'use strict';
// Pagina pubblica «Rivendica il tuo locale»: cerca nella guida (nomi.tsv) e invia la stessa richiesta della scheda nell'app.
const API='https://ubalduqlnkubddemkmtz.supabase.co';
const KEY='eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InViYWxkdXFsbmt1YmRkZW1rbXR6Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzczNzE1MzgsImV4cCI6MjA5Mjk0NzUzOH0.mf1r62f392p6BnugWPT7Fkn7zB-tMhs2ytjwTE1MBDs';
const el=id=>document.getElementById(id);
const fold=s=>String(s||'').normalize('NFD').replace(/[̀-ͯ]/g,'').toLowerCase().replace(/[^a-z0-9]+/g,' ').trim();
let rows=[], chosen=null, role='Titolare', sending=false;
const claimId=crypto.randomUUID();

const params=new URLSearchParams(location.search);
if(params.get('citta'))el('city').value=params.get('citta').slice(0,60);

fetch('../guida-app/nomi.tsv',{signal:AbortSignal.timeout(30000)}).then(r=>{if(!r.ok)throw Error();return r.text();}).then(text=>{
  for(const line of text.split('\n')){if(!line)continue;const [key,name,city,tile]=line.split('\t');if(key&&name)rows.push({key,name,city:city||'',tile,n:fold(name),c:fold(city)});}
  el('q').disabled=false;el('status').textContent=rows.length.toLocaleString('it-IT')+' locali in tutta Italia. Scrivi almeno 2 lettere.';
  if(!matchMedia('(pointer:coarse)').matches)el('q').focus();
}).catch(()=>{el('status').textContent='Elenco non disponibile. Ricarica la pagina tra poco.';});

function search(){
  const q=fold(el('q').value), c=fold(el('city').value), list=el('results');list.replaceChildren();
  if(q.length<2){return;}
  const words=q.split(' ');const out=[];
  for(const r of rows){if(c&&!r.c.startsWith(c))continue;if(!words.every(w=>r.n.includes(w)))continue;out.push(r);if(out.length>=40)break;}
  out.sort((a,b)=>(b.n.startsWith(q)-a.n.startsWith(q))||a.n.length-b.n.length);
  for(const r of out.slice(0,12)){const li=document.createElement('li'),b=document.createElement('button');b.type='button';
    b.append(document.createTextNode(r.name));const s=document.createElement('span');s.textContent=r.city;b.append(s);b.onclick=()=>pick(r);li.append(b);list.append(li);}
  el('status').textContent=out.length?'Tocca il tuo locale.':'Nessun locale trovato. Prova con meno parole o controlla la città.';
}
let timer;for(const id of ['q','city'])el(id).addEventListener('input',()=>{clearTimeout(timer);timer=setTimeout(search,120);});

async function pick(r){
  chosen=r;el('vName').textContent=r.name;el('vWhere').textContent=r.city;
  el('search').hidden=true;el('form').hidden=false;scrollTo(0,0);
  try{const t=await (await fetch('../guida-app/t/'+r.tile+'.json')).json();
    for(const text of Object.values(t))for(const line of text.split('\n'))if(line.startsWith(r.key+'\t')){const f=line.split('\t');if(chosen===r&&f[7])el('vWhere').textContent=f[7]+', '+(f[6]||r.city);return;}
  }catch{}
}
for(const id of ['owner','phone','email'])el(id).addEventListener('input',()=>{el('error').textContent='';});
el('back').onclick=()=>{el('form').hidden=true;el('search').hidden=false;el('error').textContent='';};
for(const b of el('roles').querySelectorAll('button'))b.onclick=()=>{role=b.dataset.role;for(const o of el('roles').querySelectorAll('button'))o.setAttribute('aria-checked',String(o===b));};

function problem(f){
  if(f.owner.length<3)return 'Scrivi nome e cognome.';
  const d=f.phone.replace(/\D/g,'').length;if(d<8||d>15)return 'Controlla il numero di telefono.';
  if(f.email&&!/^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(f.email))return 'Controlla l’email, oppure lasciala vuota.';
  return '';
}
el('send').onclick=async()=>{
  if(sending||!chosen)return;
  const f={owner:el('owner').value.trim(),phone:el('phone').value.trim(),email:el('email').value.trim(),note:el('note').value.trim()};
  const p=problem(f);el('error').textContent=p;if(p)return;
  sending=true;el('send').disabled=true;el('send').textContent='Invio…';
  try{
    const r=await fetch(API+'/rest/v1/rpc/lume_venue_claim',{method:'POST',headers:{apikey:KEY,'Content-Type':'application/json'},signal:AbortSignal.timeout(15000),
      body:JSON.stringify({claim_id:claimId,place_key:('osm:'+chosen.key).slice(0,120),place_name:chosen.name.slice(0,160),city:chosen.city.slice(0,120),owner_name:f.owner,owner_role:role,phone:f.phone,email:f.email||null,note:f.note||null})});
    if(!r.ok){const t=await r.text();throw Error(/TRY_LATER/.test(t)?'Troppe richieste in questo momento. Riprova fra qualche minuto.':'Invio non riuscito. Controlla i dati e riprova.');}
    el('form').hidden=true;el('done').hidden=false;scrollTo(0,0);
  }catch(e){el('error').textContent=e.name==='TimeoutError'||e.name==='TypeError'?'Invio non riuscito. Controlla la connessione e riprova.':e.message;}
  finally{sending=false;el('send').disabled=false;el('send').textContent='Invia la richiesta';}
};
