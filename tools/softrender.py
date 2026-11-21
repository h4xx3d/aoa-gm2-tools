#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
softrender.py -- 供交互查看器使用的 numpy 软光栅渲染核心

职责:
    把 .gm2 的三角形 + .tx 的贴图装进一个 Scene, 然后按 (yaw, pitch, zoom) 每帧光栅化成 RGBA 缓冲。

设计取向:
    - 每个三角形做一次 numpy 向量运算 (包围盒网格 + 重心坐标), 1000 面量级可到交互帧率;
    - 正交投影: 不依赖模型真实尺度, 自动按包围盒取景, 旋转/缩放时不会穿帮;
    - 支持贴图 / 纯色、平面或平滑法线、线框叠加、背面剔除、alpha 丢弃(头发/镂空)。
"""
from __future__ import annotations

import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gm2 import Gm2                          # noqa: E402
import tx2png                                # noqa: E402


# ------------------------------------------------------------------ 贴图读取
def load_tx(path):
    """读取 .tga.tx 主图 -> (w, h, uint8 RGBA (h,w,4))"""
    d = open(path, "rb").read()
    version, w, h, flags, fmt, l0 = __import__("struct").unpack("<6I", d[:24])
    code = tx2png.FOURCC.get(fmt)
    block16 = False
    if code == "DXT1":
        exp8 = max(1, (w + 3) // 4) * max(1, (h + 3) // 4) * 8
        block16 = bool(l0 and l0 > exp8)
        block = 16 if block16 else 8
        size = max(1, (w + 3) // 4) * max(1, (h + 3) // 4) * block
    else:
        size = tx2png.level_bytes(fmt, w, h)
    rgba = tx2png.decode_level(d[24:24 + size], fmt, w, h, block16=block16)
    return np.frombuffer(rgba, dtype=np.uint8).reshape(h, w, 4)


PNG_CACHE = {}


def load_png(path):
    """最小 PNG 读取(仅 8bit RGB/RGBA, 过滤器 0-4), 供查看器读取已转换的 PNG"""
    if path in PNG_CACHE:
        return PNG_CACHE[path]
    import zlib
    d = open(path, "rb").read()
    if d[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a png")
    pos = 8
    w = h = bit = ctype = None
    idat = bytearray()
    while pos < len(d):
        ln = int.from_bytes(d[pos:pos + 4], "big")
        tag = d[pos + 4:pos + 8]
        body = d[pos + 8:pos + 8 + ln]
        pos += 12 + ln
        if tag == b"IHDR":
            w, h, bit, ctype = (int.from_bytes(body[0:4], "big"),
                                int.from_bytes(body[4:8], "big"), body[8], body[9])
        elif tag == b"IDAT":
            idat += body
        elif tag == b"IEND":
            break
    if bit != 8 or ctype not in (2, 6):
        raise ValueError("unsupported png (%d bit, ctype %d)" % (bit, ctype))
    ch = 4 if ctype == 6 else 3
    raw = zlib.decompress(bytes(idat))
    stride = w * ch
    out = np.zeros((h, stride), dtype=np.uint8)
    prev = np.zeros(stride, dtype=np.uint8)
    p = 0
    for y in range(h):
        f = raw[p]
        p += 1
        line = np.frombuffer(raw[p:p + stride], dtype=np.uint8).astype(np.int16)
        p += stride
        if f == 0:
            cur = line
        elif f == 1:                      # Sub
            cur = line.copy()
            for x in range(ch, stride):
                cur[x] = (cur[x] + cur[x - ch]) & 0xFF
        elif f == 2:                      # Up
            cur = (line + prev) & 0xFF
        elif f == 3:                      # Average
            cur = line.copy()
            for x in range(stride):
                left = cur[x - ch] if x >= ch else 0
                cur[x] = (cur[x] + ((int(left) + int(prev[x])) >> 1)) & 0xFF
        elif f == 4:                      # Paeth
            cur = line.copy()
            for x in range(stride):
                a = int(cur[x - ch]) if x >= ch else 0
                b = int(prev[x])
                c = int(prev[x - ch]) if x >= ch else 0
                pa, pb, pc = abs(b - c), abs(a - c), abs(a + b - 2 * c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                cur[x] = (cur[x] + pr) & 0xFF
        else:
            raise ValueError("bad png filter %d" % f)
        out[y] = cur.astype(np.uint8)
        prev = out[y]
    px = out.reshape(h, w, ch)
    if ch == 3:
        alpha = np.full((h, w, 1), 255, dtype=np.uint8)
        px = np.concatenate([px, alpha], axis=2)
    PNG_CACHE[path] = np.ascontiguousarray(px)
    return PNG_CACHE[path]


# ------------------------------------------------------------------ 场景
class Scene:
    def __init__(self, gm2_path, tex_paths=None):
        self.path = gm2_path
        self.name = os.path.splitext(os.path.basename(gm2_path))[0]
        g = Gm2(gm2_path)
        self.gm2 = g
        self.version = g.version

        pos, nrm, uv = [], [], []
        faces, face_mat = [], []
        self.groups = []          # (name, 起始面, 结束面, 材质号)
        base = 0
        for o in g.objects:
            bi = o["vertex_buff"]
            if bi < 0 or bi >= len(g.buffers):
                continue
            verts = g.buffers[bi]["verts"]
            idx = g.triangles[o["striangle"] * 3:(o["striangle"] + o["ntriangles"]) * 3]
            if not verts or not idx:
                continue
            for (p, n, _c, u, _u2, _b, _w) in verts:
                pos.append(p)
                nrm.append(n)
                uv.append(u)
            f0 = len(faces)
            for t in range(0, len(idx), 3):
                faces.append((idx[t] + base, idx[t + 1] + base, idx[t + 2] + base))
                face_mat.append(max(0, o["material"]))
            self.groups.append((o["name"] or ("obj%d" % bi), f0, len(faces), max(0, o["material"])))
            base += len(verts)

        self.P = np.array(pos, dtype=np.float32)
        self.N = np.array(nrm, dtype=np.float32)
        self.T = np.array(uv, dtype=np.float32)
        self.F = np.array(faces, dtype=np.int32) if faces else np.zeros((0, 3), np.int32)
        self.FM = np.array(face_mat, dtype=np.int32) if face_mat else np.zeros(0, np.int32)

        # 材质贴图(每个材质一张; tex_paths 可以是单个路径或按材质号的路径列表)
        self.tex_names = []
        self.textures = []
        single = isinstance(tex_paths, str) or tex_paths is None
        for mi in range(len(g.materials)):
            name = g.texture_name(mi, 0)
            self.tex_names.append(name)
            path = None
            if single:
                path = tex_paths if mi == 0 else None
            elif mi < len(tex_paths):
                path = tex_paths[mi]
            if not path or not os.path.exists(path):
                path = find_texture(gm2_path, name) if name else None
            img = None
            if path and os.path.exists(path):
                try:
                    img = load_tx(path)
                except Exception:  # noqa: BLE001
                    img = None
            self.textures.append(img)

        if len(self.P):
            self.center = (self.P.min(0) + self.P.max(0)) * 0.5
            self.extent = float(np.max(self.P.max(0) - self.P.min(0))) or 1.0
        else:
            self.center = np.zeros(3, np.float32)
            self.extent = 1.0

        self.ntri = len(self.F)

    def texture(self, mat=0):
        if 0 <= mat < len(self.textures):
            return self.textures[mat]
        return None

    # ------------------------------------------------------------------ 装配
    @staticmethod
    def merge(scenes, name=None):
        """把多个部件合并成一个场景。

        本批 .gm2 的顶点已经在共用骨架空间里(脚底 y≈0, 头顶 y≈1.8~2.0),
        因此同一 class 的部件直接叠加就是正确的装配, 不需要额外矩阵。
        """
        scenes = [s for s in scenes if s is not None and len(s.F)]
        if not scenes:
            raise ValueError("没有可合并的部件")
        out = Scene.__new__(Scene)
        out.path = ""
        out.name = name or "+".join(s.name for s in scenes)
        out.version = scenes[0].version
        out.gm2 = None
        out.groups = []
        out.tex_names = []
        out.textures = []
        out.parts = [(s.name, s.path, len(s.F)) for s in scenes]

        Ps, Ns, Ts, Fs, FMs = [], [], [], [], []
        vbase = 0
        mbase = 0
        for sc in scenes:
            if not len(sc.P):
                continue
            Ps.append(sc.P)
            Ns.append(sc.N)
            Ts.append(sc.T)
            Fs.append(sc.F + vbase)
            if len(sc.FM):
                FMs.append(sc.FM + mbase)
            else:
                FMs.append(np.zeros(len(sc.F), np.int32) + mbase)
            for g in sc.groups:
                out.groups.append((g[0], g[1], g[2], g[3] + mbase))
            out.tex_names += list(sc.tex_names)
            out.textures += list(sc.textures)
            vbase += len(sc.P)
            mbase += max(1, len(sc.textures))
        out.P = np.concatenate(Ps).astype(np.float32)
        out.N = np.concatenate(Ns).astype(np.float32)
        out.T = np.concatenate(Ts).astype(np.float32)
        out.F = np.concatenate(Fs).astype(np.int32)
        out.FM = np.concatenate(FMs).astype(np.int32)
        out.center = (out.P.min(0) + out.P.max(0)) * 0.5
        out.extent = float(np.max(out.P.max(0) - out.P.min(0))) or 1.0
        out.ntri = len(out.F)
        return out



# ------------------------------------------------------------------ 渲染器
class Renderer:
    def __init__(self, w, h, bg=(28, 30, 36)):
        self.w, self.h = w, h
        self.bg = np.array(bg, dtype=np.float32)
        self.yaw = 25.0
        self.pitch = 10.0
        self.zoom = 1.0
        self.panx = 0.0
        self.pany = 0.0
        self.use_texture = True
        self.wire = False
        self.cull = False
        self.alpha_test = False
        self.light = np.array([0.35, 0.5, 0.79], dtype=np.float32)
        self.light /= np.linalg.norm(self.light)
        self._zbuf = np.zeros((h, w), dtype=np.float32)

    def resize(self, w, h):
        self.w, self.h = w, h
        self._zbuf = np.zeros((h, w), dtype=np.float32)

    # -------------------------------------------------------------- 变换
    def _rotate(self, V, cyaw, syaw, cpit, spit):
        x = V[:, 0]
        y = V[:, 1]
        z = V[:, 2]
        x2 = x * cyaw + z * syaw
        z2 = -x * syaw + z * cyaw
        y2 = y * cpit - z2 * spit
        z3 = y * spit + z2 * cpit
        return np.stack([x2, y2, z3], axis=1)

    def render(self, scene, *, spin=0.0):
        w, h = self.w, self.h
        img = np.empty((h, w, 4), dtype=np.uint8)
        img[:, :, :3] = self.bg.astype(np.uint8)
        img[:, :, 3] = 255
        if scene is None or not len(scene.F):
            return img

        ry = math.radians(self.yaw + spin)
        rp = max(-1.45, min(1.45, math.radians(self.pitch)))
        cyaw, syaw = math.cos(ry), math.sin(ry)
        cpit, spit = math.cos(rp), math.sin(rp)

        Pr = self._rotate(scene.P - scene.center, cyaw, syaw, cpit, spit)
        Nr = self._rotate(scene.N, cyaw, syaw, cpit, spit)

        scale = (min(w, h) * 0.85) / scene.extent * self.zoom
        sx = Pr[:, 0] * scale + w * 0.5 + self.panx
        sy = h * 0.5 - Pr[:, 1] * scale + self.pany
        sz = Pr[:, 2]

        tris = scene.F
        ax, ay = sx[tris[:, 0]], sy[tris[:, 0]]
        bx, by = sx[tris[:, 1]], sy[tris[:, 1]]
        cx, cy = sx[tris[:, 2]], sy[tris[:, 2]]
        area = (bx - ax) * (cy - ay) - (cx - ax) * (by - ay)
        keep = np.abs(area) > 1e-6
        if self.cull:
            keep &= area < 0          # 屏幕 y 向下, 逆时针为正面 -> 负面积
        sel = np.nonzero(keep)[0]

        self._zbuf.fill(-1e30)
        if len(sel):
            # 逐顶点算好光照强度, 光栅化时只插值标量(比逐像素插值法线快很多)
            nl = np.sqrt((Nr * Nr).sum(1))
            nl[nl < 1e-6] = 1.0
            lam = np.abs((Nr @ self.light) / nl)
            shade = (0.34 + 0.66 * lam).astype(np.float32)
            mats = np.unique(scene.FM[sel]) if len(scene.FM) else np.array([0])
            for mat in mats.tolist():
                idxs = sel[scene.FM[sel] == mat] if len(scene.FM) else sel
                if not len(idxs):
                    continue
                t = scene.texture(mat) if self.use_texture else None
                self._raster(scene, idxs, sx, sy, sz, shade, img, t)

        if self.wire:
            self._wire(scene, sx, sy, sz, img, sel)
        return img

    # -------------------------------------------------------------- 光栅化主体
    def _raster(self, scene, idxs, sx, sy, sz, shade, img, tex):
        W, H = self.w, self.h
        zbuf = self._zbuf
        T = scene.T
        F = scene.F
        alpha_test = self.alpha_test
        for ti in idxs:
            i0, i1, i2 = F[ti]
            x0, y0, x1, y1, x2, y2 = sx[i0], sy[i0], sx[i1], sy[i1], sx[i2], sy[i2]
            minx = int(max(0, math.floor(min(x0, x1, x2))))
            maxx = int(min(W - 1, math.ceil(max(x0, x1, x2))))
            miny = int(max(0, math.floor(min(y0, y1, y2))))
            maxy = int(min(H - 1, math.ceil(max(y0, y1, y2))))
            if maxx < minx or maxy < miny:
                continue
            den = (y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2)
            if abs(den) < 1e-9:
                continue
            # 小三角形走标量快路径: 避免为几像素建 numpy 数组
            if (maxx - minx + 1) * (maxy - miny + 1) <= 64:
                self._raster_small(scene, i0, i1, i2, x0, y0, x1, y1, x2, y2, den,
                                   minx, maxx, miny, maxy, sz, shade, img, tex)
                continue
            X, Y = np.meshgrid(np.arange(minx, maxx + 1, dtype=np.float32) + 0.5,
                               np.arange(miny, maxy + 1, dtype=np.float32) + 0.5)
            w0 = ((y1 - y2) * (X - x2) + (x2 - x1) * (Y - y2)) / den
            w1 = ((y2 - y0) * (X - x2) + (x0 - x2) * (Y - y2)) / den
            w2 = 1.0 - w0 - w1
            inside = (w0 >= -1e-5) & (w1 >= -1e-5) & (w2 >= -1e-5)
            if not inside.any():
                continue
            z = w0 * sz[i0] + w1 * sz[i1] + w2 * sz[i2]
            sub = zbuf[miny:maxy + 1, minx:maxx + 1]
            m = inside & (z > sub)
            if not m.any():
                continue

            dst = img[miny:maxy + 1, minx:maxx + 1, :3]
            if tex is not None:
                u = w0 * T[i0, 0] + w1 * T[i1, 0] + w2 * T[i2, 0]
                v = w0 * T[i0, 1] + w1 * T[i1, 1] + w2 * T[i2, 1]
                th, tw = tex.shape[0], tex.shape[1]
                txi = np.clip((u * tw).astype(np.int32), 0, tw - 1)
                tyi = np.clip((v * th).astype(np.int32), 0, th - 1)
                px = tex[tyi, txi]
                if alpha_test:
                    m &= px[:, :, 3] > 90
                    if not m.any():
                        continue
                sh = w0 * shade[i0] + w1 * shade[i1] + w2 * shade[i2]
                rgb = px[m][:, :3].astype(np.float32)
                rgb *= sh[m][:, None]
                np.clip(rgb, 0, 255, out=rgb)
                dst[m] = rgb.astype(np.uint8)
            else:
                sh = w0 * shade[i0] + w1 * shade[i1] + w2 * shade[i2]
                g = np.clip(190.0 * sh[m], 0, 255).astype(np.uint8)
                dst[m] = g[:, None]
            sub[m] = z[m]

    def _raster_small(self, scene, i0, i1, i2, x0, y0, x1, y1, x2, y2, den,
                      minx, maxx, miny, maxy, sz, shade, img, tex):
        """几像素大的三角形用纯 Python 逐像素算, 比建立 numpy 数组更快"""
        T = scene.T
        zbuf = self._zbuf
        z0, z1, z2 = sz[i0], sz[i1], sz[i2]
        s0, s1, s2 = shade[i0], shade[i1], shade[i2]
        if tex is not None:
            tu0, tv0 = T[i0, 0], T[i0, 1]
            tu1, tv1 = T[i1, 0], T[i1, 1]
            tu2, tv2 = T[i2, 0], T[i2, 1]
            th, tw = tex.shape[0], tex.shape[1]
            tpx = tex
            atest = self.alpha_test
        else:
            tpx = None
            atest = False
        inv = 1.0 / den
        for py in range(miny, maxy + 1):
            yy = py + 0.5
            row = zbuf[py]
            prow = img[py]
            for px in range(minx, maxx + 1):
                xx = px + 0.5
                w0 = ((y1 - y2) * (xx - x2) + (x2 - x1) * (yy - y2)) * inv
                if w0 < -1e-5:
                    continue
                w1 = ((y2 - y0) * (xx - x2) + (x0 - x2) * (yy - y2)) * inv
                if w1 < -1e-5:
                    continue
                w2 = 1.0 - w0 - w1
                if w2 < -1e-5:
                    continue
                z = w0 * z0 + w1 * z1 + w2 * z2
                if z <= row[px]:
                    continue
                sh = w0 * s0 + w1 * s1 + w2 * s2
                if tpx is not None:
                    u = w0 * tu0 + w1 * tu1 + w2 * tu2
                    v = w0 * tv0 + w1 * tv1 + w2 * tv2
                    txi = int(u * tw)
                    tyi = int(v * th)
                    if txi < 0:
                        txi = 0
                    elif txi >= tw:
                        txi = tw - 1
                    if tyi < 0:
                        tyi = 0
                    elif tyi >= th:
                        tyi = th - 1
                    p = tpx[tyi, txi]
                    if atest and p[3] <= 90:
                        continue
                    r = p[0] * sh
                    g = p[1] * sh
                    b = p[2] * sh
                else:
                    r = g = b = 190.0 * sh
                prow[px, 0] = 255 if r > 255 else (0 if r < 0 else int(r))
                prow[px, 1] = 255 if g > 255 else (0 if g < 0 else int(g))
                prow[px, 2] = 255 if b > 255 else (0 if b < 0 else int(b))
                row[px] = z

    def _wire(self, scene, sx, sy, sz, img, sel):
        F = scene.F
        for ti in sel:
            i0, i1, i2 = F[ti]
            for a, b in ((i0, i1), (i1, i2), (i2, i0)):
                self._line(sx[a], sy[a], sx[b], sy[b], sz[a], sz[b], img)

    def _line(self, x0, y0, x1, y1, z0, z1, img):
        n = int(max(abs(x1 - x0), abs(y1 - y0))) + 1
        if n > 4096:
            return
        for k in range(n + 1):
            t = k / max(1, n)
            x = int(round(x0 + (x1 - x0) * t))
            y = int(round(y0 + (y1 - y0) * t))
            if 0 <= x < self.w and 0 <= y < self.h:
                zz = z0 + (z1 - z0) * t + 1e-4
                if zz >= self._zbuf[y, x] - 1e-4:
                    img[y, x, :3] = (90, 200, 255)


# ------------------------------------------------------------------ 场景加载器
def find_texture(gm2_path, name):
    if not name:
        return None
    p = os.path.abspath(gm2_path)
    sub = os.path.basename(os.path.dirname(p))
    res = os.path.dirname(os.path.dirname(os.path.dirname(p)))
    for cand in (os.path.join(res, "TEXTURES", sub, name + ".tx"),
                 os.path.join(res, "TEXTURES", name + ".tx")):
        if os.path.exists(cand):
            return cand
    root = os.path.join(res, "TEXTURES")
    for dirpath, _d, files in os.walk(root):
        if name + ".tx" in files:
            return os.path.join(dirpath, name + ".tx")
    return None


def load_scene(gm2_path):
    """自动按 gm2 内的贴图名寻找同级 TEXTURES 目录里的 .tga.tx"""
    return Scene(gm2_path)
