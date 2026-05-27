Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

# Brand palette (matches demo_config.yaml)
$brandAccent  = [System.Drawing.ColorTranslator]::FromHtml('#183D4C')
$brandHover   = [System.Drawing.ColorTranslator]::FromHtml('#9EC9D9')
$brandBg      = [System.Drawing.ColorTranslator]::FromHtml('#f7f9fb')
$brandSubtle  = [System.Drawing.ColorTranslator]::FromHtml('#6b7785')

# Locate Edge (fall back to default browser if missing)
$edgePaths = @(
    "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe",
    "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe"
)
$edgeExe = $edgePaths | Where-Object { Test-Path $_ } | Select-Object -First 1
$edgeProfileDir = "$env:LOCALAPPDATA\BranchOfTheFutureEdge"
$appUrl = 'http://localhost:5000'

# --- Form ---
$form = New-Object System.Windows.Forms.Form
$form.Text            = 'Branch of the Future'
$form.Size            = New-Object System.Drawing.Size(460, 220)
$form.StartPosition   = 'CenterScreen'
$form.FormBorderStyle = 'FixedDialog'
$form.MaximizeBox     = $false
$form.MinimizeBox     = $false
$form.BackColor       = $brandBg
$form.TopMost         = $true
$form.ShowInTaskbar   = $true

$title = New-Object System.Windows.Forms.Label
$title.Text      = 'Branch of the Future'
$title.Font      = New-Object System.Drawing.Font('Segoe UI Semibold', 16)
$title.ForeColor = $brandAccent
$title.AutoSize  = $false
$title.Size      = New-Object System.Drawing.Size(420, 30)
$title.Location  = New-Object System.Drawing.Point(20, 22)
$form.Controls.Add($title)

$subtitle = New-Object System.Windows.Forms.Label
$subtitle.Text      = 'Powered by Surface + On-Device AI'
$subtitle.Font      = New-Object System.Drawing.Font('Segoe UI', 9)
$subtitle.ForeColor = $brandSubtle
$subtitle.AutoSize  = $false
$subtitle.Size      = New-Object System.Drawing.Size(420, 18)
$subtitle.Location  = New-Object System.Drawing.Point(22, 54)
$form.Controls.Add($subtitle)

$status = New-Object System.Windows.Forms.Label
$status.Text      = 'Detecting silicon...'
$status.Font      = New-Object System.Drawing.Font('Segoe UI', 10)
$status.ForeColor = $brandAccent
$status.AutoSize  = $false
$status.Size      = New-Object System.Drawing.Size(420, 22)
$status.Location  = New-Object System.Drawing.Point(22, 96)
$form.Controls.Add($status)

$progress = New-Object System.Windows.Forms.ProgressBar
$progress.Style              = 'Marquee'
$progress.MarqueeAnimationSpeed = 30
$progress.Size               = New-Object System.Drawing.Size(400, 14)
$progress.Location           = New-Object System.Drawing.Point(22, 128)
$form.Controls.Add($progress)

$footer = New-Object System.Windows.Forms.Label
$footer.Text      = 'Close the command window to shut down the app.'
$footer.Font      = New-Object System.Drawing.Font('Segoe UI', 8)
$footer.ForeColor = $brandSubtle
$footer.AutoSize  = $false
$footer.Size      = New-Object System.Drawing.Size(420, 18)
$footer.Location  = New-Object System.Drawing.Point(22, 154)
$form.Controls.Add($footer)

$startTime = Get-Date
$stages = @(
    @{ After =  0; Text = 'Detecting silicon...' },
    @{ After =  4; Text = 'Connecting to Foundry Local...' },
    @{ After =  9; Text = 'Loading on-device model (NPU warmup)...' },
    @{ After = 25; Text = 'Building knowledge index...' },
    @{ After = 40; Text = 'Almost ready...' },
    @{ After = 75; Text = 'Still warming up - first launch can take a minute...' }
)

$timer = New-Object System.Windows.Forms.Timer
$timer.Interval = 1000
$timer.Add_Tick({
    $elapsed = ((Get-Date) - $startTime).TotalSeconds
    $current = $stages[0].Text
    foreach ($s in $stages) {
        if ($elapsed -ge $s.After) { $current = $s.Text }
    }
    if ($status.Text -ne $current) { $status.Text = $current }

    $listening = Get-NetTCPConnection -LocalPort 5000 -State Listen -ErrorAction SilentlyContinue
    if ($listening) {
        $status.Text = 'Ready. Opening browser...'
        $progress.Style = 'Continuous'
        $progress.Minimum = 0
        $progress.Maximum = 100
        $progress.Value = 100
        $timer.Stop()
        Start-Sleep -Milliseconds 600
        if ($edgeExe) {
            # Edge in app mode: chromeless dedicated window, isolated profile so it
            # doesn't merge with the user's normal Edge windows.
            Start-Process -FilePath $edgeExe -ArgumentList @(
                "--app=$appUrl",
                "--user-data-dir=$edgeProfileDir",
                "--new-window"
            ) | Out-Null
        } else {
            Start-Process $appUrl
        }
        $form.Close()
    }
    elseif ($elapsed -gt 600) {
        $status.Text = 'Startup is taking longer than expected. Check the console window.'
        $timer.Stop()
    }
})
$timer.Start()

[void]$form.ShowDialog()
$timer.Dispose()

# Launcher exits here. The command window (running run.bat -> python npu_demo_flask.py)
# is the user's kill switch -- closing it shuts down the Flask app. Closing the Edge
# window does NOT kill the app, so Foundry's model stays warm across browser sessions.
