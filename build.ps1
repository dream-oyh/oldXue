# 薛氏语音助手 — 一键打包脚本
# 用法: powershell -File build.ps1

$ErrorActionPreference = "Stop"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  薛氏语音助手 — 打包构建" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

# 1. 杀旧进程
Write-Host "[1/4] 停止旧进程..." -ForegroundColor Yellow
Get-Process -Name "*语音*","*python*" -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep 1

# 2. 清理
Write-Host "[2/4] 清理旧构建..." -ForegroundColor Yellow
if (Test-Path build) { Remove-Item -Recurse -Force build }
if (Test-Path dist)  { Remove-Item -Recurse -Force dist }

# 3. 确保 onnxruntime 是 pip 版（非 conda）
Write-Host "[3/4] 检查 onnxruntime..." -ForegroundColor Yellow
pip install --force-reinstall -q onnxruntime 2>$null

# 4. 打包
Write-Host "[4/4] PyInstaller 打包..." -ForegroundColor Yellow
pyinstaller voice-typing.spec --noconfirm

# 5. 结果
$exe = Get-Item "dist\薛氏语音助手.exe" -ErrorAction SilentlyContinue
if ($exe) {
    $size = [math]::Round($exe.Length / 1MB, 1)
    Write-Host ""
    Write-Host "========================================" -ForegroundColor Green
    Write-Host "  打包成功！" -ForegroundColor Green
    Write-Host "  输出: $($exe.FullName)" -ForegroundColor Green
    Write-Host "  大小: ${size}MB" -ForegroundColor Green
    Write-Host "========================================" -ForegroundColor Green
} else {
    Write-Host "打包失败！" -ForegroundColor Red
    exit 1
}
