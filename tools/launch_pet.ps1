# Launch the pet and leave it running, after proving the window really exists.
# ASCII only: Windows PowerShell 5.1 reads .ps1 as ANSI and mangles UTF-8.
param(
    [int]$WaitMs = 3500,
    [switch]$Topmost
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$pyw = "$env:USERPROFILE\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\pythonw.exe"
if (-not (Test-Path $pyw)) { $pyw = "pythonw" }
$shot = Join-Path $root "assets\live_launch.png"

$argList = @((Join-Path $root "desktop_pet.py"))
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

$script:hits = New-Object System.Collections.ArrayList
# Title is the four CJK chars of APP_NAME as code points (keep this file ASCII:
# PowerShell 5.1 reads .ps1 as ANSI and mangles non-ASCII, which can break the
# parse). Use -join: "[char] + [char]" would add the code points instead.
$title = -join @([char]0x684C, [char]0x9762, [char]0x5BA0, [char]0x7269)
$cb = [W+EnumProc]{
    param($h, $p)
    $sb = New-Object System.Text.StringBuilder 256
    [void][W]::GetWindowText($h, $sb, 256)
    if ($sb.ToString() -eq $title) {
        $r = New-Object W+RECT
        [void][W]::GetWindowRect($h, [ref]$r)
        [void]$script:hits.Add([pscustomobject]@{
            Visible = [W]::IsWindowVisible($h)
            Topmost = (([W]::GetWindowLong($h, -20) -band 0x8) -ne 0)
            W = $r.Right - $r.Left
            H = $r.Bottom - $r.Top
            At  = "$($r.Left),$($r.Top)"
        })
    }
    return $true
}
[void][W]::EnumWindows($cb, [IntPtr]::Zero)
$script:hits | Format-Table -AutoSize

# Default mode stacks the pet on the desktop layer; the window is still visible.
# W>100 skips the tiny 1x1 Tk host window used by the layered backend.
$pet = $script:hits | Where-Object { $_.Visible -and $_.W -gt 100 } | Select-Object -First 1
if ($pet) {
    Write-Output "OK: pet window alive at $($pet.At), size $($pet.W)x$($pet.H), topmost=$($pet.Topmost)"
} else {
    Write-Output "FAIL: no visible pet window found"
}

try {
    Add-Type -AssemblyName System.Windows.Forms, System.Drawing
    $b = [System.Windows.Forms.SystemInformation]::VirtualScreen
    $bmp = New-Object System.Drawing.Bitmap $b.Width, $b.Height
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.CopyFromScreen($b.Left, $b.Top, 0, 0, $bmp.Size)
    $bmp.Save($shot, [System.Drawing.Imaging.ImageFormat]::Png)
    $g.Dispose(); $bmp.Dispose()
    Write-Output "screenshot: $shot"
} catch {
    Write-Output "screenshot failed: $($_.Exception.Message)"
}

Write-Output "pet left running (pid $($proc.Id)); quit it from the tray-less right-click menu"
