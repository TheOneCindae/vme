import ezdxf, sys, collections
d=ezdxf.readfile(sys.argv[1]); msp=d.modelspace()
by=collections.defaultdict(collections.Counter)
for e in msp: by[e.dxf.layer][e.dxftype()]+=1
for l in sorted(by): print(f"{l:28} {dict(by[l])}")
print("\n--- INSERT block names ---")
print(dict(collections.Counter(e.dxf.name for e in msp if e.dxftype()=='INSERT')))
print("\n--- MTEXT samples ---")
for e in list(msp.query('MTEXT'))[:50]:
    print(f"  [{e.dxf.layer:22}] ({e.dxf.insert.x:9.0f},{e.dxf.insert.y:9.0f}) {e.text[:70]!r}")
