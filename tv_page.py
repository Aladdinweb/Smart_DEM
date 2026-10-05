"""Écran TV (salle d'attente). Autonome : aucune ressource externe, WebSocket natif.
Secret médical : seul le N° de ticket, le service et le bureau sont affichés — jamais un nom."""
TV_HTML = r"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Écran d'appel</title>
<style>
:root{--bg:#070d18;--panel:#101a2e;--text:#f4f7fb;--muted:#93a4bd;--c:#4f9dff}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--text);font-family:'Segoe UI',Arial,sans-serif;height:100vh;display:grid;grid-template-rows:auto 1fr auto;overflow:hidden;cursor:none}
header{display:flex;justify-content:space-between;align-items:center;padding:1vw 2.5vw;background:var(--panel);font-size:2.3vw;font-weight:700}
#dot{display:inline-block;width:1.1vw;height:1.1vw;border-radius:50%;background:#e74c3c;margin-right:1vw}#dot.on{background:#2ecc71}
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
#pause{position:fixed;inset:0;background:#070d18;display:none;align-items:center;justify-content:center;flex-direction:column;font-size:4vw;text-align:center;z-index:5}
#start{position:fixed;inset:0;background:#000c;display:flex;align-items:center;justify-content:center;font-size:3vw;z-index:9;cursor:pointer}
</style></head><body>
<div id="start">🔊 Touchez l'écran pour activer le son</div>
<div id="pause"><div id="pt">Veuillez patienter</div></div>
<header><div><span id="dot"></span><span id="title">Salle d'attente</span></div><div id="clock"></div></header>
<main>
  <section class="now" id="now"><div class="label">Ticket appelé</div><div id="ticket">—</div><div id="service"></div><div id="room"></div></section>
  <section class="hist"><h2>Derniers appels</h2><div id="list"></div></section>
</main>
<footer><span id="msg">Merci de patienter — présentez-vous dès l'appel de votre numéro.</span></footer>
<script>
const $=id=>document.getElementById(id);let recent=[],ctx=null,audioOn=false,paused=false;const SCREEN=new URLSearchParams(location.search).get('screen')||'';
const esc=s=>String(s==null?'':s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
$('start').onclick=()=>{ctx=new (window.AudioContext||window.webkitAudioContext)();audioOn=true;$('start').remove();};
function beep(){if(!ctx)return;[880,1175,880].forEach((f,i)=>{const o=ctx.createOscillator(),g=ctx.createGain(),t=ctx.currentTime+i*.28;
 o.frequency.value=f;o.connect(g);g.connect(ctx.destination);g.gain.setValueAtTime(.4,t);g.gain.exponentialRampToValueAtTime(.001,t+.25);o.start(t);o.stop(t+.26);});}
function speak(t){if(!audioOn||!window.speechSynthesis)return;const u=new SpeechSynthesisUtterance(t);u.lang='fr-FR';speechSynthesis.speak(u);}
function setState(s){if(!s)return;paused=!!s.paused;$('pause').style.display=paused?'flex':'none';
  $('msg').textContent=s.message||"Merci de patienter — présentez-vous dès l'appel de votre numéro.";$('pt').textContent=s.message||'Veuillez patienter';}
function render(live){
  const c=recent[0],r=document.documentElement.style;
  if(c){r.setProperty('--c',c.color||'#4f9dff');$('ticket').textContent=c.ticket;$('service').textContent=(c.icon+' '+c.service).trim();$('room').textContent=c.room;
    if(live&&!paused){const n=$('now');n.classList.remove('flash');void n.offsetWidth;n.classList.add('flash');beep();
      speak('Ticket '+c.ticket.replace('-',' ')+', '+c.service+', '+c.room);}}
  else{$('ticket').textContent='—';$('service').textContent='';$('room').textContent='';}
  $('list').innerHTML=recent.slice(1,6).map(e=>`<div class="row" style="--rc:${esc(/^#[0-9a-fA-F]{3,8}$/.test(e.color)?e.color:'#4f9dff')}"><b>${esc(e.ticket)}</b><span>${esc(e.service)}<br>${esc(e.room)} · ${esc(e.at)}</span></div>`).join('');
}
function connect(){
  const ws=new WebSocket((location.protocol==='https:'?'wss://':'ws://')+location.host+'/ws/tv'+(SCREEN?'?screen='+encodeURIComponent(SCREEN):''));
  ws.onopen=()=>$('dot').classList.add('on');
  ws.onclose=()=>{$('dot').classList.remove('on');setTimeout(connect,2000);};
  ws.onmessage=m=>{const d=JSON.parse(m.data);
    if(d.type==='snapshot'){recent=d.recent;setState(d.state);if(d.screen)$('clock').dataset.s=d.screen;render(false);}
    else if(d.type==='call'){recent.unshift(d);recent=recent.slice(0,8);render(true);}
    else if(d.type==='state'){setState(d);}
    else if(d.type==='clear'){recent=[];render(false);}};
}
fetch('/api/ping').then(r=>r.json()).then(d=>{$('title').textContent=d.name;}).catch(()=>{});
setInterval(()=>{$('clock').textContent=(($('clock').dataset.s||'')+'  '+new Date().toLocaleTimeString('fr-FR',{hour:'2-digit',minute:'2-digit'})).trim();},1000);
connect();
</script></body></html>"""
