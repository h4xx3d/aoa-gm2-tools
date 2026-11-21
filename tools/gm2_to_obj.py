#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gm2_to_obj.py -- 把 .gm2 模型导出成 OBJ + MTL(可直接拖进 Blender / 3ds Max / MeshLab)

用法:
    python gm2_to_obj.py <gm2文件或目录> [-o 输出目录] [--tex 贴图PNG目录] [--no-flip-v]
                          [--bones]  [--scale 1.0]

    --tex     指向 tx2png.py 生成 PNG 的目录, 用于 MTL 里的 map_Kd 相对路径
    --no-flip-v  不翻转 V(默认翻转: 引擎 UV 原点在左上, OBJ 在左下)
    --bones   额外输出 <名字>.bones.json (挂点矩阵 + 每顶点骨骼号)
"""
from __future__ import annotations

import argparse
import json
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gm2 import Gm2, Gm2Error          # noqa: E402


def tex_png_name(tex_ref: str) -> str:
    """'39101001.tga' -> '39101001.png'; 顺带清掉名字里的空格(原始数据里有 '39503014 .tga' 这种笔误)"""
    base = tex_ref.replace(" ", "").replace("\t", "")
    for ext in (".tga", ".bmp", ".dds", ".png", ".jpg"):
        if base.lower().endswith(ext):
            base = base[:-len(ext)]
            break
    return base + ".png"


def export(path, outdir, texdir=None, flip_v=True, bones=False, scale=1.0):
    g = Gm2(path)
    os.makedirs(outdir, exist_ok=True)
    stem = os.path.splitext(os.path.basename(path))[0]
    obj_path = os.path.join(outdir, stem + ".obj")
    mtl_path = os.path.join(outdir, stem + ".mtl")

    # ---- 材质表 ----
    mtl_lines = ["# %s" % stem, ""]
    mat_names = []
    for mi, m in enumerate(g.materials):
        mname = "%s_mat%d" % (stem, mi)
        mat_names.append(mname)
        mtl_lines.append("newmtl %s" % mname)
        kd = m["diffuse"]
        mtl_lines.append("Kd %.4f %.4f %.4f" % (kd, kd, kd))
        mtl_lines.append("Ks %.4f %.4f %.4f" % (m["specular"], m["specular"], m["specular"]))
        mtl_lines.append("Ns %.2f" % max(1.0, m["gloss"] * 100.0))
        mtl_lines.append("d 1.0")
        mtl_lines.append("illum 2")
        base_tex = g.texture_name(mi, 0)
        if base_tex:
            png = tex_png_name(base_tex)
            rel = os.path.join("..", "TEXTURES", png) if texdir is None else os.path.join(
                os.path.relpath(texdir, outdir), png)
            mtl_lines.append("map_Kd %s" % rel.replace("\\", "/"))
        nrm_tex = g.texture_name(mi, 1) if len(g.materials[mi]["texture"]) > 1 else None
        if nrm_tex:
            png = tex_png_name(nrm_tex)
            rel = os.path.join("..", "TEXTURES", png) if texdir is None else os.path.join(
                os.path.relpath(texdir, outdir), png)
            mtl_lines.append("map_Bump %s" % rel.replace("\\", "/"))
        mtl_lines.append("")
    with open(mtl_path, "w", encoding="utf-8") as f:
        f.write("\n".join(mtl_lines))

    # ---- 几何 ----
    v_lines, vt_lines, vn_lines, f_lines = [], [], [], []
    vbase = 1
    skipped = 0
    used_names = {}
    f_lines.append("mtllib %s" % os.path.basename(mtl_path))
    for oi, o in enumerate(g.objects):
        bi = o["vertex_buff"]
        if bi < 0 or bi >= len(g.buffers):
            skipped += 1
            continue
        buf = g.buffers[bi]
        verts = buf["verts"]
        idx = g.triangles[o["striangle"] * 3:(o["striangle"] + o["ntriangles"]) * 3]
        if not idx or not verts:
            skipped += 1
            continue
        mat = o["material"]
        mname = mat_names[mat] if 0 <= mat < len(mat_names) else (
            mat_names[0] if mat_names else "default")
        gname = o["name"] or ("object%d_buf%d" % (oi, bi))
        if gname in used_names:
            used_names[gname] += 1
            gname = "%s_%d" % (gname, used_names[gname])
        else:
            used_names[gname] = 0
        f_lines.append("g %s" % gname)
        f_lines.append("usemtl %s" % mname)
        for (pos, nrm, _col, uv, _uv2, _bid, _w) in verts:
            v_lines.append("v %.6f %.6f %.6f" % (pos[0] * scale, pos[1] * scale, pos[2] * scale))
            vv = (1.0 - uv[1]) if flip_v else uv[1]
            vt_lines.append("vt %.6f %.6f" % (uv[0], vv))
            n = nrm if any(nrm) else (0.0, 1.0, 0.0)
            vn_lines.append("vn %.6f %.6f %.6f" % n)
        for t in range(0, len(idx), 3):
            a, b, c = idx[t] + vbase, idx[t + 1] + vbase, idx[t + 2] + vbase
            f_lines.append("f %d/%d/%d %d/%d/%d %d/%d/%d" % (a, a, a, b, b, b, c, c, c))
        vbase += len(verts)

    with open(obj_path, "w", encoding="utf-8") as f:
        f.write("# exported from %s (VoyageEngine gm2 %s)\n" % (stem, g.version))
        f.write("\n".join(f_lines[:1]) + "\n")
        f.write("\n".join(v_lines) + "\n")
        f.write("\n".join(vt_lines) + "\n")
        f.write("\n".join(vn_lines) + "\n")
        f.write("\n".join(f_lines[1:]) + "\n")

    if bones:
        dump = dict(
            file=os.path.basename(path), version=g.version,
            bbox_size=g.bbox_size, bbox_center=g.bbox_center, radius=g.radius,
            labels=[dict(group=l["group"], name=l["name"], flags=l["flags"],
                         matrix=l["matrix"], bones=l["bones"], weight=l["weight"])
                    for l in g.labels],
            objects=[dict(name=o["name"], vertex_buff=o["vertex_buff"],
                          nvertices=o["nvertices"], ntriangles=o["ntriangles"],
                          material=o["material"], center=o["center"],
                          radius=o["radius"]) for o in g.objects],
        )
        with open(os.path.join(outdir, stem + ".bones.json"), "w", encoding="utf-8") as f:
            json.dump(dump, f, indent=1, ensure_ascii=False)

    return obj_path, len(v_lines), len(f_lines) - 2, skipped


def main(argv=None):
    ap = argparse.ArgumentParser(description="convert .gm2 models to OBJ")
    ap.add_argument("path")
    ap.add_argument("-o", "--outdir", default=None)
    ap.add_argument("--tex", default=None, help="texture PNG directory")
    ap.add_argument("--no-flip-v", action="store_true")
    ap.add_argument("--bones", action="store_true")
    ap.add_argument("--scale", type=float, default=1.0)
    args = ap.parse_args(argv)

    src = args.path
    if os.path.isdir(src):
        targets = []
        for root, _dirs, files in os.walk(src):
            for f in sorted(files):
                if f.lower().endswith(".gm2"):
                    targets.append(os.path.join(root, f))
        outdir = args.outdir or os.path.join(src, "_obj")
    else:
        targets = [src]
        outdir = args.outdir or os.path.dirname(os.path.abspath(src))

    ok = 0
    for t in targets:
        try:
            obj, nv, nf, skipped = export(t, outdir, args.tex,
                                          flip_v=not args.no_flip_v,
                                          bones=args.bones, scale=args.scale)
            print("%-18s v=%-5d f=%-5d %s" % (os.path.basename(t), nv, nf,
                                              ("(skip %d obj)" % skipped) if skipped else ""))
            ok += 1
        except Gm2Error as e:
            print("!! %s : %s" % (t, e), file=sys.stderr)
    print("done: %d/%d" % (ok, len(targets)))


if __name__ == "__main__":
    main()
