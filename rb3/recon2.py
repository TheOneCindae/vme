import ezdxf, sys, collections
d = ezdxf.readfile(sys.argv[1])
for lay in d.layouts:
    ents=list(lay)
    print(f"=== LAYOUT {lay.name!r}: {len(ents)} ents", dict(collections.Counter(e.dxftype() for e in ents)))
