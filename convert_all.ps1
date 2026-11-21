# AOA 资源一键转换: .gm2 -> OBJ, .tga.tx -> PNG, 装配角色, 生成预览图
# 用法: powershell -ExecutionPolicy Bypass -File convert_all.ps1
#       加 -SkipCharacters 可跳过第 3 步(装配全部角色, 约 2 分钟)
param([switch]$SkipCharacters)

$ErrorActionPreference = 'Stop'
Set-Location -Path $PSScriptRoot

Write-Host '==> 1/5 转换贴图 .tga.tx -> PNG'
python tools\tx2png.py RESOURCE\TEXTURES -o OUT\TEXTURES

Write-Host '==> 2/5 转换模型 .gm2 -> OBJ+MTL'
python tools\gm2_to_obj.py RESOURCE\MODELS -o OUT\MODELS --tex OUT\TEXTURES --bones

if (-not $SkipCharacters) {
    Write-Host '==> 3/5 装配全部角色(发+头+身)'
    python tools\assemble.py --all --obj OUT\MODELS\_assembly --preview-dir OUT\CHARACTERS --gallery OUT\CHARACTERS\index.html --size 460
} else {
    Write-Host '==> 3/5 跳过角色装配'
}

Write-Host '==> 4/5 生成单件预览图与 index.html'
python tools\render_all.py RESOURCE\MODELS -o OUT\PREVIEW --size 384 --skip-existing

Write-Host '==> 5/5 校验输出'
python tools\check_obj.py OUT\MODELS OUT\TEXTURES
python tools\check_obj.py OUT\MODELS\_assembly OUT\TEXTURES

Write-Host '完成。角色索引: OUT\CHARACTERS\index.html   单件索引: OUT\PREVIEW\index.html'
Write-Host '交互查看: python tools\viewer_gui.py'
