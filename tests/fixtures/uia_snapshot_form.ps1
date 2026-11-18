# Isolated Windows Forms snapshot fixture; no input simulation or owner windows.
param([ValidateSet(50,500,1000)][int]$Controls=50)
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
    $panel.Controls.Add($item)
}
$panel.ResumeLayout($false)
$form.Controls.Add($panel)
$form.Add_Shown({
    [Console]::WriteLine((@{event='ready';pid=$PID;hwnd=$form.Handle.ToInt64();controls=$Controls}|ConvertTo-Json -Compress))
    [Console]::Out.Flush()
})
$timer=[Windows.Forms.Timer]::new()
$timer.Interval=900000
$timer.Add_Tick({$form.Close()})
$timer.Start()
try{[Windows.Forms.Application]::Run($form)}finally{$timer.Dispose();$form.Dispose()}
