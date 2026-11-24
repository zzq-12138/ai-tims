# 生成开题报告技术路线图（仿范例：白底、细线框、宋体、单色）
$ErrorActionPreference='Stop'
Add-Type -AssemblyName System.Drawing

$outDir='g:\JAVA\Code\ai-tims\docs\paper\figures'
if(-not (Test-Path $outDir)){ New-Item -ItemType Directory -Path $outDir -Force | Out-Null }
$png=Join-Path $outDir 'technical_roadmap.png'

$W=1640; $H=1740
$bmp=New-Object System.Drawing.Bitmap($W,$H)
$bmp.SetResolution(300,300)
$g=[System.Drawing.Graphics]::FromImage($bmp)
$g.Clear([System.Drawing.Color]::White)
$g.SmoothingMode=[System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
$g.TextRenderingHint=[System.Drawing.Text.TextRenderingHint]::AntiAliasGridFit

$penLine=New-Object System.Drawing.Pen([System.Drawing.Color]::Black,2.2)
$penDash=New-Object System.Drawing.Pen([System.Drawing.Color]::Black,1.6)
$penDash.DashStyle=[System.Drawing.Drawing2D.DashStyle]::Dash
$brushBlack=[System.Drawing.Brushes]::Black

$fTitle=New-Object System.Drawing.Font('宋体',26,[System.Drawing.FontStyle]::Bold,[System.Drawing.GraphicsUnit]::Pixel)
$fSub=New-Object System.Drawing.Font('宋体',19,[System.Drawing.FontStyle]::Regular,[System.Drawing.GraphicsUnit]::Pixel)
$fEntry=New-Object System.Drawing.Font('宋体',24,[System.Drawing.FontStyle]::Regular,[System.Drawing.GraphicsUnit]::Pixel)

$sf=New-Object System.Drawing.StringFormat
$sf.Alignment=[System.Drawing.StringAlignment]::Center
$sf.LineAlignment=[System.Drawing.StringAlignment]::Center

function Draw-Box($x,$y,$w,$h,$title,$subs){
  $g.FillRectangle([System.Drawing.Brushes]::White,$x,$y,$w,$h)
  $g.DrawRectangle($penLine,[float]$x,[float]$y,[float]$w,[float]$h)
  $lineH=34; $subH=27
  $total=$lineH + ($subs.Count*$subH)
  $cy=$y + ($h-$total)/2
  $rect=New-Object System.Drawing.RectangleF([float]$x,[float]($cy),[float]$w,[float]$lineH)
  $g.DrawString($title,$fTitle,$brushBlack,$rect,$sf)
  $yy=$cy+$lineH
  foreach($s in $subs){
    $r=New-Object System.Drawing.RectangleF([float]$x,[float]$yy,[float]$w,[float]$subH)
    $g.DrawString($s,$fSub,$brushBlack,$r,$sf)
    $yy+=$subH
  }
}
function Draw-Arrow($x1,$y1,$x2,$y2,$pen){
  $g.DrawLine($pen,[float]$x1,[float]$y1,[float]$x2,[float]$y2)
  $head=10.0
  if([Math]::Abs($y2-$y1) -gt [Math]::Abs($x2-$x1)){
    $dir=if($y2 -gt $y1){1}else{-1}
    $pts=@(
      (New-Object System.Drawing.PointF([float]$x2,[float]$y2)),
      (New-Object System.Drawing.PointF([float]($x2-$head*0.62),[float]($y2-$dir*$head*1.35))),
      (New-Object System.Drawing.PointF([float]($x2+$head*0.62),[float]($y2-$dir*$head*1.35)))
    )
  } else {
    $dir=if($x2 -gt $x1){1}else{-1}
    $pts=@(
      (New-Object System.Drawing.PointF([float]$x2,[float]$y2)),
      (New-Object System.Drawing.PointF([float]($x2-$dir*$head*1.35),[float]($y2-$head*0.62))),
      (New-Object System.Drawing.PointF([float]($x2-$dir*$head*1.35),[float]($y2+$head*0.62)))
    )
  }
  $g.FillPolygon([System.Drawing.Brushes]::Black,$pts)
}

$bw=580; $bx=400; $bh=170; $step=255; $y0=230

# 入口
$g.DrawString('工单关闭事件',$fEntry,$brushBlack,(New-Object System.Drawing.RectangleF([float]($bx),[float]100,[float]$bw,[float]40)),$sf)
Draw-Arrow ($bx+$bw/2) 150 ($bx+$bw/2) $y0 $penLine

$boxes=@(
  @('分步抽取',@('现象 → 根因 → 措施 → 验证 → 条件','另设反向项：排除过哪些可能、有无最终结论')),
  @('证据校验门',@('格式校验、证据回溯、反向项核验','未过即停，标记证据不足并留空')),
  @('条件字段化',@('设备型号 · 工艺段 · 材料或批次','参数区间 · 前置状态')),
  @('条件判别与去重',@('该合并 / 不该合并','事实冲突 / 条件冲突')),
  @('三档门控',@('A 正常推送 · B 仅供参考 · C 不推送')),
  @('知识入库与推送',@('带条件、可追溯','按条件过滤后推送'))
)
for($i=0;$i -lt $boxes.Count;$i++){
  $y=$y0+$i*$step
  Draw-Box $bx $y $bw $bh $boxes[$i][0] $boxes[$i][1]
  if($i -lt $boxes.Count-1){
    Draw-Arrow ($bx+$bw/2) ($y+$bh) ($bx+$bw/2) ($y+$step) $penLine
  }
}

# 右侧支线：阈值定参与跨库迁移复核 → 指回三档门控
$sx=1150; $sw=450; $sh=140
$sy=$y0+4*$step + ($bh-$sh)/2
Draw-Box $sx $sy $sw $sh '阈值定参与跨库迁移复核' @('小库定参、大库复核','失效即判不可迁移')
Draw-Arrow $sx ($sy+$sh/2) ($bx+$bw) ($sy+$sh/2) $penDash

$bmp.Save($png,[System.Drawing.Imaging.ImageFormat]::Png)
$g.Dispose(); $bmp.Dispose()
Write-Output ('PNG: ' + $png + '  ' + (Get-Item $png).Length + ' bytes')
