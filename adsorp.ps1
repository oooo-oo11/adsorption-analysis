# =====================================================================
#  吸附数据分析 - PowerShell 入口
#
#  用法：
#    .\adsorp.ps1                      自动找数据并跑完整分析
#    .\adsorp.ps1 run --template ...   指定模板
#    .\adsorp.ps1 check --template ... 只校验，不拟合
#
#  若提示「禁止运行脚本」，改用：
#    powershell -ExecutionPolicy Bypass -File .\adsorp.ps1
#  或只对当前用户放开：
#    Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
# =====================================================================
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $root
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'

# 控制台按 UTF-8 解码，否则 Python 输出的中文在 GBK 代码页下会变成乱码。
# （bat 用 chcp 65001 达到同样效果；PowerShell 没有 chcp，需改 [Console] 的编码）
try {
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
    $OutputEncoding = [System.Text.Encoding]::UTF8
} catch {
    # 某些宿主（如非交互式管道）不允许改控制台编码，忽略即可，不影响计算
}

function Test-PythonDeps {
    param([string]$Exe, [string[]]$Prefix = @())
    try {
        & $Exe @Prefix -c "import numpy, pandas, scipy, matplotlib, openpyxl" 2>$null | Out-Null
        return ($LASTEXITCODE -eq 0)
    } catch {
        return $false
    }
}

$py = $null
$pyPrefix = @()

if ($env:ADSORP_PYTHON -and (Test-Path -LiteralPath $env:ADSORP_PYTHON)) {
    if (Test-PythonDeps $env:ADSORP_PYTHON) { $py = $env:ADSORP_PYTHON }
}
if (-not $py -and (Test-Path -LiteralPath '.\python\python.exe')) {
    if (Test-PythonDeps '.\python\python.exe') { $py = '.\python\python.exe' }
}
if (-not $py -and (Test-Path -LiteralPath '.\.venv\Scripts\python.exe')) {
    if (Test-PythonDeps '.\.venv\Scripts\python.exe') { $py = '.\.venv\Scripts\python.exe' }
}
if (-not $py -and (Get-Command py -ErrorAction SilentlyContinue)) {
    if (Test-PythonDeps 'py' @('-3')) { $py = 'py'; $pyPrefix = @('-3') }
}
if (-not $py -and (Get-Command python -ErrorAction SilentlyContinue)) {
    if (Test-PythonDeps 'python') { $py = 'python' }
}

if (-not $py) {
    Write-Host '[错误] 没有找到可用的 Python（需要 numpy / pandas / scipy / matplotlib / openpyxl）。' -ForegroundColor Red
    Write-Host '  本交付包自带 python\ ，若该目录缺失，可以：'
    Write-Host '  1) 安装 Python 3.10 或更高版本，安装时勾选 Add python.exe to PATH'
    Write-Host '  2) python -m venv .venv'
    Write-Host '     .\.venv\Scripts\python -m pip install -r requirements.txt'
    Write-Host '  3) 设置环境变量 ADSORP_PYTHON，指向 python.exe 的完整路径'
    exit 1
}

& $py @pyPrefix -m adsorp.cli @args
$code = $LASTEXITCODE

# 无参数（相当于双击）成功后打开报告
if ($code -eq 0 -and $args.Count -eq 0) {
    $report = Join-Path $root 'output\报告.html'
    if (Test-Path -LiteralPath $report) { Start-Process -FilePath $report }
}

exit $code
