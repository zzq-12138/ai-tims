# 第五章插图公用绘图函数（300dpi，15cm 插入宽度，1px = 4.167px/pt 反算）
$ErrorActionPreference='Stop'
Add-Type -AssemblyName System.Drawing

$script:FontName='宋体'
$script:Black=[System.Drawing.Color]::Black
$script:Gray6=[System.Drawing.Color]::FromArgb(240,240,240)
$script:GrayLine=[System.Drawing.Color]::FromArgb(120,120,120)
$script:White=[System.Drawing.Color]::White

function New-FigCanvas([int]$w,[int]$h){
  $bmp=New-Object System.Drawing.Bitmap($w,$h)
  $bmp.SetResolution(300,300)
  $g=[System.Drawing.Graphics]::FromImage($bmp)
  $g.Clear([System.Drawing.Color]::White)
  $g.SmoothingMode=[System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
  $g.TextRenderingHint=[System.Drawing.Text.TextRenderingHint]::AntiAliasGridFit
  $g.PixelOffsetMode=[System.Drawing.Drawing2D.PixelOffsetMode]::HighQuality
  return @($bmp,$g)
}

function Txt($g,[string]$text,[double]$x,[double]$y,[double]$w,[double]$h,[int]$px,[bool]$bold,[string]$ha,[string]$va){
  $style=if($bold){[System.Drawing.FontStyle]::Bold}else{[System.Drawing.FontStyle]::Regular}
  $font=New-Object System.Drawing.Font($script:FontName,[float]$px,$style,[System.Drawing.GraphicsUnit]::Pixel)
  $sf=New-Object System.Drawing.StringFormat
  if($ha -eq 'center'){$sf.Alignment=[System.Drawing.StringAlignment]::Center}
  elseif($ha -eq 'right'){$sf.Alignment=[System.Drawing.StringAlignment]::Far}
  else{$sf.Alignment=[System.Drawing.StringAlignment]::Near}
  if($va -eq 'center'){$sf.LineAlignment=[System.Drawing.StringAlignment]::Center}
  elseif($va -eq 'bottom'){$sf.LineAlignment=[System.Drawing.StringAlignment]::Far}
  else{$sf.LineAlignment=[System.Drawing.StringAlignment]::Near}
  $brush=New-Object System.Drawing.SolidBrush($script:Black)
  $g.DrawString($text,$font,$brush,(New-Object System.Drawing.RectangleF([float]$x,[float]$y,[float]$w,[float]$h)),$sf)
  $brush.Dispose(); $font.Dispose(); $sf.Dispose()
}

function MkPen([double]$px,[bool]$dash){
  $p=New-Object System.Drawing.Pen($script:Black,[float]$px)
  if($dash){ $p.DashStyle=[System.Drawing.Drawing2D.DashStyle]::Custom; $p.DashPattern=@(6,4) }
  return $p
}
function MkPenColor([System.Drawing.Color]$c,[double]$px,[bool]$dash){
  $p=New-Object System.Drawing.Pen($c,[float]$px)
  if($dash){ $p.DashStyle=[System.Drawing.Drawing2D.DashStyle]::Custom; $p.DashPattern=@(6,4) }
  return $p
}
function MkBrush([System.Drawing.Color]$c){ return New-Object System.Drawing.SolidBrush($c) }
function MkHatch([System.Drawing.Drawing2D.HatchStyle]$style){
  return New-Object System.Drawing.Drawing2D.HatchBrush($style,$script:Black,$script:White)
}

function RBox($g,[double]$x,[double]$y,[double]$w,[double]$h,[double]$r,$fill,$pen){
  $path=New-Object System.Drawing.Drawing2D.GraphicsPath
  $d=$r*2
  $path.AddArc([float]$x,[float]$y,[float]$d,[float]$d,180,90)
  $path.AddArc([float]($x+$w-$d),[float]$y,[float]$d,[float]$d,270,90)
  $path.AddArc([float]($x+$w-$d),[float]($y+$h-$d),[float]$d,[float]$d,0,90)
  $path.AddArc([float]$x,[float]($y+$h-$d),[float]$d,[float]$d,90,90)
  $path.CloseFigure()
  if($fill){ $b=MkBrush $fill; $g.FillPath($b,$path); $b.Dispose() }
  $g.DrawPath($pen,$path)
  $path.Dispose()
}

function ArrowDown($g,[double]$x,[double]$y1,[double]$y2,$pen,[double]$head){
  $g.DrawLine($pen,[float]$x,[float]$y1,[float]$x,[float]($y2-$head))
  $pts=@(
    (New-Object System.Drawing.PointF([float]$x,[float]$y2)),
    (New-Object System.Drawing.PointF([float]($x-$head*0.65),[float]($y2-$head))),
    (New-Object System.Drawing.PointF([float]($x+$head*0.65),[float]($y2-$head)))
  )
  $b=MkBrush $pen.Color; $g.FillPolygon($b,$pts); $b.Dispose()
}

function ArrowRight($g,[double]$x1,[double]$y1,[double]$x2,[double]$y2,$pen,[double]$head){
  $g.DrawLine($pen,[float]$x1,[float]$y1,[float]($x2-$head),[float]$y2)
  $pts=@(
    (New-Object System.Drawing.PointF([float]$x2,[float]$y2)),
    (New-Object System.Drawing.PointF([float]($x2-$head),[float]($y2-$head*0.65))),
    (New-Object System.Drawing.PointF([float]($x2-$head),[float]($y2+$head*0.65)))
  )
  $b=MkBrush $pen.Color; $g.FillPolygon($b,$pts); $b.Dispose()
}

# 方框内：标题 + 若干行正文，垂直居中
function BoxContent($g,[double]$x,[double]$y,[double]$w,[double]$h,[string]$title,[string[]]$lines,[int]$tpx,[int]$bpx){
  $lineH=$bpx+14
  $total=$tpx+20+($lines.Count*$lineH)
  $yy=$y+($h-$total)/2
  $tx=$x+14; $tw=$w-28
  Txt $g $title $tx $yy $tw $tpx $tpx $true 'center' 'center'
  $yy+=$tpx+18
  foreach($s in $lines){
    Txt $g $s $tx $yy $tw $lineH $bpx $false 'center' 'center'
    $yy+=$lineH
  }
}

function Save-Fig($bmp,[string]$png,[string]$preview,[int]$pw){
  $bmp.Save($png,[System.Drawing.Imaging.ImageFormat]::Png)
  $ph=[int]($bmp.Height*$pw/$bmp.Width)
  $pre=New-Object System.Drawing.Bitmap($pw,$ph)
  $pg=[System.Drawing.Graphics]::FromImage($pre)
  $pg.InterpolationMode=[System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
  $pg.DrawImage($bmp,0,0,$pw,$ph)
  $pg.Dispose()
  $pre.Save($preview,[System.Drawing.Imaging.ImageFormat]::Png)
  $pre.Dispose()
  Write-Output ('OK ' + $png + '  ' + (Get-Item $png).Length + ' bytes  ' + $bmp.Width + 'x' + $bmp.Height + ' = ' + [Math]::Round($bmp.Width/300*2.54,2) + ' x ' + [Math]::Round($bmp.Height/300*2.54,2) + ' cm')
}
