# 图 5-6 raw 与 instruct 的阈值曲线（数据图）
# 数据来源：docs/paper/评测/Qwen3Embedding门控阈值实测结果.md
#   §二 raw：T=0.50/0.55/0.60/0.65/0.70/0.75/0.80/0.85
#     正例覆盖 100.0/100.0/92.0/91.0/87.0/68.0/35.0/2.0
#     混合等权错误 65.4/64.1/61.7/60.5/56.1/45.4/28.3/0.0
#   §三 instruct：同阈值点
#     正例覆盖 100.0/96.0/93.0/89.0/82.0/71.0/50.0/26.0
#     混合等权错误 60.4/58.0/56.4/54.0/47.6/30.7/12.5/0.0
. (Join-Path $PSScriptRoot 'ch5_common.ps1')

$W=1772; $H=1150
$bmp,$g=New-FigCanvas $W $H
$penAxis=MkPen 2.6 $false
$penGrid=MkPenColor ([System.Drawing.Color]::FromArgb(215,215,215)) 1.4 $false
$penSolid=MkPen 4.2 $false
$penDash=MkPen 4.2 $true
$penV=MkPenColor ([System.Drawing.Color]::FromArgb(150,150,150)) 2.4 $true
$brushBlack=MkBrush $script:Black
$brushWhite=MkBrush $script:White

$Ts=@(0.50,0.55,0.60,0.65,0.70,0.75,0.80,0.85)

function Draw-Panel($g,[double]$x0,[double]$x1,[double]$y0,[double]$y1,[double[]]$ys1,[double[]]$ys2,[string]$title,[string]$ylab){
  Txt $g $title $x0 52 ($x1-$x0) 56 44 $true 'left' 'center'
  Txt $g $ylab ($x0-130) ($y0-62) 240 48 38 $false 'left' 'center'
  $sx=($x1-$x0)/(0.85-0.50); $sy=($y1-$y0)/100.0
  function PX([double]$v){ return $x0+($v-0.50)*$sx }
  function PY([double]$v){ return $y1-$v*$sy }
  foreach($v in @(0,20,40,60,80,100)){
    $yy=PY $v
    $g.DrawLine($penGrid,[float]$x0,[float]$yy,[float]$x1,[float]$yy)
    Txt $g ([string]$v) ($x0-90) ($yy-28) 80 56 38 $false 'right' 'center'
  }
  foreach($v in $Ts){
    $xx=PX $v
    $g.DrawLine($penGrid,[float]$xx,[float]$y0,[float]$xx,[float]$y1)
    Txt $g $v.ToString('0.00') ($xx-70) ($y1+8) 140 46 38 $false 'center' 'center'
  }
  $g.DrawLine($penAxis,[float]$x0,[float]$y1,[float]$x1,[float]$y1)
  $g.DrawLine($penAxis,[float]$x0,[float]$y0,[float]$x0,[float]$y1)
  foreach($v in @(0.70,0.75)){
    $xx=PX $v
    $g.DrawLine($penV,[float]$xx,[float]$y0,[float]$xx,[float]$y1)
  }
  # raw 虚线
  for($i=0;$i -lt $Ts.Count-1;$i++){
    $g.DrawLine($penDash,[float](PX $Ts[$i]),[float](PY $ys2[$i]),[float](PX $Ts[$i+1]),[float](PY $ys2[$i+1]))
  }
  # instruct 实线
  for($i=0;$i -lt $Ts.Count-1;$i++){
    $g.DrawLine($penSolid,[float](PX $Ts[$i]),[float](PY $ys1[$i]),[float](PX $Ts[$i+1]),[float](PY $ys1[$i+1]))
  }
  for($i=0;$i -lt $Ts.Count;$i++){
    $xx=PX $Ts[$i]
    $d1=PY $ys1[$i]; $d2=PY $ys2[$i]
    $g.FillEllipse($brushBlack,[float]($xx-9),[float]($d1-9),[float]18,[float]18)
    $g.FillEllipse($brushWhite,[float]($xx-8),[float]($d2-8),[float]16,[float]16)
    $g.DrawEllipse($penAxis,[float]($xx-8),[float]($d2-8),[float]16,[float]16)
  }
  return @{X0=$x0;X1=$x1;Y1=$y1;SX=$sx;SY=$sy}
}

$covRaw=@(100.0,100.0,92.0,91.0,87.0,68.0,35.0,2.0)
$covIns=@(100.0,96.0,93.0,89.0,82.0,71.0,50.0,26.0)
$errRaw=@(65.4,64.1,61.7,60.5,56.1,45.4,28.3,0.0)
$errIns=@(60.4,58.0,56.4,54.0,47.6,30.7,12.5,0.0)

$a=Draw-Panel $g 200 850 190 880 $covIns $covRaw '（a）正例覆盖率随阈值变化' '百分比（%）'
$b=Draw-Panel $g 1090 1710 190 880 $errIns $errRaw '（b）混合等权错误率随阈值' '百分比（%）'

# 0.70 / 0.75 工作点由灰色竖虚线标出，具体数值见图注与正文表

Txt $g '阈值 T' 200 948 650 46 38 $false 'center' 'center'
Txt $g '阈值 T' 1090 948 620 46 38 $false 'center' 'center'

# 图例
$lx=300; $ly=1042
$g.DrawLine($penSolid,[float]$lx,[float]$ly,[float]($lx+90),[float]$ly)
$g.FillEllipse($brushBlack,[float]($lx+36),[float]($ly-9),[float]18,[float]18)
Txt $g 'instruct（查询侧前缀）' ($lx+110) ($ly-28) 520 56 38 $false 'left' 'center'
$lx=960
$g.DrawLine($penDash,[float]$lx,[float]$ly,[float]($lx+90),[float]$ly)
$g.FillEllipse($brushWhite,[float]($lx+36),[float]($ly-8),[float]16,[float]16)
$g.DrawEllipse($penAxis,[float]($lx+36),[float]($ly-8),[float]16,[float]16)
Txt $g 'raw（不加前缀）' ($lx+110) ($ly-28) 420 56 38 $false 'left' 'center'
Txt $g '灰虚线：T=0.70 与 0.75' 300 1092 700 40 38 $false 'left' 'center'

$g.Dispose()
Save-Fig $bmp (Join-Path $PSScriptRoot 'fig5_6_threshold_curves.png') (Join-Path $PSScriptRoot 'fig5_6_threshold_curves_preview15cm.png') 567
$bmp.Dispose()
$brushBlack.Dispose(); $brushWhite.Dispose()
Write-Output '字号: 面板标题 44px=10.56pt, 刻度/数值/图例 38px=9.12pt'
