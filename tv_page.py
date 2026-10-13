"""Écran TV (salle d'attente). Autonome : aucune ressource externe, WebSocket natif.
Secret médical : seul le N° de ticket, le service et le bureau sont affichés — jamais un nom.
Appariement : sans écran configuré, la TV affiche un code court (TV-4092) à saisir à l'Accueil."""
TV_HTML = r"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Écran d'appel</title>
<style>
:root{--bg:#070d18;--panel:#101a2e;--text:#f4f7fb;--muted:#93a4bd;--c:#4f9dff}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--text);font-family:'Segoe UI',Arial,sans-serif;height:100vh;display:grid;grid-template-rows:auto 1fr auto;overflow:hidden}
header{display:flex;justify-content:space-between;align-items:center;padding:1vw 2.5vw;background:var(--panel);font-size:2.3vw;font-weight:700}
#dot{display:inline-block;width:1.1vw;height:1.1vw;border-radius:50%;background:#e74c3c;margin-right:1vw}#dot.on{background:#2ecc71}
.tools button{background:#1b2a47;color:var(--text);border:0;border-radius:.8vw;font-size:2vw;padding:.2vw .9vw;margin-left:.6vw;cursor:pointer;opacity:.55}
.tools button:hover{opacity:1}
main{display:grid;grid-template-columns:2.2fr 1fr;gap:2vw;padding:2vw}
.now{background:var(--panel);border-radius:2vw;border:.6vw solid var(--c);display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;padding:1vw}
.label{font-size:2.6vw;color:var(--muted);letter-spacing:.35vw;text-transform:uppercase}
#ticket{font-size:21vw;font-weight:900;line-height:1;color:var(--c);letter-spacing:.3vw}
#service{font-size:4vw;font-weight:700;margin-top:.5vw}
#room{font-size:5vw;font-weight:800;margin-top:1.2vw;background:var(--c);color:#06101d;padding:.6vw 3vw;border-radius:1.5vw}
.flash{animation:flash .8s ease-in-out 5}@keyframes flash{50%{background:#1b2e52}}
.hist{background:var(--panel);border-radius:2vw;padding:1.6vw;overflow:hidden}
.hist h2{font-size:2vw;color:var(--muted);margin-bottom:1vw;text-transform:uppercase;letter-spacing:.2vw}
.row{display:flex;justify-content:space-between;align-items:center;padding:.9vw 1vw;margin-bottom:.8vw;border-radius:1vw;background:#0b1425;border-left:1vw solid var(--rc)}
.row b{font-size:3.4vw;color:var(--rc)}.row span{color:var(--text);font-size:1.8vw;text-align:right;line-height:1.25}
footer{padding:1vw 2.5vw;background:var(--panel);color:var(--muted);font-size:2.2vw;text-align:center;white-space:nowrap;overflow:hidden}
#msg{display:inline-block;padding-left:100%;animation:scroll 22s linear infinite;color:#ffd166;font-weight:700}
@keyframes scroll{to{transform:translateX(-100%)}}
#alerts{position:fixed;top:0;left:0;right:0;z-index:7}
.alert{font-size:3.2vw;font-weight:800;text-align:center;padding:1.1vw 2vw;color:#fff}
.alert.INFO{background:#1565c0}.alert.ALERTE{background:#ef6c00}.alert.URGENCE{background:#c62828;animation:blink .7s steps(2) infinite}
@keyframes blink{50%{background:#7f1010}}
#pause,#pair{position:fixed;inset:0;background:#070d18;display:none;align-items:center;justify-content:center;flex-direction:column;font-size:4vw;text-align:center;z-index:5;padding:3vw}
#pause{z-index:5}#pair{z-index:8}
#code{font-size:16vw;font-weight:900;color:#4f9dff;letter-spacing:.8vw;margin:2vw}
#start{position:fixed;inset:0;background:#000c;display:flex;align-items:center;justify-content:center;font-size:3vw;z-index:9;cursor:pointer}
</style></head><body>
<div id="start">🔊 Touchez l'écran pour activer le son</div>
<div id="pair"><div>Appariement de cet écran</div><div id="code">TV-····</div>
  <div style="font-size:2.4vw;color:#93a4bd">À l'Accueil : <b>Écrans TV › Appairer un écran</b> — saisissez ce code et choisissez l'écran.</div></div>
<div id="pause"><div id="pt">Veuillez patienter</div></div>
<div id="alerts"></div>
<header><div><span id="dot"></span><span id="title">Salle d'attente</span></div>
  <div class="tools"><span id="clock"></span><button id="rep" title="Répéter l'appel">📢</button><button id="spk" title="Voix (touche V)">🔊</button></div></header>
<main>
  <section class="now" id="now"><div class="label">Ticket appelé</div><div id="ticket">—</div><div id="service"></div><div id="room"></div></section>
  <section class="hist"><h2>Derniers appels</h2><div id="list"></div></section>
</main>
<footer><span id="msg">Merci de patienter — présentez-vous dès l'appel de votre numéro.</span></footer>
<script>
const $=id=>document.getElementById(id);
const LS=window.localStorage;
let recent=[],ctx=null,audioOn=false,paused=false,voiceOn=true,localMute=LS.getItem('dem_mute')==='1',last=null,screen=new URLSearchParams(location.search).get('screen')||LS.getItem('dem_screen')||'',token=LS.getItem('dem_token')||'';
const esc=s=>String(s==null?'':s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
$('start').onclick=()=>{ctx=new (window.AudioContext||window.webkitAudioContext)();audioOn=true;$('start').remove();};
function tone(freqs,dur,gap,vol){if(!ctx)return;freqs.forEach((f,i)=>{const o=ctx.createOscillator(),g=ctx.createGain(),t=ctx.currentTime+i*gap;
 o.frequency.value=f;o.connect(g);g.connect(ctx.destination);g.gain.setValueAtTime(vol,t);g.gain.exponentialRampToValueAtTime(.001,t+dur);o.start(t);o.stop(t+dur+.01);});}
const beep=()=>tone([880,1175,880],.25,.28,.4), beepAlert=()=>tone([1400,1000,1400,1000],.18,.22,.5);
/* Voix : une voix FÉMININE française est recherchée (Hortense, Julie, Denise…) ; à défaut, la première voix française disponible. */
function pickVoice(){const vs=(window.speechSynthesis?speechSynthesis.getVoices():[]).filter(v=>/^fr/i.test(v.lang));
 const fem=/hortense|julie|denise|eloise|éloïse|amelie|amélie|audrey|marie|lea|léa|female|femme|google fran/i;return vs.find(v=>fem.test(v.name))||vs[0]||null;}
if(window.speechSynthesis)speechSynthesis.onvoiceschanged=()=>pickVoice();
function speak(ev){if(!audioOn||!voiceOn||localMute||!window.speechSynthesis)return;
 const m=/^([A-Za-z]+)-0*(\d+)$/.exec(ev.ticket||'');const t=m?`Ticket ${m[1].split('').join(' ')}, numéro ${m[2]}`:`Ticket ${ev.ticket}`;
 const u=new SpeechSynthesisUtterance(`${t}, ${ev.room}`);u.lang='fr-FR';const v=pickVoice();if(v)u.voice=v;u.pitch=1.15;u.rate=.95;speechSynthesis.cancel();speechSynthesis.speak(u);}
function setState(s){if(!s)return;paused=!!s.paused;voiceOn=s.voice!==false;$('pause').style.display=paused?'flex':'none';
  $('msg').textContent=s.message||"Merci de patienter — présentez-vous dès l'appel de votre numéro.";$('pt').textContent=s.message||'Veuillez patienter';updSpk();}
function updSpk(){$('spk').textContent=(voiceOn&&!localMute)?'🔊':'🔇';}
$('spk').onclick=()=>{localMute=!localMute;LS.setItem('dem_mute',localMute?'1':'0');updSpk();};
$('rep').onclick=()=>{if(last){beep();speak(last);}};
document.addEventListener('keydown',e=>{if(e.key==='v'||e.key==='V')$('spk').click();if(e.key==='p'||e.key==='P'){LS.removeItem('dem_screen');LS.removeItem('dem_token');location.href='/tv';}});
function render(live){
  const c=recent[0],r=document.documentElement.style;
  if(c){r.setProperty('--c',/^#[0-9a-fA-F]{3,8}$/.test(c.color)?c.color:'#4f9dff');$('ticket').textContent=c.ticket;$('service').textContent=(c.icon+' '+c.service).trim();$('room').textContent=c.room;
    last=c;if(live&&!paused){const n=$('now');n.classList.remove('flash');void n.offsetWidth;n.classList.add('flash');beep();speak(c);}}
  else{$('ticket').textContent='—';$('service').textContent='';$('room').textContent='';}
  $('list').innerHTML=recent.slice(1,6).map(e=>`<div class="row" style="--rc:${esc(/^#[0-9a-fA-F]{3,8}$/.test(e.color)?e.color:'#4f9dff')}"><b>${esc(e.ticket)}</b><span>${esc(e.service)}<br>${esc(e.room)} · ${esc(e.at)}</span></div>`).join('');
}
/* Bandeaux dynamiques d'alerte / d'urgence (temporisés) */
function showAlert(a,live){document.getElementById('al-'+a.id)?.remove();const d=document.createElement('div');d.id='al-'+a.id;
  d.className='alert '+(['INFO','ALERTE','URGENCE'].includes(a.level)?a.level:'INFO');d.textContent=(a.level==='URGENCE'?'🚨 ':a.level==='ALERTE'?'⚠️ ':'ℹ️ ')+a.text;
  $('alerts').appendChild(d);if(live&&a.level!=='INFO')beepAlert();setTimeout(()=>d.remove(),Math.max(1,a.seconds)*1000);}
function connect(){
  const ws=new WebSocket((location.protocol==='https:'?'wss://':'ws://')+location.host+'/ws/tv'+(screen?'?screen='+encodeURIComponent(screen):(token?'?token='+encodeURIComponent(token):'')));
  ws.onopen=()=>$('dot').classList.add('on');
  ws.onclose=()=>{$('dot').classList.remove('on');setTimeout(connect,2000);};
  ws.onmessage=m=>{const d=JSON.parse(m.data);
    if(d.type==='snapshot'){recent=d.recent;setState(d.state);if(d.screen)$('clock').dataset.s=d.screen;$('alerts').innerHTML='';(d.announcements||[]).forEach(a=>showAlert(a,false));render(false);}
    else if(d.type==='call'){recent.unshift(d);recent=recent.slice(0,8);render(true);}
    else if(d.type==='state'){setState(d);}
    else if(d.type==='clear'){recent=[];render(false);}
    else if(d.type==='announce'){showAlert(d,true);}
    else if(d.type==='announce_clear'){if(d.id==='*')$('alerts').innerHTML='';else document.getElementById('al-'+d.id)?.remove();}};
}
async function pairing(){
  $('pair').style.display='flex';
  const r=await (await fetch('/api/tv/pair',{method:'POST'})).json();token=r.token||'';LS.setItem('dem_token',token);$('code').textContent=r.code||'TV-····';
  const t=setInterval(async()=>{try{const s=await (await fetch('/api/tv/pair/'+token)).json();
    if(s.bound){clearInterval(t);screen=s.screen;LS.setItem('dem_screen',screen);$('pair').style.display='none';$('clock').dataset.s=s.name;connect();}
    else if(!s.pending){clearInterval(t);pairing();}}catch(e){}},2000);
}
async function start(){
  try{const d=await (await fetch('/api/ping')).json();$('title').textContent=d.name;}catch(e){}
  if(screen){connect();return;}
  if(token){try{const s=await (await fetch('/api/tv/pair/'+token)).json();if(s.bound){screen=s.screen;LS.setItem('dem_screen',screen);connect();return;}}catch(e){}}
  pairing();
}
setInterval(()=>{$('clock').textContent=(($('clock').dataset.s||'')+'  '+new Date().toLocaleTimeString('fr-FR',{hour:'2-digit',minute:'2-digit'})).trim();},1000);
start();
</script></body></html>"""
