# Test-owned WinForms form for native semantic UIA selection.
# It has no connection to a user's desktop, browser, clipboard, or owner grant.
param([Parameter(Mandatory=$true)][string]$SignalPath,[switch]$Ambiguous)
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$form=[Windows.Forms.Form]::new()
$form.Text='UDB semantic fixture '+[Guid]::NewGuid().ToString('N')
$form.Width=520
$form.Height=260
$form.StartPosition='Manual'
$form.Location=[Drawing.Point]::new(40,40)
$form.ShowInTaskbar=$false
$form.FormBorderStyle=[Windows.Forms.FormBorderStyle]::FixedToolWindow
$container=[Windows.Forms.Panel]::new()
$container.Name='UDB_RESULTS_CONTAINER'
$container.AccessibleName='UDB_RESULTS_CONTAINER'
$container.Dock=[Windows.Forms.DockStyle]::Fill
$alpha=[Windows.Forms.Button]::new()
$alpha.Name='UDB_RESULT_ALPHA'
$alpha.AccessibleName='UDB result item alpha'
$alpha.Text='UDB result item alpha'
$alpha.Location=[Drawing.Point]::new(12,18)
$alpha.Size=[Drawing.Size]::new(440,42)
$beta=[Windows.Forms.Button]::new()
$beta.Name='UDB_RESULT_BETA'
$beta.AccessibleName='UDB result item beta'
$beta.Text='UDB result item beta'
if($Ambiguous){$beta.Location=[Drawing.Point]::new(12,18)}else{$beta.Location=[Drawing.Point]::new(12,78)}
$beta.Size=[Drawing.Size]::new(440,42)
$script:clickCount=0
$alpha.Add_Click({
    $script:clickCount++
    [IO.File]::WriteAllText($SignalPath,(@{count=$script:clickCount;target='alpha'}|ConvertTo-Json -Compress))
})
$beta.Add_Click({
    $script:clickCount++
    [IO.File]::WriteAllText($SignalPath,(@{count=$script:clickCount;target='beta'}|ConvertTo-Json -Compress))
})
$container.Controls.Add($alpha)
$container.Controls.Add($beta)
$form.Controls.Add($container)
$form.Add_Shown({
    [Console]::WriteLine((@{event='ready';pid=$PID;hwnd=$form.Handle.ToInt64()}|ConvertTo-Json -Compress))
    [Console]::Out.Flush()
})
$timer=[Windows.Forms.Timer]::new()
$timer.Interval=900000
$timer.Add_Tick({$form.Close()})
$timer.Start()
try{[Windows.Forms.Application]::Run($form)}finally{$timer.Dispose();$form.Dispose()}
