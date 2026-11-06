# SPDX-License-Identifier: GPL-3.0-or-later
# GoleM — voir (et fermer) les boîtes de dialogue d'un processus de la VM. Lancé par `win.sh dialog`
# DANS la session graphique : une session SSH ne voit pas les fenêtres du bureau.
#
#   dialog.ps1 -Process reaper              -> liste les boîtes visibles et leur texte
#   dialog.ps1 -Process reaper -Button "&No" -> clique ce bouton dans chacune
#
# Né le 2026-10-01 : sur un Windows où REAPER n'a jamais servi, sa boîte « You have not yet
# selected an audio device » bloque __startup.lua — GoleM démarre inerte, et rien ne le dit.
param([string]$Process = 'reaper', [string]$Button = '', [string]$Out = 'C:\golem-dialog.txt')
Add-Type @"
using System; using System.Text; using System.Runtime.InteropServices; using System.Collections.Generic;
public class GolemDlg {
  public delegate bool P(IntPtr h, IntPtr l);
  [DllImport("user32.dll")] public static extern bool EnumWindows(P p, IntPtr l);
  [DllImport("user32.dll")] public static extern bool EnumChildWindows(IntPtr h, P p, IntPtr l);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetClassName(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
  [DllImport("user32.dll")] public static extern bool PostMessage(IntPtr h, uint m, IntPtr w, IntPtr l);
  public static List<string> Run(HashSet<uint> pids, string button) { var r = new List<string>();
    EnumWindows((h,l)=>{ uint pid; GetWindowThreadProcessId(h,out pid); var c=new StringBuilder(256); GetClassName(h,c,256);
      if (pids.Contains(pid) && IsWindowVisible(h) && c.ToString()=="#32770") {
        var t=new StringBuilder(512); GetWindowText(h,t,512); r.Add("DIALOG: "+t);
        EnumChildWindows(h,(ch,ll)=>{ var ct=new StringBuilder(2048); GetWindowText(ch,ct,2048); var cc=new StringBuilder(256); GetClassName(ch,cc,256);
          if (ct.Length>0) { r.Add("  ["+cc+"] "+ct.ToString().Replace("\r"," ").Replace("\n"," "));
            if (button.Length>0 && ct.ToString()==button) { PostMessage(ch,0x00F5,IntPtr.Zero,IntPtr.Zero); r.Add("  -> CLIC"); } }
          return true; }, IntPtr.Zero); }
      return true; }, IntPtr.Zero); return r; }
}
"@
$pids = New-Object 'System.Collections.Generic.HashSet[uint32]'
Get-Process $Process -ErrorAction SilentlyContinue | ForEach-Object { [void]$pids.Add([uint32]$_.Id) }
$rows = [GolemDlg]::Run($pids, $Button)
if (-not $rows.Count) { $rows = @("(aucune boîte de dialogue visible pour « $Process »)") }
Set-Content -Path $Out -Value $rows -Encoding UTF8
