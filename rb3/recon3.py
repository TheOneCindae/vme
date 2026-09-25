import ezdxf, sys
d = ezdxf.readfile(sys.argv[1]); lay=d.layout('Layout1')
ts=[]
for e in lay:
    if e.dxftype()=='MTEXT':
        ts.append((round(e.dxf.insert.y,1), round(e.dxf.insert.x,1), e.text.replace('\n',' '), e.dxf.layer))
ts.sort(key=lambda t:(-t[0],t[1]))
for y,x,t,l in ts: print(f"{y:9.1f} {x:9.1f} [{l:16}] {t!r}")
