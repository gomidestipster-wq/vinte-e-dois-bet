const $=s=>document.querySelector(s), $$=s=>document.querySelectorAll(s);
let tab="sports", openId=null, slip=null, pollEv=null, crashId=null, crashTimer=null, authMode="login";
const fmtB=c=>(c/100).toLocaleString("pt-BR",{style:"currency",currency:"BRL"});

async function api(p,o={}){
  const r=await fetch(p,{method:o.method||"GET",headers:{"Content-Type":"application/json"},credentials:"same-origin",body:o.body?JSON.stringify(o.body):undefined});
  let d={}; try{d=await r.json()}catch(e){}
  if(!r.ok) throw new Error(typeof d.detail==="string"?d.detail:("erro "+r.status));
  return d;
}
function toast(m,err){const t=$("#toast");t.textContent=m;t.className=err?"err":"";setTimeout(()=>t.className="",2800);}
async function me(){try{return await api("/api/me")}catch(e){return null}}

async function boot(){
  const u=await me();
  if(!u){$("#auth").classList.remove("hide")}else{$("#btnSair").classList.remove("hide");refreshTop();renderTab();}
}
$("#aToggle").onclick=()=>{
  authMode=authMode==="login"?"reg":"login";
  const reg=authMode==="reg";
  $("#aBtn").textContent=reg?"criar":"entrar";
  $("#aBd").classList.toggle("hide",!reg);
  $("#aName").classList.toggle("hide",!reg);
  $("#authMsg").textContent="";
};
$("#aBtn").onclick=async()=>{
  try{
    const cpf=$("#aCpf").value.replace(/\D/g,"");
    if(authMode==="login"){await api("/api/login",{method:"POST",body:{cpf,password:$("#aPass").value}})}
    else await api("/api/register",{method:"POST",body:{name:$("#aName").value||"jogador",cpf,birth_date:$("#aBd").value,password:$("#aPass").value}});
    $("#auth").classList.add("hide");$("#btnSair").classList.remove("hide");refreshTop();renderTab();
  }catch(e){$("#authMsg").textContent=e.message}
};
$("#btnSair").onclick=async()=>{await fetch("/api/logout",{method:"POST"});location.reload()};
async function refreshTop(){const u=await me();if(u)$("#bal").textContent=fmtB(u.balance_brl)+" · "+(u.balance_usdt/100).toFixed(2)+"$"}

$("#tabs").addEventListener("click",e=>{const b=e.target.closest("button");if(!b)return;setTab(b.dataset.tab)});
function setTab(t){tab=t;$$("#tabs button").forEach(x=>x.classList.toggle("on",x.dataset.tab===t));clearPoll();slip=null;paintSlip();renderTab()}
function clearPoll(){if(pollEv){clearInterval(pollEv);pollEv=null}if(crashTimer){clearInterval(crashTimer);crashTimer=null}}

async function renderTab(){
  clearPoll();
  const v=$("#view");
  if(tab==="casino"){v.innerHTML=cashinoShell();bindCrash();return}
  if(tab==="wallet"){showWallet();return}
  try{
    const q={sports:"kind=FOOTBALL&status=SCHEDULED",live:"kind=FOOTBALL&status=LIVE",politics:"kind=POLITICS"}[tab];
    const r=await api("/api/events?"+q);
    const evs=r.events;
    if(!evs.length){v.innerHTML='<div class="empty">nada por aqui ainda.<br>a casa abre mercado o tempo todo.</div>';return}
    v.innerHTML=evs.map(evCard).join("");
    $$("#view [data-ev]").forEach(el=>el.onclick=()=>openEvent(+el.dataset.ev));
    if(tab==="live")pollEv=setInterval(renderTab,3000);
  }catch(e){v.innerHTML='<div class="empty">'+e.message+'</div>'}
}
function evCard(e){
  const badge=e.status==="LIVE"?'<span class="liv">● AO VIVO</span>':'<span class="pre">'+(e.starts_at?new Date(e.starts_at).toLocaleString("pt-BR",{day:"2-digit",month:"2-digit",hour:"2-digit",minute:"2-digit"}):"em breve")+'</span>';
  return '<div class="ev" data-ev="'+e.id+'"><div class="ev-t">'+e.title+'</div><div class="ev-s">'+(e.league?'<span>'+e.league+'</span> ':"")+badge+'</div></div>';
}

async function openEvent(id){openId=id;slip=null;paintSlip();await renderEvent()}
async function renderEvent(){
  clearPoll();
  try{
    const e=await api("/api/events/"+openId);
    $("#view").innerHTML='<button class="back" id="bk">← voltar</button>'+
      '<h2>'+e.title+'</h2>'+
      (e.state&&e.state.minute?'<div class="score">'+e.state.sh+' × '+e.state.sa+' <span class="min">min '+e.state.minute+'</span></div>':"")+
      e.markets.filter(m=>m.status==="OPEN").map(mkCard).join("")||'<div class="empty">mercados fechados</div>';
    $("#bk").onclick=()=>{openId=null;paintSlip();renderTab()};
    $$("#view .odd").forEach(b=>b.onclick=()=>{
      const mk=b.dataset.mk;
      slip=(slip&&slip.mk===mk)?null:{mk:+mk,o:+b.dataset.o,label:b.dataset.l,odd:+b.dataset.v,cap:+b.dataset.cap};
      paintSlip();paintSel(mk);
    });
    if(e.status==="LIVE")pollEv=setInterval(renderEvent,3000);
  }catch(err){toast(err.message,true)}
}
function mkCard(m){
  return '<section class="mk"><h3>'+m.title+'<span class="cap"> máx '+fmtB(m.cap_cents)+'</span></h3>'+
    m.outcomes.map(o=>'<button class="odd" data-mk="'+m.id+'" data-o="'+o.id+'" data-l="'+o.label+'" data-v="'+o.odd+'" data-cap="'+m.cap_cents+'"><i>'+o.label+'</i><b>'+o.odd.toFixed(2)+'</b></button>').join("")+
    '</section>';
}
function paintSel(mk){$$("#view .odd").forEach(b=>b.classList.toggle("sel",!!(slip&&+b.dataset.mk===+mk&&+b.dataset.o===slip.o)))}
function paintSlip(){
  const s=$("#slipbar");
  if(!slip||openId===null){s.classList.add("hide");return}
  s.classList.remove("hide");
  s.innerHTML='<div class="slip-info"><b>'+slip.label+'</b> @ '+slip.odd.toFixed(2)+
    '<input id="stake" type="number" inputmode="decimal" value="10" min="0.10" step="0.10" max="'+(Math.min(slip.cap,500000)/100)+'"></div>'+
    '<div class="slip-pot">retorna <b id="pot">'+fmtB(Math.round(1000*slip.odd))+'</b></div>'+
    '<button id="go" class="gold">apostar</button>';
  const st=$("#stake");
  st.oninput=()=>{$("#pot").textContent=fmtB(Math.round((+st.value||0)*100*slip.odd))};
  $("#go").onclick=async()=>{
    const cents=Math.round((+st.value||0)*100);
    try{
      const r=await api("/api/bets",{method:"POST",body:{market_id:slip.mk,outcome_id:slip.o,stake_cents:cents,currency:"BRL"}});
      let msg="fechou "+slip.label+" a "+r.odd.toFixed(2)+" → "+fmtB(r.potential_cents);
      if(r.moves.length)msg+=" · linha ajustou: "+r.moves.map(m=>m.hot+" "+m.from.toFixed(2)+"→"+m.to.toFixed(2)).join(", ");
      toast(msg);slip=null;refreshTop();renderEvent();
    }catch(e){toast(e.message,true)}
  };
}

$("#btnCarteira").onclick=()=>{tab="wallet";renderTab()};
async function showWallet(){
  const v=$("#view");
  v.innerHTML='<div class="wallet"><h2>carteira</h2>'+
    '<h4>depositar</h4><div class="wform"><input id="depBrl" type="number" inputmode="decimal" placeholder="valor"><select id="depCur"><option>BRL</option><option>USDT</option></select><button id="depGo" class="gold">gerar</button></div><div id="depMsg" class="msg"></div>'+
    '<h4>sacar</h4><div class="wform"><input id="wdBrl" type="number" inputmode="decimal" placeholder="valor"><input id="wdDest" placeholder="chave PIX ou endereço USDT"><select id="wdCur"><option>BRL</option><option>USDT</option></select><button id="wdGo" class="gold">solicitar</button></div><div id="wdMsg" class="msg"></div>'+
    '<h4>movimentos</h4><div id="txl"></div>'+
    '<div class="wform" style="margin-top:14px"><input id="seDays" type="number" value="30" min="1" placeholder="dias"><button id="seGo" class="linkbtn">autoexcluir por N dias</button></div>'+
    '<button class="back" id="wx" style="margin-top:14px">← fechar</button></div>';
  $("#wx").onclick=()=>setTab("sports");
  const paint=async()=>{
    const u=await me();if(!u)return;
    const t=await api("/api/wallet/txs");
    $("#txl").innerHTML=t.txs.map(x=>'<div class="txl-i"><span class="'+(x.amount_cents>=0?"plus":"minus")+'">'+(x.currency==="BRL"?fmtB(x.amount_cents):(x.amount_cents/100).toFixed(2)+" USDT")+'</span> '+x.kind+'</div>').join("")||"<div class='empty'>nenhum movimento</div>";
  };
  await paint();
  $("#depGo").onclick=async()=>{
    try{
      const cur=$("#depCur").value;
      const r=await api("/api/wallet/deposit",{method:"POST",body:{amount_cents:Math.round((+$("#depBrl").value||0)*100),currency:cur,method:cur==="BRL"?"PIX":"USDT"}});
      let html;
      if(cur==="BRL"&&r.qr){
        html='<div style="display:flex;gap:12px;align-items:flex-start"><img src="'+r.qr+'" alt="QR" style="width:180px;height:180px;border-radius:10px">'
          +'<div><div class="msg">escaneie com o app do banco</div>'
          +'<input id="copyEmv" readonly value="'+r.emv+'" style="width:230px;font-size:10px;margin-top:6px">'
          +'<div style="margin-top:6px"><button class="linkbtn" onclick="copyEmv()">copiar copia-e-cola</button></div></div></div>';
      }else if(cur==="BRL"){
        html="aguardando PIX — identificador <b>"+r.txid+"</b> (a sua gateway confirma na hora; senão a casa confirma no console)";
      }else{
        html="envie <b>"+(($("#depBrl").value||0))+" USDT</b> (<b>rede Solana</b>) para <b>"+r.usdt_address+"</b> — identificador <b>"+r.txid+"</b>";
      }
      $("#depMsg").innerHTML=html;
      if(cur==="BRL")pollDep(r.txid);
    }catch(e){$("#depMsg").textContent=e.message}
  };
  $("#wdGo").onclick=async()=>{
    try{
      await api("/api/wallet/withdraw",{method:"POST",body:{amount_cents:Math.round((+$("#wdBrl").value||0)*100),currency:$("#wdCur").value,dest:$("#wdDest").value}});
      $("#wdMsg").textContent="solicitado — a casa libera em seguida";paint();
    }catch(e){$("#wdMsg").textContent=e.message}
  };
  $("#seGo").onclick=async()=>{try{await fetch("/api/me/self-exclude?days="+$("#seDays").value,{method:"POST"});toast("autoexclusão ativada")}catch(e){toast(e.message,true)}};
}

// ---------------- cassino: crash ----------------
function cashinoShell(){
  return '<div class="crash"><canvas id="cv" width="360" height="220"></canvas><div id="crashBig">pronto</div>'+
   '<div class="wform"><input id="csStake" type="number" value="5" min="0.10" step="0.10"><select id="csCur"><option>BRL</option><option>USDT</option></select>'+
   '<button id="csGo" class="gold">apostar</button><button id="csCash" class="gold cash hide">RESGATAR</button></div><div id="crashMsg" class="msg"></div></div>';
}
function bindCrash(){
  drawIdle();
  $("#csGo").onclick=async()=>{
    if(crashTimer)return;
    try{
      const cur=$("#csCur").value;
      const r=await api("/api/crash/start",{method:"POST",body:{client_seed:Math.random().toString(36).slice(2),currency:cur,stake_cents:Math.round((+$("#csStake").value||0)*100)}});
      crashId=r.round_id;pts=[];
      $("#crashMsg").innerHTML="na sorte… (prova: "+r.round_id+")";
      $("#csCash").classList.remove("hide");
      tick();crashTimer=setInterval(tick,200);refreshTop();
    }catch(e){$("#crashMsg").textContent=e.message}
  };
  $("#csCash").onclick=async()=>{
    try{
      const r=await api("/api/crash/"+crashId+"/cashout",{method:"POST"});
      $("#crashMsg").innerHTML="resgatou a "+r.mult.toFixed(2)+"× — <b>"+fmtB(r.cashout_cents)+"</b>";
      stopCrash();refreshTop();
    }catch(e){$("#crashMsg").textContent=e.message;stopCrash()}
  };
}
let pts=[];
function stopCrash(){if(crashTimer){clearInterval(crashTimer);crashTimer=null}crashId=null;$("#csCash").classList.add("hide")}
async function tick(){
  if(!crashId)return;
  try{
    const r=await api("/api/crash/"+crashId);
    pts.push(r.mult);if(pts.length>150)pts.shift();
    drawCv(pts,r.mult,r.status);
    $("#crashBig").textContent=r.mult.toFixed(2)+"×"+(r.cashed_mult?" (resgatado "+r.cashed_mult.toFixed(2)+"×)":"");
    if(r.status==="CRASHED"){
      $("#crashMsg").innerHTML="crash em <b>"+r.crash_point.toFixed(2)+"×</b> · prova: <code>"+r.server_seed.slice(0,12)+"…|"+r.client_seed.slice(0,8)+"</code>";
      stopCrash();
    }
  }catch(e){stopCrash()}
}
function drawIdle(){const cv=$("#cv");if(cv){const c=cv.getContext("2d");c.fillStyle="#11161d";c.fillRect(0,0,cv.width,cv.height);c.strokeStyle="#f5c518";c.font="20px sans-serif";c.fillText("22 CRASH",20,40)}}
function drawCv(pts,m,st){
  const cv=$("#cv");if(!cv)return;const ctx=cv.getContext("2d");
  ctx.clearRect(0,0,cv.width,cv.height);
  const max=Math.max(2,m*1.15);
  ctx.beginPath();
  pts.forEach((p,i)=>{
    const x=i/(150-1)*cv.width, y=cv.height-((Math.min(p,max)-1)/(max-1))*cv.height;
    i?ctx.lineTo(x,y):ctx.moveTo(x,y);
  });
  ctx.strokeStyle=st==="CRASHED"?"#ff5c5c":"#f5c518";ctx.lineWidth=2;ctx.stroke();
}
function copyEmv(){var el=document.getElementById("copyEmv");if(el&&navigator.clipboard)navigator.clipboard.writeText(el.value)}
function pollDep(txid){var t=setInterval(async function(){try{var s=await api("/api/wallet/deposit-status?txid="+encodeURIComponent(txid));if(s.status==="DONE"){clearInterval(t);$("#depMsg").innerHTML="<b class='plus'>pix confirmado ✓</b> saldo atualizado";refreshTop();}}catch(e){clearInterval(t);}},4000);setTimeout(function(){clearInterval(t)},120000);}
boot();
