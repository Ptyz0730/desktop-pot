# Launch the pet, prove it exists as a window, and grab a screenshot.
# ASCII only: Windows PowerShell 5.1 reads .ps1 as ANSI and mangles UTF-8.
param(
    [string]$Image = "",
    [int]$WaitMs = 4000,
    [switch]$Topmost
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$pyw = "$env:USERPROFILE\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\pythonw.exe"
if (-not (Test-Path $pyw)) { $pyw = "pythonw" }
$tag = if ($Image -ne "") { $Image -replace '[^\w]', '' } else { 'default' }
$shot = Join-Path $root "assets\live_$tag.png"

$argList = @((Join-Path $root "desktop_pet.py"))
if ($Image -ne "") { $argList += @("--image", $Image) }
if ($Topmost) { $argList += "--topmost" }
$proc = Start-Process -FilePath $pyw -ArgumentList $argList -PassThru
Start-Sleep -Milliseconds $WaitMs

Add-Type @"
using System;
using System.Runtime.InteropServices;
using System.Text;
public class W {
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr p);
  [DllImport("user32.dll")] public static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
  [DllImport("user32.dll")] public static extern int GetWindowLong(IntPtr h, int i);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  public delegate bool EnumProc(IntPtr h, IntPtr p);
  public struct RECT { public int Left, Top, Right, Bottom; }
}
"@

$found = New-Object System.Collections.ArrayList
$cb = [W+EnumProc]{
    param($h, $p)
    $sb = New-Object System.Text.StringBuilder 256
    [void][W]::GetWindowText($h, $sb, 256)
    $t = $sb.ToString()
    if ($t.Length -gt 0) {
        $r = New-Object W+RECT
        [void][W]::GetWindowRect($h, [ref]$r)
        $ex = [W]::GetWindowLong($h, -20)
        [void]$found.Add([pscustomobject]@{
            Handle  = $h
            Title   = $t
            Visible = [W]::IsWindowVisible($h)
            Topmost = (($ex -band 0x8) -ne 0)
            ExStyle = ("0x{0:X}" -f $ex)
            Rect    = "$($r.Left),$($r.Top) - $($r.Right),$($r.Bottom)"
        })
    }
    return $true
}
[void][W]::EnumWindows($cb, [IntPtr]::Zero)

# Only look at the pet's own window. Its title is the four CJK chars used by
# APP_NAME, spelled out as code points so this file stays pure ASCII.
# NOTE: use -join; in PowerShell "[char] + [char]" adds the code points.
# NOTE: non-ASCII anywhere in this file corrupts parsing under PowerShell 5.1
#       (it reads .ps1 as ANSI), so keep comments ASCII.
$title = -join @([char]0x684C, [char]0x9762, [char]0x5BA0, [char]0x7269)
$hits = @($found | Where-Object { $_.Title -eq $title })
$hits | Format-Table -AutoSize

$pet = $hits | Select-Object -First 1
if ($pet) {
    Write-Output "OK: pet window alive at $($pet.Rect), visible=$($pet.Visible), topmost=$($pet.Topmost), exstyle=$($pet.ExStyle)"
} else {
    Write-Output "FAIL: no window titled '$title' found"
}

try {
    Add-Type -AssemblyName System.Windows.Forms, System.Drawing
    $b = [System.Windows.Forms.SystemInformation]::VirtualScreen
    $bmp = New-Object System.Drawing.Bitmap $b.Width, $b.Height
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.CopyFromScreen($b.Left, $b.Top, 0, 0, $bmp.Size)
    $bmp.Save($shot, [System.Drawing.Imaging.ImageFormat]::Png)
    $g.Dispose(); $bmp.Dispose()
    Write-Output "screenshot: $shot ($((Get-Item $shot).Length) bytes)"
} catch {
    Write-Output "screenshot failed: $($_.Exception.Message)"
}

Stop-Process -Id $proc.Id -Force
Write-Output "pet process stopped"
