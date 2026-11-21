# AOA（机甲世纪 / VoyageEngine）模型与贴图：格式说明与打开方式

本文说明 `RESOURCE\MODELS\*.gm2` 与 `RESOURCE\TEXTURES\*.tga.tx` 两种文件的内部结构，并给出把它们转换成通用格式的完整做法。

**结论**：这两种文件是引擎私有格式，通用软件无法直接打开。用本目录 `tools\` 下的脚本转换或交互查看即可。

---

> 本仓库只包含脚本与文档；`RESOURCE\`（解包资源）与 `OUT\`（转换输出）不在仓库内，运行脚本前请自行放入。

## 0. 3D 交互查看器（推荐先试这个）

```powershell
python tools\viewer_gui.py
```

左侧有「单件模型」和「角色装配」两个标签页，右侧是实时 3D 视图，贴图自动加载，不用转换、不用显卡。


| 操作 | 作用 |
|---|---|
| 左键拖动 | 旋转 |
| 右键拖动 | 平移 |
| 滚轮 | 缩放 |
| 双击列表 / ↑ ↓ | 切换模型（装配页里切换同一类的编号） |
| T | 贴图 / 纯色切换 |
| W | 线框叠加 |
| A | Alpha 丢弃（头发、镂空） |
| C | 背面剔除 |
| R | 重置视角 |
| 空格 | 自动旋转 |

### 0.1 角色动态装配

「角色装配」页把头发、头、身体三个槽实时合成一个完整角色，**任一槽换部件立即重新生成，视角不重置**，可以一边旋转一边对比换装效果：


| 控件 | 作用 |
|---|---|
| 类 / 体型 | 过滤候选部件；选「全部」可跨类混搭（会显示 ⚠ 提示，骨架尺寸不同可能悬空） |
| 整套编号列表 | 点一下把三个槽一起设成该编号（`3/3` 齐全，`1/3 缺01,02` 缺件） |
| 头发 / 头部 / 身体 下拉 | 逐槽自由替换，改完立刻合成；前面的勾选框可整体隐藏该槽 |
| 导出 OBJ | 把当前合成结果写到 `OUT\MODELS\_assembly\`（文件名列出三个部件名） |
| 随机三件 | 三槽各自随机，常能拼出整套编号里没有的搭配 |
| 清空 | 三个槽全部取消 |

信息区显示部件数、面数、三个部件名，以及当前是「整套 xxx」还是「手工混搭」。↑↓ 在同一类的整套编号之间切换。

装配原理：这批 `.gm2` 的顶点本来就写在**共用骨架空间**里（脚底 y≈0、头顶 y≈1.8~2.0，同一类的 `Bip01 HeadNub` 等挂点坐标完全相同），所以同一类的部件直接叠加即正确，不需要对齐操作。部件场景按路径缓存（24 个），换部件只需重新拼接顶点数组，实测重建 + 渲染约 30~60 ms。

命名规则（434 个文件全部符合）：

```
39 <类 1-6> <槽 01-03> <编号 001-114>
   槽 01 = 头发    槽 02 = 头    槽 03 = 身体(含衣服/手套/靴子)
```

同一「类 + 编号」的三个槽属于同一个角色。136 个组合的三部件齐全，另外 20 个只有部分部件。

### 0.2 命令行装配与批量导出

```powershell
python tools\assemble.py --list                                  # 列出全部组合与缺失情况
python tools\assemble.py --class 3 --variant 111 --preview a.png  # 装配一个, 出预览图
python tools\assemble.py --from 39303111 --obj OUT\MODELS\_assembly  # 按任一部件名自动补齐其它槽
python tools\assemble.py --parts 39101001,39102001,39103001 --obj OUT\MODELS\_assembly
python tools\assemble.py --all --obj OUT\MODELS\_assembly --preview-dir OUT\CHARACTERS --gallery OUT\CHARACTERS\index.html --size 460
```

最后一条会把 136 个齐全组合全部装配、导出 OBJ、渲染预览并生成 `OUT\CHARACTERS\index.html` 索引页。

其他启动方式：

```powershell
python tools\viewer_gui.py RESOURCE\MODELS\human\39303111.gm2   # 直接打开某个模型
python tools\viewer_gui.py --root "D:\别处解包的MODELS"        # 换模型根目录
```

实现说明：`tools\softrender.py` 是基于 numpy 的软光栅渲染核心（正交投影、重心坐标填充、z-buffer、逐顶点光照、最近邻贴图采样），`Scene.merge()` 负责把多个部件合成一个场景。拖动时自动降到约 400px 渲染保证跟手，停手 140ms 后补全分辨率。实测帧时间：

| 场景面数 | 拖动中 | 静止全分辨率 |
|---|---|---|
| 256 面（单个头部） | 约 26 ms（39 fps） | 约 60 ms |
| 1441 面（单套衣服） | 约 68 ms（15 fps） | 约 90 ms |
| 3288 面（三部件装配） | 约 175 ms（6 fps） | 约 260 ms |

---

## 1. 已生成的结果（可直接查看）

| 目录 | 内容 | 数量 |
|---|---|---|
| `OUT\TEXTURES\` | `.tga.tx` 转换出的 PNG 贴图 | 518 个 |
| `OUT\MODELS\` | `.gm2` 转换出的 OBJ + MTL | 434 个模型 |
| `OUT\MODELS\_assembly\` | 装配后的完整角色 OBJ + MTL | 138 个角色 |
| `OUT\CHARACTERS\` | 装配角色预览图 + `index.html` 索引页 | 136 张 |
| `OUT\PREVIEW\` | 每个单件的离线渲染预览图 | 434 张 |
| `OUT\PREVIEW\index.html` | 单件预览索引页，双击用浏览器打开 | — |

查看顺序建议：

1. 双击 `OUT\CHARACTERS\index.html` 先看装配好的完整角色，挑中满意的再进 Blender。
2. 双击 `OUT\PREVIEW\index.html` 查看全部单件（发型、头、衣服各自的原始模型）。
3. 用 `python tools\viewer_gui.py` 边转边看，或在装配页试各种组合。
4. 需要编辑或导出时，把 `OUT\MODELS\_assembly` 或 `OUT\MODELS` 里的 OBJ 导入 Blender / 3ds Max。

---

## 2. 环境要求

- Python 3.8 或以上。
- 转换脚本只用标准库；交互查看器另需 numpy（`pip install numpy`）与 tkinter（Windows 版 Python 自带）。
- 全部脚本位于 `tools\`，命令在 PowerShell 中执行，工作目录为项目根目录。

---

## 3. 用法

### 3.1 转换贴图

```powershell
python tools\tx2png.py RESOURCE\TEXTURES -o OUT\TEXTURES
```

输出格式可选 `--fmt png|tga|dds`，默认 PNG。脚本对每个文件打印尺寸、D3D 格式和 mip 级数。

### 3.2 转换模型

```powershell
python tools\gm2_to_obj.py RESOURCE\MODELS -o OUT\MODELS --tex OUT\TEXTURES
```

- `--tex` 指定贴图 PNG 目录，用于在 MTL 中写入 `map_Kd` 相对路径。
- `--bones` 额外输出 `<模型名>.bones.json`，包含挂点矩阵和物体信息。
- `--no-flip-v` 关闭 V 翻转。默认执行 `v' = 1 - v`，原因见 5.3。

### 3.3 生成预览图

```powershell
# 单个模型
python tools\render_preview.py RESOURCE\MODELS\human\39102001.gm2 -o OUT\PREVIEW\head.png --size 512 --yaw 35 --pitch 15

# 全部模型 + index.html
python tools\render_all.py RESOURCE\MODELS -o OUT\PREVIEW --size 384
```

`render_preview.py` 是纯标准库软光栅，用于确认几何与贴图是否解析正确，不代替正式渲染。交互查看用第 0 节的 `viewer_gui.py`。

### 3.4 装配角色

见第 0.2 节的 `assemble.py` 用法。批量把全部角色装配、导出并生成索引页：

```powershell
python tools\assemble.py --all --obj OUT\MODELS\_assembly --preview-dir OUT\CHARACTERS --gallery OUT\CHARACTERS\index.html --size 460
```

### 3.5 校验

```powershell
python tools\gm2.py RESOURCE\MODELS        # 解析全部 .gm2, 报告每个文件的顶点/三角数、缓冲布局、异常
python tools\check_obj.py OUT\MODELS OUT\TEXTURES   # 校验 OBJ 索引范围与贴图引用是否缺失
python tools\check_obj.py OUT\MODELS\_assembly OUT\TEXTURES   # 校验装配导出的 OBJ
```

### 3.6 一步跑完全流程

```powershell
powershell -ExecutionPolicy Bypass -File convert_all.ps1
```

该脚本依次执行 3.1 至 3.5 的五步。已生成过的预览图可用 `render_all.py --skip-existing` 跳过重渲染；加 `-SkipCharacters` 可跳过装配步骤。

---

## 4. 格式说明

### 4.1 贴图 `.tga.tx`

文件 = 24 字节文件头 + 像素数据（+ mip 链）。全部字段为小端。

| 偏移 | 类型 | 含义 |
|---|---|---|
| 0 | uint32 | 版本，样本中恒为 0 |
| 4 | uint32 | 宽度（像素） |
| 8 | uint32 | 高度（像素） |
| 12 | uint32 | 标志位：bit3（值 8）置位表示带 mip 链；值 1 表示只有主图 |
| 16 | uint32 | D3DFORMAT 常量，决定像素格式 |
| 20 | uint32 | 主图字节数 |
| 24 | — | 主图像素数据，随后依次为各级 mip |

D3DFORMAT 取值（本例数据中出现过的）：

| 值 | 格式 | 每像素字节 | 内存通道顺序 |
|---|---|---|---|
| 21 | `D3DFMT_A8R8G8B8` | 4 | B,G,R,A |
| 22 | `D3DFMT_X8R8G8B8` | 4 | B,G,R,A（A 无效） |
| 23 | `D3DFMT_R5G6B5` | 2 | 5:6:5，无 alpha |
| 25 | `D3DFMT_A1R5G5B5` | 2 | 1 位 alpha + 5:5:5 |
| 26 | `D3DFMT_A4R4G4B4` | 2 | 4:4:4:4 |
| 0x31545844 | `DXT1` | 0.5 | BC1 块压缩 |
| 0x33545844 | `DXT3` | 1 | BC2 块压缩（显式 4 位 alpha） |

像素行序为**自上而下**（第 0 行是图像顶部），与 D3D 纹理内存一致。转换脚本按此顺序写出 PNG，无需翻转。

两个已知的不规则之处，脚本已处理：

- 部分文件在 D3DFORMAT 字段写 `DXT1`，但主图字节数等于 `宽×高×1`，即实际按 DXT3 的每块 16 字节存储。脚本用主图字节数判定每块是 8 还是 16 字节。
- `D3DFMT_A4R4G4B4` 的部分文件，其 mip 链在小于 16×16 的级别上被截断。脚本只保证主图正确，其余级别按文件实际长度解析。

### 4.2 模型 `.gm2`

文件由固定顺序的若干段组成，段大小由文件头计数推出。全部字段为小端。

文件头（72 字节）：

| 偏移 | 类型 | 含义 |
|---|---|---|
| 0 | char[4] | 版本字符串，样本中恒为 `"60.1"` |
| 4 | int32 | 标志位，样本中恒为 0 |
| 8 | int32 | 名字区字节数 |
| 12 | int32 | 名字个数 |
| 16 | int32 | 贴图个数 |
| 20 | int32 | 材质个数 |
| 24 | int32 | 灯光个数（本批样本均为 0，脚本对非 0 值报错退出） |
| 28 | int32 | 挂点个数 |
| 32 | int32 | 物体个数 |
| 36 | int32 | 三角面总数 |
| 40 | int32 | 顶点缓冲个数 |
| 44 | float[3] | 包围盒尺寸 |
| 56 | float[3] | 包围盒中心 |
| 68 | float | 包围球半径 |

段顺序与大小：

| 段 | 大小 | 说明 |
|---|---|---|
| NAMES | `名字区字节数` | 以 `\0` 分隔的字符串表，含骨骼名、贴图名、模型名 |
| NAMEREFS | `名字个数 × 4` | 按顺序重复列出的名字偏移 |
| TEXTURES | `贴图个数 × 4` | 每项是字符串表偏移，如 `"39101001.tga"` |
| MATERIALS | `材质个数 × 56` | 名称、漫反射/高光/光泽、`texture_type[4]`、`texture[4]` 索引 |
| LABELS | `挂点个数 × 108` | 挂点名 + 4×4 矩阵 + `bones[4]` + `weight[4]` |
| OBJECTS | `物体个数 × 108` | 物体名、包围盒、顶点缓冲号、三角范围、顶点范围、材质号 |
| TRIANGLES | `三角面数 × 6` | 每面 3 个 uint16 顶点下标 |
| VRTBUFFS | `顶点缓冲个数 × 8` | 每项 `{int32 type, int32 size}` |
| VERTICES | 各缓冲 `size` 之和 | 按缓冲顺序紧接排列 |

顶点记录由 `pos(3f)` + 蒙皮块 + `normal(3f)` + `color(4B)` + `uv(2f)`（可能再跟第二组 UV）组成。这批文件共出现 6 种步长：36、44、48、52、56、60 字节，对应蒙皮块 0/8/12/16 字节与 1 或 2 组 UV 的不同组合。

解析时，脚本先用物体记录里的 `nvertices` 反推步长（`size / nvertices`），再用"法线是否接近单位向量""UV 是否落在 [0,1]"给候选布局打分，选出唯一自洽的布局。

验证结果：434 个 `.gm2` 全部解析成功；每个物体的 `nvertices` 与其顶点缓冲的顶点数一致；三角面下标全部落在范围内；文件末字节与各段长度之和完全吻合。

三角面的顶点下标相对**所属顶点缓冲**的起点，物体的 `svertex` 在样本中恒为 0。

---

## 5. 打开方式

### 5.1 只看贴图

`OUT\TEXTURES\*.png` 可用任意看图软件打开。原文件不能直接打开，因为像素数据是未压缩的裸 RGBA/BC 数据，不是 TGA 编码。

若要在没有脚本的环境里应急查看 `D3DFMT_A8R8G8B8` 的 `.tga.tx`：删除前 24 字节，在文件开头拼接 18 字节 TGA 头（`00 00 02 00 00 00 00 00 <宽:2> <高:2> 20 08`，小端），存为 `.tga`。得到的是上下颠倒的图，因为 TGA 默认自下而上。

### 5.2 模型进 Blender

1. 打开 Blender 4.x。
2. 菜单 `File → Import → Wavefront (.obj)`，选择 `OUT\MODELS\39102001.obj`。
3. 导入面板中保持默认的 `Y up`、`-Z forward`。
4. MTL 中的 `map_Kd` 写的是 `../TEXTURES/xxx.png`。只要保持 `OUT\MODELS` 与 `OUT\TEXTURES` 的相对位置不变，贴图会自动加载。

其他可用的查看器：Windows 自带「3D 查看器」可直接打开 OBJ（无贴图），MeshLab、Wings3D、3ds Max、Maya 亦可导入 OBJ。

### 5.3 关于 V 坐标

引擎的 UV 原点在左上，OBJ 的 UV 原点在左下。`gm2_to_obj.py` 默认写出 `v' = 1 - v`，因此导入 Blender 后贴图位置正确。若某个软件导入后贴图上下颠倒，改用 `--no-flip-v` 重新导出。

### 5.4 关于骨骼、装配与动画

- 本批 `.gm2` 是装配在共用骨架上的部件（头发、头、身体三大槽），文件内只保存绑定姿态的顶点。同一类的部件顶点都在同一骨架空间里，因此按「类 + 编号」取三个槽直接叠加即为正确装配（见第 0.1 节）。
- 装配结果是静态几何，没有骨架。若要在 Blender 里做动作，需要自己建骨架并绑定；顶点记录里的 `weight` / `boneid` 与 `LABELS` 的挂点矩阵可作参考（`gm2_to_obj.py --bones` 会导出）。
- 动画数据不在 `.gm2` 内，而在 `resource\animation.pcg` 中，属于另一套格式，本次未处理。
- 不同「类」的部件不要混装：类 1 与类 3 的骨架尺寸不同（头顶分别约 1.82 / 1.96），混装会悬空或穿插。

### 5.5 交互查看器的能力边界

- 只做"看"：不支持编辑、骨骼动画。
- 装配页支持逐槽自由替换与跨类混搭，但混装不同「类」会因骨架尺寸不同而悬空；命令行 `--parts` 也可手工指定任意部件列表。
- 正交投影，没有透视和阴影；光照是固定的单方向 Lambert + 环境项，用于看清贴图而不是还原引擎效果。
- 渲染分辨率随窗口变化，窗口越大帧时间越长。

---

## 6. 已知限制

1. 未导出骨骼与蒙皮权重到 3D 软件可用的格式（OBJ 无此能力）。需要时可从 `tools\gm2.py` 的 `buffers[i]['verts']` 取 `boneid` 与 `weight`。
2. 有 1 个材质引用的贴图名带多余空格（`39503014 .tga`），导出时已自动去掉空格，PNG 引用齐全。
3. 156 个「类 + 编号」组合中只有 136 个三部件齐全；缺部件的组合仍可装配现有部件，但角色不完整。
4. 灯光段（`LIGHTS`）在本批样本中全部为空，脚本未实现该段解析；遇到灯光数非 0 的文件会直接报错退出，不会输出错误几何。
5. 预览图与查看器都是软光栅的近似结果，用于确认解析正确，光照与引擎实际效果不同。

---

## 7. 文件清单

```
<项目根目录>
├─ RESOURCE\                     原始解包结果（只读，不要改动）
│  ├─ MODELS\human\*.gm2         434 个模型
│  └─ TEXTURES\human\*.tga.tx    518 个贴图
├─ OUT\
│  ├─ TEXTURES\*.png             转换后的贴图
│  ├─ MODELS\*.obj / *.mtl       单件模型
│  ├─ MODELS\_assembly\*.obj     装配后的完整角色
│  ├─ CHARACTERS\*.png + index.html  装配角色预览与索引页
│  ├─ PREVIEW\*.png + index.html 单件预览图与索引页
│  ├─ viewer_screenshot.png      交互查看器截图（单件）
│  └─ viewer_assembly.png        交互查看器截图（装配）
├─ tools\
│  ├─ viewer_gui.py              交互式 3D 查看器（tkinter + numpy，含装配页）
│  ├─ softrender.py              软光栅渲染核心 + Scene.merge 装配
│  ├─ assemble.py                部件装配 / 批量装配 / 生成角色索引页
│  ├─ objwrite.py                Scene（含装配体）→ OBJ + MTL
│  ├─ tx2png.py                  .tga.tx → PNG/TGA/DDS
│  ├─ gm2.py                     .gm2 解析库（可单独运行做全量校验）
│  ├─ gm2_to_obj.py              .gm2 → OBJ + MTL（单件）
│  ├─ render_preview.py          单个模型软光栅预览（纯标准库版）
│  ├─ render_all.py              批量预览 + 生成 index.html
│  └─ check_obj.py               OBJ/MTL 自洽性与贴图引用检查
├─ convert_all.ps1               一键跑完转换全流程
└─ README.md                     本文件
```