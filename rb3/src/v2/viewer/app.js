// rb3 v2 viewer — raw WebGL lines, no external anything.
const DIACOL = {8:'--d8',10:'--d10',12:'--d12',16:'--d16',20:'--d20',25:'--d25',32:'--d32'};
const cssv = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
function hex2rgb(h){h=h.replace('#','');
  if(h.length===3)h=h.split('').map(c=>c+c).join('');
  return [parseInt(h.slice(0,2),16)/255,parseInt(h.slice(2,4),16)/255,parseInt(h.slice(4,6),16)/255];}
const colOf = d => hex2rgb(cssv(DIACOL[Math.round(d)]||'--d32'));

const cv=document.getElementById('gl');
const gl=cv.getContext('webgl',{antialias:true,alpha:false});
const VS=`attribute vec3 p;attribute vec3 c;uniform mat4 mvp;varying vec3 vc;
void main(){vc=c;gl_Position=mvp*vec4(p,1.0);}`;
const FS=`precision mediump float;varying vec3 vc;void main(){gl_FragColor=vec4(vc,1.0);}`;
function sh(t,s){const o=gl.createShader(t);gl.shaderSource(o,s);gl.compileShader(o);
  if(!gl.getShaderParameter(o,gl.COMPILE_STATUS))throw gl.getShaderInfoLog(o);return o;}
const prog=gl.createProgram();
gl.attachShader(prog,sh(gl.VERTEX_SHADER,VS));gl.attachShader(prog,sh(gl.FRAGMENT_SHADER,FS));
gl.linkProgram(prog);gl.useProgram(prog);
const aP=gl.getAttribLocation(prog,'p'),aC=gl.getAttribLocation(prog,'c');
const uM=gl.getUniformLocation(prog,'mvp');
const bufP=gl.createBuffer(),bufC=gl.createBuffer();

const mul=(a,b)=>{const o=new Float32Array(16);
  for(let i=0;i<4;i++)for(let j=0;j<4;j++){let s=0;for(let k=0;k<4;k++)s+=a[k*4+j]*b[i*4+k];o[i*4+j]=s;}return o;};
function persp(f,ar,n,fa){const t=1/Math.tan(f/2);return new Float32Array(
  [t/ar,0,0,0, 0,t,0,0, 0,0,(fa+n)/(n-fa),-1, 0,0,2*fa*n/(n-fa),0]);}
function lookAt(e,c,u){
  const s=(a,b)=>[a[0]-b[0],a[1]-b[1],a[2]-b[2]];
  const nz=(v)=>{const l=Math.hypot(...v)||1;return [v[0]/l,v[1]/l,v[2]/l];};
  const cr=(a,b)=>[a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]];
  const f=nz(s(c,e)),r=nz(cr(f,u)),v=cr(r,f);
  return new Float32Array([r[0],v[0],-f[0],0, r[1],v[1],-f[1],0, r[2],v[2],-f[2],0,
    -(r[0]*e[0]+r[1]*e[1]+r[2]*e[2]),-(v[0]*e[0]+v[1]*e[1]+v[2]*e[2]),
     (f[0]*e[0]+f[1]*e[1]+f[2]*e[2]),1]);}

let cam={az:-0.9,el:0.32,dist:1,tx:0,ty:0,tz:0};
let spin=false, showBox=true, showDrawn=false;
let cur=null, nvert=0, lastMVP=null;
let visDia=new Set(), visMark=new Set(), picked=[];

// ---------------------------------------------------------------- geometry
const barVisible = b => visDia.has(Math.round(b.dia)) && (!b.mark || visMark.has(b.mark));

function buildBuffers(){
  const m=MODEL[cur], P=[], C=[];
  for(const b of m.bars){
    if(!barVisible(b)) continue;
    const isPick = picked.some(p=>p.bar===b);
    let c = isPick ? [1,1,1] : colOf(b.dia);
    for(let i=0;i<b.pts.length-1;i++){P.push(...b.pts[i],...b.pts[i+1]);C.push(...c,...c);}
  }
  if(showDrawn){
    const c=hex2rgb(cssv('--drawn'));
    for(const s of (OVERLAY[cur]||[])){
      if(!visDia.has(Math.round(s[6]))) continue;
      P.push(s[0],s[1],s[2],s[3],s[4],s[5]);C.push(...c,...c);
    }
  }
  if(showBox){
    const e=m.envelope,W=e.width_mm,T=e.thickness_mm||200,H=e.height_mm;
    const g=hex2rgb(cssv('--line'));
    const V=[[0,0,0],[W,0,0],[0,T,0],[W,T,0],[0,0,H],[W,0,H],[0,T,H],[W,T,H]];
    const E=[[0,1],[0,2],[1,3],[2,3],[4,5],[4,6],[5,7],[6,7],[0,4],[1,5],[2,6],[3,7]];
    for(const [a,b] of E){P.push(...V[a],...V[b]);C.push(...g,...g);}
  }
  if(picked.length===2 && picked[0].seg && picked[1].seg){
    const w=[1,1,1], p=picked[0].closest, q=picked[1].closest;
    P.push(...p,...q);C.push(...w,...w);
  }
  gl.bindBuffer(gl.ARRAY_BUFFER,bufP);
  gl.bufferData(gl.ARRAY_BUFFER,new Float32Array(P),gl.STATIC_DRAW);
  gl.bindBuffer(gl.ARRAY_BUFFER,bufC);
  gl.bufferData(gl.ARRAY_BUFFER,new Float32Array(C),gl.STATIC_DRAW);
  nvert=P.length/3;
}
function fit(){
  const e=MODEL[cur].envelope;
  cam.tx=e.width_mm/2;cam.ty=(e.thickness_mm||200)/2;cam.tz=e.height_mm/2;
  cam.dist=Math.max(e.width_mm,e.height_mm)*1.25;
}
function draw(){
  const w=cv.clientWidth,h=cv.clientHeight,dpr=Math.min(devicePixelRatio||1,2);
  if(cv.width!==w*dpr||cv.height!==h*dpr){cv.width=w*dpr;cv.height=h*dpr;}
  gl.viewport(0,0,cv.width,cv.height);
  const bg=hex2rgb(cssv('--stage'));gl.clearColor(bg[0],bg[1],bg[2],1);
  gl.enable(gl.DEPTH_TEST);gl.clear(gl.COLOR_BUFFER_BIT|gl.DEPTH_BUFFER_BIT);
  const eye=[cam.tx+cam.dist*Math.cos(cam.el)*Math.cos(cam.az),
             cam.ty+cam.dist*Math.cos(cam.el)*Math.sin(cam.az),
             cam.tz+cam.dist*Math.sin(cam.el)];
  const mvp=mul(persp(0.85,w/h,cam.dist*0.02,cam.dist*8),
                lookAt(eye,[cam.tx,cam.ty,cam.tz],[0,0,1]));
  lastMVP=mvp;
  gl.uniformMatrix4fv(uM,false,mvp);
  gl.bindBuffer(gl.ARRAY_BUFFER,bufP);gl.enableVertexAttribArray(aP);
  gl.vertexAttribPointer(aP,3,gl.FLOAT,false,0,0);
  gl.bindBuffer(gl.ARRAY_BUFFER,bufC);gl.enableVertexAttribArray(aC);
  gl.vertexAttribPointer(aC,3,gl.FLOAT,false,0,0);
  gl.drawArrays(gl.LINES,0,nvert);
  if(spin){cam.az+=0.0035;}
  requestAnimationFrame(draw);
}

// -------------------------------------------------------------- interaction
let drag=null, downAt=null;
cv.addEventListener('pointerdown',e=>{drag={x:e.clientX,y:e.clientY,b:e.button};
  downAt=[e.clientX,e.clientY];cv.setPointerCapture(e.pointerId);});
cv.addEventListener('pointerup',e=>{
  if(downAt&&Math.hypot(e.clientX-downAt[0],e.clientY-downAt[1])<5) pickAt(e);
  drag=null;});
cv.addEventListener('pointermove',e=>{
  if(!drag)return;
  const dx=e.clientX-drag.x,dy=e.clientY-drag.y;drag.x=e.clientX;drag.y=e.clientY;
  if(drag.b===2||e.shiftKey){
    const k=cam.dist*0.0016;
    cam.tx+=dx*k*Math.sin(cam.az);cam.ty-=dx*k*Math.cos(cam.az);cam.tz+=dy*k;
  }else{cam.az-=dx*0.008;cam.el=Math.max(-1.5,Math.min(1.5,cam.el+dy*0.008));}
});
cv.addEventListener('contextmenu',e=>e.preventDefault());
cv.addEventListener('wheel',e=>{e.preventDefault();cam.dist*=Math.exp(e.deltaY*0.0012);},
  {passive:false});

function proj(p){ // world -> css pixels, or null behind the camera
  const m=lastMVP;if(!m)return null;
  const x=m[0]*p[0]+m[4]*p[1]+m[8]*p[2]+m[12];
  const y=m[1]*p[0]+m[5]*p[1]+m[9]*p[2]+m[13];
  const w=m[3]*p[0]+m[7]*p[1]+m[11]*p[2]+m[15];
  if(w<=0)return null;
  return [(x/w*0.5+0.5)*cv.clientWidth,(0.5-y/w*0.5)*cv.clientHeight,w];
}
function ptSeg2(p,a,b){
  const vx=b[0]-a[0],vy=b[1]-a[1];const L=vx*vx+vy*vy;
  let t=L?((p[0]-a[0])*vx+(p[1]-a[1])*vy)/L:0;t=Math.max(0,Math.min(1,t));
  return Math.hypot(p[0]-a[0]-t*vx,p[1]-a[1]-t*vy);
}
function segSeg3(p1,p2,q1,q2){ // min distance + the closest pair of points
  const d1=[p2[0]-p1[0],p2[1]-p1[1],p2[2]-p1[2]];
  const d2=[q2[0]-q1[0],q2[1]-q1[1],q2[2]-q1[2]];
  const r=[p1[0]-q1[0],p1[1]-q1[1],p1[2]-q1[2]];
  const dot=(a,b)=>a[0]*b[0]+a[1]*b[1]+a[2]*b[2];
  const a=dot(d1,d1),e=dot(d2,d2),f=dot(d2,r),c=dot(d1,r),b=dot(d1,d2);
  let s=0,t=0;const den=a*e-b*b;
  if(a<=1e-9&&e<=1e-9){}
  else if(a<=1e-9){t=Math.max(0,Math.min(1,f/e));}
  else if(e<=1e-9){s=Math.max(0,Math.min(1,-c/a));}
  else{
    if(den>1e-9)s=Math.max(0,Math.min(1,(b*f-c*e)/den));
    t=(b*s+f)/e;
    if(t<0){t=0;s=Math.max(0,Math.min(1,-c/a));}
    else if(t>1){t=1;s=Math.max(0,Math.min(1,(b-c)/a));}
  }
  const P=[p1[0]+d1[0]*s,p1[1]+d1[1]*s,p1[2]+d1[2]*s];
  const Q=[q1[0]+d2[0]*t,q1[1]+d2[1]*t,q1[2]+d2[2]*t];
  return {d:Math.hypot(P[0]-Q[0],P[1]-Q[1],P[2]-Q[2]),P,Q};
}
function pickAt(ev){
  const r=cv.getBoundingClientRect();
  const mp=[ev.clientX-r.left,ev.clientY-r.top];
  let best=null;
  for(const b of MODEL[cur].bars){
    if(!barVisible(b))continue;
    const S=b.pts.map(proj);
    for(let i=0;i<S.length-1;i++){
      if(!S[i]||!S[i+1])continue;
      const d=ptSeg2(mp,S[i],S[i+1]);
      if(d<8 && (!best||S[i][2]<best.z||d<best.d-4)){best={bar:b,d,z:S[i][2]};}
    }
    if(b.pts.length===1&&S[0]){const d=Math.hypot(mp[0]-S[0][0],mp[1]-S[0][1]);
      if(d<8&&(!best||d<best.d))best={bar:b,d,z:S[0][2]};}
  }
  if(!best){clearPick();return;}
  if(picked.length===2)picked=[];
  if(picked.length===1&&picked[0].bar===best.bar){clearPick();return;}
  picked.push({bar:best.bar,seg:true});
  if(picked.length===2){
    const A=picked[0].bar,B=picked[1].bar;
    let bd=Infinity,P=null,Q=null;
    const segs=x=>x.pts.length>1?x.pts.slice(0,-1).map((p,i)=>[p,x.pts[i+1]]):[[x.pts[0],x.pts[0]]];
    for(const s1 of segs(A))for(const s2 of segs(B)){
      const r=segSeg3(s1[0],s1[1],s2[0],s2[1]);
      if(r.d<bd){bd=r.d;P=r.P;Q=r.Q;}
    }
    picked[0].closest=P;picked[1].closest=Q;
    const clear=Math.max(0,bd-A.dia/2-B.dia/2);
    document.getElementById('measure').textContent =
      `${A.mark||'?'} T${Math.round(A.dia)} ↔ ${B.mark||'?'} T${Math.round(B.dia)}: `+
      `${bd.toFixed(0)} mm centre-to-centre (clear ${clear.toFixed(0)} mm)`;
  }else{
    document.getElementById('measure').textContent =
      `${best.bar.mark||'?'} T${Math.round(best.bar.dia)} selected — click a second bar`;
  }
  buildBuffers();
}
function clearPick(){picked=[];document.getElementById('measure').textContent='';buildBuffers();}

// ------------------------------------------------------------------- panels
const fmt=(n,d=0)=>n==null?'—':n.toLocaleString(undefined,{minimumFractionDigits:d,maximumFractionDigits:d});
const elements=Object.keys(MODEL).sort();
const selEl=document.getElementById('panel');
for(const p of elements){const o=document.createElement('option');o.value=p;o.textContent=p;selEl.append(o);}

function buildToggles(){
  const m=MODEL[cur];
  const dc={},mc={};
  for(const b of m.bars){const d=Math.round(b.dia);dc[d]=(dc[d]||0)+1;
    if(b.mark)mc[b.mark]=(mc[b.mark]||0)+1;}
  visDia=new Set(Object.keys(dc).map(Number));
  visMark=new Set(Object.keys(mc));
  document.getElementById('dias').innerHTML=Object.keys(dc).map(Number).sort((a,b)=>a-b)
    .map(d=>`<label class="chk"><input type="checkbox" checked data-dia="${d}">`+
      `<i class="sw" style="background:var(${DIACOL[d]||'--d32'})"></i>T${d}`+
      `<span class="n">${dc[d]}</span></label>`).join('');
  document.getElementById('marks').innerHTML=Object.keys(mc)
    .sort((a,b)=>a.localeCompare(b,undefined,{numeric:true}))
    .map(k=>`<label class="chk"><input type="checkbox" checked data-mark="${k}">`+
      `${k}<span class="n">${mc[k]}</span></label>`).join('');
  document.querySelectorAll('#dias input').forEach(cb=>cb.onchange=()=>{
    const d=+cb.dataset.dia;cb.checked?visDia.add(d):visDia.delete(d);buildBuffers();});
  document.querySelectorAll('#marks input').forEach(cb=>cb.onchange=()=>{
    cb.checked?visMark.add(cb.dataset.mark):visMark.delete(cb.dataset.mark);buildBuffers();});
}
document.getElementById('mall').onclick=()=>{
  document.querySelectorAll('#marks input').forEach(cb=>{cb.checked=true;visMark.add(cb.dataset.mark);});
  buildBuffers();};
document.getElementById('mnone').onclick=()=>{
  document.querySelectorAll('#marks input').forEach(cb=>{cb.checked=false;});
  visMark=new Set();buildBuffers();};

function render(p){
  cur=p;picked=[];document.getElementById('measure').textContent='';
  selEl.value=p;
  const m=MODEL[p],e=m.envelope,sch=BBS[p]||{bars:[]},a=ACC[p];
  buildToggles();
  document.getElementById('acc').innerHTML = a ? `
    <div class="kpi"><b>${fmt(a.drawn_bars)}</b><span>bars drawn (${a.view})</span></div>
    <div class="kpi"><b>${fmt(a.model_bars)}</b><span>model bars in that view</span></div>
    <div class="kpi"><b>${fmt(a.median_mm,1)} mm</b><span>median offset to nearest drawn bar</span></div>
    <div class="kpi"><b>${fmt(a.p90_mm,1)} mm</b><span>90th percentile offset</span></div>
    <div class="kpi"><b>${a.frac_within_25mm==null?'—':Math.round(100*a.frac_within_25mm)+'%'}</b><span>within 25 mm</span></div>
    <div class="kpi"><b>${fmt(a.density_mismatch_pct,1)}%</b><span>density profile mismatch</span></div>`
    : `<div class="kpi" style="grid-column:1/-1"><b>—</b><span>no matching drawn view</span></div>`;
  document.getElementById('accnote').textContent =
    'Measured by src/v2/check.py against the (R) DXF, not asserted. Lower is better; '+
    '0 mm and 0% would mean the model sits exactly on the drawn steel.';
  const w=(sch.bars||[]).reduce((s,b)=>s+(b.weight_kg||0),0);
  document.getElementById('kpis').innerHTML=`
    <div class="kpi"><b>${fmt(m.bars.length)}</b><span>bars in 3D</span></div>
    <div class="kpi"><b>${fmt((sch.bars||[]).length)}</b><span>schedule marks</span></div>
    <div class="kpi" style="grid-column:1/-1"><b>${fmt(e.width_mm)} × ${fmt(e.thickness_mm)} × ${fmt(e.height_mm)} mm</b>
      <span>width × thickness × height · sheet ${m.sheet}</span></div>`;
  const tb=document.querySelector('#tbl tbody');tb.innerHTML='';
  for(const b of (sch.bars||[]).slice().sort((x,y)=>x.mark.localeCompare(y.mark,undefined,{numeric:true}))){
    const tr=document.createElement('tr');tr.dataset.mark=b.mark;
    tr.innerHTML=`<td><i class="sw" style="background:var(${DIACOL[Math.round(b.dia_mm)]||'--d32'})"></i> ${b.mark}</td>
      <td>T${fmt(b.dia_mm)}</td><td>${b.shape||''}</td><td>${fmt(b.bar_length_mm)}</td>
      <td>${fmt(b.qty)}</td><td>${fmt(b.weight_kg,1)}</td>`;
    tr.onclick=()=>{ // isolate this mark
      const only=!(visMark.size===1&&visMark.has(b.mark));
      document.querySelectorAll('#marks input').forEach(cb=>{
        cb.checked=only?cb.dataset.mark===b.mark:true;});
      visMark=new Set([...document.querySelectorAll('#marks input')]
        .filter(cb=>cb.checked).map(cb=>cb.dataset.mark));
      [...tb.children].forEach(r=>r.setAttribute('aria-selected',only&&r.dataset.mark===b.mark));
      buildBuffers();};
    tb.append(tr);
  }
  fit();buildBuffers();
  document.getElementById('hud').textContent=
    `${p}\n${m.bars.length} bars · ${(OVERLAY[p]||[]).length} drawn segments\n`+
    `drag orbit · shift-drag pan · wheel zoom · click bars to measure`;
}
selEl.onchange=()=>render(selEl.value);
document.getElementById('bfit').onclick=()=>fit();
document.getElementById('bspin').onclick=e=>{spin=!spin;e.target.setAttribute('aria-pressed',spin);};
document.getElementById('bbox').onclick=e=>{showBox=!showBox;
  e.target.setAttribute('aria-pressed',showBox);buildBuffers();};
document.getElementById('bdrawn').onclick=e=>{showDrawn=!showDrawn;
  e.target.setAttribute('aria-pressed',showDrawn);buildBuffers();};
document.getElementById('bclear').onclick=clearPick;

render(elements.find(p=>(MODEL[p].bars||[]).length>0) || elements[0]);draw();
