#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
render_preview.py -- 用纯 Python 软光栅把 .gm2 + .tga.tx 渲染成 PNG 预览图
(只依赖标准库; 用于在没有 3D 软件时快速确认模型/贴图是否正确)

用法:
    python render_preview.py <model.gm2> [-t texture.tga.tx] [-o out.png]
                              [--size 640] [--yaw 25] [--pitch 10] [--flip-v]
"""
from __future__ import annotations

import argparse
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tx2png                              # noqa: E402
from gm2 import Gm2                        # noqa: E402


def load_texture(path):
    """返回 (w, h, rgba bytes) 或 None"""
    if not path or not os.path.exists(path):
        return None
    d = open(path, "rb").read()
    version, w, h, flags, fmt, l0 = __import__("struct").unpack("<6I", d[:24])
    code = tx2png.FOURCC.get(fmt)
    block16 = False
    if code == "DXT1":
        exp8 = max(1, (w + 3) // 4) * max(1, (h + 3) // 4) * 8
        block16 = bool(l0 and l0 > exp8)
        if block16:
            size = max(1, (w + 3) // 4) * max(1, (h + 3) // 4) * 16
        else:
            size = max(1, (w + 3) // 4) * max(1, (h + 3) // 4) * 8
    else:
        size = tx2png.level_bytes(fmt, w, h)
    return w, h, tx2png.decode_level(d[24:24 + size], fmt, w, h, block16=block16)


def render(gm2_path, tex_path, out_png, size=640, yaw=25.0, pitch=10.0, flip_v=False,
           wire=False):
    g = Gm2(gm2_path)
    tex = load_texture(tex_path) if tex_path else None

    # 收集三角形 (pos, normal, uv)
    tris = []
    for o in g.objects:
        buf = g.buffers[o["vertex_buff"]]
        verts = buf["verts"]
        idx = g.triangles[o["striangle"] * 3:(o["striangle"] + o["ntriangles"]) * 3]
        for t in range(0, len(idx), 3):
            try:
                tris.append((verts[idx[t]], verts[idx[t + 1]], verts[idx[t + 2]]))
            except IndexError:
                pass
    if not tris:
        raise SystemExit("no geometry")

    # 自动居中 + 缩放
    xs = [v[0][0] for tri in tris for v in tri]
    ys = [v[0][1] for tri in tris for v in tri]
    zs = [v[0][2] for tri in tris for v in tri]
    cx, cy, cz = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2, (min(zs) + max(zs)) / 2
    ext = max(max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs)) or 1.0

    ry, rp = math.radians(yaw), math.radians(pitch)
    cyaw, syaw = math.cos(ry), math.sin(ry)
    cpit, spit = math.cos(rp), math.sin(rp)

    def xform(p):
        x, y, z = p[0] - cx, p[1] - cy, p[2] - cz
        x, z = x * cyaw + z * syaw, -x * syaw + z * cyaw
        y, z = y * cpit - z * spit, y * spit + z * cpit
        return x, y, z

    scale = (size * 0.9) / ext
    W = H = size
    zbuf = [-1e30] * (W * H)
    img = bytearray(b"\x20\x22\x28\xff" * (W * H))

    light = (0.35, 0.5, 0.79)
    ln = math.sqrt(sum(c * c for c in light))
    light = tuple(c / ln for c in light)

    for tri in tris:
        pts = []
        for (pos, nrm, col, uv, uv2, _b, _w) in tri:
            x, y, z = xform(pos)
            nx, ny, nz = xform((pos[0] + nrm[0], pos[1] + nrm[1], pos[2] + nrm[2]))
            nx, ny, nz = nx - x, ny - y, nz - z
            sx = W * 0.5 + x * scale
            sy = H * 0.5 - y * scale
            pts.append((sx, sy, z, (nx, ny, nz), uv, col))
        (x0, y0, _z0, n0, uv0, c0), (x1, y1, _z1, n1, uv1, c1), (x2, y2, _z2, n2, uv2, c2) = pts
        minx = max(0, int(min(x0, x1, x2)))
        maxx = min(W - 1, int(max(x0, x1, x2)) + 1)
        miny = max(0, int(min(y0, y1, y2)))
        maxy = min(H - 1, int(max(y0, y1, y2)) + 1)
        den = (y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2)
        if abs(den) < 1e-9:
            continue
        for py in range(miny, maxy + 1):
            for px in range(minx, maxx + 1):
                w0 = ((y1 - y2) * (px - x2) + (x2 - x1) * (py - y2)) / den
                w1 = ((y2 - y0) * (px - x2) + (x0 - x2) * (py - y2)) / den
                w2 = 1.0 - w0 - w1
                if w0 < -1e-6 or w1 < -1e-6 or w2 < -1e-6:
                    continue
                z = w0 * pts[0][2] + w1 * pts[1][2] + w2 * pts[2][2]
                o = py * W + px
                if z <= zbuf[o]:
                    continue
                u = w0 * uv0[0] + w1 * uv1[0] + w2 * uv2[0]
                v = w0 * uv0[1] + w1 * uv1[1] + w2 * uv2[1]
                if flip_v:
                    v = 1.0 - v
                if tex:
                    tw, th, tdata = tex
                    tx = min(tw - 1, max(0, int(u * tw)))
                    ty = min(th - 1, max(0, int(v * th)))
                    ti = (ty * tw + tx) * 4
                    r, gg, b = tdata[ti], tdata[ti + 1], tdata[ti + 2]
                else:
                    r = gg = b = 200
                nx = w0 * n0[0] + w1 * n1[0] + w2 * n2[0]
                ny = w0 * n0[1] + w1 * n1[1] + w2 * n2[1]
                nz = w0 * n0[2] + w1 * n1[2] + w2 * n2[2]
                nl = math.sqrt(nx * nx + ny * ny + nz * nz) or 1.0
                lam = abs((nx * light[0] + ny * light[1] + nz * light[2]) / nl)
                shade = 0.35 + 0.75 * lam
                oo = o * 4
                img[oo] = min(255, int(r * shade))
                img[oo + 1] = min(255, int(gg * shade))
                img[oo + 2] = min(255, int(b * shade))
                img[oo + 3] = 255
                zbuf[o] = z
    tx2png.write_png(out_png, bytes(img), W, H)
    return out_png


def guess_texture(model_path, tex_name):
    """按 .../MODELS/<子目录>/x.gm2 -> .../TEXTURES/<子目录>/x.tga.tx 的约定找贴图"""
    if not tex_name:
        return None
    model_path = os.path.abspath(model_path)
    sub = os.path.basename(os.path.dirname(model_path))
    d = os.path.dirname(os.path.dirname(os.path.dirname(model_path)))  # .../RESOURCE
    cand = os.path.join(d, "TEXTURES", sub, tex_name + ".tx")
    if os.path.exists(cand):
        return cand
    cand = os.path.join(d, "TEXTURES", tex_name + ".tx")
    if os.path.exists(cand):
        return cand
    for root, _dirs, files in os.walk(os.path.join(d, "TEXTURES")):
        if tex_name + ".tx" in files:
            return os.path.join(root, tex_name + ".tx")
    return None


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("model")
    ap.add_argument("-t", "--texture", default=None)
    ap.add_argument("-o", "--out", default=None)
    ap.add_argument("--size", type=int, default=640)
    ap.add_argument("--yaw", type=float, default=25.0)
    ap.add_argument("--pitch", type=float, default=10.0)
    ap.add_argument("--flip-v", action="store_true")
    args = ap.parse_args(argv)
    tex = args.texture
    if tex is None:
        g = Gm2(args.model)
        name = g.texture_name(0)
        if name:
            tex = guess_texture(args.model, name)
    out = args.out or (os.path.splitext(os.path.basename(args.model))[0] + "_preview.png")
    print(render(args.model, tex, out, args.size, args.yaw, args.pitch, args.flip_v), tex)


if __name__ == "__main__":
    main()
