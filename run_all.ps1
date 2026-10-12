# 一键：跑管线并启动本地服务
# 用法：
#   .\run_all.ps1            # 联网抓数 + 生成图表 + 起服务
#   .\run_all.ps1 -NoFetch   # 用本地数据重算并起服务
param([switch]$NoFetch)
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
$ErrorActionPreference = "Stop"

if ($NoFetch) {
    python src\pipeline.py --no-fetch
} else {
    python src\pipeline.py --figs
}

Write-Host ""
Write-Host "服务地址: http://127.0.0.1:8000  (Ctrl+C 停止)"
python src\serve.py
