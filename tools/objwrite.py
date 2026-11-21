#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
objwrite.py -- 把 softrender.Scene(单件或装配体)写成 OBJ + MTL

与 gm2_to_obj.py 的区别: 这里不依赖 .gm2 内部结构, 直接吃 Scene 的顶点/索引/材质数组,
因此装配后的合成场景也能用同一套代码导出。
"""
from __future__ import annotations

import os

MAT_FMT = "%.4f"


def tex_png_name(tex_ref: str) -> str:
    """'39101001.tga' -> '39101001.png' (顺手清掉原数据里的空格笔误)"""
    base = (tex_ref or "").replace(" ", "").replace("\t", "")
    for ext in (".tga", ".bmp", ".dds", ".png", ".jpg"):
        if base.lower().endswith(ext):
            base = base[:-len(ext)]
            break
    return base + ".png"


def write_obj(scene, outdir, stem, texdir, flip_v=True, scale=1.0):
    os.makedirs(outdir, exist_ok=True)
    obj_path = os.path.join(outdir, stem + ".obj")
    mtl_path = os.path.join(outdir, stem + ".mtl")
    rel_tex = os.path.relpath(texdir, outdir).replace("\\", "/") if texdir else "../TEXTURES"

    # ---- MTL: 每个材质一条, 贴图名来自 Scene 的 tex_names
    lines = ["# %s (assembled by assemble.py)" % stem, ""]
    mat_names = []
    for mi in range(len(scene.tex_names) or 1):
        mname = "%s_mat%d" % (stem, mi)
        mat_names.append(mname)
        lines += ["newmtl %s" % mname, "Kd 0.8500 0.8500 0.8500",
                  "Ks 0.1500 0.1500 0.1500", "Ns 20.00", "d 1.0", "illum 2"]
        tex = scene.tex_names[mi] if mi < len(scene.tex_names) else None
        if tex:
            lines.append("map_Kd %s/%s" % (rel_tex, tex_png_name(tex)))
        lines.append("")
    with open(mtl_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    # ---- OBJ: 顶点表写一次, 面按材质分组
    with open(obj_path, "w", encoding="utf-8") as f:
        f.write("# %s\nmtllib %s\n" % (stem, os.path.basename(mtl_path)))
        for v in scene.P:
            f.write("v %.6f %.6f %.6f\n" % (v[0] * scale, v[1] * scale, v[2] * scale))
        for t in scene.T:
            vv = (1.0 - t[1]) if flip_v else t[1]
            f.write("vt %.6f %.6f\n" % (t[0], vv))
        for n in scene.N:
            if not any(n):
                n = (0.0, 1.0, 0.0)
            f.write("vn %.6f %.6f %.6f\n" % (n[0], n[1], n[2]))
        nmat = max(1, len(mat_names))
        for m in range(nmat):
            sel = (scene.FM == m)
            if not len(sel):
                continue
            faces = scene.F[sel]
            if not len(faces):
                continue
            f.write("g %s_mat%d\nusemtl %s\n" % (stem, m, mat_names[m]))
            for a, b, c in faces:
                f.write("f %d/%d/%d %d/%d/%d %d/%d/%d\n"
                        % (a + 1, a + 1, a + 1, b + 1, b + 1, b + 1, c + 1, c + 1, c + 1))
    return obj_path, mtl_path
