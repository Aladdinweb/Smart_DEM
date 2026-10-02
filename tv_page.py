"""Page de l'écran TV (salle d'attente). Autonome : aucune ressource externe, WebSocket natif."""
TV_HTML = r"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Écran d'appel</title>
<style>
:root{--bg:#0b1220;--panel:#121b2e;--accent:#4f9dff;--text:#f2f5fa;--muted:#8fa0b8}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--text);font-family:'Segoe UI',Arial,sans-serif;height:100vh;display:grid;grid-template-rows:auto 1fr auto;overflow:hidden;cursor:none}
header{display:flex;justify-content:space-between;align-items:center;padding:1.2vw 2.5vw;background:var(--panel);font-size:2.2vw;font-weight:600}
#dot{display:inline-block;width:1.1vw;height:1.1vw;border-radius:50%;background:#e74c3c;margin-right:1vw}
#dot.on{background:#2ecc71}
main{display:grid;grid-template-columns:2fr 1fr;gap:2vw;padding:2vw}
.now{background:var(--panel);border-radius:2vw;display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;padding:2vw}
.label{font-size:2.4vw;color:var(--muted);letter-spacing:.3vw;text-transform:uppercase}
#ticket{font-size:16vw;font-weight:800;line-height:1.05}
#service{font-size:3.4vw;margin-top:1vw}
#room{font-size:3vw;color:var(--accent);margin-top:1.2vw;font-weight:600}
.flash{animation:flash .9s ease-in-out 4}
@keyframes flash{50%{background:#1d4ed8}}
.hist{background:var(--panel);border-radius:2vw;padding:2vw;overflow:hidden}
.hist h2{font-size:2vw;color:var(--muted);margin-bottom:1vw;text-transform:uppercase;letter-spacing:.2vw}
.row{display:flex;justify-content:space-between;align-items:center;padding:1vw 0;border-bottom:1px solid #22304a;font-size:2.4vw}
.row b{font-size:2.8vw}.row span{color:var(--muted);font-size:1.7vw;text-align:right}
footer{padding:1vw 2.5vw;color:var(--muted);font-size:1.8vw;text-align:center}
#start{position:fixed;inset:0;background:#000c;display:flex;align-items:center;justify-content:center;font-size:3vw;z-index:9;cursor:pointer}
</style></head><body>
<div id="start">🔊 Touchez l'écran pour activer le son</div>
<header><div><span id="dot"></span><span id="title">Salle d'attente</span></div><div id="clock"></div></header>
<main>
  <section class="now" id="now"><div class="label">Ticket appelé</div><div id="ticket">—</div>
    <div id="service"></div><div id="room"></div></section>
  <section class="hist"><h2>Derniers appels</h2><div id="list"></div></section>
</main>
<footer>Merci de patienter — présentez-vous dès l'appel de votre numéro.</footer>
<script>
const $=id=>document.getElementById(id);let recent=[],ctx=null,audioOn=false;
$('start').onclick=()=>{ctx=new (window.AudioContext||window.webkitAudioContext)();audioOn=true;$('start').remove();};
function beep(){if(!ctx)return;[880,1175].forEach((f,i)=>{const o=ctx.createOscillator(),g=ctx.createGain(),t=ctx.currentTime+i*.28;
 o.frequency.value=f;o.connect(g);g.connect(ctx.destination);g.gain.setValueAtTime(.35,t);g.gain.exponentialRampToValueAtTime(.001,t+.25);o.start(t);o.stop(t+.26);});}
function speak(t){if(!audioOn||!window.speechSynthesis)return;const u=new SpeechSynthesisUtterance(t);u.lang='fr-FR';speechSynthesis.speak(u);}
function render(live){
  const c=recent[0];
  if(c){$('ticket').textContent=c.ticket;$('service').textContent=(c.icon+' '+c.service).trim();$('room').textContent=c.room;
    if(live){const n=$('now');n.classList.remove('flash');void n.offsetWidth;n.classList.add('flash');beep();
      speak('Ticket '+c.ticket.replace('-',' ')+', '+c.service+', '+c.room);}}
  $('list').innerHTML=recent.slice(1,7).map(e=>`<div class="row"><b>${e.ticket}</b><span>${e.service}<br>${e.room} · ${e.at}</span></div>`).join('');
}
function connect(){
  const ws=new WebSocket((location.protocol==='https:'?'wss://':'ws://')+location.host+'/ws/tv');
  ws.onopen=()=>$('dot').classList.add('on');
  ws.onclose=()=>{$('dot').classList.remove('on');setTimeout(connect,2000);};
  ws.onmessage=m=>{const d=JSON.parse(m.data);
    if(d.type==='snapshot'){recent=d.recent;render(false);}
    else if(d.type==='call'){recent.unshift(d);recent=recent.slice(0,8);render(true);}};
}
fetch('/api/ping').then(r=>r.json()).then(d=>{$('title').textContent=d.name;}).catch(()=>{});
setInterval(()=>{$('clock').textContent=new Date().toLocaleTimeString('fr-FR',{hour:'2-digit',minute:'2-digit'});},1000);
connect();
</script></body></html>"""
