param([Parameter(Mandatory=$true)][string]$ReadyPath)
$ErrorActionPreference='Stop'
trap {
 [IO.File]::WriteAllText($ReadyPath+'.error',[string]$_.Exception.Message)
 exit 1
}
Add-Type -AssemblyName PresentationFramework
[xml]$xaml=@'
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation" xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
 Title="UDB synthetic tab strip" Width="600" Height="400" Left="60" Top="60" ShowInTaskbar="False">
 <TabControl SelectedIndex="1">
  <TabItem Header="Ordinary" AutomationProperties.AutomationId="Ordinary"><TextBlock Text="Synthetic ordinary tab"/></TabItem>
  <TabItem Header="AI" AutomationProperties.AutomationId="AI"><TextBlock Text="Synthetic registered tab"/></TabItem>
 </TabControl>
</Window>
'@
$window=[Windows.Markup.XamlReader]::Load([Xml.XmlNodeReader]::new($xaml))
# Show() synchronously creates the native HWND. Publish it immediately,
# rather than waiting for Loaded/ContentRendered: CI desktop composition may
# delay those WPF events indefinitely even when a window handle already exists.
$window.Add_Closed({[Windows.Threading.Dispatcher]::CurrentDispatcher.BeginInvokeShutdown([Windows.Threading.DispatcherPriority]::Normal)})
$window.Show()
$handle=[Windows.Interop.WindowInteropHelper]::new($window).Handle.ToInt64()
if($handle -le 0){throw 'Synthetic WPF window has no native handle'}
[IO.File]::WriteAllText($ReadyPath+'.tmp',(@{hwnd=$handle;pid=$PID}|ConvertTo-Json -Compress))
[IO.File]::Move($ReadyPath+'.tmp',$ReadyPath)
[Windows.Threading.Dispatcher]::Run()
