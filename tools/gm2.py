#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gm2.py -- VoyageEngine(Storm Engine 分支) .gm2 模型解析 + 导出 OBJ/MTL

文件结构 (全部小端, 已用 434 个真实 .gm2 验证):

  GM2_HEAD
     0  char   version[4]   "60.1"
     4  int32  flags
     8  int32  name_size        名字区字节数
    12  int32  nnames           名字个数
    16  int32  ntextures
    20  int32  nmaterials
    24  int32  nlights
    28  int32  nlabels           挂点/骨骼矩阵
    32  int32  nobjects
    36  int32  ntriangles        总三角数
    40  int32  nvrtbuffs         顶点缓冲个数
    44  vec3   bbox_size
    56  vec3   bbox_center
    68  float  radius

  NAMES         name_size 字节, 以 0 分隔的字符串表; 材质/贴图/物体用"字符串表内偏移"引用
  NAMEREFS      nnames * int32  (名字偏移按顺序再列一遍)
  TEXTURES      ntextures * int32  -> 字符串表偏移 (例如 "39101001.tga")
  MATERIALS     nmaterials * 56
                  int32 group_name, name; float diffuse, specular, gloss, selfIllum;
                  int32 texture_type[4] (0=无 1=base 2=normal); int32 texture[4]
  LIGHTS        nlights * (未在样本中出现, 未解析)
  LABELS        nlabels * 108
                  int32 group_name, name, flags; float m[4][4]; int32 bones[4]; float weight[4]
  OBJECTS       nobjects * 108
                  int32 group_name, name, flags; vec3 center; float radius;
                  int32 vertex_buff, ntriangles, striangle, nvertices, svertex,
                        material, lights[8], bones[4], atriangles, pad
  TRIANGLES     ntriangles * 3 * uint16     (相对所属顶点缓冲的下标)
  VRTBUFFS      nvrtbuffs * { int32 type, int32 size }   size = 该缓冲顶点数据字节数
  VERTICES      按 type 排列的顶点数据

顶点(按 stride 判定):
   44 字节: pos(3f) weight(f) boneid(i) normal(3f) color(i) uv(2f)
   52 字节: 同上 + uv2(2f)
   36 字节: pos(3f) normal(3f) color(i) uv(2f)      (静态顶点)
"""
from __future__ import annotations

import json
import os
import struct
import sys

HEAD_FMT = "<4s10i3f3ff"
HEAD_SIZE = 72

# 布局候选: 顶点 = pos(3f) + 蒙皮块(skin 字节) + normal(3f) + color(4B) + uv 若干组(2f 每组)
# 已在实际文件中见到 stride 36/44/48/52/56/60 共 6 种
SKIN_CANDIDATES = (0, 8, 12, 16, 20, 24)
UVSET_CANDIDATES = (1, 2, 3)


class Gm2Error(Exception):
    pass


class Gm2:
    def __init__(self, path):
        self.path = path
        self.data = open(path, "rb").read()
        self._parse()

    # ------------------------------------------------------------------ header
    def _parse(self):
        d = self.data
        if len(d) < HEAD_SIZE:
            raise Gm2Error("file too small")
        (ver, self.flags, self.name_size, self.nnames, self.ntextures,
         self.nmaterials, self.nlights, self.nlabels, self.nobjects,
         self.ntriangles, self.nvrtbuffs) = struct.unpack("<4s10i", d[:44])
        self.version = ver.decode("latin1").rstrip("\0")
        if self.version not in ("60.1", "56.1", "58.1", "1.05"):
            raise Gm2Error("unexpected version %r" % self.version)
        (self.bbox_size, self.bbox_center, self.radius) = (
            struct.unpack("<3f", d[44:56]), struct.unpack("<3f", d[56:68]),
            struct.unpack("<f", d[68:72])[0])

        off = HEAD_SIZE
        # 字符串表
        blob = d[off:off + self.name_size]
        if len(blob) != self.name_size:
            raise Gm2Error("truncated names")
        self.names = {}
        pos = 0
        while pos < self.name_size:
            end = blob.find(b"\0", pos)
            if end < 0:
                end = self.name_size
            self.names[pos] = blob[pos:end].decode("latin1")
            pos = end + 1
        off += self.name_size

        off += self.nnames * 4                      # NAMEREFS
        self.textures = list(struct.unpack("<%di" % self.ntextures,
                                          d[off:off + 4 * self.ntextures])) if self.ntextures else []
        off += self.ntextures * 4

        self.materials = []
        for _ in range(self.nmaterials):
            g, n = struct.unpack("<2i", d[off:off + 8])
            diffuse, specular, gloss, selfillum = struct.unpack("<4f", d[off + 8:off + 24])
            ttype = struct.unpack("<4i", d[off + 24:off + 40])
            tex = struct.unpack("<4i", d[off + 40:off + 56])
            self.materials.append(dict(group=self.name_of(g), name=self.name_of(n),
                                       diffuse=diffuse, specular=specular,
                                       gloss=gloss, selfillum=selfillum,
                                       texture_type=ttype, texture=tex))
            off += 56

        if self.nlights:
            raise Gm2Error("nlights=%d 未支持" % self.nlights)

        self.labels = []
        for _ in range(self.nlabels):
            g, n, fl = struct.unpack("<3i", d[off:off + 12])
            m = struct.unpack("<16f", d[off + 12:off + 76])
            bones = struct.unpack("<4i", d[off + 76:off + 92])
            weight = struct.unpack("<4f", d[off + 92:off + 108])
            self.labels.append(dict(group=self.name_of(g), name=self.name_of(n),
                                    flags=fl, matrix=m, bones=bones, weight=weight))
            off += 108

        self.objects = []
        for _ in range(self.nobjects):
            g, n, fl = struct.unpack("<3i", d[off:off + 12])
            center = struct.unpack("<3f", d[off + 12:off + 24])
            radius = struct.unpack("<f", d[off + 24:off + 28])[0]
            (vb, ntri, stri, nverts, svert, mat) = struct.unpack("<6i", d[off + 28:off + 52])
            self.objects.append(dict(group=self.name_of(g), name=self.name_of(n),
                                     flags=fl, center=center, radius=radius,
                                     vertex_buff=vb, ntriangles=ntri, striangle=stri,
                                     nvertices=nverts, svertex=svert, material=mat))
            off += 108

        tri_off = off
        self.triangles = struct.unpack("<%dH" % (self.ntriangles * 3),
                                       d[tri_off:tri_off + self.ntriangles * 6])
        off += self.ntriangles * 6

        self.vrtbuffs = []
        for _ in range(self.nvrtbuffs):
            typ, size = struct.unpack("<2i", d[off:off + 8])
            self.vrtbuffs.append((typ, size))
            off += 8

        self.buffers = []
        for bi, (typ, size) in enumerate(self.vrtbuffs):
            raw = d[off:off + size]
            if len(raw) != size:
                raise Gm2Error("truncated vertex buffer")
            off += size
            hint = 0
            for o in self.objects:
                if o["vertex_buff"] == bi and o["nvertices"] > 0:
                    hint = max(hint, o["nvertices"])
            self.buffers.append(self._decode_vertices(raw, typ, size, hint))
        if off != len(d):
            self.warn = "trailing %d bytes" % (len(d) - off)

    def name_of(self, ref):
        return self.names.get(ref, "")

    # ---------------------------------------------------------------- vertices
    def _decode_vertices(self, raw, typ, size, hint_n=0):
        """推出 stride 与布局: 优先用物体记录里的顶点数(hint), 再用"法线是否单位向量 / UV 是否合理"打分"""
        cands = []
        for skin in SKIN_CANDIDATES:
            for uvsets in UVSET_CANDIDATES:
                stride = 28 + skin + 8 * uvsets
                if size % stride:
                    continue
                n = size // stride
                if hint_n and n != hint_n:
                    continue
                verts = self._decode_with_stride(raw, stride, skin, uvsets)
                cands.append((self._score(verts), stride, skin, uvsets, verts))
        if not cands and hint_n:
            return self._decode_vertices(raw, typ, size, 0)   # 放弃 hint 再试一次
        if not cands:
            raise Gm2Error("cannot decode vertex buffer type=%d size=%d" % (typ, size))
        cands.sort(key=lambda c: (c[0], c[3]), reverse=True)
        score, stride, skin, uvsets, verts = cands[0]
        if score < 0.5:
            raise Gm2Error("vertex buffer type=%d size=%d 布局无法确定 (score=%.2f)" %
                           (typ, size, score))
        return dict(type=typ, stride=stride, skin=skin, uvsets=uvsets,
                    verts=verts, score=score)

    def _decode_with_stride(self, raw, stride, skin, uvsets):
        n = len(raw) // stride
        verts = []
        uv_off = 12 + skin + 12 + 4        # pos + skin + normal + color
        for i in range(n):
            o = i * stride
            pos = struct.unpack("<3f", raw[o:o + 12])
            nrm = struct.unpack("<3f", raw[o + 12 + skin:o + 24 + skin])
            col = struct.unpack("<I", raw[o + 24 + skin:o + 28 + skin])[0]
            uv = struct.unpack("<2f", raw[o + uv_off:o + uv_off + 8])
            uv2 = (struct.unpack("<2f", raw[o + uv_off + 8:o + uv_off + 16])
                   if uvsets >= 2 else None)
            w = struct.unpack("<f", raw[o + 12:o + 16])[0] if skin >= 4 else 0.0
            bid = struct.unpack("<i", raw[o + 16:o + 20])[0] if skin >= 8 else -1
            verts.append((pos, nrm, col, uv, uv2, bid, w))
        return verts

    @staticmethod
    def _score(verts):
        if not verts:
            return 0.0
        gn = gu = gp = 0
        for pos, nrm, _c, uv, _uv2, _b, _w in verts:
            if all(-500.0 < v < 500.0 for v in pos):
                gp += 1
            if abs(sum(v * v for v in nrm) - 1.0) < 0.05:
                gn += 1
            if all(-0.02 <= v <= 1.02 for v in uv):
                gu += 1
        n = len(verts)
        return (gn + gu + gp) / (3.0 * n)


    # ------------------------------------------------------------------ report
    def texture_name(self, material_index, slot=0):
        if not self.materials or material_index < 0 or material_index >= len(self.materials):
            return None
        idx = self.materials[material_index]["texture"][slot]
        if idx < 0 or idx >= len(self.textures):
            return None
        return self.name_of(self.textures[idx])


def bbox_of(points):
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    zs = [p[2] for p in points]
    return (min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs))


if __name__ == "__main__":
    import glob
    _here = os.path.dirname(os.path.abspath(__file__))
    _default = os.path.join(os.path.dirname(_here), "RESOURCE", "MODELS", "human")
    root = sys.argv[1] if len(sys.argv) > 1 else _default
    files = sorted(glob.glob(os.path.join(root, "*.gm2")))
    nfail = 0
    for p in files:
        try:
            g = Gm2(p)
        except Exception as e:  # noqa: BLE001
            nfail += 1
            print("FAIL", os.path.basename(p), e)
            continue
        vt = sum(len(b["verts"]) for b in g.buffers)
        tri = g.ntriangles
        texs = [g.texture_name(i) for i in range(len(g.materials))]
        # 校验: 每个物体的下标范围
        problems = []
        for oi, o in enumerate(g.objects):
            b = g.buffers[o["vertex_buff"]]
            if len(b["verts"]) != o["nvertices"]:
                problems.append("obj%d nverts %d != buf %d" %
                                (oi, o["nvertices"], len(b["verts"])))
            if o["svertex"]:
                problems.append("obj%d svertex=%d" % (oi, o["svertex"]))
            sub = g.triangles[o["striangle"] * 3:(o["striangle"] + o["ntriangles"]) * 3]
            if sub and max(sub) >= o["nvertices"]:
                problems.append("obj%d index %d >= %d" % (oi, max(sub), o["nvertices"]))
            if o["striangle"] + o["ntriangles"] > g.ntriangles:
                problems.append("obj%d tri range overflow" % oi)
        print("%-16s v=%4d tri=%4d objs=%d bufs=%s tex=%s %s" % (
            os.path.basename(p), vt, tri, len(g.objects),
            [(b["type"], b["stride"]) for b in g.buffers], texs,
            ("!! " + "; ".join(problems)) if problems else ""))
    print("total", len(files), "fail", nfail)
