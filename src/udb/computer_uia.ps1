# Fixed current-user UI Automation helper. Caller checks a local owner grant.
# No arbitrary scripts/selectors, password reads, clipboard, elevation or input hooks.
param([switch]$Persistent)
$ErrorActionPreference='Stop'
[Console]::InputEncoding=[Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
function Observe-State([scriptblock]$Check) {
    $timer=[Diagnostics.Stopwatch]::StartNew()
    do {
        if(& $Check){return $true}
        if($timer.ElapsedMilliseconds -ge 500){return $false}
        Start-Sleep -Milliseconds 25
    } while($true)
}
function Test-ChatGPTReplyCandidate([string]$value) {
    # A ChatGPT accessibility tree can expose its persistent footer after
    # the assistant speaker label but before any real generated text.
    # Never report this UI chrome as the first assistant response.
    if([string]::IsNullOrWhiteSpace($value)){return $false}
    $trimmed=$value.Trim()
    if($trimmed -match '^(ChatGPT có thể mắc lỗi|ChatGPT can make mistakes)([.!?:\s]|$)'){
        return $false
    }
    if($trimmed -in @(
        'Hỏi ChatGPT','Ask ChatGPT','Sao chép','Copy',
        'Phản hồi mới nhất','Latest response',
        'Chính sách quyền riêng tư','Privacy Policy',
        'Điều khoản sử dụng','Terms of Use'
    )){return $false}
    return $true
}
function Invoke-UdbUia([string]$raw) {
try {
    if (-not $script:UdbAutomationTypesLoaded) {
        Add-Type -AssemblyName UIAutomationClient
        Add-Type -AssemblyName UIAutomationTypes
        $script:UdbAutomationTypesLoaded = $true
    }
    if($raw.Length -gt 100000){throw 'Request too large'}
    $r=$raw|ConvertFrom-Json
    if($r.mode -notin @('snapshot','set_value','invoke','uia_focus','wait_for','read_text','set_checked','select','expand','collapse','scroll_into_view','ranked_control','poll_chatgpt_reply','chatgpt_prepare','chatgpt_commit')){throw 'Unsupported UIA mode'}
    $root=[Windows.Automation.AutomationElement]::FromHandle([IntPtr][long]$r.hwnd)
    if(!$root -or $root.Current.ProcessId -ne [int]$r.pid){throw 'Observed window changed'}
    # Initialize AutomationElement before registering the standard .NET proxies.
    # Without these, Win32/WinForms controls can appear as generic Panes and
    # fail to expose ValuePattern/InvokePattern in this short-lived client.
    if (-not $script:UdbProvidersRegistered) {
        $providers=[Reflection.Assembly]::Load('UIAutomationClientsideProviders, Version=4.0.0.0, Culture=neutral, PublicKeyToken=31bf3856ad364e35')
        [Windows.Automation.ClientSettings]::RegisterClientSideProviderAssembly($providers.GetName())
        $script:UdbProvidersRegistered=$true
        # The first request must reacquire after registering Win32 proxies.
        # Warm requests already use those proxies, so avoid a redundant
        # cross-process FromHandle/PID read while keeping fresh validation.
        $root=[Windows.Automation.AutomationElement]::FromHandle([IntPtr][long]$r.hwnd)
        if(!$root -or $root.Current.ProcessId -ne [int]$r.pid){throw 'Observed window changed'}
    }
    if($r.mode -in @('chatgpt_prepare','chatgpt_commit')) {
        # Targeted two-pass ChatGPT form automation. Only one exact editor
        # and the fixed Send button; no generic selectors or cookie access.
        if($r.text -isnot [string] -or $r.text.Length -lt 1 -or
            $r.text.Length -gt 5000) {
            throw 'Invalid ChatGPT text'
        }
        $docFilter=[Windows.Automation.PropertyCondition]::new(
            [Windows.Automation.AutomationElement]::ControlTypeProperty,
            [Windows.Automation.ControlType]::Document
        )
        $documents=$root.FindAll([Windows.Automation.TreeScope]::Descendants,$docFilter)
        $chatCount=0
        foreach($doc in $documents) {
            if($doc.Current.Name -ceq 'ChatGPT'){$chatCount++}
        }
        if($chatCount -ne 1){throw 'ChatGPT document not unique'}
        $editFilter=[Windows.Automation.AndCondition]::new(
            [Windows.Automation.PropertyCondition]::new(
                [Windows.Automation.AutomationElement]::ControlTypeProperty,
                [Windows.Automation.ControlType]::Edit
            ),
            [Windows.Automation.PropertyCondition]::new(
                [Windows.Automation.AutomationElement]::NameProperty,'Hỏi ChatGPT'
            )
        )
        $editors=$root.FindAll([Windows.Automation.TreeScope]::Descendants,$editFilter)
        if($editors.Count -ne 1){throw 'ChatGPT editor ambiguous or missing'}
        $editor=$editors[0]
        if(!$editor.Current.IsEnabled -or $editor.Current.IsOffscreen -or
            $editor.Current.IsPassword){throw 'ChatGPT editor unavailable'}
        $textFilter=[Windows.Automation.PropertyCondition]::new(
            [Windows.Automation.AutomationElement]::ControlTypeProperty,
            [Windows.Automation.ControlType]::Text
        )
        $texts=$root.FindAll([Windows.Automation.TreeScope]::Descendants,$textFilter)
        foreach($entry in $texts) {
            if($entry.Current.Name -in @('ChatGPT đã nói:','ChatGPT said:')){
                throw 'Existing conversation; do not submit'
            }
        }
        $pattern=$null
        if($editor.TryGetCurrentPattern([Windows.Automation.TextPattern]::Pattern,[ref]$pattern)){
            $value=[string]$pattern.DocumentRange.GetText(5001)
        } elseif($editor.TryGetCurrentPattern([Windows.Automation.ValuePattern]::Pattern,[ref]$pattern)){
            $value=[string]$pattern.Current.Value
        } else {
            throw 'ChatGPT editor cannot be read'
        }
        if($r.mode -eq 'chatgpt_prepare'){
            $initial=$value.TrimEnd([char]13,[char]10)
            if($initial -cne '' -and $initial -cne 'Hỏi ChatGPT'){
                throw 'Existing draft preserved; no input injected'
            }
            $editor.SetFocus()
            @{ok=$true;prepared=$true;replay_safe=$false}|ConvertTo-Json -Compress
            return
        }
        if($value -cne [string]$r.text){
            throw 'ChatGPT text does not match exact request; no submit'
        }
        $sendFilter=[Windows.Automation.AndCondition]::new(
            [Windows.Automation.PropertyCondition]::new(
                [Windows.Automation.AutomationElement]::ControlTypeProperty,
                [Windows.Automation.ControlType]::Button
            ),
            [Windows.Automation.PropertyCondition]::new(
                [Windows.Automation.AutomationElement]::NameProperty,'Gửi'
            )
        )
        $buttons=$root.FindAll([Windows.Automation.TreeScope]::Descendants,$sendFilter)
        if($buttons.Count -ne 1){throw 'ChatGPT send button ambiguous or missing'}
        $send=$buttons[0]
        if(!$send.Current.IsEnabled -or $send.Current.IsOffscreen -or
            $send.Current.IsPassword){throw 'ChatGPT send button unavailable'}
        $invoke=$send.GetCurrentPattern([Windows.Automation.InvokePattern]::Pattern)
        $invoke.Invoke()
        @{ok=$true;invoked=$true;verified_text=$true;replay_safe=$false} |
            ConvertTo-Json -Compress
        return
    }
    if($r.mode -eq 'poll_chatgpt_reply') {
        # Dedicated read-only post-submit observer. No browser CDP, cross-tab
        # search, credentials, arbitrary selectors, clipboard or user input.
        if([string]::IsNullOrWhiteSpace([string]$r.text) -or
            ([string]$r.text).Length -gt 5000 -or
            [int]$r.wait_ms -lt 500 -or [int]$r.wait_ms -gt 10000 -or
            [int]$r.limit -lt 1 -or [int]$r.limit -gt 5000 -or
            $r.condition -notin @('exists','first_text')) {
            throw 'Invalid ChatGPT reply observation limits'
        }
        $expected=[string]$r.text
        $wait=[int]$r.wait_ms
        $maxText=[int]$r.limit
        $condition=[Windows.Automation.PropertyCondition]::new(
            [Windows.Automation.AutomationElement]::ControlTypeProperty,
            [Windows.Automation.ControlType]::Text
        )
        $timer=[Diagnostics.Stopwatch]::StartNew()
        $response=''
        $bestResponse=''
        $complete=$false
        $firstReplyMs=$null
        do {
            # Re-validate observed window and process before each UIA read.
            if(!$root.Current.IsEnabled -or $root.Current.ProcessId -ne [int]$r.pid) {
                throw 'Observed Chrome window changed during reply'
            }
            $items=$root.FindAll([Windows.Automation.TreeScope]::Descendants,$condition)
            $sent=$false
            $assistant=$false
            $sentCount=0
            $assistantCount=0
            $done=$false
            $response=''
            foreach($node in $items) {
                if($node.Current.IsPassword){continue}
                $value=[string]$node.Current.Name
                if($value -in @('Đã hoàn tất phản hồi','Response complete','Response finished')) {
                    $done=$true
                }
                if($value -ceq $expected) {
                    $sentCount++; $sent=$true; continue
                }
                if($sent -and $value -in @('ChatGPT đã nói:','ChatGPT said:')) {
                    $assistantCount++; $assistant=$true; continue
                }
                if($assistant -and !$response -and (Test-ChatGPTReplyCandidate $value)) {
                    $response=$value
                }
            }
            if($sentCount -gt 1 -or $assistantCount -gt 1) {
                throw 'Ambiguous ChatGPT conversation; do not return a reply'
            }
            if($sent -and $assistant -and $response){
                $bestResponse=$response
                if($null -eq $firstReplyMs){
                    $firstReplyMs=$timer.ElapsedMilliseconds
                }
                if($done){$complete=$true; break}
                if($r.condition -eq 'first_text'){break}
            }
            if($timer.ElapsedMilliseconds -ge $wait){break}
            Start-Sleep -Milliseconds 120
        } while($true)
        # Even after a timeout, preserve the last UI-visible answer fragment.
        # Incomplete text must NEVER be described as a completed answer.
        $truncated=$bestResponse.Length -gt $maxText
        if($truncated) {
            $n=$maxText
            if($n -gt 0 -and [char]::IsHighSurrogate($bestResponse[$n-1]) -and
                [char]::IsLowSurrogate($bestResponse[$n])) {$n--}
            $bestResponse=$bestResponse.Substring(0,$n)
        }
        @{ok=$true;completed=$complete;partial=(!$complete -and ($bestResponse.Length -gt 0));
          reply=$bestResponse;elapsed_ms=$timer.ElapsedMilliseconds;
          first_reply_ms=$(if($null -eq $firstReplyMs){-1}else{$firstReplyMs});
          truncated=$truncated;
          timeout=(!$complete);replay_safe=$false} |
            ConvertTo-Json -Compress -Depth 3
        return
    }
    if($r.mode -eq 'snapshot') {
      # Experimental read-only property cache; locally opt-in, per request.
      # No AutomationElement, control selector, grant, HWND or PID is reused.
      $snapshotCache=$null
      if($env:UDB_UIA_SNAPSHOT_CACHE -ceq '1'){
          $snapshotCache=[Windows.Automation.CacheRequest]::new()
          $snapshotCache.TreeScope=[Windows.Automation.TreeScope]::Element
          $snapshotCache.TreeFilter=[Windows.Automation.Condition]::TrueCondition
          $snapshotCache.AutomationElementMode=[Windows.Automation.AutomationElementMode]::Full
          foreach($property in @(
              [Windows.Automation.AutomationElement]::NameProperty,
              [Windows.Automation.AutomationElement]::AutomationIdProperty,
              [Windows.Automation.AutomationElement]::ControlTypeProperty,
              [Windows.Automation.AutomationElement]::IsEnabledProperty,
              [Windows.Automation.AutomationElement]::IsOffscreenProperty,
              [Windows.Automation.AutomationElement]::IsPasswordProperty,
              [Windows.Automation.AutomationElement]::BoundingRectangleProperty
          )){$snapshotCache.Add($property)}
      }
      $view='control'
      foreach($walker in @([Windows.Automation.TreeWalker]::ControlViewWalker,[Windows.Automation.TreeWalker]::RawViewWalker)) {
        $queue=[Collections.Generic.Queue[object]]::new();$queue.Enqueue($root)
        $rows=[Collections.Generic.List[object]]::new()
        while($queue.Count -gt 0 -and $rows.Count -lt 200) {
            $element=$queue.Dequeue()
            # The root was obtained before the cache request; children are
            # created via the cache-aware walker overload below.
            $c=if($null -ne $snapshotCache -and $rows.Count -gt 0){
                $element.Cached
            }else{$element.Current}
            $rect=$c.BoundingRectangle
            if($c.IsPassword) {
                $rows.Add(@{name='<password>';password=$true;automation_id=$c.AutomationId})
            } else {
                $label=[string]$c.Name
                if($label.Length -gt 500){$label=$label.Substring(0,500)}
                $coords=@($rect.X,$rect.Y,$rect.Width,$rect.Height)
                $invalid=@($coords|Where-Object {[double]::IsNaN($_) -or [double]::IsInfinity($_)})
                $bounds=if($rect.IsEmpty -or $invalid.Count){@()}else{$coords}
                $patterns=@($element.GetSupportedPatterns() | ForEach-Object { $_.ProgrammaticName -replace 'PatternIdentifiers.Pattern$','' })
                $state=@{name=$label;automation_id=$c.AutomationId;control_type=$c.ControlType.ProgrammaticName;
                    enabled=$c.IsEnabled;offscreen=$c.IsOffscreen;bounds=$bounds;patterns=$patterns}
                $p=$null
                if($element.TryGetCurrentPattern([Windows.Automation.TogglePattern]::Pattern,[ref]$p)){$state.toggle_state=$p.Current.ToggleState.ToString()}
                $p=$null
                if($element.TryGetCurrentPattern([Windows.Automation.SelectionItemPattern]::Pattern,[ref]$p)){$state.selected=$p.Current.IsSelected}
                $p=$null
                if($element.TryGetCurrentPattern([Windows.Automation.ExpandCollapsePattern]::Pattern,[ref]$p)){$state.expanded=$p.Current.ExpandCollapseState.ToString()}
                $p=$null
                if($element.TryGetCurrentPattern([Windows.Automation.ValuePattern]::Pattern,[ref]$p)){$state.readonly=$p.Current.IsReadOnly}
                $rows.Add($state)
                $child=if($null -ne $snapshotCache){
                    $walker.GetFirstChild($element,$snapshotCache)
                }else{$walker.GetFirstChild($element)}
                $count=0
                while($child -and $queue.Count -lt 400 -and $count -lt 100) {
                    $queue.Enqueue($child)
                    $child=if($null -ne $snapshotCache){
                        $walker.GetNextSibling($child,$snapshotCache)
                    }else{$walker.GetNextSibling($child)}
                    $count++
                }
            }
        }
        if($rows.Count -gt 1 -or $view -eq 'raw'){break}
        # Some providers expose children only in Raw View. Stay below the
        # same verified HWND; never search the desktop or match another app.
        $view='raw'
      }
        $hasChildren=$rows.Count -gt 1
        $next=if($hasChildren){''}else{'No accessible child controls exposed. List windows again and select the application frame; do not assume a generic Pane is actionable.'}
        @{ok=$true;elements=$rows.ToArray();truncated=($queue.Count -gt 0);tree_view=$view;children_exposed=$hasChildren;next_action=$next}|ConvertTo-Json -Depth 7 -Compress
        return
    }
    if($r.mode -eq 'ranked_control') {
        # Read-only bounded semantic selection within one exact UIA container.
        # No arbitrary queries or JavaScript; the later invoke revalidates
        # exact name/type and refuses ambiguity or stale windows.
        $needle=[string]$r.text
        if($needle.Length -lt 4 -or $needle.Length -gt 160 -or
           (!$r.name -and !$r.automation_id)) {
            throw 'ranked_control requires a 4..160 character phrase and exact container'
        }
        $allowedTypes=@{
            Hyperlink=[Windows.Automation.ControlType]::Hyperlink;
            Button=[Windows.Automation.ControlType]::Button;
            ListItem=[Windows.Automation.ControlType]::ListItem;
            MenuItem=[Windows.Automation.ControlType]::MenuItem
        }
        $kind=([string]$r.control_type) -creplace '^ControlType\.',''
        if(!$allowedTypes.ContainsKey($kind)){throw 'Unsupported ranked control type'}
        $containerConditions=[Collections.Generic.List[Windows.Automation.Condition]]::new()
        if($r.automation_id){
            $containerConditions.Add([Windows.Automation.PropertyCondition]::new(
                [Windows.Automation.AutomationElement]::AutomationIdProperty,
                [string]$r.automation_id))
        }
        if($r.name){
            $containerConditions.Add([Windows.Automation.PropertyCondition]::new(
                [Windows.Automation.AutomationElement]::NameProperty,
                [string]$r.name))
        }
        $containerCondition=if($containerConditions.Count -eq 1){
            $containerConditions[0]
        }else{
            [Windows.Automation.AndCondition]::new($containerConditions.ToArray())
        }
        $containers=$root.FindAll([Windows.Automation.TreeScope]::Descendants,$containerCondition)
        if($containers.Count -ne 1){throw 'Ranked control container is absent or ambiguous'}
        if($containers[0].Current.IsPassword){throw 'Password containers are refused'}
        $filter=[Windows.Automation.PropertyCondition]::new(
            [Windows.Automation.AutomationElement]::ControlTypeProperty,
            $allowedTypes[$kind])
        $items=$containers[0].FindAll([Windows.Automation.TreeScope]::Descendants,$filter)
        if($items.Count -gt 1500){throw 'Ranked control scan exceeds bounded scope'}
        $candidates=[Collections.Generic.List[object]]::new()
        foreach($node in $items) {
            $current=$node.Current
            if($current.IsPassword -or !$current.IsEnabled -or $current.IsOffscreen){continue}
            $label=[string]$current.Name
            if($label.Length -gt 500 -or
                $label.IndexOf($needle,[StringComparison]::OrdinalIgnoreCase) -lt 0){continue}
            $rect=$current.BoundingRectangle
            if($rect.IsEmpty -or $rect.Width -le 0 -or $rect.Height -le 0){continue}
            $pattern=$null
            if(!$node.TryGetCurrentPattern(
                [Windows.Automation.InvokePattern]::Pattern,[ref]$pattern)){continue}
            $candidates.Add(@{name=$label;automation_id=[string]$current.AutomationId;
                control_type=$current.ControlType.ProgrammaticName;
                left=[double]$rect.Left;top=[double]$rect.Top})
            if($candidates.Count -gt 64){throw 'Ranked control matches exceed limit'}
        }
        if($candidates.Count -eq 0) {
            @{ok=$true;found=$false;matched=0}|ConvertTo-Json -Compress
            return
        }
        $ordered=@($candidates|Sort-Object -Property @{Expression={$_.top};Ascending=$true},@{Expression={$_.left};Ascending=$true})
        if($ordered.Count -gt 1 -and $ordered[0].top -eq $ordered[1].top -and
            $ordered[0].left -eq $ordered[1].left){
            throw 'Ranked first control is ambiguous'
        }
        $chosen=$ordered[0]
        @{ok=$true;found=$true;matched=$ordered.Count;
          name=$chosen.name;automation_id=$chosen.automation_id;
          control_type=$chosen.control_type}|ConvertTo-Json -Compress
        return
    }
    $conditions=[Collections.Generic.List[Windows.Automation.Condition]]::new()
    if($r.automation_id){$conditions.Add([Windows.Automation.PropertyCondition]::new([Windows.Automation.AutomationElement]::AutomationIdProperty,[string]$r.automation_id))}
    if($r.name){$conditions.Add([Windows.Automation.PropertyCondition]::new([Windows.Automation.AutomationElement]::NameProperty,[string]$r.name))}
    if($r.control_type) {
        $types=@{Edit=[Windows.Automation.ControlType]::Edit;Button=[Windows.Automation.ControlType]::Button;
            ComboBox=[Windows.Automation.ControlType]::ComboBox;CheckBox=[Windows.Automation.ControlType]::CheckBox;
            Text=[Windows.Automation.ControlType]::Text;Document=[Windows.Automation.ControlType]::Document;
            List=[Windows.Automation.ControlType]::List;ListItem=[Windows.Automation.ControlType]::ListItem;
            Tree=[Windows.Automation.ControlType]::Tree;TreeItem=[Windows.Automation.ControlType]::TreeItem;
            RadioButton=[Windows.Automation.ControlType]::RadioButton;Tab=[Windows.Automation.ControlType]::Tab;
            TabItem=[Windows.Automation.ControlType]::TabItem;MenuItem=[Windows.Automation.ControlType]::MenuItem;
            Pane=[Windows.Automation.ControlType]::Pane;Group=[Windows.Automation.ControlType]::Group;
            Slider=[Windows.Automation.ControlType]::Slider;ScrollBar=[Windows.Automation.ControlType]::ScrollBar;
            Hyperlink=[Windows.Automation.ControlType]::Hyperlink;DataGrid=[Windows.Automation.ControlType]::DataGrid;
            DataItem=[Windows.Automation.ControlType]::DataItem;Custom=[Windows.Automation.ControlType]::Custom;
            Image=[Windows.Automation.ControlType]::Image;ToolBar=[Windows.Automation.ControlType]::ToolBar;
            Menu=[Windows.Automation.ControlType]::Menu;Window=[Windows.Automation.ControlType]::Window}
        $kind=([string]$r.control_type) -creplace '^ControlType\.',''
        if(!$types.ContainsKey($kind)){throw 'Unsupported control type'}
        $conditions.Add([Windows.Automation.PropertyCondition]::new([Windows.Automation.AutomationElement]::ControlTypeProperty,$types[$kind]))
    }
    if($conditions.Count -eq 0) {
        if($r.mode -ne 'uia_focus'){throw 'Provide an exact control ID or name'}
        $target=$root
    } else {
        $condition=if($conditions.Count -eq 1){$conditions[0]}else{[Windows.Automation.AndCondition]::new($conditions.ToArray())}
        if($r.mode -eq 'wait_for') {
            if(!$r.automation_id -and !$r.name){throw 'wait_for needs exact ID or name'}
            if([int]$r.wait_ms -lt 0 -or [int]$r.wait_ms -gt 10000 -or $r.condition -notin @('exists','absent','enabled')){throw 'Invalid wait options'}
            $timer=[Diagnostics.Stopwatch]::StartNew()
            $matched=$false;$observed=$null
            $observerRequested=($r.event_observer -eq $true -and [int]$r.wait_ms -gt 0)
            $observerUsed=$false;$observerKind='';$observerHandler=$null
            $observerSignal=$null;$observerCleanup=$true
            $observerSignals=[Collections.Concurrent.ConcurrentQueue[bool]]::new()
            $rootRuntimeId=@($root.GetRuntimeId()) -join '.'
            if($observerRequested){
                $observerSignal=[Threading.AutoResetEvent]::new($false)
                $signalRef=$observerSignal
                $signalQueue=$observerSignals
                try {
                    if($r.condition -eq 'enabled'){
                        $handlerBlock={
                            param($sender,$eventArgs)
                            if($eventArgs.Property -eq [Windows.Automation.AutomationElement]::IsEnabledProperty){
                                [void]$signalQueue.Enqueue($true)
                                [void]$signalRef.Set()
                            }
                        }.GetNewClosure()
                        $observerHandler=[Windows.Automation.AutomationPropertyChangedEventHandler]$handlerBlock
                        $observerKind='property'
                        [Windows.Automation.Automation]::AddAutomationPropertyChangedEventHandler(
                            $root,
                            [Windows.Automation.TreeScope]::Subtree,
                            $observerHandler,
                            [Windows.Automation.AutomationProperty[]]@(
                                [Windows.Automation.AutomationElement]::IsEnabledProperty
                            )
                        )
                    }else{
                        $handlerBlock={
                            param($sender,$eventArgs)
                            [void]$signalQueue.Enqueue($true)
                            [void]$signalRef.Set()
                        }.GetNewClosure()
                        $observerHandler=[Windows.Automation.StructureChangedEventHandler]$handlerBlock
                        $observerKind='structure'
                        [Windows.Automation.Automation]::AddStructureChangedEventHandler(
                            $root,
                            [Windows.Automation.TreeScope]::Subtree,
                            $observerHandler
                        )
                    }
                    $observerUsed=$true
                }catch{
                    if($observerKind -eq 'property' -and $observerHandler){
                        try{
                            [Windows.Automation.Automation]::RemoveAutomationPropertyChangedEventHandler(
                                $root,$observerHandler
                            )
                        }catch{$observerCleanup=$false}
                    }elseif($observerKind -eq 'structure' -and $observerHandler){
                        try{
                            [Windows.Automation.Automation]::RemoveStructureChangedEventHandler(
                                $root,$observerHandler
                            )
                        }catch{$observerCleanup=$false}
                    }
                    $observerKind=''
                    $observerUsed=$false
                }
            }
            try{
                do {
                    $liveRoot=[Windows.Automation.AutomationElement]::FromHandle([IntPtr]$r.hwnd)
                    if($null -eq $liveRoot -or $liveRoot.Current.ProcessId -ne [int]$r.pid){
                        throw 'Observed window identity changed while waiting'
                    }
                    $liveRuntimeId=@($liveRoot.GetRuntimeId()) -join '.'
                    if($liveRuntimeId -ne $rootRuntimeId){
                        throw 'Observed window identity changed while waiting'
                    }
                    $found=$liveRoot.FindAll([Windows.Automation.TreeScope]::Descendants,$condition)
                    if($found.Count -gt 1){throw 'Wait selector is ambiguous'}
                    if($found.Count -eq 1 -and $found[0].Current.IsPassword){throw 'Password controls are refused'}
                    $matched=if($r.condition -eq 'absent'){$found.Count -eq 0}elseif($r.condition -eq 'enabled'){$found.Count -eq 1 -and $found[0].Current.IsEnabled}else{$found.Count -eq 1}
                    if($matched -and $found.Count -eq 1){$observed=@{automation_id=$found[0].Current.AutomationId;name=$found[0].Current.Name;control_type=$found[0].Current.ControlType.ProgrammaticName}}
                    if($matched -or $timer.ElapsedMilliseconds -ge [int]$r.wait_ms){break}
                    $remaining=[int][Math]::Min(100,[Math]::Max(1,([int]$r.wait_ms - [int]$timer.ElapsedMilliseconds)))
                    if($observerUsed){
                        [void]$observerSignal.WaitOne($remaining)
                    }else{
                        Start-Sleep -Milliseconds $remaining
                    }
                } while($true)
            }finally{
                if($observerKind -eq 'property' -and $observerHandler){
                    try{
                        [Windows.Automation.Automation]::RemoveAutomationPropertyChangedEventHandler(
                            $root,$observerHandler
                        )
                        $observerCleanup=$true
                    }catch{$observerCleanup=$false}
                }elseif($observerKind -eq 'structure' -and $observerHandler){
                    try{
                        [Windows.Automation.Automation]::RemoveStructureChangedEventHandler(
                            $root,$observerHandler
                        )
                        $observerCleanup=$true
                    }catch{$observerCleanup=$false}
                }
                if($observerSignal){$observerSignal.Dispose()}
            }
            $observerMode=if($observerUsed){'event'}else{'polling'}
            $observerSignalCount=$observerSignals.Count
            @{ok=$true;matched=$matched;timed_out=(!$matched);elapsed_ms=$timer.ElapsedMilliseconds;element=$observed;observer_mode=$observerMode;observer_signals=$observerSignalCount;observer_cleanup=$observerCleanup}|ConvertTo-Json -Depth 4 -Compress
            return
        }
        $matches=$root.FindAll([Windows.Automation.TreeScope]::Descendants,$condition)
        if($matches.Count -ne 1){throw 'Selector must match exactly one control'}
        $target=$matches[0]
    }
    if($target.Current.IsPassword){throw 'Password controls are refused'}
    if($r.mode -eq 'read_text') {
        if(($r.limit -isnot [int] -and $r.limit -isnot [long]) -or $r.limit -lt 1 -or $r.limit -gt 5000){throw 'Invalid text limit'}
        $p=$null
        if($target.TryGetCurrentPattern([Windows.Automation.TextPattern]::Pattern,[ref]$p)) {
            $value=$p.DocumentRange.GetText([int]$r.limit+1);$method='TextPattern'
        } elseif($target.TryGetCurrentPattern([Windows.Automation.ValuePattern]::Pattern,[ref]$p)) {
            $value=[string]$p.Current.Value;$method='ValuePattern'
        } else {throw 'Text/Value pattern unsupported'}
        $truncated=$value.Length -gt [int]$r.limit
        if($truncated){
            $count=[int]$r.limit
            if($count -gt 0 -and [char]::IsHighSurrogate($value[$count-1]) -and [char]::IsLowSurrogate($value[$count])){$count--}
            $value=$value.Substring(0,$count)
        }
        @{ok=$true;text=$value;truncated=$truncated;method=$method}|ConvertTo-Json -Depth 3 -Compress
        return
    }
    if(!$target.Current.IsEnabled){throw 'Disabled control'}
    if($r.mode -eq 'set_checked') {
        if($r.checked -isnot [bool]){throw 'checked must be boolean'}
        $p=$target.GetCurrentPattern([Windows.Automation.TogglePattern]::Pattern)
        $desired=if($r.checked){[Windows.Automation.ToggleState]::On}else{[Windows.Automation.ToggleState]::Off}
        $changed=$p.Current.ToggleState -ne $desired
        if($changed){$p.Toggle()}
        if(!(Observe-State {$p.Current.ToggleState -eq $desired})){throw 'State mismatch; inspect before retrying'}
        @{ok=$true;checked=[bool]$r.checked;changed=$changed;replay_safe=$false}|ConvertTo-Json -Compress
    } elseif($r.mode -eq 'select') {
        if($r.text) {
            if(([string]$r.text).Length -gt 500){throw 'Selection label too large'}
            $label=[Windows.Automation.PropertyCondition]::new([Windows.Automation.AutomationElement]::NameProperty,[string]$r.text)
            $selectable=[Windows.Automation.PropertyCondition]::new([Windows.Automation.AutomationElement]::IsSelectionItemPatternAvailableProperty,$true)
            $items=$target.FindAll([Windows.Automation.TreeScope]::Descendants,[Windows.Automation.AndCondition]::new($label,$selectable))
            if($items.Count -ne 1){throw 'Selection label must match one descendant'}
            $target=$items[0]
            if($target.Current.ProcessId -ne [int]$r.pid -or $target.Current.IsPassword -or !$target.Current.IsEnabled){throw 'Selection target refused'}
        }
        $p=$target.GetCurrentPattern([Windows.Automation.SelectionItemPattern]::Pattern)
        $already=$p.Current.IsSelected
        if(!$already){$p.Select()}
        if(!(Observe-State {$p.Current.IsSelected})){throw 'Selection readback mismatch'}
        @{ok=$true;selected=$true;already_set=$already;replay_safe=$false}|ConvertTo-Json -Compress
    } elseif($r.mode -in @('expand','collapse')) {
        $p=$target.GetCurrentPattern([Windows.Automation.ExpandCollapsePattern]::Pattern)
        $desired=if($r.mode -eq 'expand'){[Windows.Automation.ExpandCollapseState]::Expanded}else{[Windows.Automation.ExpandCollapseState]::Collapsed}
        $changed=$p.Current.ExpandCollapseState -ne $desired
        if($changed){if($r.mode -eq 'expand'){$p.Expand()}else{$p.Collapse()}}
        if(!(Observe-State {$p.Current.ExpandCollapseState -eq $desired})){throw 'Expansion readback mismatch'}
        @{ok=$true;expanded=($r.mode -eq 'expand');changed=$changed;replay_safe=$false}|ConvertTo-Json -Compress
    } elseif($r.mode -eq 'scroll_into_view') {
        $p=$target.GetCurrentPattern([Windows.Automation.ScrollItemPattern]::Pattern)
        $p.ScrollIntoView()
        $visible=Observe-State {!$target.Current.IsOffscreen}
        @{ok=$true;requested=$true;offscreen=(!$visible);replay_safe=$false}|ConvertTo-Json -Compress
    } elseif($r.mode -eq 'uia_focus') {
        $target.SetFocus();@{ok=$true;focus_requested=$true}|ConvertTo-Json -Compress
    } elseif($r.mode -eq 'set_value') {
        if(([string]$r.text).Length -gt 5000){throw 'Text too large'}
        $pattern=$null
        if($target.TryGetCurrentPattern([Windows.Automation.ValuePattern]::Pattern,[ref]$pattern)) {
            if($pattern.Current.IsReadOnly){throw 'Read-only control'}
            $pattern.SetValue([string]$r.text)
            if($pattern.Current.Value -cne [string]$r.text){throw 'Value readback mismatch'}
            $method='ValuePattern'
        } else {
            # Multiline native Edit controls can expose TextPattern without ValuePattern.
            # A fixed, timeout-bounded app-local message is allowed only to that
            # same-PID/root Edit handle. No arbitrary message/HWND is accepted.
            if (-not ('UDBEdit' -as [type])) {
            Add-Type -TypeDefinition @'
using System;
using System.Text;
using System.Runtime.InteropServices;
public static class UDBEdit {
 [DllImport("user32.dll")] public static extern IntPtr GetAncestor(IntPtr h, uint flag);
 [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
 [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetClassName(IntPtr h, StringBuilder b, int n);
 [DllImport("user32.dll", EntryPoint="GetWindowLongW")] public static extern int GetStyle(IntPtr h, int index);
 [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern IntPtr SendMessageTimeout(IntPtr h, uint m, UIntPtr w, string s, uint flags, uint ms, out UIntPtr result);
 [DllImport("user32.dll", EntryPoint="SendMessageTimeoutW", CharSet=CharSet.Unicode)] public static extern IntPtr ReadText(IntPtr h, uint m, UIntPtr w, StringBuilder b, uint flags, uint ms, out UIntPtr result);
}
'@
            }
            $handle=[IntPtr][long]$target.Current.NativeWindowHandle
            $class=[Text.StringBuilder]::new(256);[UDBEdit]::GetClassName($handle,$class,256)>$null
            [uint32]$ownerPid=0;[UDBEdit]::GetWindowThreadProcessId($handle,[ref]$ownerPid)>$null
            if($class.ToString() -cne 'Edit' -or $ownerPid -ne [int]$r.pid -or
                [UDBEdit]::GetAncestor($handle,2) -ne [IntPtr][long]$r.hwnd -or
                ([UDBEdit]::GetStyle($handle,-16) -band 32)) {throw 'Native Edit fallback refused'}
            [UIntPtr]$ack=[UIntPtr]::Zero
            if([UDBEdit]::SendMessageTimeout($handle,12,[UIntPtr]::Zero,[string]$r.text,2,1000,[ref]$ack) -eq [IntPtr]::Zero){throw 'Edit message refused'}
            $read=[Text.StringBuilder]::new(5001)
            if([UDBEdit]::ReadText($handle,13,([UIntPtr]::new([uint32]5001)),$read,2,1000,[ref]$ack) -eq [IntPtr]::Zero){throw 'Edit readback refused'}
            if($read.ToString() -cne [string]$r.text){throw 'Edit readback mismatch'}
            $method='same_process_root_Edit_message'
        }
        @{ok=$true;verified_control_value=$true;characters=([string]$r.text).Length;method=$method}|ConvertTo-Json -Compress
    } else {
        $pattern=$target.GetCurrentPattern([Windows.Automation.InvokePattern]::Pattern)
        $pattern.Invoke();@{ok=$true;invoked=$true;verified_application_result=$false}|ConvertTo-Json -Compress
    }
} catch {
    @{ok=$false;error='UI Automation failed: control changed, selector ambiguous, pattern unsupported, or access refused.'}|ConvertTo-Json -Compress
    return
}
}

# Standard input is a private inherited pipe, not a remotely accessible
# command surface. Strictly one JSON request/reply per line in worker mode.
# No UIA elements, passwords, request payloads or owner permissions are cached.
if($Persistent) {
    [int]$script:UdbSequence=0
    while($true) {
        $line=[Console]::In.ReadLine()
        if($null -eq $line){break}
        $script:UdbSequence++
        $response=Invoke-UdbUia $line
        if($response -isnot [string] -or $response.Length -gt 260000) {
            $response='{"ok":false,"error":"UIA worker produced an invalid response"}'
        }
        # The private, ordered IPC channel uses a monotonically increasing
        # sequence to prevent a stale/duplicate response being accepted for
        # a later mutation. Python validates this before using the result.
        [Console]::Out.WriteLine(
            '{"sequence":'+$script:UdbSequence+',"result":'+$response+'}'
        )
        [Console]::Out.Flush()
    }
} else {
    $response=Invoke-UdbUia ([Console]::In.ReadToEnd())
    if($response -isnot [string] -or $response.Length -gt 262144) {
        [Console]::Out.WriteLine('{"ok":false,"error":"UIA produced an invalid response"}')
        exit 1
    }
    [Console]::Out.WriteLine($response)
    try {
        $reply=$response|ConvertFrom-Json
        if($reply.ok -ne $true){exit 1}
    } catch {exit 1}
}
