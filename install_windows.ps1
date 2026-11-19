param([string]$Source = (Join-Path $PSScriptRoot 'dist\SubLens'))
$ErrorActionPreference = 'Stop'
$Source = (Resolve-Path -LiteralPath $Source).Path
$exeSource = Join-Path $Source 'SubLens.exe'
if (-not (Test-Path -LiteralPath $exeSource)) { throw 'Build the application first: build_windows.ps1' }

$installRoot = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'Programs\SubLens'
$desktop = [Environment]::GetFolderPath('DesktopDirectory')
if ([string]::IsNullOrWhiteSpace($desktop)) {
    $shellFolders = Get-ItemProperty -LiteralPath 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders' -ErrorAction SilentlyContinue
    if ($shellFolders.Desktop) { $desktop = [Environment]::ExpandEnvironmentVariables($shellFolders.Desktop) }
}
if ([string]::IsNullOrWhiteSpace($desktop)) { $desktop = Join-Path $env:USERPROFILE 'Desktop' }
$programs = [Environment]::GetFolderPath('Programs')
foreach ($directory in @($installRoot, $desktop, $programs)) {
    New-Item -ItemType Directory -Path $directory -Force | Out-Null
}
$exeTarget = Join-Path $installRoot 'SubLens.exe'
$running = Get-Process -Name 'SubLens' -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq $exeTarget }
if ($running) {
    # Keep an active editing session intact; the shortcut will open the new build.
    $versionName = (Get-Date -Format 'yyyyMMdd_HHmmss') + '_' + [guid]::NewGuid().ToString('N').Substring(0, 6)
    $installRoot = Join-Path $installRoot ('versions\' + $versionName)
    New-Item -ItemType Directory -Path $installRoot -Force | Out-Null
    $exeTarget = Join-Path $installRoot 'SubLens.exe'
}
foreach ($item in Get-ChildItem -LiteralPath $Source -Force) {
    Copy-Item -LiteralPath $item.FullName -Destination $installRoot -Recurse -Force
}
$shell = New-Object -ComObject WScript.Shell
$shortcuts = @((Join-Path $desktop 'SubLens.lnk'), (Join-Path $programs 'SubLens.lnk'))
$shortcutTemplate = Join-Path $installRoot 'SubLens.lnk'
$shortcut = $shell.CreateShortcut($shortcutTemplate)
$shortcut.TargetPath = $exeTarget
$shortcut.WorkingDirectory = $installRoot
$shortcut.IconLocation = "$exeTarget,0"
$shortcut.Description = 'SubLens - Video subtitle OCR and SRT editor'
$shortcut.Save()
foreach ($shortcutPath in $shortcuts) {
    # WSH can fail to save directly into a redirected Desktop with Unicode in its path.
    Copy-Item -LiteralPath $shortcutTemplate -Destination $shortcutPath -Force
}
[pscustomobject]@{ Application = $exeTarget; DesktopShortcut = $shortcuts[0]; StartMenuShortcut = $shortcuts[1] } | Format-List
