# 重绘：Qwen3-Embedding-8B 新门控基线（2026-11-19 实测）
# 数据来源（全部内联，逐条对应原文表格，未做二次改写）：
#   docs/paper/评测/Qwen3Embedding门控阈值实测结果.md
#     §二 主表一 raw（Hit@1=82.0%, AUC=0.6271）分数分布 mean/p10/median/p90/min/max
#     §三 主表二 instruct（Hit@1=92.0%, AUC=0.7408）同上
#     §6.2 T=0.70：覆盖 82.0%、正例错误 2.4%、负例错误 62.3%、负例(有效)54.5%、混合 47.6%、混合(有效)45.1%
#   采集时间：2026-11-19（公司内网执行机，qwen3_gate_eval.py 单次运行，失败 0 条）
# 说明：0.70 阈值下 P/N/LG 三池的 A/B/C 逐档条数未随结果回传（逐条 CSV 留在执行机），
#       因此本图不画分档柱状图，改用「分数分布分位 + 阈值线」和「指标条」表达。
# 运行：powershell -ExecutionPolicy Bypass -File redraw_qwen3_gate.ps1
Add-Type -AssemblyName System.Drawing

$outDir = Split-Path -Parent $PSScriptRoot
if (-not $outDir) { $outDir = (Get-Location).Path }
$fontName = "Microsoft YaHei"
$W = 1600; $H = 980

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

# ============ 图 5-9：新基线（instruct + T=0.70） ============
$bmp, $g = New-Canvas $W $H
$black = New-Brush 30 30 30
$grey  = New-Brush 110 110 110
$blue  = New-Brush 47 111 196
$orange= New-Brush 224 123 57
$red   = New-Brush 199 62 58
$green = New-Brush 76 149 84
$purple= New-Brush 126 87 174

Draw-Text $g "图 5-13  新基线门控表现（Qwen3-Embedding-8B + 查询侧 instruction，T=0.70，软带 0.07）" 60 24 30 $black $true "left"
Draw-Text $g "数据：docs/paper/评测/Qwen3Embedding门控阈值实测结果.md §二/§三 与 §6.2；n=300（P/LG/N 各 100）；采集 2026-11-19" 60 66 17 $grey $false "left"

# ---- 左：分数分位（p10-p90 带 + 中位） ----
$LX = 90; $LY = 150; $LW = 620; $LH = 620
$yMin = 0.40; $yMax = 0.95
$yOf = { param($v) $LY + $LH - (($v - $yMin) / ($yMax - $yMin)) * $LH }

Draw-Text $g "正/负例 top1 余弦分布（instruct 与 raw 对照）" ($LX + $LW/2) 108 20 $black $true "center"
# 坐标轴
$g.DrawLine((New-PenColor 60 60 60 2 $false), $LX, $LY, $LX, ($LY+$LH))
$g.DrawLine((New-PenColor 60 60 60 2 $false), $LX, ($LY+$LH), ($LX+$LW), ($LY+$LH))
foreach ($v in @(0.4,0.5,0.6,0.7,0.8,0.9)) {
    $y = & $yOf $v
    $g.DrawLine((New-PenColor 225 225 225 1 $false), $LX, $y, ($LX+$LW), $y)
    Draw-Text $g ("{0:N1}" -f $v) ($LX-14) ($y-11) 16 $grey $false "right"
}
# 阈值线
$yT = & $yOf 0.70; $yB = & $yOf 0.77
$g.DrawLine((New-PenColor 199 62 58 2 $true), $LX, $yT, ($LX+$LW), $yT)
$g.DrawLine((New-PenColor 76 149 84 2 $true), $LX, $yB, ($LX+$LW), $yB)
Draw-Text $g "红虚线：T = 0.70（C 档分界）　绿虚线：T+软带 = 0.77（A 档下限）" ($LX+$LW) 132 14 $grey $false "right"

# 数据：mean, p10, median, p90, min, max
$groups = @(
    @{ name="正例 raw";      mean=0.7617; p10=0.6692; med=0.7776; p90=0.8293; min=0.5551; max=0.9061; c=$blue },
    @{ name="负例 raw";      mean=0.7115; p10=0.5474; med=0.7308; p90=0.8353; min=0.4748; max=0.9167; c=$red },
    @{ name="正例 instruct"; mean=0.7784; p10=0.6375; med=0.7974; p90=0.8868; min=0.5179; max=0.9224; c=$blue },
    @{ name="负例 instruct"; mean=0.6904; p10=0.5301; med=0.7073; p90=0.8224; min=0.4439; max=0.9008; c=$red }
)
$n = $groups.Count
$step = $LW / ($n + 1)
for ($i=0; $i -lt $n; $i++) {
    $grp = $groups[$i]
    $x = $LX + $step * ($i + 1)
    $penC = New-PenColor $grp.c.Color.R $grp.c.Color.G $grp.c.Color.B 3 $false
    # min-max 细线
    $g.DrawLine((New-PenColor 160 160 160 1 $false), $x, (& $yOf $grp.min), $x, (& $yOf $grp.max))
    $g.DrawLine((New-PenColor 160 160 160 1 $false), $x-9, (& $yOf $grp.min), $x+9, (& $yOf $grp.min))
    $g.DrawLine((New-PenColor 160 160 160 1 $false), $x-9, (& $yOf $grp.max), $x+9, (& $yOf $grp.max))
    # p10-p90 粗线
    $g.DrawLine($penC, $x, (& $yOf $grp.p10), $x, (& $yOf $grp.p90))
    $g.FillEllipse($grp.c, $x-8, ((& $yOf $grp.med)-8), 16, 16)
    Draw-Text $g ("{0:N3}" -f $grp.med) ($x+14) ((& $yOf $grp.med)-11) 15 $grp.c $true "left"
    Draw-Text $g $grp.name $x ($LY+$LH+14) 16 $black $false "center"
    Draw-Text $g ("p10 {0:N3}" -f $grp.p10) $x ($LY+$LH+40) 13 $grey $false "center"
    Draw-Text $g ("p90 {0:N3}" -f $grp.p90) $x ($LY+$LH+60) 13 $grey $false "center"
}
Draw-Text $g "细线=min–max，粗线=p10–p90，圆点=中位；两池各 100 条" ($LX+$LW/2) ($LY+$LH+92) 15 $grey $false "center"

# ---- 右：T=0.70 关键指标 ----
$RX = 800; $RY = 150; $RW = 720; $RH = 620
Draw-Text $g "T=0.70 关键指标（instruct；混合口径按 P+LG+N 各 100 等权）" ($RX + $RW/2) 108 20 $black $true "center"
$metrics = @(
    @{ n="正例覆盖";        v=82.0;  c=$blue },
    @{ n="正例错误";        v=2.4;   c=$green },
    @{ n="负例错误";        v=62.3;  c=$orange },
    @{ n="负例错误|有效87"; v=54.5;  c=$orange },
    @{ n="混合错误";        v=47.6;  c=$red },
    @{ n="混合错误|有效";   v=45.1;  c=$red },
    @{ n="LG 错误";         v=100.0; c=$purple }
)
$baseY = $RY + $RH
$barMaxH = $RH - 40
$cnt = $metrics.Count
$slot = $RW / $cnt
for ($i=0; $i -lt $cnt; $i++) {
    $m = $metrics[$i]
    $x = $RX + $slot*$i + $slot*0.18
    $bw = $slot*0.64
    $h = $barMaxH * ($m.v / 100.0)
    $g.FillRectangle($m.c, $x, ($baseY - $h), $bw, $h)
    $label = if ($m.v -ge 99.95) { "100%" } else { ("{0:N1}%" -f $m.v) }
    Draw-Text $g $label ($x + $bw/2) ($baseY - $h - 28) 17 $black $true "center"
    $parts = $m.n.Split("|")
    if ($parts.Count -eq 2) {
        Draw-Text $g $parts[0] ($x + $bw/2) ($baseY + 10) 13 $black $false "center"
        Draw-Text $g $parts[1] ($x + $bw/2) ($baseY + 28) 13 $black $false "center"
    } else {
        Draw-Text $g $m.n ($x + $bw/2) ($baseY + 18) 13 $black $false "center"
    }
}
$g.DrawLine((New-PenColor 60 60 60 2 $false), $RX, $baseY, ($RX+$RW), $baseY)
Draw-Text $g "读数：0.70 不是「错误率达标点」，" ($RX) ($baseY+78) 15 $grey $false "left"
Draw-Text $g "而是「恢复被 0.75 误杀的正确回答」的取舍点；" ($RX) ($baseY+102) 15 $grey $false "left"
Draw-Text $g "混合口径含 LG（gold 移除后必然不可用），" ($RX) ($baseY+126) 15 $grey $false "left"
Draw-Text $g "不能单独当系统错误率（见结果文档 §七.3）。" ($RX) ($baseY+150) 15 $grey $false "left"
Draw-Text $g "LG 错误率 100% 是构造结果，不是模型缺陷。" ($RX) ($baseY+174) 15 $grey $false "left"

$path1 = Join-Path $outDir "fig19_qwen3_gate_070.png"
$bmp.Save($path1, [System.Drawing.Imaging.ImageFormat]::Png)
$g.Dispose(); $bmp.Dispose()

# ============ 图 5-10：raw vs instruct 阈值曲线 ============
$bmp, $g = New-Canvas 1600 1000
$black = New-Brush 30 30 30
$grey  = New-Brush 110 110 110
$blue  = New-Brush 47 111 196
$orange= New-Brush 224 123 57
$red   = New-Brush 199 62 58
$green = New-Brush 76 149 84

Draw-Text $g "图 5-14  raw 与 instruct 阈值曲线对比（Qwen3-Embedding-8B，310 库）" 60 24 30 $black $true "left"
Draw-Text $g "数据：docs/paper/评测/Qwen3Embedding门控阈值实测结果.md §二（raw）/§三（instruct）关键阈值点；n=300；采集 2026-11-19" 60 66 17 $grey $false "left"

$Ts = @(0.50,0.55,0.60,0.65,0.70,0.75,0.80,0.85)
$covRaw   = @(100.0,100.0,92.0,91.0,87.0,68.0,35.0,2.0)
$covIns   = @(100.0,96.0,93.0,89.0,82.0,71.0,50.0,26.0)
$perRaw   = @(18.0,18.0,12.0,11.0,9.2,5.9,0.0,0.0)
$perIns   = @(8.0,4.2,3.2,3.4,2.4,0.0,0.0,0.0)
$mixRaw   = @(65.4,64.1,61.7,60.5,56.1,45.4,28.3,0.0)
$mixIns   = @(60.4,58.0,56.4,54.0,47.6,30.7,12.5,0.0)

function Draw-LineChart($g, $x0, $y0, $w, $h, $title, $series, $yMin, $yMax, $markT) {
    Draw-Text $g $title ($x0 + $w/2) ($y0 - 44) 20 $black $true "center"
    $g.DrawLine((New-PenColor 60 60 60 2 $false), $x0, $y0, $x0, ($y0+$h))
    $g.DrawLine((New-PenColor 60 60 60 2 $false), $x0, ($y0+$h), ($x0+$w), ($y0+$h))
    $yOf = { param($v) $y0 + $h - (($v - $yMin)/($yMax-$yMin))*$h }
    $xOf = { param($t) $x0 + (($t - 0.50)/(0.85-0.50))*$w }
    for ($v = $yMin; $v -le $yMax; $v += 20) {
        $y = & $yOf $v
        $g.DrawLine((New-PenColor 228 228 228 1 $false), $x0, $y, ($x0+$w), $y)
        Draw-Text $g ("{0:N0}%" -f $v) ($x0-12) ($y-10) 15 $grey $false "right"
    }
    foreach ($t in $Ts) {
        $x = & $xOf $t
        Draw-Text $g ("{0:N2}" -f $t) $x ($y0+$h+8) 14 $grey $false "center"
    }
    foreach ($t in $markT) {
        $x = & $xOf $t
        $g.DrawLine((New-PenColor 150 150 150 1 $true), $x, $y0, $x, ($y0+$h))
    }
    foreach ($s in $series) {
        $pen = New-PenColor $s.c.R $s.c.G $s.c.B 3 $false
        for ($i=0; $i -lt $Ts.Count-1; $i++) {
            $g.DrawLine($pen, (& $xOf $Ts[$i]), (& $yOf $s.v[$i]), (& $xOf $Ts[$i+1]), (& $yOf $s.v[$i+1]))
        }
        for ($i=0; $i -lt $Ts.Count; $i++) {
            $x = & $xOf $Ts[$i]; $y = & $yOf $s.v[$i]
            $g.FillEllipse($s.c, ($x-5), ($y-5), 10, 10)
        }
    }
}

$series1 = @(
    @{ name="正例覆盖 raw";      v=$covRaw; c=$blue },
    @{ name="正例覆盖 instruct"; v=$covIns; c=$green }
)
$series2 = @(
    @{ name="混合错误 raw";      v=$mixRaw; c=$red },
    @{ name="混合错误 instruct"; v=$mixIns; c=$orange },
    @{ name="正例错误 raw";      v=$perRaw; c=(New-Brush 150 90 160) },
    @{ name="正例错误 instruct"; v=$perIns; c=(New-Brush 90 160 170) }
)

Draw-LineChart $g 110 180 660 500 "正例覆盖率（分母 100）" $series1 0 100 @(0.70,0.75)
Draw-LineChart $g 890 180 660 500 "错误推送率（分母=推送量）" $series2 0 80 @(0.70,0.75)

# 图例（图下方横排，避免压线）
$lgY = 730
$g.DrawLine((New-PenColor 47 111 196 3 $false), 120, ($lgY+10), 168, ($lgY+10))
Draw-Text $g "正例覆盖 raw" 178 ($lgY-2) 16 $grey $false "left"
$g.DrawLine((New-PenColor 76 149 84 3 $false), 330, ($lgY+10), 378, ($lgY+10))
Draw-Text $g "正例覆盖 instruct" 388 ($lgY-2) 16 $grey $false "left"
$g.DrawLine((New-PenColor 199 62 58 3 $false), 600, ($lgY+10), 648, ($lgY+10))
Draw-Text $g "混合错误 raw" 658 ($lgY-2) 16 $grey $false "left"

$g.DrawLine((New-PenColor 224 123 57 3 $false), 120, ($lgY+46), 168, ($lgY+46))
Draw-Text $g "混合错误 instruct" 178 ($lgY+34) 16 $grey $false "left"
$g.DrawLine((New-PenColor 150 90 160 3 $false), 330, ($lgY+46), 378, ($lgY+46))
Draw-Text $g "正例错误 raw" 388 ($lgY+34) 16 $grey $false "left"
$g.DrawLine((New-PenColor 90 160 170 3 $false), 600, ($lgY+46), 648, ($lgY+46))
Draw-Text $g "正例错误 instruct" 658 ($lgY+34) 16 $grey $false "left"
Draw-Text $g "灰色竖虚线：T=0.70（新）与 T=0.75（旧）" 890 ($lgY+34) 16 $grey $false "left"

Draw-Text $g "读数：instruct 曲线整体位于 raw 上方（同覆盖率下错误率更低）；0.75 处 instruct 正例错误已为 0，" 110 830 16 $grey $false "left"
Draw-Text $g "但覆盖只剩 71.0%（29 条正确回答被挡）；0.70 把覆盖拉回 82.0%，代价是正例错误 2.4%。" 110 858 16 $grey $false "left"
Draw-Text $g "混合错误率受 LG 池结构性影响（凡推必错），不可单独据此宣称「系统错误率」。" 110 886 16 $grey $false "left"

$path2 = Join-Path $outDir "fig20_qwen3_raw_vs_instruct.png"
$bmp.Save($path2, [System.Drawing.Imaging.ImageFormat]::Png)
$g.Dispose(); $bmp.Dispose()

Get-Item $path1, $path2 | Select-Object FullName, Length
