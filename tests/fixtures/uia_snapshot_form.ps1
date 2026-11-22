# Isolated Windows Forms snapshot fixture; no input simulation or owner windows.
param([ValidateSet(50,500,1000)][int]$Controls=50,[string]$DynamicSignalPath='',[string]$DynamicTriggerPath='')
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$form=[Windows.Forms.Form]::new()
$form.Text='UDB UIA snapshot fixture '+[Guid]::NewGuid().ToString('N')
$form.Width=580
$form.Height=440
$form.StartPosition='Manual'
$form.Location=[Drawing.Point]::new(40,40)
$form.ShowInTaskbar=$false
$form.FormBorderStyle=[Windows.Forms.FormBorderStyle]::FixedToolWindow
$panel=[Windows.Forms.Panel]::new()
$panel.Dock=[Windows.Forms.DockStyle]::Fill
$panel.AutoScroll=$true
$panel.SuspendLayout()
for($i=0;$i -lt $Controls;$i++){
    $item=if($i%4 -eq 0){[Windows.Forms.Label]::new()}
        elseif($i%4 -eq 1){[Windows.Forms.Button]::new()}
        elseif($i%4 -eq 2){[Windows.Forms.CheckBox]::new()}
        else{[Windows.Forms.TextBox]::new()}
    $item.Name=('Fixture'+$i.ToString('D4'))
    $item.AccessibleName=('Fixture item '+$i.ToString('D4'))
    $item.Location=[Drawing.Point]::new(8,(($i+1)*26))
    $item.Size=[Drawing.Size]::new(480,24)
    if($i%4 -eq 3){
        $item.Text='fixture data'
        if($i -eq 3){
            $item.Name='FixturePassword'
            $item.UseSystemPasswordChar=$true
            $item.Text='UDB_PRIVATE_CANARY_MUST_NOT_APPEAR'
        }
    }else{$item.Text=('Fixture item '+$i.ToString('D4'))}
    if($i -eq 0){
        $item.Name='FixtureDynamicTarget'
        $item.AccessibleName='UDB_DYNAMIC_BEFORE'
        $item.Text='UDB_DYNAMIC_BEFORE'
    }
    $panel.Controls.Add($item)
}
$panel.ResumeLayout($false)
$form.Controls.Add($panel)
$dynamicTimer=$null
if($DynamicSignalPath){
    $dynamicTimer=[Windows.Forms.Timer]::new()
    if(-not $DynamicTriggerPath){throw 'Dynamic UIA fixture requires an explicit trigger path'}
    $dynamicTimer.Interval=100
    $dynamicTimer.Add_Tick({
        if(-not (Test-Path -LiteralPath $DynamicTriggerPath)){return}
        $dynamicTimer.Stop()
        $target=$panel.Controls.Find('FixtureDynamicTarget',$true) | Select-Object -First 1
        if($null -eq $target){throw 'Dynamic UIA fixture target disappeared unexpectedly'}
        $target.AccessibleName='UDB_DYNAMIC_AFTER'
        $target.Text='UDB_DYNAMIC_AFTER'
        [IO.File]::WriteAllText($DynamicSignalPath,'{"event":"changed"}')
    })
}
$form.Add_Shown({
    [Console]::WriteLine((@{event='ready';pid=$PID;hwnd=$form.Handle.ToInt64();controls=$Controls}|ConvertTo-Json -Compress))
    [Console]::Out.Flush()
    if($dynamicTimer){$dynamicTimer.Start()}
})
$timer=[Windows.Forms.Timer]::new()
$timer.Interval=900000
$timer.Add_Tick({$form.Close()})
$timer.Start()
try{[Windows.Forms.Application]::Run($form)}finally{if($dynamicTimer){$dynamicTimer.Dispose()};$timer.Dispose();$form.Dispose()}
