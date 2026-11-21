#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
assemble.py -- 把多个 .gm2 部件装配成一个完整角色

命名规则(已用全部 434 个文件验证):
    39 <类 1-6> <槽 01-03> <编号 001-114>
      槽 01 = 头发   槽 02 = 头   槽 03 = 身体(含衣服/手套/靴子)
    同一"类 + 编号"的三个槽就是同一个角色的三个部件;
    部件顶点本来就写在共用骨架空间里(脚底 y≈0, 头顶 y≈1.8~2.0), 所以装配是直接叠加, 不需要额外矩阵。

用法:
    python tools\assemble.py --list                        # 列出可装配的组合
    python tools\assemble.py --class 3 --variant 111 --preview OUT\PREVIEW\as.png
    python tools\assemble.py --from 39303111 --obj OUT\MODELS\_assembly
    python tools\assemble.py --parts 39101001,39102001,39103001 --obj OUT\MODELS\_assembly
"""
from __future__ import annotations

import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import softrender as sr                      # noqa: E402
import tx2png                                # noqa: E402
from objwrite import write_obj               # noqa: E402

SLOTS = (("01", "头发"), ("02", "头部"), ("03", "身体"))
NAME_RE = re.compile(r"^(\d{2})(\d)(\d{2})(\d{3})$")
DEFAULT_ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "RESOURCE", "MODELS")


def parse_name(name):
    """'39303111' -> ('3', '03', '111'); 不是本批命名则返回 None"""
    m = NAME_RE.match(os.path.splitext(os.path.basename(name))[0])
    if not m:
        return None
    return m.group(2), m.group(3), m.group(4)


def scan(models_root):
    """扫描目录, 返回 {(类, 编号): {槽: 路径}}"""
    table = {}
    for dirpath, _d, files in os.walk(models_root):
        for fn in files:
            if not fn.lower().endswith(".gm2"):
                continue
            p = os.path.join(dirpath, fn)
            got = parse_name(fn)
            if not got:
                continue
            cls, slot, var = got
            table.setdefault((cls, var), {})[slot] = p
    return table


def variants(models_root):
    """返回 [(类, 编号, 部件数, 缺哪些槽)] , 按类与编号排序"""
    table = scan(models_root)
    out = []
    for (cls, var), slots in table.items():
        have = [s for s, _ in SLOTS if s in slots]
        missing = [s for s, _ in SLOTS if s not in slots]
        out.append((cls, var, len(have), missing))
    out.sort(key=lambda x: (x[0], x[1]))
    return out


def parts_of(models_root, cls, var):
    table = scan(models_root)
    slots = table.get((cls, var), {})
    return [(s, slots[s]) for s, _ in SLOTS if s in slots], [s for s, _ in SLOTS if s not in slots]


def assemble(paths, name=None, cache=None):
    """把若干 .gm2 合并成一个 Scene"""
    scenes = []
    for p in paths:
        key = os.path.abspath(p)
        if cache is not None and key in cache:
            scenes.append(cache[key])
        else:
            sc = sr.load_scene(p)
            if cache is not None:
                cache[key] = sc
            scenes.append(sc)
    stem = name or ("asm_" + "_".join(os.path.splitext(os.path.basename(p))[0] for p in paths))
    return sr.Scene.merge(scenes, name=stem)


def by_class(models_root, cls, var):
    paths, missing = parts_of(models_root, cls, var)
    return [p for _s, p in paths], missing


def resolve_from(models_root, any_name):
    """给任意一个部件名, 自动补齐同 类+编号 的其它槽"""
    got = parse_name(any_name)
    if not got:
        raise SystemExit("无法解析模型名: %s (期望 39<类><槽><编号>)" % any_name)
    cls, _slot, var = got
    paths, missing = by_class(models_root, cls, var)
    if not paths:
        raise SystemExit("找不到 class=%s variant=%s 的部件" % (cls, var))
    return cls, var, paths, missing


def main(argv=None):
    ap = argparse.ArgumentParser(description="装配 .gm2 部件为完整角色")
    ap.add_argument("--root", default=DEFAULT_ROOT, help="模型根目录")
    ap.add_argument("--list", action="store_true", help="列出可装配组合")
    ap.add_argument("--class", dest="cls", default=None, help="类 1-6")
    ap.add_argument("--variant", default=None, help="编号, 如 001 / 111")
    ap.add_argument("--from", dest="from_name", default=None, help="从任意部件名推导")
    ap.add_argument("--parts", default=None, help="逗号分隔的部件名/路径, 忽略命名规则")
    ap.add_argument("--obj", default=None, help="导出 OBJ 的目录")
    ap.add_argument("--all", action="store_true", help="装配并导出所有三部件齐全的组合")
    ap.add_argument("--preview-dir", default=None, help="批量预览图目录(配合 --all)")
    ap.add_argument("--gallery", default=None, help="批量装配后生成 HTML 索引页(配合 --all)")
    ap.add_argument("--texdir", default=None, help="贴图 PNG 目录(默认 OUT\\TEXTURES)")
    ap.add_argument("--preview", default=None, help="渲染预览 PNG 路径")
    ap.add_argument("--size", type=int, default=560, help="预览图高度")
    ap.add_argument("--yaw", type=float, default=22.0)
    ap.add_argument("--pitch", type=float, default=6.0)
    args = ap.parse_args(argv)

    root = args.root
    if not os.path.isdir(root):
        raise SystemExit("模型根目录不存在: %s" % root)
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    texdir = args.texdir or os.path.join(here, "OUT", "TEXTURES")

    if args.list:
        rows = variants(root)
        cur = None
        for cls, var, n, missing in rows:
            if cls != cur:
                print("class %s:" % cls)
                cur = cls
            print("   %s  部件 %d/3%s" % (var, n, ("  缺: " + ",".join(missing)) if missing else ""))
        full = sum(1 for r in rows if r[2] == 3)
        print("\n可装配(三部件齐全)组合: %d / %d" % (full, len(rows)))
        return 0

    if args.all:
        rows = [r for r in variants(root) if r[2] == 3]
        cache = {}
        cards = []
        for cls, var, _n, _m in rows:
            paths, _missing = by_class(root, cls, var)
            stem = "asm_%s%s" % (cls, var)
            scene = assemble(paths, name=stem, cache=cache)
            if args.obj:
                write_obj(scene, args.obj, stem, texdir)
            if args.preview_dir:
                w = max(120, int(args.size * 0.75))
                r = sr.Renderer(w, args.size)
                r.yaw, r.pitch = args.yaw, args.pitch
                img = r.render(scene)
                os.makedirs(args.preview_dir, exist_ok=True)
                png = os.path.join(args.preview_dir, stem + ".png")
                tx2png.write_png(png, img.tobytes(), w, args.size)
                cards.append((stem, cls, var, len(scene.F)))
            print("%s  部件 %d  面 %d" % (stem, len(paths), len(scene.F)))
        print("共装配 %d 个角色" % len(rows))
        if args.gallery and cards:
            html = ['<!DOCTYPE html><html><head><meta charset="utf-8"><title>装配角色</title>',
                    '<style>body{background:#181a20;color:#ddd;font:13px/1.5 "Segoe UI",sans-serif;margin:24px}',
                    'h1{font-size:18px}.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:14px}',
                    '.card{background:#22252d;border:1px solid #2e3240;border-radius:8px;padding:8px}',
                    '.card img{width:100%;border-radius:4px;background:#000}',
                    '.n{color:#8fd3ff;font-family:Consolas,monospace}.t{color:#9aa3b2;font-size:11px}',
                    '</style></head><body><h1>装配后的完整角色 <span style="color:#8a93a5">(%d 个)</span></h1>' % len(cards),
                    '<div class="grid">']
            for stem, cls, var, nf in cards:
                html.append('<div class="card"><a href="%s.png"><img src="%s.png" loading="lazy"></a>'
                            '<div class="n">%s</div><div class="t">类 %s · 编号 %s · %d 面</div></div>'
                            % (stem, stem, stem, cls, var, nf))
            html.append('</div></body></html>')
            open(args.gallery, "w", encoding="utf-8").write("\n".join(html))
            print("索引页: %s" % args.gallery)
        return 0

    if args.parts:
        items = [s.strip() for s in args.parts.split(",") if s.strip()]
        paths = []
        for it in items:
            cand = it if os.path.exists(it) else os.path.join(root, it)
            if not os.path.exists(cand) and not cand.lower().endswith(".gm2"):
                cand += ".gm2"
            if not os.path.exists(cand):
                raise SystemExit("找不到部件: %s" % it)
            paths.append(cand)
        stem = os.path.splitext(os.path.basename(paths[0]))[0] + "_asm"
        cls = var = None
        missing = []
    elif args.from_name:
        cls, var, paths, missing = resolve_from(root, args.from_name)
        stem = "asm_%s%s" % (cls, var)
    elif args.cls and args.variant:
        cls, var = args.cls, args.variant
        paths, missing = by_class(root, cls, var)
        if not paths:
            raise SystemExit("class=%s variant=%s 没有部件" % (cls, var))
        stem = "asm_%s%s" % (cls, var)
    else:
        ap.print_help()
        return 1

    print("装配 %s%s -> %s" % ("class " + cls if cls else "", " variant " + var if var else "",
                             ", ".join(os.path.basename(p) for p in paths)))
    if missing:
        print("  注意: 缺槽 %s, 只用现有部件装配" % ",".join(missing))

    scene = assemble(paths, name=stem)
    print("  顶点 %d, 面 %d, 材质 %d, 贴图 %s"
          % (len(scene.P), len(scene.F), len(scene.tex_names),
             ", ".join(t or "-" for t in scene.tex_names)))

    if args.obj:
        texdir = args.texdir or os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "OUT", "TEXTURES")
        obj, mtl = write_obj(scene, args.obj, stem, texdir)
        print("  已导出: %s" % obj)

    if args.preview:
        w = max(120, int(args.size * 0.75))
        r = sr.Renderer(w, args.size)
        r.yaw, r.pitch = args.yaw, args.pitch
        img = r.render(scene)
        d = os.path.dirname(os.path.abspath(args.preview))
        os.makedirs(d, exist_ok=True)
        tx2png.write_png(args.preview, img.tobytes(), w, args.size)
        print("  预览图: %s" % args.preview)
    return 0


if __name__ == "__main__":
    sys.exit(main())
