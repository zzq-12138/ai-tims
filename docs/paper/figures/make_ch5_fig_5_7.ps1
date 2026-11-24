# 图 5-7 三池错误推送率与 N 覆盖率随阈值变化（instruct，328 条库）
# 数据来源：docs/paper/评测/门控切片复算_20261123.md §二（600 行逐条 CSV 聚合；每池 n=100）
#   T=0.65/0.70/0.72/0.75/0.77
#   P 错误率 3.4 / 2.4 / 2.5 / 0.0 / 0.0
#   N 错误率 68.1 / 62.3 / 58.7 / 41.4 / 23.8
#   LG 错误率 100.0（构造：凡推必错）
#   N 覆盖率 72.0 / 53.0 / 46.0 / 29.0 / 21.0
. (Join-Path $PSScriptRoot 'ch5_common.ps1')

$W=1772; $H=1060
$bmp,$g=New-FigCanvas $W $H
$penAxis=MkPen 2.6 $false
$penGrid=MkPenColor ([System.Drawing.Color]::FromArgb(215,215,215)) 1.4 $false
$penP=MkPen 4.2 $false
$penN=MkPen 3.4 $false
$penLG=MkPen 3.4 $true
$penCov=MkPen 3.4 $false
$penV=MkPenColor ([System.Drawing.Color]::FromArgb(150,150,150)) 2.2 $true
$brushBlack=MkBrush $script:Black
$brushWhite=MkBrush $script:White

$Ts=@(0.65,0.70,0.72,0.75,0.77)
$pErr=@(3.4,2.4,2.5,0.0,0.0)
$nErr=@(68.1,62.3,58.7,41.4,23.8)
$lgErr=@(100.0,100.0,100.0,100.0,100.0)
$nCov=@(72.0,53.0,46.0,29.0,21.0)

Txt $g '（a）三池错误推送率（instruct）' 170 48 760 56 42 $true 'left' 'center'
Txt $g '（b）N 池覆盖率（instruct）' 1080 48 640 56 42 $true 'left' 'center'

$y0=200; $y1=830
$x0=210; $x1=860; $rx0=1090; $rx1=1700
$sx=($x1-$x0)/(0.77-0.65); $sy=($y1-$y0)/100.0

function PX([double]$v){ return $x0+($v-0.65)*$sx }
function PY([double]$v){ return $y1-$v*$sy }
function RX([double]$v){ return $rx0+($v-0.65)*($rx1-$rx0)/(0.77-0.65) }

# 网格与坐标
foreach($v in @(0,20,40,60,80,100)){
  $yy=PY $v
  $g.DrawLine($penGrid,[float]$x0,[float]$yy,[float]$x1,[float]$yy)
  $g.DrawLine($penGrid,[float]$rx0,[float]$yy,[float]$rx1,[float]$yy)
  Txt $g ([string]$v) ($x0-88) ($yy-28) 76 56 38 $false 'right' 'center'
}
foreach($t in $Ts){
  $xx=PX $t; $xx2=RX $t
  $g.DrawLine($penGrid,[float]$xx,[float]$y0,[float]$xx,[float]$y1)
  $g.DrawLine($penGrid,[float]$xx2,[float]$y0,[float]$xx2,[float]$y1)
  Txt $g $t.ToString('0.00') ($xx-72) ($y1+8) 144 44 38 $false 'center' 'center'
  Txt $g $t.ToString('0.00') ($xx2-72) ($y1+8) 144 44 38 $false 'center' 'center'
}
foreach($t in @(0.70,0.75,0.77)){
  $xx=PX $t; $xx2=RX $t
  $g.DrawLine($penV,[float]$xx,[float]$y0,[float]$xx,[float]$y1)
  $g.DrawLine($penV,[float]$xx2,[float]$y0,[float]$xx2,[float]$y1)
}
$g.DrawLine($penAxis,[float]$x0,[float]$y1,[float]$x1,[float]$y1)
$g.DrawLine($penAxis,[float]$x0,[float]$y0,[float]$x0,[float]$y1)
$g.DrawLine($penAxis,[float]$rx0,[float]$y1,[float]$rx1,[float]$y1)
$g.DrawLine($penAxis,[float]$rx0,[float]$y0,[float]$rx0,[float]$y1)

function Plot-Series($g,[double[]]$xs,[double[]]$ys,$pen,$fx,$fy,[string]$marker){
  for($i=0;$i -lt $xs.Count-1;$i++){
    $g.DrawLine($pen,[float](& $fx $xs[$i]),[float](& $fy $ys[$i]),[float](& $fx $xs[$i+1]),[float](& $fy $ys[$i+1]))
  }
  if($marker -ne 'none'){
    for($i=0;$i -lt $xs.Count;$i++){
      $xx=& $fx $xs[$i]; $yy=& $fy $ys[$i]
      if($marker -eq 'fill'){
        $g.FillEllipse($brushBlack,[float]($xx-10),[float]($yy-10),[float]20,[float]20)
      } else {
        $g.FillEllipse($brushWhite,[float]($xx-10),[float]($yy-10),[float]20,[float]20)
        $g.DrawEllipse($penAxis,[float]($xx-10),[float]($yy-10),[float]20,[float]20)
      }
    }
  }
}
Plot-Series $g $Ts $pErr $penP ${function:PX} ${function:PY} 'fill'
Plot-Series $g $Ts $nErr $penN ${function:PX} ${function:PY} 'open'
Plot-Series $g $Ts $lgErr $penLG ${function:PX} ${function:PY} 'none'
Plot-Series $g $Ts $nCov $penCov ${function:RX} ${function:PY} 'fill'

# 关键点标注
Txt $g '68.1' ((PX 0.65)+14) ((PY 68.1)-52) 130 44 38 $true 'left' 'center'
Txt $g '23.8' ((PX 0.77)-150) ((PY 23.8)-56) 130 44 38 $true 'right' 'center'
Txt $g '100.0（构造）' ((PX 0.68)-10) ((PY 100.0)+12) 300 48 38 $false 'left' 'center'
Txt $g '3.4 → 0.0' ((PX 0.65)+14) ((PY 3.4)+16) 220 44 38 $false 'left' 'center'
Txt $g '72.0' ((RX 0.65)+14) ((PY 72.0)-52) 130 44 38 $true 'left' 'center'
Txt $g '21.0' ((RX 0.77)-140) ((PY 21.0)+14) 130 44 38 $true 'right' 'center'

Txt $g '阈值 T' $x0 ($y1+58) ($x1-$x0) 44 38 $false 'center' 'center'
Txt $g '阈值 T' $rx0 ($y1+58) ($rx1-$rx0) 44 38 $false 'center' 'center'
Txt $g '百分比（%）' ($x0-140) ($y0-52) 260 44 38 $false 'left' 'center'
Txt $g '百分比（%）' ($rx0-140) ($y0-52) 260 44 38 $false 'left' 'center'

# 图例
$lx=110; $ly=950
$g.DrawLine($penP,[float]$lx,[float]$ly,[float]($lx+70),[float]$ly)
$g.FillEllipse($brushBlack,[float]($lx+25),[float]($ly-10),[float]20,[float]20)
Txt $g 'P 错误率' ($lx+84) ($ly-28) 200 56 38 $false 'left' 'center'
$lx=370
$g.DrawLine($penN,[float]$lx,[float]$ly,[float]($lx+70),[float]$ly)
$g.FillEllipse($brushWhite,[float]($lx+25),[float]($ly-10),[float]20,[float]20)
$g.DrawEllipse($penAxis,[float]($lx+25),[float]($ly-10),[float]20,[float]20)
Txt $g 'N 错误率' ($lx+84) ($ly-28) 200 56 38 $false 'left' 'center'
$lx=630
$g.DrawLine($penLG,[float]$lx,[float]$ly,[float]($lx+70),[float]$ly)
Txt $g 'LG 错误率' ($lx+84) ($ly-28) 210 56 38 $false 'left' 'center'
$lx=910
$g.DrawLine($penCov,[float]$lx,[float]$ly,[float]($lx+70),[float]$ly)
$g.FillEllipse($brushBlack,[float]($lx+25),[float]($ly-10),[float]20,[float]20)
Txt $g 'N 覆盖率' ($lx+84) ($ly-28) 200 56 38 $false 'left' 'center'
Txt $g '注：LG 为 leave-gold-out 构造池，推送即错；其 100% 不代表模型缺陷。' 110 1004 1550 46 38 $false 'left' 'center'

$g.Dispose()
Save-Fig $bmp (Join-Path $PSScriptRoot 'fig5_7_pool_curves.png') (Join-Path $PSScriptRoot 'fig5_7_pool_curves_preview15cm.png') 567
$bmp.Dispose()
$brushBlack.Dispose(); $brushWhite.Dispose()
Write-Output '字号: 面板标题 42px=10.08pt, 数值/刻度/图例 38px=9.12pt'
