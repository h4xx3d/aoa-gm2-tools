#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
render_all.py -- 批量把 .gm2 渲染成 PNG 预览, 并生成一个 HTML 索引页(双击即可浏览)

用法:
    python render_all.py <MODELS目录> [-o 预览输出目录] [--size 384] [--yaw 30] [--pitch 12]
"""
from __future__ import annotations

import argparse
import html
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gm2 import Gm2                      # noqa: E402
from render_preview import render, guess_texture   # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("models")
    ap.add_argument("-o", "--out", default=None)
    ap.add_argument("--size", type=int, default=384)
    ap.add_argument("--yaw", type=float, default=30.0)
    ap.add_argument("--pitch", type=float, default=12.0)
    ap.add_argument("--skip-existing", action="store_true", help="已有 PNG 的模型不再渲染")
    args = ap.parse_args(argv)

    files = []
    for root, _d, fs in os.walk(args.models):
        for f in sorted(fs):
            if f.lower().endswith(".gm2"):
                files.append(os.path.join(root, f))
    outdir = args.out or os.path.join(args.models, "_preview")
    os.makedirs(outdir, exist_ok=True)

    rows = []
    ok = 0
    for p in files:
        stem = os.path.splitext(os.path.basename(p))[0]
        png = os.path.join(outdir, stem + ".png")
        tex = None
        try:
            g = Gm2(p)
            name = g.texture_name(0)
            tex = guess_texture(p, name)
            if not (args.skip_existing and os.path.exists(png)):
                render(p, tex, png, args.size, args.yaw, args.pitch, False)
            ok += 1
            rows.append((stem, [g.texture_name(i) or "-" for i in range(len(g.materials))],
                         g.ntriangles, os.path.basename(tex) if tex else "(无贴图)"))
        except Exception as e:  # noqa: BLE001
            print("!!", os.path.basename(p), e, file=sys.stderr)

    page = ['<!DOCTYPE html><html><head><meta charset="utf-8">',
            '<title>AOA 模型预览</title>',
            '<style>',
            'body{background:#181a20;color:#ddd;font:13px/1.5 "Segoe UI",sans-serif;margin:24px}',
            'h1{font-size:18px;font-weight:600}',
            '.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:14px}',
            '.card{background:#22252d;border:1px solid #2e3240;border-radius:8px;padding:8px}',
            '.card img{width:100%;border-radius:4px;background:#000}',
            '.n{color:#8fd3ff;font-family:Consolas,monospace}',
            '.t{color:#9aa3b2;font-size:11px;word-break:break-all}',
            '</style></head><body>',
            '<h1>AOA / VoyageEngine 模型预览 <span style="color:#8a93a5;font-size:13px">(' +
            str(ok) + ' 个 .gm2)</span></h1>',
            '<p style="color:#8a93a5">由 tools/render_preview.py 离线渲染，用于确认几何与贴图解析是否正确。</p>',
            '<div class="grid">']
    for stem, texs, ntri, texfile in rows:
        page.append('<div class="card"><a href="%s.png"><img src="%s.png" loading="lazy"></a>'
                    '<div class="n">%s</div><div class="t">%d 三角面 · %s</div></div>' % (
                        html.escape(stem), html.escape(stem), html.escape(stem),
                        ntri, html.escape(", ".join(texs))))
    page.append("</div></body></html>")
    with open(os.path.join(outdir, "index.html"), "w", encoding="utf-8") as f:
        f.write("\n".join(page))
    print("rendered %d/%d -> %s" % (ok, len(files), outdir))


if __name__ == "__main__":
    main()
