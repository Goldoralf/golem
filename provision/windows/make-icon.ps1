# SPDX-License-Identifier: GPL-3.0-or-later
# GoleM - fabrique TOUTES les icones de l'app depuis un seul dessin : la barre oblique rouge de la
# marque "/golem_" (2026-10-02 : "un "/" de couleur rouge"), sur une tuile sombre.
#   app/icons/golem.ico        raccourcis Windows "GoleM" et "Stop GoleM"
#   app/icons/golem-phone.ico  raccourci "GoleM Phone" : la meme barre dans un smartphone
#   app/favicon.ico            onglet / barre des taches (16, 32, 48)
#   app/icons/favicon-32.png, favicon-180.png, icon-512.png   pages, Companion, manifeste, lanceur Linux
#
# LE ROUGE : #ff5a3c, c'est --accent / --sect-live de app/style.css et --c-acc du Companion - la
# couleur exacte de la barre oblique du logo dans la barre du haut. Le fond : #0c0e12, le
# theme_color du manifeste. Ne pas "ajuster" l'un sans l'autre.
#     powershell -File provision\windows\make-icon.ps1
$root = Split-Path (Split-Path $PSScriptRoot)
Add-Type -AssemblyName System.Drawing
$red = [Drawing.Color]::FromArgb(255, 0xff, 0x5a, 0x3c)
$bg = [Drawing.Color]::FromArgb(255, 0x0c, 0x0e, 0x12)
$edge = [Drawing.Color]::FromArgb(255, 0x2a, 0x2e, 0x35)

function RoundRect($x, $y, $w, $h, $r) {
    $p = New-Object Drawing.Drawing2D.GraphicsPath
    $p.AddArc($x, $y, 2 * $r, 2 * $r, 180, 90); $p.AddArc($x + $w - 2 * $r, $y, 2 * $r, 2 * $r, 270, 90)
    $p.AddArc($x + $w - 2 * $r, $y + $h - 2 * $r, 2 * $r, 2 * $r, 0, 90); $p.AddArc($x, $y + $h - 2 * $r, 2 * $r, 2 * $r, 90, 90)
    $p.CloseFigure(); return $p
}

# La barre oblique, centree en (cx, cy) dans une boite de hauteur h : un trait epais a bouts
# horizontaux, comme le "/" de la police monospace grasse du logo.
function Slash($g, $cx, $cy, $h, $small) {
    $w = $h * ($(if ($small) { 0.28 } else { 0.20 }))
    $dx = $h * 0.20
    $pts = [Drawing.PointF[]]@(
        (New-Object Drawing.PointF ($cx - $dx - $w / 2), ($cy + $h / 2)),
        (New-Object Drawing.PointF ($cx - $dx + $w / 2), ($cy + $h / 2)),
        (New-Object Drawing.PointF ($cx + $dx + $w / 2), ($cy - $h / 2)),
        (New-Object Drawing.PointF ($cx + $dx - $w / 2), ($cy - $h / 2)))
    if (-not $small) {
        # le halo du logo (text-shadow 0 0 10px, 45 %) : des contours larges et transparents
        for ($i = 16; $i -ge 1; $i--) {
            $pen = New-Object Drawing.Pen ([Drawing.Color]::FromArgb(5, $red)), ($h * 0.022 * $i)
            $pen.LineJoin = [Drawing.Drawing2D.LineJoin]::Round
            $g.DrawPolygon($pen, $pts)
        }
    }
    $g.FillPolygon((New-Object Drawing.SolidBrush $red), $pts)
}

function Draw($s, $kind) {
    $bmp = New-Object Drawing.Bitmap $s, $s, ([Drawing.Imaging.PixelFormat]::Format32bppArgb)
    $g = [Drawing.Graphics]::FromImage($bmp)
    $g.SmoothingMode = [Drawing.Drawing2D.SmoothingMode]::AntiAlias
    $g.PixelOffsetMode = [Drawing.Drawing2D.PixelOffsetMode]::HighQuality
    $g.CompositingQuality = [Drawing.Drawing2D.CompositingQuality]::HighQuality
    $g.Clear([Drawing.Color]::Transparent)
    $small = $s -lt 32
    if ($kind -eq 'phone') {
        # un smartphone portrait : corps sombre, lisere gris, ecouteur ; l'ecran porte la barre rouge
        $w = $s * 0.56; $x = ($s - $w) / 2; $y = $s * 0.02; $h = $s * 0.96
        $body = RoundRect $x $y $w $h ($w * 0.18)
        $g.FillPath((New-Object Drawing.SolidBrush $bg), $body)
        $g.DrawPath((New-Object Drawing.Pen ([Drawing.Color]::FromArgb(255, 120, 128, 140)), ([Math]::Max(1, $s / 40))), $body)
        if ($s -ge 32) {
            $m = $w * 0.08
            $sp = RoundRect ($s / 2 - $w * 0.14) ($y + $m * 0.7) ($w * 0.28) ([Math]::Max(1, $m * 0.45)) ([Math]::Max(0.5, $m * 0.22))
            $g.FillPath((New-Object Drawing.SolidBrush ([Drawing.Color]::FromArgb(255, 120, 128, 140))), $sp)
        }
        Slash $g ($s / 2) ($s / 2) ($h * 0.46) $small
    } else {
        # la tuile : fond du theme, coins arrondis, un fin lisere pour ne pas se perdre sur un bureau sombre
        $m = [Math]::Max(0, $s * 0.03)
        $tile = RoundRect $m $m ($s - 2 * $m) ($s - 2 * $m) (($s - 2 * $m) * 0.22)
        $g.FillPath((New-Object Drawing.SolidBrush $bg), $tile)
        if ($s -ge 32) { $g.DrawPath((New-Object Drawing.Pen $edge, ([Math]::Max(1, $s / 96))), $tile) }
        Slash $g ($s / 2) ($s / 2) ($s * $(if ($small) { 0.74 } else { 0.62 })) $small
    }
    $g.Dispose()
    return $bmp
}

function Png($bmp) { $ms = New-Object IO.MemoryStream; $bmp.Save($ms, [Drawing.Imaging.ImageFormat]::Png); return , $ms.ToArray() }

function Ico($path, $kind, $sizes) {
    $pngs = @(); foreach ($s in $sizes) { $b = Draw $s $kind; $pngs += , (Png $b); $b.Dispose() }
    $out = New-Object IO.MemoryStream; $wr = New-Object IO.BinaryWriter $out
    $wr.Write([UInt16]0); $wr.Write([UInt16]1); $wr.Write([UInt16]$sizes.Count)
    $offset = 6 + 16 * $sizes.Count
    for ($i = 0; $i -lt $sizes.Count; $i++) {
        $s = $sizes[$i]; $d = $pngs[$i]
        $wr.Write([byte]($s % 256)); $wr.Write([byte]($s % 256)); $wr.Write([byte]0); $wr.Write([byte]0)
        $wr.Write([UInt16]1); $wr.Write([UInt16]32); $wr.Write([UInt32]$d.Length); $wr.Write([UInt32]$offset)
        $offset += $d.Length
    }
    foreach ($d in $pngs) { $wr.Write($d) }
    $wr.Flush(); [IO.File]::WriteAllBytes((Join-Path $root $path), $out.ToArray())
    "$path : $($sizes -join ', ')"
}

$all = 16, 20, 24, 32, 40, 48, 64, 96, 128, 256
Ico 'app\icons\golem.ico' 'tile' $all
Ico 'app\icons\golem-phone.ico' 'phone' $all
Ico 'app\favicon.ico' 'tile' @(16, 32, 48)
foreach ($s in 32, 180, 512) {
    $name = $(if ($s -eq 512) { 'icon-512.png' } else { "favicon-$s.png" })
    $b = Draw $s 'tile'; $b.Save((Join-Path $root "app\icons\$name"), [Drawing.Imaging.ImageFormat]::Png); $b.Dispose()
    "app\icons\$name"
}
