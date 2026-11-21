#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
github_upload.py -- 把本项目的脚本文件上传到 GitHub（只传脚本/文档，不传资源与输出）

依赖: 仅标准库。认证用环境变量或参数传入的 Personal Access Token(classic: ghp_...)。

用法:
    $env:GH_TOKEN = "ghp_xxx"
    python tools\\github_upload.py --dry-run                  # 只看要上传哪些文件
    python tools\\github_upload.py                            # 上传(仓库不存在则创建)
    python tools\\github_upload.py --repo my-repo --public     # 指定仓库名/公开
    python tools\\github_upload.py --update                   # 覆盖已存在的文件(更新内容)

只上传: README.md, convert_all.ps1, .gitignore, tools/*.py
跳过  : RESOURCE/, OUT/, __pycache__/, tools/_ 开头的临时脚本
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

API = "https://api.github.com"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKIP_DIRS = {"RESOURCE", "OUT", "__pycache__", ".git"}
NOTE_LINE = ("> 本仓库只包含脚本与文档；`RESOURCE\\`（解包资源）与 `OUT\\`（转换输出）不在仓库内，"
             "运行脚本前请自行放入。")


# ------------------------------------------------------------------ HTTP
def api(path, method="GET", data=None, token="", raw=False, retries=3):
    """带重试的 API 调用(网络抖动/SSL EOF 在本机到 GitHub 的链路上偶发)"""
    last = (-1, "not tried", {})
    for attempt in range(retries):
        last = _api_once(path, method, data, token, raw)
        code = last[0]
        if code != -1:
            return last
        time.sleep(0.8 * (attempt + 1))
    return last


def _api_once(path, method="GET", data=None, token="", raw=False):
    url = path if path.startswith("http") else API + path
    body = json.dumps(data).encode("utf-8") if data is not None else None
    req = urllib.request.Request(url, data=body, method=method)
    req.add_header("Authorization", "token " + token)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", "aoa-uploader")
    if body is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            payload = r.read()
            return r.status, (payload if raw else (json.loads(payload) if payload else {})), dict(r.headers)
    except urllib.error.HTTPError as e:
        txt = e.read().decode("utf-8", "replace")
        try:
            txt = json.loads(txt)
        except Exception:  # noqa: BLE001
            pass
        return e.code, txt, dict(e.headers)
    except Exception as e:  # noqa: BLE001
        return -1, repr(e), {}


# ------------------------------------------------------------------ 文件收集
def collect(include_images=False):
    files = []
    for name in ("README.md", "convert_all.ps1", ".gitignore"):
        p = os.path.join(ROOT, name)
        if os.path.exists(p):
            files.append((name, p))
    tdir = os.path.join(ROOT, "tools")
    if os.path.isdir(tdir):
        for fn in sorted(os.listdir(tdir)):
            if not fn.endswith(".py") or fn.startswith("_"):
                continue
            files.append(("tools/" + fn, os.path.join(tdir, fn)))
    if include_images:
        for fn in ("viewer_screenshot.png", "viewer_dynamic.png"):
            p = os.path.join(ROOT, "OUT", fn)
            if os.path.exists(p):
                files.append(("docs/" + fn, p))
    return files


def readme_for_repo():
    """README 里引用了本地 OUT 目录的截图, 仓库里没有, 换成一行说明"""
    p = os.path.join(ROOT, "README.md")
    text = open(p, encoding="utf-8").read()
    text = re.sub(r"^!\[[^\]]*\]\((?:OUT|docs)/[^)]*\)\s*$", "", text, flags=re.M)
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.startswith("## 0."):
            lines.insert(i, NOTE_LINE + "\n")
            break
    return "\n".join(lines)


# ------------------------------------------------------------------ 主流程
def main(argv=None):
    ap = argparse.ArgumentParser(description="上传项目脚本到 GitHub")
    ap.add_argument("--token", default=os.environ.get("GH_TOKEN", ""))
    ap.add_argument("--repo", default="aoa-gm2-tools")
    ap.add_argument("--public", action="store_true", help="公开仓库(默认私有)")
    ap.add_argument("--description",
                    default="机甲世纪/AOA (VoyageEngine) 的 .gm2 模型与 .tga.tx 贴图解析、转换、装配与查看工具")
    ap.add_argument("--update", action="store_true", help="覆盖已存在的文件")
    ap.add_argument("--images", action="store_true", help="顺带上传 OUT 下的两张截图到 docs/")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    files = collect(include_images=args.images)
    print("待上传 %d 个文件:" % len(files))
    for path, local in files:
        print("   %-28s %8d B" % (path, os.path.getsize(local)))
    if args.dry_run:
        return 0

    token = (args.token or "").strip()
    if not token:
        print("缺少 token: 设置环境变量 GH_TOKEN 或传 --token", file=sys.stderr)
        return 2
    if not token.startswith(("ghp_", "github_pat_")):
        print("token 前缀异常(应为 ghp_ 或 github_pat_)", file=sys.stderr)
    if token.startswith("ghp_") and len(token) != 40:
        print("警告: classic token 应为 40 字符, 当前 %d 字符, 可能复制时丢了字符"
              % len(token), file=sys.stderr)

    code, me, _ = api("/user", token=token)
    if code != 200:
        print("认证失败(%s): %s" % (code, me), file=sys.stderr)
        return 3
    login = me["login"]
    print("账号: %s" % login)

    full = "%s/%s" % (login, args.repo)
    code, repo, _ = api("/repos/" + full, token=token)
    if code == 404:
        code, repo, _ = api("/user/repos", "POST", {
            "name": args.repo,
            "description": args.description,
            "private": not args.public,
            "has_issues": True,
            "has_wiki": False,
            "auto_init": False,
        }, token=token)
        if code not in (200, 201):
            print("创建仓库失败(%s): %s" % (code, repo), file=sys.stderr)
            return 4
        print("已创建仓库: %s (%s)" % (repo["full_name"], "public" if not repo["private"] else "private"))
    elif code == 200:
        print("使用已有仓库: %s" % repo["full_name"])
    else:
        print("查询仓库失败(%s): %s" % (code, repo), file=sys.stderr)
        return 4

    ok = fail = skip = 0
    for path, local in files:
        if path == "README.md":
            content = readme_for_repo().encode("utf-8")
        else:
            content = open(local, "rb").read()
        cpath = "/repos/%s/contents/%s" % (full, path.replace("\\", "/"))
        ccode, cur, _ = api(cpath, token=token)
        sha = None
        if ccode == 200 and isinstance(cur, dict):
            sha = cur.get("sha")
            if not args.update:
                print("   跳过(已存在) %s" % path)
                skip += 1
                continue
        payload = {
            "message": ("Update " if sha else "Add ") + path,
            "content": base64.b64encode(content).decode("ascii"),
        }
        if sha:
            payload["sha"] = sha
        wcode, res, _ = api(cpath, "PUT", payload, token=token)
        if wcode in (200, 201):
            print("   [OK] %s" % path)
            ok += 1
        else:
            print("   [FAIL] %s -> %s %s" % (path, wcode, res), file=sys.stderr)
            fail += 1

    # 列一下远程目录, 确认结果
    tcode, tree, _ = api("/repos/%s/git/trees/HEAD?recursive=1" % full, token=token)
    if tcode == 200 and isinstance(tree, dict):
        paths = sorted(t["path"] for t in tree.get("tree", []) if t["type"] == "blob")
        print("\n远程文件 (%d):" % len(paths))
        for p in paths:
            print("   " + p)

    print("\n完成: 新增/更新 %d, 跳过 %d, 失败 %d" % (ok, skip, fail))
    print("仓库地址: %s" % repo.get("html_url", "https://github.com/" + full))
    return 0 if fail == 0 else 5


if __name__ == "__main__":
    sys.exit(main())
