#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""检查导出的 OBJ/MTL 是否自洽, 并统计贴图引用是否缺失"""
import glob
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
objdir = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "OUT", "MODELS")
texdir = sys.argv[2] if len(sys.argv) > 2 else os.path.join(ROOT, "OUT", "TEXTURES")

bad = 0
missing = {}
total_f = 0
for p in sorted(glob.glob(os.path.join(objdir, '*.obj'))):
    nv = nvt = nvn = nf = 0
    ok = True
    for line in open(p, encoding='utf-8'):
        if line.startswith('v '):
            nv += 1
        elif line.startswith('vt '):
            nvt += 1
        elif line.startswith('vn '):
            nvn += 1
        elif line.startswith('f '):
            nf += 1
            for tok in line.split()[1:]:
                parts = tok.split('/')
                for k, lim in ((0, nv), (1, nvt), (2, nvn)):
                    if k < len(parts) and parts[k]:
                        idx = int(parts[k])
                        if idx < 1 or idx > lim:
                            print('BAD INDEX', os.path.basename(p), tok)
                            ok = False
    total_f += nf
    if not ok or nf == 0:
        bad += 1
        print('PROBLEM', os.path.basename(p), nv, nvt, nvn, nf)
    # 贴图引用
    mtl = os.path.join(objdir, os.path.basename(p)[:-4] + '.mtl')
    if os.path.exists(mtl):
        for line in open(mtl, encoding='utf-8'):
            if line.startswith('map_Kd '):
                rel = line.split(None, 1)[1].strip()
                target = os.path.normpath(os.path.join(objdir, rel))
                if not os.path.exists(target):
                    missing[os.path.basename(rel)] = missing.get(os.path.basename(rel), 0) + 1

print('objs=%d bad=%d faces=%d' % (len(glob.glob(os.path.join(objdir, '*.obj'))), bad, total_f))
print('missing textures:', len(missing))
for k, v in sorted(missing.items())[:20]:
    print('   ', k, v)
