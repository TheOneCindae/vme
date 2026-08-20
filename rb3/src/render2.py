import sys, math, re, glob; sys.path.insert(0,'src')
import ezdxf, shapelib, legend2
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from pathlib import Path

def norm(c): return re.sub(r"\s*\(.*\)$","",c).strip()
WANT = {'M_00','M_17','M_17A','26','M_T1','M_T10',
        'Rebar Shape 8','Rebar Shape 9','Rebar Shape 30','Rebar Shape 31'}
found={}
for f in sorted(glob.glob('dxf/*_S.dxf')):
    doc=ezdxf.readfile(f); L=shapelib.find_labels(doc)
    for c in legend2.clusters(doc):
        b=c['bbox']
        if b[2]-b[0]>90 or b[3]-b[1]>60: continue
        lab=legend2.label_for(L,b)
        if not lab: continue
        lab=norm(lab)
        if lab not in WANT: continue
        dm=legend2.dims_for(doc,b,pad=10.0)
        letters={d['text'] for d in dm if d['text']}
        if lab in found and len(found[lab][2])>=len(letters): continue
        found[lab]=(c,dm,letters,Path(f).stem)

n=len(found); cols=5; rows=(n+cols-1)//cols
fig,axes=plt.subplots(rows,cols,figsize=(4.2*cols,4.2*rows))
for ax,(code,(c,dm,letters,src)) in zip(axes.ravel(), sorted(found.items())):
    for e in c['ents']:
        if e.dxftype()=='LINE':
            ax.plot([e.dxf.start.x,e.dxf.end.x],[e.dxf.start.y,e.dxf.end.y],'-',lw=1.4,color='#1b6ac9')
        else:
            a0,a1=e.dxf.start_angle,e.dxf.end_angle; sw=(a1-a0)%360
            t=[math.radians(a0+sw*i/30) for i in range(31)]
            ax.plot([e.dxf.center.x+e.dxf.radius*math.cos(x) for x in t],
                    [e.dxf.center.y+e.dxf.radius*math.sin(x) for x in t],'-',lw=1.4,color='#1b6ac9')
    for d in dm:
        (x2,y2),(x3,y3)=d['p2'],d['p3']
        ax.plot([x2,x3],[y2,y3],'-',lw=1.0,color='crimson',alpha=.8)
        ax.plot([x2,x3],[y2,y3],'|',color='crimson',ms=8)
        ax.annotate(f"{d['text']}={d['m']:.2f}" if d['m'] else d['text'],
                    ((x2+x3)/2,(y2+y3)/2), color='crimson', fontsize=10, weight='bold')
    ax.set_title(f"{code}  [{src}]",fontsize=10); ax.set_aspect('equal'); ax.axis('off')
for ax in axes.ravel()[n:]: ax.axis('off')
plt.tight_layout(); plt.savefig('out/shapes_dims.png',dpi=110)
print("codes:",sorted(found)); print("missing:",WANT-set(found))
