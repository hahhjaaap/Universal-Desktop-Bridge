# Register a UDB portable EXE for Windows Start/Search, for the current user only.
# This script never starts UDB or grants AI/Windows access.
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Exe,
    [string]$DataHome = (Join-Path $env:LOCALAPPDATA 'UniversalDesktopBridge'),
    [string]$ShortcutDir = (Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs')
)
$ErrorActionPreference = 'Stop'
if ($env:OS -ne 'Windows_NT') { throw 'Windows is required.' }
$target = [IO.Path]::GetFullPath($Exe)
if ([IO.Path]::GetFileName($target) -ine 'udb.exe' -or !(Test-Path -LiteralPath $target -PathType Leaf)) {
    throw 'Select the existing standalone udb.exe.'
}
# A shortcut target must be a local, ordinary, non-redirected file.
$cursor = $target
while ($cursor) {
    if (Test-Path -LiteralPath $cursor) {
        $item = Get-Item -LiteralPath $cursor -Force
        if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
            throw 'Redirected/symlinked paths are not accepted.'
        }
    }
    $parent = [IO.Path]::GetDirectoryName($cursor)
    if (!$parent -or $parent -eq $cursor) { break }
    $cursor = $parent
}
if ([IO.Path]::IsPathRooted($ShortcutDir) -eq $false) {
    throw 'ShortcutDir must be absolute.'
}
[IO.Directory]::CreateDirectory([IO.Path]::GetFullPath($ShortcutDir)) | Out-Null
$link = Join-Path $ShortcutDir 'UDB - Universal Desktop Bridge.lnk'
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($link)
if ((Test-Path -LiteralPath $link) -and $shortcut.Description -ne 'UDB-managed Start Menu shortcut') {
    throw 'The existing shortcut is not UDB-managed; nothing was overwritten.'
}
$shortcut.TargetPath = $target
$shortcut.Arguments = '--home "' + ([IO.Path]::GetFullPath($DataHome)) + '" gui'
$shortcut.WorkingDirectory = [IO.Path]::GetDirectoryName($target)
$shortcut.IconLocation = $target + ',0'
$shortcut.Description = 'UDB-managed Start Menu shortcut'
$shortcut.Save()
$verify = $shell.CreateShortcut($link)
if ($verify.TargetPath -ine $target -or $verify.Description -ne 'UDB-managed Start Menu shortcut') {
    throw 'The created shortcut did not verify.'
}
Write-Output ('Start Menu shortcut ready: ' + $link)

$liveLink = Join-Path $ShortcutDir 'UDB Live.lnk'
$live = $shell.CreateShortcut($liveLink)
$liveDescription = 'UDB-managed Cloudflare Live shortcut'
if ((Test-Path -LiteralPath $liveLink) -and $live.Description -ne $liveDescription) {
    throw 'The existing UDB Live shortcut is not UDB-managed; preserved it.'
}
$live.TargetPath = $target
$live.Arguments = '--home "' + ([IO.Path]::GetFullPath($DataHome)) + '" live --gui'
$live.WorkingDirectory = [IO.Path]::GetDirectoryName($target)
$live.IconLocation = $target + ',0'
$live.Hotkey = 'CTRL+ALT+U'
$live.Description = $liveDescription
$live.Save()
$liveCheck = $shell.CreateShortcut($liveLink)
$verifiedHotkey = ($liveCheck.Hotkey.ToUpperInvariant().Split('+') | Sort-Object) -join '+'
if ($liveCheck.TargetPath -ine $target -or $verifiedHotkey -ne 'ALT+CTRL+U') {
    throw 'UDB Live shortcut verification failed.'
}
Write-Output ('UDB Live shortcut ready (Ctrl+Alt+U): ' + $liveLink)
