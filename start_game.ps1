# 一鍵啟動（W6 D3）：啟動測試伺服器 -> 開網頁 -> 自動打完一局 -> 關閉伺服器。
# 用法（專案根目錄，PowerShell）：
#     .\start_game.ps1
#     .\start_game.ps1 -Seed 5 -Delay 3
#     .\start_game.ps1 -NoVerify          # 不做畫面驗證（除錯用）
param(
    [int]$Seed = 1,
    [int]$Delay = 3,
    [int]$Port = 8000,
    [switch]$NoVerify
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (Test-Path ".venv\Scripts\Activate.ps1") { . .venv\Scripts\Activate.ps1 }

$base = "http://127.0.0.1:$Port"
$server = Start-Process -FilePath python -ArgumentList @("-m", "uvicorn", "test_interface.app:app", "--port", "$Port") -PassThru -WindowStyle Minimized

try {
    $ready = $false
    for ($i = 0; $i -lt 40; $i++) {
        try { Invoke-RestMethod "$base/api/health" | Out-Null; $ready = $true; break } catch { Start-Sleep -Milliseconds 500 }
    }
    if (-not $ready) { throw "測試伺服器沒有在 20 秒內啟動" }

    Start-Process "$base/?scenario=game"
    Write-Host "已開啟 $base/?scenario=game ；等網頁載入..."
    Start-Sleep -Seconds 4

    $runArgs = @("-m", "test_interface.run_full_game", "--url", $base, "--seed", "$Seed", "--delay", "$Delay")
    if ($NoVerify) { $runArgs += "--no-verify" }
    python @runArgs
    $code = $LASTEXITCODE
}
finally {
    if ($server -and -not $server.HasExited) { Stop-Process -Id $server.Id -Force }
}
exit $code