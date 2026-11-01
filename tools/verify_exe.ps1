# Verify the built exe really puts a topmost pet window on screen.
# ASCII only: Windows PowerShell 5.1 reads .ps1 as ANSI and mangles UTF-8.
param(
    [string]$Exe,
    [int]$WaitMs = 5000
)
$ErrorActionPreference = "Stop"
if (-not $Exe) {
    $root0 = Split-Path -Parent $PSScriptRoot
    $found = Get-ChildItem (Join-Path $root0 "dist") -Recurse -Filter *.exe -ErrorAction SilentlyContinue |
             Select-Object -First 1
    if (-not $found) { throw "no exe found under dist" }
    $Exe = $found.FullName
}
$root = Split-Path -Parent $PSScriptRoot
$shot = Join-Path $root "assets\exe_live.png"

$proc = Start-Process -FilePath $Exe -PassThru
Start-Sleep -Milliseconds $WaitMs

Add-Type @"
using System;
using System.Runtime.InteropServices;
using System.Text;
public class EW {
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr p);
  [DllImport("user32.dll")] public static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
  [DllImport("user32.dll")] public static extern int GetWindowLong(IntPtr h, int i);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
  public delegate bool EnumProc(IntPtr h, IntPtr p);
  public struct RECT { public int Left, Top, Right, Bottom; }
}
"@

$script:rows = New-Object System.Collections.ArrayList
$cb = [EW+EnumProc]{
    param($h, $p)
    $wpid = 0
    [void][EW]::GetWindowThreadProcessId($h, [ref]$wpid)
    if ($wpid -eq $proc.Id) {
        $sb = New-Object System.Text.StringBuilder 256
        [void][EW]::GetWindowText($h, $sb, 256)
        $r = New-Object EW+RECT
        [void][EW]::GetWindowRect($h, [ref]$r)
        [void]$script:rows.Add([pscustomobject]@{
            Visible = [EW]::IsWindowVisible($h)
            Topmost = (([EW]::GetWindowLong($h, -20) -band 0x8) -ne 0)
            W = $r.Right - $r.Left
            H = $r.Bottom - $r.Top
            At = "$($r.Left),$($r.Top)"
        })
    }
    return $true
}
[void][EW]::EnumWindows($cb, [IntPtr]::Zero)
$script:rows | Format-Table -AutoSize

$pet = $script:rows | Where-Object { $_.Visible -and $_.W -gt 100 } | Select-Object -First 1
if ($pet) {
    Write-Output "OK: exe window on screen at $($pet.At), $($pet.W)x$($pet.H), topmost=$($pet.Topmost)"
} else {
    Write-Output "FAIL: exe produced no visible window"
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
} catch { Write-Output "screenshot failed: $($_.Exception.Message)" }

Stop-Process -Id $proc.Id -Force
Write-Output "exe stopped"
