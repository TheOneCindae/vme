import ezdxf, sys, collections
d = ezdxf.readfile(sys.argv[1])
msp = d.modelspace()
c = collections.Counter(e.dxftype() for e in msp)
print("MODELSPACE entities:", dict(c))
print("LAYERS:", sorted(l.dxf.name for l in d.layers))
print("BLOCKS:", sorted(b.name for b in d.blocks if not b.name.startswith('*'))[:80])
# text sample
txts=[]
for e in msp:
    if e.dxftype()=='TEXT': txts.append((e.dxf.insert.x,e.dxf.insert.y,e.dxf.text))
    elif e.dxftype()=='MTEXT': txts.append((e.dxf.insert.x,e.dxf.insert.y,e.text))
print("TEXT count:", len(txts))
for t in sorted(txts,key=lambda t:(-t[1],t[0]))[:60]: print(f"  {t[0]:10.1f} {t[1]:10.1f}  {t[2]!r}")
