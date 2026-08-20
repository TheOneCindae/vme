const DIACOL = {8:'--d8',10:'--d10',12:'--d12',16:'--d16',20:'--d20',25:'--d25',32:'--d32'};
const cssv = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
function hex2rgb(h){h=h.replace('#','');
  if(h.length===3)h=h.split('').map(c=>c+c).join('');
  return [parseInt(h.slice(0,2),16)/255,parseInt(h.slice(2,4),16)/255,parseInt(h.slice(4,6),16)/255];}

const cv=document.getElementById('gl');
const gl=cv.getContext('webgl',{antialias:true,alpha:false});
const VS=`attribute vec3 p;attribute vec3 c;uniform mat4 mvp;varying vec3 vc;
void main(){vc=c;gl_Position=mvp*vec4(p,1.0);}`;
const FS=`precision mediump float;varying vec3 vc;uniform float dim;
void main(){gl_FragColor=vec4(vc*dim,1.0);}`;
function sh(t,s){const o=gl.createShader(t);gl.shaderSource(o,s);gl.compileShader(o);
  if(!gl.getShaderParameter(o,gl.COMPILE_STATUS))throw gl.getShaderInfoLog(o);return o;}
const prog=gl.createProgram();
gl.attachShader(prog,sh(gl.VERTEX_SHADER,VS));gl.attachShader(prog,sh(gl.FRAGMENT_SHADER,FS));
gl.linkProgram(prog);gl.useProgram(prog);
const aP=gl.getAttribLocation(prog,'p'),aC=gl.getAttribLocation(prog,'c');
const uM=gl.getUniformLocation(prog,'mvp'),uD=gl.getUniformLocation(prog,'dim');
const bufP=gl.createBuffer(),bufC=gl.createBuffer();

// --- matrices ---
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

let cam={az:-0.9,el:0.32,dist:1,tx:0,ty:0,tz:0},spin=false,showBox=true;
let verts=null,cols=null,nvert=0,sel=null,cur=null;

function buildBuffers(panel,selMark){
  const m=MODEL[panel];const P=[],C=[];
  const colOf=d=>hex2rgb(cssv(DIACOL[d]||'--d32'));
  for(const b of m.bars){
    const on = !selMark || b.mark===selMark;
    let c=colOf(Math.round(b.dia_mm));
    if(selMark && !on) c=c.map(x=>x*0.22+0.10);
    for(let i=0;i<b.pts.length-1;i++){
      P.push(...b.pts[i],...b.pts[i+1]); C.push(...c,...c);
    }
  }
  if(showBox){
    const e=m.envelope,W=e.width_mm,T=e.thickness_mm||200,H=e.height_mm;
    const g=hex2rgb(cssv('--line'));
    const V=[[0,0,0],[W,0,0],[0,T,0],[W,T,0],[0,0,H],[W,0,H],[0,T,H],[W,T,H]];
    const E=[[0,1],[0,2],[1,3],[2,3],[4,5],[4,6],[5,7],[6,7],[0,4],[1,5],[2,6],[3,7]];
    for(const [a,b2] of E){P.push(...V[a],...V[b2]);C.push(...g,...g);}
  }
  verts=new Float32Array(P);cols=new Float32Array(C);nvert=P.length/3;
  gl.bindBuffer(gl.ARRAY_BUFFER,bufP);gl.bufferData(gl.ARRAY_BUFFER,verts,gl.STATIC_DRAW);
  gl.bindBuffer(gl.ARRAY_BUFFER,bufC);gl.bufferData(gl.ARRAY_BUFFER,cols,gl.STATIC_DRAW);
}
function fit(panel){
  const e=MODEL[panel].envelope;
  cam.tx=e.width_mm/2;cam.ty=(e.thickness_mm||200)/2;cam.tz=e.height_mm/2;
  cam.dist=Math.max(e.width_mm,e.height_mm)*1.25;
}
function draw(){
  const w=cv.clientWidth,h=cv.clientHeight,dpr=Math.min(devicePixelRatio||1,2);
  if(cv.width!==w*dpr||cv.height!==h*dpr){cv.width=w*dpr;cv.height=h*dpr;}
  gl.viewport(0,0,cv.width,cv.height);
  const bg=hex2rgb(cssv('--panel'));gl.clearColor(bg[0],bg[1],bg[2],1);
  gl.enable(gl.DEPTH_TEST);gl.clear(gl.COLOR_BUFFER_BIT|gl.DEPTH_BUFFER_BIT);
  const eye=[cam.tx+cam.dist*Math.cos(cam.el)*Math.cos(cam.az),
             cam.ty+cam.dist*Math.cos(cam.el)*Math.sin(cam.az),
             cam.tz+cam.dist*Math.sin(cam.el)];
  const mvp=mul(persp(0.85,w/h,cam.dist*0.02,cam.dist*8),
                lookAt(eye,[cam.tx,cam.ty,cam.tz],[0,0,1]));
  gl.useProgram(prog);gl.uniformMatrix4fv(uM,false,mvp);gl.uniform1f(uD,1.0);
  gl.bindBuffer(gl.ARRAY_BUFFER,bufP);gl.enableVertexAttribArray(aP);
  gl.vertexAttribPointer(aP,3,gl.FLOAT,false,0,0);
  gl.bindBuffer(gl.ARRAY_BUFFER,bufC);gl.enableVertexAttribArray(aC);
  gl.vertexAttribPointer(aC,3,gl.FLOAT,false,0,0);
  gl.drawArrays(gl.LINES,0,nvert);
  if(spin){cam.az+=0.0035;}
  requestAnimationFrame(draw);
}

// --- interaction ---
let drag=null;
cv.addEventListener('pointerdown',e=>{drag={x:e.clientX,y:e.clientY,b:e.button};cv.setPointerCapture(e.pointerId);});
cv.addEventListener('pointerup',e=>{drag=null;});
cv.addEventListener('pointermove',e=>{
  if(!drag)return;
  const dx=e.clientX-drag.x,dy=e.clientY-drag.y;drag.x=e.clientX;drag.y=e.clientY;
  if(drag.b===2||e.shiftKey){
    const k=cam.dist*0.0016;
    cam.tx-=dx*k*Math.sin(cam.az)*-1;cam.ty-=dx*k*Math.cos(cam.az);cam.tz+=dy*k;
  }else{
    cam.az-=dx*0.008;cam.el=Math.max(-1.5,Math.min(1.5,cam.el+dy*0.008));
  }
});
cv.addEventListener('contextmenu',e=>e.preventDefault());
cv.addEventListener('wheel',e=>{e.preventDefault();
  cam.dist*=Math.exp(e.deltaY*0.0012);},{passive:false});

// --- UI ---
const fmt=(n,d=0)=>n==null?'—':n.toLocaleString(undefined,{minimumFractionDigits:d,maximumFractionDigits:d});
const panels=Object.keys(MODEL).sort();
const selEl=document.getElementById('panel');
for(const p of panels){const o=document.createElement('option');o.value=p;o.textContent=p;selEl.append(o);}

function provenance(m){
  const s={};
  for(const b of m.bars){
    const k=b.placement.startsWith('section')?'section':
            b.placement.startsWith('spaced')?'spaced':'distributed';
    s[k]=(s[k]||0)+1;
  }
  s.thru=m.bars.filter(b=>b.through_thickness).length;
  return s;
}
function render(panel){
  cur=panel;sel=null;
  const m=MODEL[panel],e=m.envelope,sch=BBS[panel];
  const w=m.bars.reduce((a,b)=>a+b.weight_kg,0);
  const bw=sch&&sch.summary&&sch.summary.total?sch.summary.total.weight_kg:null;
  document.getElementById('kpis').innerHTML=`
    <div class="kpi"><b>${fmt(m.bars.length)}</b><span>bars placed</span></div>
    <div class="kpi"><b>${fmt(sch.bars.length)}</b><span>schedule marks</span></div>
    <div class="kpi"><b>${fmt(w,2)} kg</b><span>model weight</span></div>
    <div class="kpi"><b>${fmt(bw,2)} kg</b><span>schedule weight</span></div>
    <div class="kpi" style="grid-column:1/-1"><b>${fmt(e.width_mm)} × ${fmt(e.thickness_mm)} × ${fmt(e.height_mm)} mm</b>
      <span>panel width × thickness × height, read from the drawing</span></div>`;
  const dias=[...new Set(sch.bars.map(b=>Math.round(b.dia_mm)))].sort((a,b)=>a-b);
  document.getElementById('legend').innerHTML=dias.map(d=>
    `<span><i class="sw" style="background:var(${DIACOL[d]||'--d32'})"></i>T${d}</span>`).join('');
  const tb=document.querySelector('#tbl tbody');tb.innerHTML='';
  for(const b of sch.bars.slice().sort((a,b)=>a.mark.localeCompare(b.mark,undefined,{numeric:true}))){
    const tr=document.createElement('tr');tr.dataset.mark=b.mark;
    tr.innerHTML=`<td><i class="sw" style="background:var(${DIACOL[Math.round(b.dia_mm)]||'--d32'})"></i>${b.mark}</td>
      <td>T${fmt(b.dia_mm)}</td><td>${b.shape}</td><td>${fmt(b.bar_length_mm)}</td>
      <td>${fmt(b.qty)}</td><td>${fmt(b.weight_kg,2)}</td>`;
    tr.title=(()=>{const q=MODEL[cur].bars.find(x=>x.mark===b.mark);
      return q?`runs along ${q.run_axis}, folds in ${q.fold_axis} — ${q.axis_reason}`+
        (q.spacing_mm?` · @${q.spacing_mm} mm`:''):'';})();
    tr.onclick=()=>{sel=(sel===b.mark)?null:b.mark;
      [...tb.children].forEach(r=>r.setAttribute('aria-selected',r.dataset.mark===sel));
      buildBuffers(cur,sel);};
    tb.append(tr);
  }
  const pv=provenance(m),tot=m.bars.length;
  document.getElementById('prov').innerHTML=
    `Placement evidence — <b>${fmt(pv.section||0)}</b> read from section cuts, `+
    `<b>${fmt(pv.spaced||0)}</b> arrayed at the spacing the drawing annotates, `+
    `<b>${fmt(pv.distributed||0)}</b> spread evenly where the drawing gave neither `+
    `(${Math.round(100*(tot-(pv.distributed||0))/tot)}% positioned from drawing evidence). `+
    `<b>${fmt(pv.thru||0)}</b> bars hook through the panel thickness — decided from the `+
    `drawing's "U Bar"/link labels and from legs equal to the clear distance between covers, `+
    `not by guesswork. Every bar's length, diameter, shape and weight comes from the schedule.`;
  fit(panel);buildBuffers(panel,null);
  document.getElementById('hud').textContent=
    `${panel}   ${m.bars.length} bars   drag rotate · shift-drag pan · scroll zoom`;
}
selEl.onchange=()=>render(selEl.value);
document.getElementById('bfit').onclick=()=>fit(cur);
document.getElementById('bspin').onclick=e=>{spin=!spin;e.target.setAttribute('aria-pressed',spin);};
document.getElementById('bbox').onclick=e=>{showBox=!showBox;
  e.target.setAttribute('aria-pressed',showBox);buildBuffers(cur,sel);};

// whole-set totals
let TB=0,TW=0,TM=0,TP=0;
for(const p of panels){const m=MODEL[p];TB+=m.bars.length;TM+=BBS[p].bars.length;
  TW+=m.bars.reduce((a,b)=>a+b.weight_kg,0);
  TP+=m.bars.filter(b=>!b.placement.startsWith('distributed')).length;}
document.getElementById('tot').innerHTML=`
  <div class="kpi"><b>${fmt(panels.length)}</b><span>panels</span></div>
  <div class="kpi"><b>${fmt(TM)}</b><span>schedule marks</span></div>
  <div class="kpi"><b>${fmt(TB)}</b><span>bars in 3D</span></div>
  <div class="kpi"><b>${fmt(TW,2)} kg</b><span>total steel</span></div>`;
document.getElementById('footnote').innerHTML=META.footnote;
render(panels[0]);draw();
