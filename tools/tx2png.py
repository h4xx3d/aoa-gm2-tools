#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tx2png.py  --  将 Storm/VoyageEngine 引擎的 .tga.tx 贴图转换为 PNG / TGA / DDS

AOA(机甲世纪) 的贴图文件结构(小端):

    offset 0   uint32  version          (值为 0)
    offset 4   uint32  width
    offset 8   uint32  height
    offset 12  uint32  flags            (bit0/bit1 = ?, bit3 = 有 mipmap; 1 = 无 mipmap)
    offset 16  uint32  d3dformat        21=A8R8G8B8  23=R5G6B5  25=A1R5G5B5
                                        26=A4R4G4B4  22=X8R8G8B8  0x31545844='DXT1'
                                        0x33545844='DXT3'  0x35545844='DXT5'
    offset 20  uint32  level0_size      第 0 级(主图)字节数
    offset 24  ...     像素数据         之后依次是 mip 各级(可能缺失/截断)

用法:
    python tx2png.py <文件或目录> [-o 输出目录] [--fmt png|tga|dds] [--all]
        --all   同时导出 mipmap 各级 (默认只导主图)
"""
from __future__ import annotations

import argparse
import os
import struct
import sys
import zlib

# ---------------------------------------------------------------- D3D formats
FMT_A8R8G8B8 = 21
FMT_X8R8G8B8 = 22
FMT_R5G6B5 = 23
FMT_X1R5G5B5 = 24
FMT_A1R5G5B5 = 25
FMT_A4R4G4B4 = 26
FMT_A8 = 28
FMT_L8 = 50
FMT_A8L8 = 51

FOURCC = {
    0x31545844: "DXT1",
    0x33545844: "DXT3",
    0x34545844: "DXT4",
    0x35545844: "DXT5",
    0x32545844: "DXT2",
}


def bytes_per_pixel(fmt: int):
    return {
        FMT_A8R8G8B8: 4, FMT_X8R8G8B8: 4,
        FMT_R5G6B5: 2, FMT_X1R5G5B5: 2, FMT_A1R5G5B5: 2, FMT_A4R4G4B4: 2,
        FMT_A8: 1, FMT_L8: 1, FMT_A8L8: 2,
    }.get(fmt)


def level_bytes(fmt: int, w: int, h: int) -> int:
    """返回某一 mip 级在文件中的字节数"""
    bpp = bytes_per_pixel(fmt)
    if bpp is not None:
        return w * h * bpp
    if fmt in FOURCC:
        code = FOURCC[fmt]
        bw = max(1, (w + 3) // 4)
        bh = max(1, (h + 3) // 4)
        return bw * bh * (8 if code == "DXT1" else 16)
    raise ValueError("unsupported d3dformat 0x%08X" % fmt)


# ---------------------------------------------------------------- block decode
def decode_dxt(data: bytes, w: int, h: int, code: str, force_block16: bool = False):
    out = bytearray(w * h * 4)
    bw, bh = (w + 3) // 4, (h + 3) // 4
    block = 16 if (force_block16 or code != "DXT1") else 8
    pos = 0
    for by in range(bh):
        for bx in range(bw):
            chunk = data[pos:pos + block]
            pos += block
            if len(chunk) < block:
                chunk = chunk + b"\0" * (block - len(chunk))
            if block == 8:
                c = _dxt1_colors(chunk)
                alpha = [255] * 16
            else:
                c = _565_pair(chunk[8:12])
                if code in ("DXT3", "DXT2"):
                    alpha = _dxt3_alpha(chunk[0:8])
                else:
                    alpha = _dxt5_alpha(chunk[0:8])
            bits = int.from_bytes(chunk[block - 4:block], "little")
            for i in range(16):
                px = bx * 4 + (i & 3)
                py = by * 4 + (i >> 2)
                if px >= w or py >= h:
                    continue
                o = (py * w + px) * 4
                idx = (bits >> (2 * i)) & 3
                out[o:o + 3] = c[idx]
                out[o + 3] = alpha[i]
    return bytes(out)


def _565_pair(chunk: bytes):
    c0, c1 = struct.unpack("<HH", chunk)
    return _expand565(c0, c1, False)


def _dxt1_colors(chunk: bytes):
    c0, c1 = struct.unpack("<HH", chunk[:4])
    return _expand565(c0, c1, True)


def _expand565(c0: int, c1: int, dxt1: bool):
    def un(v):
        r = (v >> 11) & 0x1F
        g = (v >> 5) & 0x3F
        b = v & 0x1F
        return bytes(((r << 3) | (r >> 2), (g << 2) | (g >> 4), (b << 3) | (b >> 2)))

    p0, p1 = un(c0), un(c1)
    if c0 > c1 or not dxt1:
        p2 = bytes(((2 * p0[i] + p1[i]) // 3) for i in range(3))
        p3 = bytes(((p0[i] + 2 * p1[i]) // 3) for i in range(3))
        return (p0, p1, p2, p3)
    p2 = bytes(((p0[i] + p1[i]) // 2) for i in range(3))
    return (p0, p1, p2, b"\0\0\0")


def _dxt3_alpha(chunk: bytes):
    a = int.from_bytes(chunk, "little")
    return [((a >> (4 * i)) & 0xF) * 17 for i in range(16)]


def _dxt5_alpha(chunk: bytes):
    a0, a1 = chunk[0], chunk[1]
    if a0 > a1:
        table = [a0, a1] + [((7 - i) * a0 + (i + 1) * a1) // 8 for i in range(6)]
    else:
        table = [a0, a1] + [((5 - i) * a0 + (i + 1) * a1) // 6 for i in range(4)] + [0, 255]
    bits = int.from_bytes(chunk[2:8], "little")
    return [table[(bits >> (3 * i)) & 7] for i in range(16)]


# ---------------------------------------------------------------- pixel decode
def decode_level(data: bytes, fmt: int, w: int, h: int, block16: bool = False):
    """解码一级 mip 为 RGBA8888"""
    if fmt in FOURCC:
        return decode_dxt(data, w, h, FOURCC[fmt], force_block16=block16)
    bpp = bytes_per_pixel(fmt)
    if bpp is None:
        raise ValueError("unsupported d3dformat 0x%08X" % fmt)
    out = bytearray(w * h * 4)
    n = w * h
    if fmt in (FMT_A8R8G8B8, FMT_X8R8G8B8):
        # 内存中顺序 B,G,R,A
        for i in range(n):
            b, g, r, a = data[4 * i:4 * i + 4]
            o = 4 * i
            out[o] = r
            out[o + 1] = g
            out[o + 2] = b
            out[o + 3] = a if fmt == FMT_A8R8G8B8 else 255
    elif fmt in (FMT_A1R5G5B5, FMT_X1R5G5B5, FMT_A4R4G4B4, FMT_R5G6B5):
        for i in range(n):
            v = data[2 * i] | (data[2 * i + 1] << 8)
            o = 4 * i
            if fmt == FMT_R5G6B5:
                r, g, b, a = (v >> 11) & 0x1F, (v >> 5) & 0x3F, v & 0x1F, 255
                out[o] = (r << 3) | (r >> 2)
                out[o + 1] = (g << 2) | (g >> 4)
                out[o + 2] = (b << 3) | (b >> 2)
            elif fmt == FMT_A4R4G4B4:
                a, r, g, b = (v >> 12) & 0xF, (v >> 8) & 0xF, (v >> 4) & 0xF, v & 0xF
                out[o], out[o + 1], out[o + 2], out[o + 3] = r * 17, g * 17, b * 17, a * 17
            else:  # 1:5:5:5
                a, r, g, b = (v >> 15) & 1, (v >> 10) & 0x1F, (v >> 5) & 0x1F, v & 0x1F
                out[o] = (r << 3) | (r >> 2)
                out[o + 1] = (g << 3) | (g >> 2)
                out[o + 2] = (b << 3) | (b >> 2)
                out[o + 3] = 255 if (fmt == FMT_X1R5G5B5 or a) else 0
    elif fmt in (FMT_A8, FMT_L8):
        for i in range(n):
            v = data[i]
            out[4 * i:4 * i + 4] = bytes((v, v, v, 255))
    elif fmt == FMT_A8L8:
        for i in range(n):
            l, a = data[2 * i], data[2 * i + 1]
            out[4 * i:4 * i + 4] = bytes((l, l, l, a))
    return bytes(out)


# ---------------------------------------------------------------- file writers
def write_png(path: str, rgba: bytes, w: int, h: int):
    raw = bytearray()
    stride = w * 4
    for y in range(h):
        raw.append(0)
        raw += rgba[y * stride:(y + 1) * stride]

    def chunk(tag: bytes, payload: bytes) -> bytes:
        return (struct.pack(">I", len(payload)) + tag + payload
                + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF))

    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n")
        f.write(chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)))
        f.write(chunk(b"IDAT", zlib.compress(bytes(raw), 6)))
        f.write(chunk(b"IEND", b""))


def write_tga(path: str, rgba: bytes, w: int, h: int):
    hdr = struct.pack("<BBBHHBHHHHBB", 0, 0, 2, 0, 0, 0, 0, 0, w, h, 32, 8)
    bgra = bytearray(len(rgba))
    bgra[0::4] = rgba[2::4]
    bgra[1::4] = rgba[1::4]
    bgra[2::4] = rgba[0::4]
    bgra[3::4] = rgba[3::4]
    with open(path, "wb") as f:
        f.write(hdr)
        f.write(bgra)  # TGA 为 B,G,R,A 顺序


def write_dds(path: str, rgba: bytes, w: int, h: int):
    """存成 A8R8G8B8 的非压缩 DDS(内存序为 BGRA，与 D3D 一致)"""
    flags = 0x1 | 0x2 | 0x4 | 0x1000 | 0x8
    pitch = w * 4
    hdr = struct.pack("<4s7I44x", b"DDS ", 124, flags, h, w, pitch, 0, 0)
    hdr += struct.pack("<2I4s5I", 32, 0x41, b"\0\0\0\0", 32, 0x00FF0000, 0x0000FF00,
                       0x000000FF, 0xFF000000)
    bgra = bytearray(len(rgba))
    bgra[0::4] = rgba[2::4]
    bgra[1::4] = rgba[1::4]
    bgra[2::4] = rgba[0::4]
    bgra[3::4] = rgba[3::4]
    with open(path, "wb") as f:
        f.write(hdr)
        f.write(bgra)


# ---------------------------------------------------------------- main convert
def convert(path: str, outdir: str, fmt: str = "png", all_levels: bool = False,
            verbose: bool = True):
    data = open(path, "rb").read()
    if len(data) < 24:
        raise ValueError("file too small")
    version, w, h, flags, d3dfmt, l0size = struct.unpack("<6I", data[:24])
    if not (0 < w <= 8192 and 0 < h <= 8192):
        raise ValueError("bad dimensions %dx%d" % (w, h))
    code = FOURCC.get(d3dfmt)
    block16 = False
    if code == "DXT1":
        # 本引擎部分文件 fourcc 写 DXT1 但每像素按 1 字节存储(DXT3/DXT5 尺寸)
        exp8 = max(1, (w + 3) // 4) * max(1, (h + 3) // 4) * 8
        if l0size and l0size > exp8:
            block16 = True

    levels = []
    off = 24
    cw, ch = w, h
    while True:
        try:
            size = level_bytes(FMT_A8R8G8B8 if block16 else d3dfmt, cw, ch)
        except ValueError:
            size = 0
        if code == "DXT1" and block16:
            size = max(1, (cw + 3) // 4) * max(1, (ch + 3) // 4) * 16
        if off + size > len(data) or size == 0:
            break
        levels.append((cw, ch, data[off:off + size]))
        off += size
        if cw == 1 and ch == 1:
            break
        cw, ch = max(1, cw // 2), max(1, ch // 2)
        if not all_levels and len(levels) == 1:
            break

    rgba = decode_level(levels[0][2], d3dfmt, w, h, block16=block16)
    base = os.path.splitext(os.path.splitext(os.path.basename(path))[0])[0]
    os.makedirs(outdir, exist_ok=True)
    out = os.path.join(outdir, base + "." + fmt)
    if fmt == "png":
        write_png(out, rgba, w, h)
    elif fmt == "tga":
        write_tga(out, rgba, w, h)
    else:
        write_dds(out, rgba, w, h)
    if verbose:
        name = code or {FMT_A8R8G8B8: "A8R8G8B8", FMT_X8R8G8B8: "X8R8G8B8",
                        FMT_R5G6B5: "R5G6B5", FMT_A1R5G5B5: "A1R5G5B5",
                        FMT_X1R5G5B5: "X1R5G5B5", FMT_A4R4G4B4: "A4R4G4B4"}.get(
                            d3dfmt, "0x%08X" % d3dfmt)
        print("%-34s %4dx%-4d %-9s levels=%d -> %s" %
              (os.path.basename(path), w, h, name, len(levels), os.path.basename(out)))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="convert .tga.tx textures to png/tga/dds")
    ap.add_argument("path", help="file or directory (recursive)")
    ap.add_argument("-o", "--outdir", default=None)
    ap.add_argument("--fmt", default="png", choices=("png", "tga", "dds"))
    ap.add_argument("--all", action="store_true", help="also export mip chain as file_mipN")
    args = ap.parse_args(argv)

    src = args.path
    if os.path.isdir(src):
        targets = []
        for root, _dirs, files in os.walk(src):
            for f in sorted(files):
                if f.lower().endswith((".tx", ".dds")):
                    targets.append(os.path.join(root, f))
        outdir = args.outdir or os.path.join(src, "_png")
    else:
        targets = [src]
        outdir = args.outdir or os.path.dirname(os.path.abspath(src))

    ok = err = 0
    for t in targets:
        try:
            convert(t, outdir, args.fmt)
            ok += 1
        except Exception as e:  # noqa: BLE001
            err += 1
            print("!! %s : %s" % (t, e), file=sys.stderr)
    print("done: %d ok, %d failed" % (ok, err))


if __name__ == "__main__":
    main()
