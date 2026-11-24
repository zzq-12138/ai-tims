# 技术路线图 v4：按 16cm 插入宽度反算（1890px @300dpi，1:1 不缩放）
$ErrorActionPreference='Stop'
Add-Type -AssemblyName System.Drawing

$outDir='g:\JAVA\Code\ai-tims\docs\paper\figures'
$png=Join-Path $outDir 'technical_roadmap_v4.png'
$prev=Join-Path $outDir 'technical_roadmap_v4_preview16cm.png'

# 16cm @ 300dpi = 1889.8 px -> 1890
$W=1890; $H=1590
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

$pen=[System.Drawing.Pen]::new($black,3.2)
$penBranch=[System.Drawing.Pen]::new($grayLine,2.4)
$penBranch.DashStyle=[System.Drawing.Drawing2D.DashStyle]::Dash
$penBranch.DashPattern=@(5,4)

# 46px = 11.04pt；41px = 9.84pt（300dpi）
$fEntry =New-Object System.Drawing.Font('宋体',46,[System.Drawing.FontStyle]::Regular,[System.Drawing.GraphicsUnit]::Pixel)
$fTitle =New-Object System.Drawing.Font('宋体',46,[System.Drawing.FontStyle]::Bold,[System.Drawing.GraphicsUnit]::Pixel)
$fSub   =New-Object System.Drawing.Font('宋体',41,[System.Drawing.FontStyle]::Regular,[System.Drawing.GraphicsUnit]::Pixel)
$fLegend=New-Object System.Drawing.Font('宋体',38,[System.Drawing.FontStyle]::Regular,[System.Drawing.GraphicsUnit]::Pixel)

$sf=New-Object System.Drawing.StringFormat
$sf.Alignment=[System.Drawing.StringAlignment]::Center
$sf.LineAlignment=[System.Drawing.StringAlignment]::Center
$sfLeft=New-Object System.Drawing.StringFormat
$sfLeft.Alignment=[System.Drawing.StringAlignment]::Near
$sfLeft.LineAlignment=[System.Drawing.StringAlignment]::Center
$brushBlack=New-Object System.Drawing.SolidBrush($black)

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

function Draw-Box($x,$y,$w,$h,$title,$subs,$fill,$borderPen){
  $path=Get-RoundPath $x $y $w $h 15
  $g.FillPath((New-Object System.Drawing.SolidBrush($fill)),$path)
  $g.DrawPath($borderPen,$path)
  $lineH=62; $subH=52
  $total=$lineH + ($subs.Count*$subH)
  $cy=$y + ($h-$total)/2
  $g.DrawString($title,$fTitle,$brushBlack,(New-Object System.Drawing.RectangleF([float]$x,[float]$cy,[float]$w,[float]$lineH)),$sf)
  $yy=$cy+$lineH
  foreach($s in $subs){
    $g.DrawString($s,$fSub,$brushBlack,(New-Object System.Drawing.RectangleF([float]$x,[float]$yy,[float]$w,[float]$subH)),$sf)
    $yy+=$subH
  }
  $path.Dispose()
}

function Draw-Arrow($x1,$y1,$x2,$y2,$pen,$headLen,$headW){
  $g.DrawLine($pen,[float]$x1,[float]$y1,[float]$x2,[float]($y2-$headLen))
  $pts=@(
    (New-Object System.Drawing.PointF([float]$x2,[float]$y2)),
    (New-Object System.Drawing.PointF([float]($x2-$headW),[float]($y2-$headLen))),
    (New-Object System.Drawing.PointF([float]($x2+$headW),[float]($y2-$headLen)))
  )
  $g.FillPolygon((New-Object System.Drawing.SolidBrush($pen.Color)),$pts)
}

$bw=917; $bx=181; $bh=181; $gap=49; $step=$bh+$gap; $y0=149
$cx=$bx+$bw/2

$g.DrawString('工单关闭事件',$fEntry,$brushBlack,(New-Object System.Drawing.RectangleF([float]$bx,[float]56,[float]$bw,[float]60)),$sf)
Draw-Arrow $cx 118 $cx $y0 $pen 20 11

$boxes=@(
  @('分步抽取',@('现象 → 根因 → 措施 → 验证 → 条件'),$false),
  @('证据校验门',@('格式 / 证据回溯 / 反向项','未过即停 · 证据不足留空'),$true),
  @('条件字段化',@('型号 · 工艺段 · 材料或批次','参数区间 · 前置状态'),$false),
  @('条件判别与去重',@('该合并 / 不该合并','事实冲突 / 条件冲突'),$false),
  @('三档门控',@('A 推送 · B 仅供参考 · C 不推送'),$true),
  @('知识入库与推送',@('带条件、可追溯','按条件过滤后推送'),$false)
)
for($i=0;$i -lt $boxes.Count;$i++){
  $y=$y0+$i*$step
  $fill=if($boxes[$i][2]){$grayFill}else{[System.Drawing.Color]::White}
  Draw-Box $bx $y $bw $bh $boxes[$i][0] $boxes[$i][1] $fill $pen
  if($i -lt $boxes.Count-1){
    Draw-Arrow $cx ($y+$bh) $cx ($y+$step) $pen 20 11
  }
}

# 右侧回环校验支线
$sx=1227; $sw=576; $sh=160
$sy=( $y0+4*$step ) + ($bh-$sh)/2
Draw-Box $sx $sy $sw $sh '阈值定参' @('小库定参、大库复核','失效即判不可迁移') ([System.Drawing.Color]::White) $penBranch
$by=$sy+$sh/2
$g.DrawLine($penBranch,[float]$sx,[float]$by,[float]($bx+$bw+32),[float]$by)
$pts=@(
  (New-Object System.Drawing.PointF([float]($bx+$bw),[float]$by)),
  (New-Object System.Drawing.PointF([float]($bx+$bw+32),[float]($by-12))),
  (New-Object System.Drawing.PointF([float]($bx+$bw+32),[float]($by+12)))
)
$g.FillPolygon((New-Object System.Drawing.SolidBrush($grayLine)),$pts)

# 图例
$ly=1518
$g.DrawLine($penBranch,[float]$bx,[float]$ly,[float]($bx+120),[float]$ly)
$g.DrawString('虚线为回环校验',$fLegend,$brushBlack,(New-Object System.Drawing.RectangleF([float]($bx+142),[float]($ly-30),[float]700,[float]60)),$sfLeft)

$g.Dispose()

$bmp.Save($png,[System.Drawing.Imaging.ImageFormat]::Png)
# 16cm 等比预览（96dpi 屏幕：16cm ≈ 605px）
$pw=605; $ph=[int]($H*$pw/$W)
$preview=New-Object System.Drawing.Bitmap($pw,$ph)
$pg=[System.Drawing.Graphics]::FromImage($preview)
$pg.InterpolationMode=[System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
$pg.DrawImage($bmp,0,0,$pw,$ph)
$pg.Dispose()
$preview.Save($prev,[System.Drawing.Imaging.ImageFormat]::Png)
$preview.Dispose()
$bmp.Dispose()

Write-Output ('v4: ' + $png + '  ' + (Get-Item $png).Length + ' bytes  ' + $W + 'x' + $H + '  = ' + [Math]::Round($W/300*2.54,2) + ' x ' + [Math]::Round($H/300*2.54,2) + ' cm')
Write-Output ('preview: ' + $prev + '  ' + $pw + 'x' + $ph)
Write-Output ('磅数: 步骤名 ' + [Math]::Round(46/300*72,2) + 'pt, 要素 ' + [Math]::Round(41/300*72,2) + 'pt, 图例 ' + [Math]::Round(38/300*72,2) + 'pt')
