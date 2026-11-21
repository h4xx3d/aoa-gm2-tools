#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
viewer_gui.py -- AOA(.gm2 + .tga.tx) 交互式 3D 查看器 (tkinter + numpy 软光栅, 无需显卡/第三方包)

运行:
    python tools\viewer_gui.py
    python tools\viewer_gui.py RESOURCE\MODELS\human\39303111.gm2
    python tools\viewer_gui.py --root D:\游戏\解包目录      # 指定模型根目录

操作:
    左键拖动      旋转
    右键拖动      平移
    滚轮          缩放
    双击列表      载入该模型
    T             贴图 / 纯色
    W             线框叠加
    A             Alpha 丢弃(头发、镂空)
    C             背面剔除
    R             重置视角
    空格          自动旋转
    ↑ / ↓         上一个 / 下一个模型
"""
from __future__ import annotations

import argparse
import math
import os
import random
import sys
import time
import tkinter as tk
from tkinter import ttk

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np                                  # noqa: E402
import softrender as sr                             # noqa: E402
import assemble as asm                              # noqa: E402
from objwrite import write_obj                      # noqa: E402

APP_TITLE = "AOA 模型查看器 · gm2 + tx"
CACHE_MAX = 24        # 部件场景缓存条数(动态装配会反复切换部件)
SLOTS = asm.SLOTS
_DEBUG_LOG = os.environ.get("AOA_VIEWER_DEBUG", "")


class Viewer:
    def __init__(self, root, models_root, initial=None):
        self.root = root
        self.models_root = models_root
        self.models = []            # 全部模型路径
        self.shown = []             # 过滤后显示的路径
        self.cache = {}             # path -> Scene (部件级缓存, 动态装配复用)
        self.slot_paths = {}        # 装配槽 -> 当前部件路径
        self.scene = None
        self.scene_ms = 0.0
        self.fast = False
        self.full_after_id = None
        self.spin = False
        self.spin_after_id = None

        self.renderer = sr.Renderer(640, 640)
        self._ph = None

        root.title(APP_TITLE)
        sw = root.winfo_screenwidth()
        sh = root.winfo_screenheight()
        w = min(1180, max(760, sw - 120))
        h = min(800, max(520, sh - 160))
        root.geometry("%dx%d+%d+%d" % (w, h, max(0, (sw - w) // 2), max(0, (sh - h) // 3)))
        root.minsize(720, 480)
        self._build_ui()
        self._scan_models()
        if initial:
            self.load(os.path.abspath(initial))
        elif self.shown:
            prefer = [p for p in self.shown if os.path.basename(p) == "39102001.gm2"]
            self.load(prefer[0] if prefer else self.shown[0])

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        self.root.rowconfigure(1, weight=1)
        self.root.columnconfigure(1, weight=1)

        # 顶部工具栏
        bar = ttk.Frame(self.root, padding=(8, 6))
        bar.grid(row=0, column=0, columnspan=2, sticky="ew")
        self.var_tex = tk.BooleanVar(value=True)
        self.var_wire = tk.BooleanVar(value=False)
        self.var_alpha = tk.BooleanVar(value=False)
        self.var_cull = tk.BooleanVar(value=False)
        self.var_spin = tk.BooleanVar(value=False)
        for text, var, cmd in (("贴图", self.var_tex, self._toggle_tex),
                               ("线框", self.var_wire, self._toggle_wire),
                               ("Alpha", self.var_alpha, self._toggle_alpha),
                               ("背面剔除", self.var_cull, self._toggle_cull),
                               ("自动旋转", self.var_spin, self._toggle_spin)):
            ttk.Checkbutton(bar, text=text, variable=var, command=cmd).pack(side="left", padx=(0, 10))
        ttk.Button(bar, text="重置视角", command=self.reset_view).pack(side="left")
        self.lbl_info = ttk.Label(bar, text="", anchor="e")
        self.lbl_info.pack(side="right")

        # 左侧: 两个标签页(单件 / 装配)
        left = ttk.Frame(self.root, padding=(8, 0, 4, 8))
        left.grid(row=1, column=0, sticky="nsew")
        left.rowconfigure(0, weight=1)
        left.columnconfigure(0, weight=1)
        self.nb = ttk.Notebook(left)
        self.nb.grid(row=0, column=0, sticky="nsew")

        # --- 页1: 单件模型
        page1 = ttk.Frame(self.nb, padding=6)
        page1.rowconfigure(2, weight=1)
        page1.columnconfigure(0, weight=1)
        ttk.Label(page1, text="过滤").grid(row=0, column=0, sticky="w")
        self.var_filter = tk.StringVar()
        ent = ttk.Entry(page1, textvariable=self.var_filter, width=22)
        ent.grid(row=1, column=0, sticky="ew", pady=(2, 4))
        ent.bind("<KeyRelease>", lambda e: self._apply_filter())
        box = ttk.Frame(page1)
        box.grid(row=2, column=0, sticky="nsew")
        box.rowconfigure(0, weight=1)
        box.columnconfigure(0, weight=1)
        self.listbox = tk.Listbox(box, width=26, activestyle="none",
                                  exportselection=False, font=("Consolas", 10))
        self.listbox.grid(row=0, column=0, sticky="nsew")
        sb = ttk.Scrollbar(box, orient="vertical", command=self.listbox.yview)
        sb.grid(row=0, column=1, sticky="ns")
        self.listbox.configure(yscrollcommand=sb.set)
        self.listbox.bind("<<ListboxSelect>>", self._on_select)
        self.lbl_count = ttk.Label(page1, text="")
        self.lbl_count.grid(row=3, column=0, sticky="w", pady=(4, 0))
        self.nb.add(page1, text="单件模型")

        # --- 页2: 角色装配
        page2 = ttk.Frame(self.nb, padding=6)
        page2.rowconfigure(4, weight=1)
        page2.columnconfigure(0, weight=1)
        ttk.Label(page2, text="类 / 体型").grid(row=0, column=0, sticky="w")
        self.var_class = tk.StringVar(value="1")
        self.cmb_class = ttk.Combobox(page2, textvariable=self.var_class, width=10, state="readonly",
                                      values=["全部"] + [str(i) for i in range(1, 7)])
        self.cmb_class.grid(row=1, column=0, sticky="w", pady=(2, 6))
        self.cmb_class.bind("<<ComboboxSelected>>", lambda e: self._refresh_variants())

        ttk.Label(page2, text="整套编号(发+头+身)").grid(row=2, column=0, sticky="w")
        asmbox = ttk.Frame(page2)
        asmbox.grid(row=3, column=0, sticky="nsew", pady=(2, 4))
        asmbox.rowconfigure(0, weight=1)
        asmbox.columnconfigure(0, weight=1)
        self.varlist = tk.Listbox(asmbox, width=28, height=8, activestyle="none",
                                  exportselection=False, font=("Consolas", 10))
        self.varlist.grid(row=0, column=0, sticky="nsew")
        sb2 = ttk.Scrollbar(asmbox, orient="vertical", command=self.varlist.yview)
        sb2.grid(row=0, column=1, sticky="ns")
        self.varlist.configure(yscrollcommand=sb2.set)
        self.varlist.bind("<<ListboxSelect>>", self._on_variant_select)

        # 逐槽动态装配: 三行 [显示] [部件下拉]
        slotbox = ttk.Frame(page2)
        slotbox.grid(row=4, column=0, sticky="ew", pady=(6, 2))
        slotbox.columnconfigure(1, weight=1)
        self.slot_vars = {}
        self.slot_on = {}
        self.slot_cmb = {}
        for r, (code, label) in enumerate(SLOTS):
            on = tk.BooleanVar(value=True)
            self.slot_on[code] = on
            ttk.Checkbutton(slotbox, text=label, variable=on, width=5,
                            command=self._rebuild).grid(row=r, column=0, sticky="w")
            var = tk.StringVar()
            self.slot_vars[code] = var
            cmb = ttk.Combobox(slotbox, textvariable=var, width=20, state="readonly")
            cmb.grid(row=r, column=1, sticky="ew", pady=1)
            cmb.bind("<<ComboboxSelected>>", lambda e, c=code: self._on_slot_change(c))
            self.slot_cmb[code] = cmb

        self.lbl_asm = ttk.Label(page2, text="", wraplength=210, justify="left")
        self.lbl_asm.grid(row=5, column=0, sticky="ew", pady=(4, 2))
        row = ttk.Frame(page2)
        row.grid(row=6, column=0, sticky="ew")
        ttk.Button(row, text="导出 OBJ", command=self._export_assembly).pack(side="left")
        ttk.Button(row, text="随机三件", command=self._random_assembly).pack(side="left", padx=(4, 0))
        ttk.Button(row, text="清空", command=self._clear_assembly).pack(side="left", padx=(4, 0))
        self.nb.add(page2, text="角色装配")

        # 右侧画布
        right = ttk.Frame(self.root, padding=(0, 0, 8, 8))
        right.grid(row=1, column=1, sticky="nsew")
        right.rowconfigure(0, weight=1)
        right.columnconfigure(0, weight=1)
        self.canvas = tk.Canvas(right, bg="#1c1e24", highlightthickness=0)
        self.canvas.grid(row=0, column=0, sticky="nsew")

        self.lbl_status = ttk.Label(right, text="", anchor="w")
        self.lbl_status.grid(row=1, column=0, sticky="ew", pady=(6, 0))

        c = self.canvas
        c.bind("<ButtonPress-1>", self._press_rot)
        c.bind("<B1-Motion>", self._drag_rot)
        c.bind("<ButtonRelease-1>", self._release)
        c.bind("<ButtonPress-3>", self._press_pan)
        c.bind("<B3-Motion>", self._drag_pan)
        c.bind("<ButtonRelease-3>", self._release)
        c.bind("<ButtonPress-2>", self._press_pan)
        c.bind("<B2-Motion>", self._drag_pan)
        c.bind("<MouseWheel>", self._wheel)
        c.bind("<Button-4>", lambda e: self._zoom(1.1))
        c.bind("<Button-5>", lambda e: self._zoom(1 / 1.1))
        c.bind("<Configure>", lambda e: self.request_render())
        self.root.bind("<KeyPress>", self._key)
        self.root.bind("<Up>", lambda e: self._step(-1))
        self.root.bind("<Down>", lambda e: self._step(1))

    # ------------------------------------------------------------------ 装配页
    def _root_dir(self):
        if self.models_root:
            return self.models_root
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return os.path.join(here, "RESOURCE", "MODELS")

    def _refresh_variants(self):
        """类选择变化时: 重刷整套编号列表 + 三个槽的候选部件"""
        cls = self.var_class.get() or "1"
        self._asm_table = asm.scan(self._root_dir())
        rows = asm.variants(self._root_dir())
        self._variant_rows = rows if cls == "全部" else [r for r in rows if r[0] == cls]

        self.varlist.delete(0, "end")
        for c, var, n, missing in self._variant_rows:
            tag = " 缺%s" % ",".join(missing) if missing else ""
            prefix = "" if cls != "全部" else "C%s " % c
            self.varlist.insert("end", "%s%s %d/3%s" % (prefix, var, n, tag))

        # 每个槽的候选: {槽: [(显示名, 路径)]}
        self._slot_candidates = {}
        for code, _label in SLOTS:
            items = []
            for p in self.models:
                got = asm.parse_name(p)
                if got and got[1] == code and (cls == "全部" or got[0] == cls):
                    items.append((os.path.splitext(os.path.basename(p))[0], p))
            items.sort()
            self._slot_candidates[code] = items
            names = [n for n, _p in items]
            self.slot_cmb[code].configure(values=names)
            # 当前选择仍在新候选里就保留, 否则换成第一个
            cur = self.slot_vars[code].get()
            valid = {n: p for n, p in items}
            if cur in valid:
                self.slot_paths[code] = valid[cur]
            elif names:
                self.slot_vars[code].set(names[0])
                self.slot_paths[code] = valid[names[0]]
            else:
                self.slot_vars[code].set("")
                self.slot_paths[code] = None
        self.lbl_asm.configure(text="类 %s · %d 个整套编号 · 逐槽可单独换"
                               % (cls, len(self._variant_rows)))
        if any(self.slot_paths.values()):
            self._rebuild()

    def _name_to_path(self, code, name):
        for n, p in self._slot_candidates.get(code, ()):
            if n == name:
                return p
        return None

    def _on_slot_change(self, code):
        """单个槽换部件 -> 立即重新合成(不重置视角)"""
        self.slot_paths[code] = self._name_to_path(code, self.slot_vars[code].get())
        self.slot_on[code].set(True)
        self._rebuild()

    def _on_variant_select(self, _evt=None):
        """点整套编号 -> 三个槽一起设置"""
        sel = self.varlist.curselection()
        if not sel or sel[0] >= len(self._variant_rows):
            return
        cls, var, _n, _m = self._variant_rows[sel[0]]
        self._apply_variant(cls, var)

    def _apply_variant(self, cls, var):
        table = getattr(self, "_asm_table", None) or asm.scan(self._root_dir())
        slots = table.get((cls, var), {})
        if not slots:
            return
        for code, _label in SLOTS:
            if code in slots:
                p = slots[code]
                self.slot_paths[code] = p
                self.slot_vars[code].set(os.path.splitext(os.path.basename(p))[0])
                self.slot_on[code].set(True)
            else:
                self.slot_paths[code] = None
                self.slot_vars[code].set("")
        self._rebuild()

    def _matching_variant(self, cur):
        """当前三槽正好构成某个整套编号时返回其编号, 否则 None"""
        table = getattr(self, "_asm_table", None) or {}
        for cls, var, _n, _m in getattr(self, "_variant_rows", []):
            slots = table.get((cls, var), {})
            if tuple(slots.get(c) for c, _l in SLOTS) == cur:
                return "%s-%s" % (cls, var)
        return None

    def _random_assembly(self):
        """三槽各自随机(同类的整套优先) - 也能拼出混搭"""
        cls = self.var_class.get() or "1"
        for code, _label in SLOTS:
            items = self._slot_candidates.get(code, [])
            if not items:
                continue
            n, p = random.choice(items)
            self.slot_vars[code].set(n)
            self.slot_paths[code] = p
            self.slot_on[code].set(True)
        self._rebuild()

    def _clear_assembly(self):
        for code, _label in SLOTS:
            self.slot_on[code].set(False)
            self.slot_paths[code] = None
            self.slot_vars[code].set("")
        self.scene = None
        self.canvas.delete("all")
        self.lbl_asm.configure(text="已清空, 勾选或选择部件即可重新装配")
        self.lbl_status.configure(text="")
        self.root.title(APP_TITLE)

    def _rebuild(self):
        """按当前三槽选择即时合成; 保留视角, 便于对比不同部件"""
        if not hasattr(self, "slot_paths"):
            return
        paths = [self.slot_paths[c] for c, _l in SLOTS
                 if self.slot_on[c].get() and self.slot_paths.get(c)]
        if not paths:
            self.scene = None
            self.canvas.delete("all")
            self.lbl_asm.configure(text="没有勾选任何部件")
            self.lbl_status.configure(text="")
            return
        t0 = time.time()
        try:
            scene = asm.assemble(paths, name="doll_" + "_".join(
                os.path.splitext(os.path.basename(p))[0] for p in paths), cache=self.cache)
        except Exception as e:  # noqa: BLE001
            self.lbl_asm.configure(text="装配失败: %s" % e)
            return
        ms = (time.time() - t0) * 1000
        self.scene = scene
        self.scene_ms = ms
        classes = {asm.parse_name(p)[0] for p in paths if asm.parse_name(p)}
        warn = ""
        if len(classes) > 1:
            warn = "  ⚠ 跨类混装(%s), 骨架尺寸不同, 可能悬空" % "/".join(sorted(classes))
        names = " · ".join(os.path.splitext(os.path.basename(p))[0] for p in paths)
        cur = tuple(self.slot_paths.get(c) if self.slot_on[c].get() else None
                    for c, _l in SLOTS)
        matched = self._matching_variant(cur)
        tail = ("  · 整套 %s" % matched) if matched else "  · 手工混搭"
        self.lbl_asm.configure(text="%d 部件 · %d 面\n%s\n%s%s"
                               % (len(paths), len(scene.F), names, tail.lstrip(" ·"), warn))
        self.root.title("动态装配 %d 部件 · %s" % (len(paths), APP_TITLE))
        self._update_status(0.0, 0, 0, False)
        self.request_render()

    def _export_assembly(self):
        if self.scene is None or not getattr(self.scene, "parts", None):
            self.lbl_asm.configure(text="当前没有装配体, 先勾选部件")
            return
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        outdir = os.path.join(here, "OUT", "MODELS", "_assembly")
        texdir = os.path.join(here, "OUT", "TEXTURES")
        try:
            obj, _mtl = write_obj(self.scene, outdir, self.scene.name, texdir)
        except Exception as e:  # noqa: BLE001
            self.lbl_asm.configure(text="导出失败: %s" % e)
            return
        self.lbl_asm.configure(text="已导出 OUT\\MODELS\\_assembly\\%s" % os.path.basename(obj))

    # ------------------------------------------------------------------ 模型列表
    def _scan_models(self):
        roots = []
        if self.models_root:
            roots = [self.models_root]
        else:
            here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            roots = [os.path.join(here, "RESOURCE", "MODELS")]
        found = []
        for r in roots:
            for dirpath, _d, files in os.walk(r):
                for f in files:
                    if f.lower().endswith(".gm2"):
                        found.append(os.path.abspath(os.path.join(dirpath, f)))
        self.models = sorted(found, key=lambda p: os.path.basename(p))
        self._apply_filter()
        self._refresh_variants()

    def _apply_filter(self):
        q = self.var_filter.get().strip().lower()
        self.shown = [p for p in self.models if q in os.path.basename(p).lower()]
        self.listbox.delete(0, "end")
        for p in self.shown:
            self.listbox.insert("end", os.path.splitext(os.path.basename(p))[0])
        self.lbl_count.configure(text="%d / %d" % (len(self.shown), len(self.models)))
        if self.scene is not None:
            try:
                i = self.shown.index(self.scene.path)
                self.listbox.selection_clear(0, "end")
                self.listbox.selection_set(i)
                self.listbox.see(i)
            except ValueError:
                pass

    def _on_select(self, _evt=None):
        sel = self.listbox.curselection()
        if not sel:
            return
        p = self.shown[sel[0]]
        if self.scene is None or p != self.scene.path:
            self.load(p)

    def _step(self, d):
        # 动态装配模式: ↑↓ 在同一类的整套编号之间切换(三槽同步换)
        if self.scene is not None and getattr(self.scene, "parts", None):
            rows = getattr(self, "_variant_rows", [])
            if not rows:
                return
            cur_var = None
            for code, _l in SLOTS:
                p = self.slot_paths.get(code)
                got = asm.parse_name(p) if p else None
                if got:
                    cur_var = got[2]
                    break
            vars_ = [r[1] for r in rows]
            try:
                i = vars_.index(cur_var)
            except ValueError:
                i = 0
            j = (i + d) % len(rows)
            self.varlist.selection_clear(0, "end")
            self.varlist.selection_set(j)
            self.varlist.see(j)
            self._apply_variant(rows[j][0], rows[j][1])
            return
        if not self.shown:
            return
        if self.scene is None:
            self.load(self.shown[0])
            return
        try:
            i = self.shown.index(self.scene.path)
        except ValueError:
            i = 0
        self.load(self.shown[(i + d) % len(self.shown)])

    # ------------------------------------------------------------------ 载入
    def _get_scene(self, path):
        if path in self.cache:
            return self.cache[path], 0.0
        t0 = time.time()
        scene = sr.load_scene(path)
        dt = (time.time() - t0) * 1000
        if len(self.cache) >= CACHE_MAX:
            self.cache.pop(next(iter(self.cache)))
        self.cache[path] = scene
        return scene, dt

    def load(self, path):
        try:
            scene, ms = self._get_scene(path)
        except Exception as e:  # noqa: BLE001
            self.lbl_status.configure(text="载入失败: %s (%s)" % (os.path.basename(path), e))
            return
        self.scene = scene
        self.scene_ms = ms
        self.root.title("%s · %s" % (scene.name, APP_TITLE))
        if _DEBUG_LOG:
            import traceback
            with open(_DEBUG_LOG, "a", encoding="utf-8") as f:
                f.write("load %s  <- %s\n" % (scene.name, " > ".join(
                    "%s:%d" % (os.path.basename(fr.filename), fr.lineno)
                    for fr in traceback.extract_stack()[-4:-1])))
        self.reset_view(redraw=False)
        self._sync_selection()
        self._update_status(0.0, 0, 0, False)
        self.request_render(reset_view=True)

    def _sync_selection(self):
        if self.scene is None:
            return
        try:
            i = self.shown.index(self.scene.path)
        except ValueError:
            return
        self.listbox.selection_clear(0, "end")
        self.listbox.selection_set(i)
        self.listbox.see(i)

    def reset_view(self, redraw=True):
        self.renderer.yaw = 25.0
        self.renderer.pitch = 10.0
        self.renderer.zoom = 1.0
        self.renderer.panx = 0.0
        self.renderer.pany = 0.0
        if redraw:
            self.request_render(reset_view=True)

    # ------------------------------------------------------------------ 交互
    def _press_rot(self, ev):
        self._drag = (ev.x, ev.y)
        self.fast = True

    def _drag_rot(self, ev):
        if not getattr(self, "_drag", None):
            return
        dx = ev.x - self._drag[0]
        dy = ev.y - self._drag[1]
        self._drag = (ev.x, ev.y)
        self.renderer.yaw += dx * 0.45
        self.renderer.pitch = max(-85.0, min(85.0, self.renderer.pitch - dy * 0.35))
        self.request_render()

    def _press_pan(self, ev):
        self._drag = (ev.x, ev.y)
        self.fast = True

    def _drag_pan(self, ev):
        if not getattr(self, "_drag", None):
            return
        dx = ev.x - self._drag[0]
        dy = ev.y - self._drag[1]
        self._drag = (ev.x, ev.y)
        self.renderer.panx += dx
        self.renderer.pany += dy
        self.request_render()

    def _release(self, _ev=None):
        self._drag = None
        self.fast = False
        self.request_render()

    def _wheel(self, ev):
        self._zoom(1.12 if ev.delta > 0 else 1 / 1.12)

    def _zoom(self, f):
        self.renderer.zoom = max(0.1, min(12.0, self.renderer.zoom * f))
        self.request_render()

    def _key(self, ev):
        k = ev.char.lower()
        if k == "t":
            self.var_tex.set(not self.var_tex.get())
            self._toggle_tex()
        elif k == "w":
            self.var_wire.set(not self.var_wire.get())
            self._toggle_wire()
        elif k == "a":
            self.var_alpha.set(not self.var_alpha.get())
            self._toggle_alpha()
        elif k == "c":
            self.var_cull.set(not self.var_cull.get())
            self._toggle_cull()
        elif k == "r":
            self.reset_view()
        elif k == " ":
            self.var_spin.set(not self.var_spin.get())
            self._toggle_spin()

    def _toggle_tex(self):
        self.renderer.use_texture = self.var_tex.get()
        self.request_render()

    def _toggle_wire(self):
        self.renderer.wire = self.var_wire.get()
        self.request_render()

    def _toggle_alpha(self):
        self.renderer.alpha_test = self.var_alpha.get()
        self.request_render()

    def _toggle_cull(self):
        self.renderer.cull = self.var_cull.get()
        self.request_render()

    def _toggle_spin(self):
        self.spin = self.var_spin.get()
        if self.spin:
            self._spin_tick()
        elif self.spin_after_id:
            self.root.after_cancel(self.spin_after_id)
            self.spin_after_id = None
            self.request_render()

    def _spin_tick(self):
        if not self.spin:
            return
        self.renderer.yaw += 1.6
        self.renderer.yaw %= 360.0
        self.fast = True
        self.draw(fast=True)
        self.spin_after_id = self.root.after(33, self._spin_tick)

    # ------------------------------------------------------------------ 渲染
    def request_render(self, reset_view=False):
        """合并短时间内的多次请求: 拖动时立刻画低分辨率, 停手后补全分辨率"""
        if self.full_after_id:
            self.root.after_cancel(self.full_after_id)
        if self.fast:
            self.draw(fast=True)
        self.full_after_id = self.root.after(140, self._draw_full)

    def _draw_full(self):
        self.full_after_id = None
        if self.spin:
            return
        self.fast = False
        self.draw(fast=False)

    def draw(self, fast=False):
        if self.scene is None:
            return
        W = max(96, self.canvas.winfo_width())
        H = max(96, self.canvas.winfo_height())
        if fast:
            # 拖动/自转时把渲染分辨率压到 ~400px 以内, 保证跟手
            div = max(2, int(math.ceil(max(W, H) / 400.0)))
        else:
            div = 1
        rw = max(64, W // div)
        rh = max(64, H // div)
        t0 = time.time()
        self.renderer.resize(rw, rh)
        img = self.renderer.render(self.scene)
        ms = (time.time() - t0) * 1000
        ppm = b"P6\n%d %d\n255\n" % (rw, rh) + np.ascontiguousarray(img[:, :, :3]).tobytes()
        ph = tk.PhotoImage(data=ppm)
        if div != 1:
            ph = ph.zoom(div)
        self._ph = ph
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, anchor="nw", image=ph)
        self._update_status(ms, rw, rh, fast)

    def _update_status(self, ms, rw, rh, fast):
        s = self.scene
        tex = ", ".join(t or "-" for t in s.tex_names) or "-"
        load = ("  载入 %.0f ms" % self.scene_ms) if self.scene_ms else ""
        rend = ("  渲染 %.0f ms @%dx%d%s" % (ms, rw, rh, " (拖动中)" if fast else "")) if ms else ""
        parts = getattr(s, "parts", None)
        pinfo = ("   [装配: %s]" % " + ".join(p[0] for p in parts)) if parts else ""
        self.lbl_status.configure(
            text="%s   %d 顶点 / %d 面   贴图: %s%s%s%s"
                 % (s.name, len(s.P), len(s.F), tex, pinfo, rend, load))
        self.lbl_info.configure(text="左键旋转 · 右键平移 · 滚轮缩放 · T 贴图 · W 线框 · 空格自动旋转")


def _enable_dpi_awareness():
    """Windows 高 DPI: 让窗口尺寸/坐标按物理像素处理, 否则 150% 缩放时窗口会超出屏幕"""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)      # per-monitor
        except Exception:                                        # noqa: BLE001
            ctypes.windll.user32.SetProcessDPIAware()
    except Exception:                                            # noqa: BLE001
        pass


def main(argv=None):
    ap = argparse.ArgumentParser(description="AOA gm2/tx 交互查看器")
    ap.add_argument("model", nargs="?", default=None, help="启动时载入的 .gm2")
    ap.add_argument("--root", default=None, help="模型根目录(默认 RESOURCE\\MODELS)")
    args = ap.parse_args(argv)

    _enable_dpi_awareness()
    root = tk.Tk()
    try:
        root.tk.call("tk", "scaling", 1.34)      # 高分屏下字体略放大, 几何仍按物理像素
    except tk.TclError:
        pass
    Viewer(root, args.root, args.model)
    root.mainloop()


if __name__ == "__main__":
    main()
