# Rejected-HWND only; never observes or mutates a real Windows UI.
param([ValidateRange(5,100)][int]$Samples=30)
$ErrorActionPreference='Stop'
$helper=Join-Path (Split-Path -Parent $PSScriptRoot) 'src\udb\computer_uia.ps1'
if(-not(Test-Path -LiteralPath $helper -PathType Leaf)){throw 'Missing pinned UIA helper'}
$exe=Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$wire='{"hwnd":0,"pid":-1,"mode":"snapshot"}'
function New-HelperProcess([bool]$persistent) {
    $pinfo=[Diagnostics.ProcessStartInfo]::new()
    $pinfo.FileName=$exe
    $pinfo.Arguments='-NoLogo -NoProfile -NonInteractive -Sta -ExecutionPolicy Bypass -File "'+$helper+'"'
    if($persistent){$pinfo.Arguments+=' -Persistent'}
    $pinfo.UseShellExecute=$false
    $pinfo.RedirectStandardInput=$true
    $pinfo.RedirectStandardOutput=$true
    $pinfo.RedirectStandardError=$true
    $pinfo.CreateNoWindow=$true
    $proc=[Diagnostics.Process]::new()
    $proc.StartInfo=$pinfo
    if(-not $proc.Start()){throw 'PowerShell helper launch refused'}
    return $proc
}
function Assert-Rejected([string]$line) {
    $obj=$line.TrimStart([char]0xFEFF)|ConvertFrom-Json
    if($obj.PSObject.Properties.Name -contains 'sequence'){
        if($obj.sequence -le 0){throw 'Invalid persistent reply sequence'}
        $obj=$obj.result
    }
    if($obj.ok -ne $false){throw 'Unexpected UIA outcome: the impossible window was not refused'}
}
function OneShot {
    $p=New-HelperProcess $false
    try {
        $p.StandardInput.WriteLine($wire)
        $p.StandardInput.Close()
        $response=$p.StandardOutput.ReadToEndAsync()
        if(-not $p.WaitForExit(15000)){throw 'One-shot UIA timeout'}
        $line=$response.GetAwaiter().GetResult()
        Assert-Rejected $line
        if($p.ExitCode -ne 1){throw ('Unexpected one-shot exit: '+$p.ExitCode)}
    } finally {
        if(-not $p.HasExited){$p.Kill()}
        $p.Dispose()
    }
}
function Pct([double[]]$values,[double]$q) {
    $s=@($values|Sort-Object)
    $i=($s.Count-1)*$q
    $lo=[int][Math]::Floor($i)
    $hi=[int][Math]::Ceiling($i)
    return [Math]::Round(($s[$lo]+($s[$hi]-$s[$lo])*($i-$lo)),3)
}
$oneshot=[Collections.Generic.List[double]]::new()
for($i=0;$i -lt $Samples;$i++){
    $timer=[Diagnostics.Stopwatch]::StartNew()
    OneShot
    $oneshot.Add($timer.Elapsed.TotalMilliseconds)
}
$warm=[Collections.Generic.List[double]]::new()
$p=New-HelperProcess $true
try {
    $coldTimer=[Diagnostics.Stopwatch]::StartNew()
    for($i=0;$i -le $Samples;$i++){
        $p.StandardInput.WriteLine($wire)
        $p.StandardInput.Flush()
        $read=$p.StandardOutput.ReadLineAsync()
        if(-not $read.Wait(15000)){throw 'Persistent UIA read timeout'}
        $line=$read.GetAwaiter().GetResult()
        Assert-Rejected $line
        if($i -eq 0){$cold=[Math]::Round($coldTimer.Elapsed.TotalMilliseconds,3);$coldTimer.Restart()}
        else{$warm.Add($coldTimer.Elapsed.TotalMilliseconds);$coldTimer.Restart()}
    }
} finally {
    if(-not $p.HasExited){$p.Kill()}
    $p.Dispose()
}
[pscustomobject]@{
    scope='rejected HWND/PID only; no real UI, input, network or live window'
    samples=$Samples
    one_shot=@{p50_ms=(Pct $oneshot.ToArray() 0.50);p95_ms=(Pct $oneshot.ToArray() 0.95)}
    persistent_first_call_ms=$cold
    persistent_warm=@{p50_ms=(Pct $warm.ToArray() 0.50);p95_ms=(Pct $warm.ToArray() 0.95)}
}|ConvertTo-Json -Depth 6
