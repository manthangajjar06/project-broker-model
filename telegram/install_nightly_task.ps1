# Registers a Windows Scheduled Task that runs the NIFTY 100 scan every day at 9:00 PM.
# Run once from PowerShell in the project root:
#
#   powershell -ExecutionPolicy Bypass -File telegram\install_nightly_task.ps1
#
# The task name is ProjectBrokerModelNightlyScan.

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$python = (Get-Command python -ErrorAction Stop).Source
$nightlyScript = Join-Path $PSScriptRoot "nightly.py"
$taskName = "ProjectBrokerModelNightlyScan"

if (-not (Test-Path $nightlyScript)) {
    throw "Missing nightly script: $nightlyScript"
}

$argument = "`"$nightlyScript`""
$action = New-ScheduledTaskAction -Execute $python -Argument $argument -WorkingDirectory $projectRoot
$trigger = New-ScheduledTaskTrigger -Daily -At 21:00
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Force | Out-Null

Write-Host "Scheduled task '$taskName' is installed."
Write-Host "It runs daily at 9:00 PM local time:"
Write-Host "  $python $nightlyScript"
Write-Host "Working directory: $projectRoot"
Write-Host ""
Write-Host "Check it with:  schtasks /Query /TN $taskName /V /FO LIST"
Write-Host "Remove it with: schtasks /Delete /TN $taskName /F"
