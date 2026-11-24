# 技术路线图 v2（精修版）：等宽等距、圆角细线、字号分层、关键框浅灰底、支线图例
$ErrorActionPreference='Stop'
Add-Type -AssemblyName System.Drawing

$outDir='g:\JAVA\Code\ai-tims\docs\paper\figures'
$png=Join-Path $outDir 'technical_roadmap_v2.png'

$W=1700; $H=1850
$bmp=New-Object System.Drawing.Bitmap($W,$H)
$bmp.SetResolution(300,300)
$g=[System.Drawing.Graphics]::FromImage($bmp)
$g.Clear([System.Drawing.Color]::White)
$g.SmoothingMode=[System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
$g.TextRenderingHint=[System.Drawing.Text.TextRenderingHint]::AntiAliasGridFit
$g.PixelOffsetMode=[System.Drawing.Drawing2D.PixelOffsetMode]::HighQuality

$black=[System.Drawing.Color]::Black
$grayLine=[System.Drawing.Color]::FromArgb(150,150,150)
$grayFill=[System.Drawing.Color]::FromArgb(242,242,242)

$pen=[System.Drawing.Pen]::new($black,2.0)
$penBranch=[System.Drawing.Pen]::new($grayLine,1.5)
$penBranch.DashStyle=[System.Drawing.Drawing2D.DashStyle]::Dash
$penBranch.DashPattern=@(4,3)

$fEntry=New-Object System.Drawing.Font('宋体',24,[System.Drawing.FontStyle]::Regular,[System.Drawing.GraphicsUnit]::Pixel)
$fTitle=New-Object System.Drawing.Font('宋体',30,[System.Drawing.FontStyle]::Bold,[System.Drawing.GraphicsUnit]::Pixel)
$fSub  =New-Object System.Drawing.Font('宋体',19,[System.Drawing.FontStyle]::Regular,[System.Drawing.GraphicsUnit]::Pixel)
$fLegend=New-Object System.Drawing.Font('宋体',18,[System.Drawing.FontStyle]::Regular,[System.Drawing.GraphicsUnit]::Pixel)

$sf=New-Object System.Drawing.StringFormat
$sf.Alignment=[System.Drawing.StringAlignment]::Center
$sf.LineAlignment=[System.Drawing.StringAlignment]::Center

function Get-RoundPath($x,$y,$w,$h,$r){
  $p=New-Object System.Drawing.Drawing2D.GraphicsPath
  $d=$r*2
  $p.AddArc([float]$x,[float]$y,[float]$d,[float]$d,180,90)
  $p.AddArc([float]($x+$w-$d),[float]$y,[float]$d,[float]$d,270,90)
  $p.AddArc([float]($x+$w-$d),[float]($y+$h-$d),[float]$d,[float]$d,0,90)
  $p.AddArc([float]$x,[float]($y+$h-$d),[float]$d,[float]$d,90,90)
  $p.CloseFigure()
  return $p
}

function Draw-Box($x,$y,$w,$h,$title,$subs,$fill){
  $path=Get-RoundPath $x $y $w $h 10
  $g.FillPath((New-Object System.Drawing.SolidBrush($fill)),$path)
  $g.DrawPath($pen,$path)
  $lineH=40; $subH=28
  $total=$lineH + ($subs.Count*$subH)
  $cy=$y + ($h-$total)/2
  $g.DrawString($title,$fTitle,(New-Object System.Drawing.SolidBrush($black)),(New-Object System.Drawing.RectangleF([float]$x,[float]$cy,[float]$w,[float]$lineH)),$sf)
  $yy=$cy+$lineH
  foreach($s in $subs){
    $g.DrawString($s,$fSub,(New-Object System.Drawing.SolidBrush($black)),(New-Object System.Drawing.RectangleF([float]$x,[float]$yy,[float]$w,[float]$subH)),$sf)
    $yy+=$subH
  }
  $path.Dispose()
}

function Draw-Arrow($x1,$y1,$x2,$y2,$pen){
  $headLen=14.0; $headW=7.5
  $g.DrawLine($pen,[float]$x1,[float]$y1,[float]$x2,[float]($y2-$headLen))
  $pts=@(
    (New-Object System.Drawing.PointF([float]$x2,[float]$y2)),
    (New-Object System.Drawing.PointF([float]($x2-$headW),[float]($y2-$headLen))),
    (New-Object System.Drawing.PointF([float]($x2+$headW),[float]($y2-$headLen)))
  )
  $g.FillPolygon((New-Object System.Drawing.SolidBrush($pen.Color)),$pts)
}

$bw=620; $bx=330; $bh=190; $gap=70; $step=$bh+$gap; $y0=200
$cx=$bx+$bw/2

# 入口
$g.DrawString('工单关闭事件',$fEntry,(New-Object System.Drawing.SolidBrush($black)),(New-Object System.Drawing.RectangleF([float]$bx,[float]110,[float]$bw,[float]44)),$sf)
Draw-Arrow $cx 162 $cx $y0 $pen

$boxes=@(
  @('分步抽取',@('现象 → 根因 → 措施 → 验证 → 条件','另设反向项：排除过哪些可能、有无最终结论'),$false),
  @('证据校验门',@('格式校验、证据回溯、反向项核验','未过即停，标记证据不足并留空'),$true),
  @('条件字段化',@('设备型号 · 工艺段 · 材料或批次','参数区间 · 前置状态'),$false),
  @('条件判别与去重',@('该合并 / 不该合并','事实冲突 / 条件冲突'),$false),
  @('三档门控',@('A 正常推送 · B 仅供参考 · C 不推送'),$true),
  @('知识入库与推送',@('带条件、可追溯','按条件过滤后推送'),$false)
)
for($i=0;$i -lt $boxes.Count;$i++){
  $y=$y0+$i*$step
  $fill=if($boxes[$i][2]){$grayFill}else{[System.Drawing.Color]::White}
  Draw-Box $bx $y $bw $bh $boxes[$i][0] $boxes[$i][1] $fill
  if($i -lt $boxes.Count-1){
    Draw-Arrow $cx ($y+$bh) $cx ($y+$step) $pen
  }
}

# 右侧回环校验支线
$sx=1290; $sw=390; $sh=150
$sy=( $y0+4*$step ) + ($bh-$sh)/2
Draw-Box $sx $sy $sw $sh '阈值定参' @('小库定参、大库复核','失效即判不可迁移') ([System.Drawing.Color]::White)
# 支线框改浅灰虚线描边
$path=Get-RoundPath $sx $sy $sw $sh 10
$g.DrawPath($penBranch,$path)
$path.Dispose()
# 支线箭头（浅灰虚线，指回三档门控）
$by=$sy+$sh/2
$g.DrawLine($penBranch,[float]$sx,[float]$by,[float]( $bx+$bw+16 ),[float]$by)
$pts=@(
  (New-Object System.Drawing.PointF([float]($bx+$bw),[float]$by)),
  (New-Object System.Drawing.PointF([float]($bx+$bw+16),[float]($by-7))),
  (New-Object System.Drawing.PointF([float]($bx+$bw+16),[float]($by+7)))
)
$g.FillPolygon((New-Object System.Drawing.SolidBrush($grayLine)),$pts)

# 图例
$ly=1740
$g.DrawLine($penBranch,[float]$bx,[float]$ly,[float]($bx+64),[float]$ly)
$sfLeft=New-Object System.Drawing.StringFormat
$sfLeft.Alignment=[System.Drawing.StringAlignment]::Near
$sfLeft.LineAlignment=[System.Drawing.StringAlignment]::Center
$g.DrawString('虚线为回环校验',$fLegend,(New-Object System.Drawing.SolidBrush($black)),(New-Object System.Drawing.RectangleF([float]($bx+80),[float]($ly-16),[float]380,[float]32)),$sfLeft)

$bmp.Save($png,[System.Drawing.Imaging.ImageFormat]::Png)
$g.Dispose(); $bmp.Dispose()
Write-Output ('PNG: ' + $png + '  ' + (Get-Item $png).Length + ' bytes')
