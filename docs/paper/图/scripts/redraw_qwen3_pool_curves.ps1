# 图 5-15：三池错误推送率随阈值变化（instruct，2026-11-23 切片复算）
# 数据来源（全部内联，逐条对应原文表格，未做二次改写）：
#   docs/paper/评测/门控切片复算_20261123.md §二 聚合表
#   instruct 口径，n=100/池，阈值 0.65/0.70/0.72/0.75/0.77
# 口径：
#   P 错误率 = 推送中 top1 未命中 expectedIds 的比例；
#   LG 错误率 = 100%（leave-gold-out 构造，gold 已移除，凡推必错）；
#   N 错误率 = 推送中不可用条数 / 推送条数；
#   N 覆盖率 = 推送条数 / 100。
# 运行：powershell -ExecutionPolicy Bypass -File redraw_qwen3_pool_curves.ps1
Add-Type -AssemblyName System.Drawing

$outDir = Split-Path -Parent $PSScriptRoot
if (-not $outDir) { $outDir = (Get-Location).Path }
$fontName = "Microsoft YaHei"
$W = 1600; $H = 1000

function New-Canvas($w, $h) {
    $bmp = New-Object System.Drawing.Bitmap($w, $h)
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
    $g.TextRenderingHint = [System.Drawing.Text.TextRenderingHint]::AntiAliasGridFit
    $g.Clear([System.Drawing.Color]::White)
    return @($bmp, $g)
}
function New-Brush($r, $g_, $b) { New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb($r, $g_, $b)) }
function New-PenColor($r, $g_, $b, $w, $dash) {
    $p = New-Object System.Drawing.Pen([System.Drawing.Color]::FromArgb($r, $g_, $b), $w)
    if ($dash) { $p.DashStyle = [System.Drawing.Drawing2D.DashStyle]::Dash }
    return $p
}
function Draw-Text($g, $text, $x, $y, $size, $brush, $bold, $align) {
    $style = if ($bold) { [System.Drawing.FontStyle]::Bold } else { [System.Drawing.FontStyle]::Regular }
    $font = New-Object System.Drawing.Font($fontName, $size, $style, [System.Drawing.GraphicsUnit]::Pixel)
    $sf = New-Object System.Drawing.StringFormat
    if ($align -eq "center") { $sf.Alignment = [System.Drawing.StringAlignment]::Center }
    if ($align -eq "right") { $sf.Alignment = [System.Drawing.StringAlignment]::Far }
    $g.DrawString($text, $font, $brush, [float]$x, [float]$y, $sf)
    $font.Dispose()
}

$bmp, $g = New-Canvas $W $H
$black = New-Brush 30 30 30
$grey  = New-Brush 110 110 110
$blue  = New-Brush 47 111 196
$orange= New-Brush 224 123 57
$red   = New-Brush 199 62 58
$green = New-Brush 76 149 84
$purple= New-Brush 126 87 174

Draw-Text $g "图 5-15  三池错误推送率随阈值变化（instruct，328 库）" 60 24 30 $black $true "left"
Draw-Text $g "数据：docs/paper/评测/门控切片复算_20261123.md §二；n=100/池；阈值 0.65/0.70/0.72/0.75/0.77；采集 2026-11-23" 60 66 17 $grey $false "left"

# ---- 图例 ----
$ly = 118
$g.DrawLine((New-PenColor 76 149 84 3 $false), 110, ($ly+10), 158, ($ly+10))
Draw-Text $g "P 正例" 168 ($ly-2) 16 $grey $false "left"
$g.DrawLine((New-PenColor 224 123 57 3 $false), 270, ($ly+10), 318, ($ly+10))
Draw-Text $g "N 负例" 328 ($ly-2) 16 $grey $false "left"
$g.DrawLine((New-PenColor 126 87 174 3 $false), 440, ($ly+10), 488, ($ly+10))
Draw-Text $g "LG leave-gold-out" 498 ($ly-2) 16 $grey $false "left"
Draw-Text $g "灰色竖虚线：工作点 0.70 / 0.75 / 0.77" 760 ($ly-2) 16 $grey $false "left"

# ---- 左：折线图 ----
$LX = 110; $LY = 200; $LW = 980; $LH = 560
$xMin = 0.65; $xMax = 0.77
$yOf = { param($v) $LY + $LH - ($v / 100.0) * $LH }
$xOf = { param($t) $LX + (($t - $xMin) / ($xMax - $xMin)) * $LW }
$Ts = @(0.65, 0.70, 0.72, 0.75, 0.77)
$pErr = @(3.4, 2.4, 2.5, 0.0, 0.0)
$nErr = @(68.1, 62.3, 58.7, 41.4, 23.8)
$nCov = @(72, 53, 46, 29, 21)
$lgErr = @(100.0, 100.0, 100.0, 100.0, 100.0)

# 坐标轴与网格
$g.DrawLine((New-PenColor 60 60 60 2 $false), $LX, $LY, $LX, ($LY+$LH))
$g.DrawLine((New-PenColor 60 60 60 2 $false), $LX, ($LY+$LH), ($LX+$LW), ($LY+$LH))
for ($v = 0; $v -le 100; $v += 20) {
    $y = & $yOf $v
    $g.DrawLine((New-PenColor 228 228 228 1 $false), $LX, $y, ($LX+$LW), $y)
    Draw-Text $g ("{0:N0}%" -f $v) ($LX-14) ($y-10) 15 $grey $false "right"
}
foreach ($t in $Ts) {
    $x = & $xOf $t
    Draw-Text $g ("{0:N2}" -f $t) $x ($LY+$LH+10) 15 $grey $false "center"
}
Draw-Text $g "阈值 T" ($LX+$LW/2) ($LY+$LH+40) 17 $black $true "center"
Draw-Text $g "错误推送率（分母=推送量）" ($LX+$LW/2) ($LY-16) 20 $black $true "center"

# 工作点竖虚线
foreach ($t in @(0.70, 0.75, 0.77)) {
    $x = & $xOf $t
    $g.DrawLine((New-PenColor 150 150 150 1 $true), $x, $LY, $x, ($LY+$LH))
    $label = if ($t -eq 0.77) { "0.77" } else { ("{0:N2}" -f $t) }
    Draw-Text $g $label $x ($LY-44) 14 $grey $false "center"
}

function Draw-Series($g, $values, $brush, $xOf, $yOf, $Ts) {
    $pen = New-PenColor $brush.Color.R $brush.Color.G $brush.Color.B 3 $false
    for ($i=0; $i -lt $Ts.Count-1; $i++) {
        $g.DrawLine($pen, (& $xOf $Ts[$i]), (& $yOf $values[$i]), (& $xOf $Ts[$i+1]), (& $yOf $values[$i+1]))
    }
    for ($i=0; $i -lt $Ts.Count; $i++) {
        $x = & $xOf $Ts[$i]; $y = & $yOf $values[$i]
        $g.FillEllipse($brush, ($x-6), ($y-6), 12, 12)
    }
}

Draw-Series $g $lgErr $purple $xOf $yOf $Ts
Draw-Series $g $nErr $orange $xOf $yOf $Ts
Draw-Series $g $pErr $green $xOf $yOf $Ts

# 数值标注（P 与 N 错开，避免重叠）
Draw-Text $g "LG 100%（构造性）" ($LX+$LW-8) ((& $yOf 100.0)-30) 16 $purple $true "right"
for ($i=0; $i -lt $Ts.Count; $i++) {
    $x = & $xOf $Ts[$i]
    $np = & $yOf $nErr[$i]
    Draw-Text $g ("{0:N1}%" -f $nErr[$i]) $x ($np-30) 16 $orange $true "center"
}
for ($i=0; $i -lt $Ts.Count; $i++) {
    $x = & $xOf $Ts[$i]
    $pp = & $yOf $pErr[$i]
    $dy = if ($i -eq 1 -or $i -eq 2) { 14 } else { -30 }
    Draw-Text $g ("{0:N1}%" -f $pErr[$i]) $x ($pp+$dy) 16 $green $true "center"
}

# N 覆盖率条（放在图下方）
Draw-Text $g "N 覆盖率（推送/100）：" 110 ($LY+$LH+78) 16 $black $true "left"
$covText = "0.65  72%   ｜   0.70  53%   ｜   0.72  46%   ｜   0.75  29%   ｜   0.77  21%"
Draw-Text $g $covText 330 ($LY+$LH+78) 16 $orange $false "left"

# ---- 右：读数与边界 ----
$RX = 1130; $RY = 200
Draw-Text $g "读数" $RX $RY 22 $black $true "left"
$lines = @(
    "P：0.75 起错误=0；覆盖",
    "   0.70 82.0% → 0.75 71.0% → 0.77 61.0%",
    "",
    "N：0.77 错误率 23.8%，",
    "   但覆盖只剩 21/100。",
    "",
    "LG：100% 是 leave-gold-out 构造结果，",
    "   凡推必错，不是模型缺陷。",
    "",
    "0.70 混合等权：",
    "   191 推 / 91 错 = 47.6%",
    "",
    "结论：抬高阈值不能同时获得",
    "高覆盖与低错误；不宣称达标。"
)
$yy = $RY + 42
foreach ($line in $lines) {
    Draw-Text $g $line $RX $yy 17 $grey $false "left"
    $yy += 30
}

# 底部脚注
Draw-Text $g "读法：P 与 N 的错误率分母是各自推送量；LG 的 100% 不参与「模型好坏」判断。" 110 880 16 $grey $false "left"
Draw-Text $g "0.70 不是「错误率达标点」，而是恢复被 0.75 误挡正确回答的取舍点；混合口径含 LG，不能单独当系统错误率。" 110 908 16 $grey $false "left"
Draw-Text $g "来源：门控切片复算_20261123.md §二（600 行逐条 CSV 的按阈值聚合）；原始 CSV 未回传。" 110 936 16 $grey $false "left"

$path = Join-Path $outDir "fig21_qwen3_pool_error_curves.png"
$bmp.Save($path, [System.Drawing.Imaging.ImageFormat]::Png)
$g.Dispose(); $bmp.Dispose()
Get-Item $path | Select-Object FullName, Length
