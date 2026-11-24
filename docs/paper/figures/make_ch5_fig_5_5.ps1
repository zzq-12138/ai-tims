# 图 5-5 三档门控与 T=0.70 工作点（数据图 + 机制示意）
# 数据来源：
#   docs/paper/评测/Qwen3Embedding门控阈值实测结果.md §三（instruct 分数分布）
#     P: min 0.5179 / p10 0.6375 / 中位 0.7974 / p90 0.8868 / max 0.9224
#     N: min 0.4439 / p10 0.5301 / 中位 0.7073 / p90 0.8224 / max 0.9008
#   A/B/C 分档（T=0.70、软带 0.07；每池 n=100）：
#     instruct P 61/21/18，N 21/32/47，LG 18/38/44
#   出处：同文 §6.2；docs/paper/测验/门控切片复算_20261123.md §二（600 行逐条 CSV 现算）
. (Join-Path $PSScriptRoot 'ch5_common.ps1')

$W=1772; $H=1460
$bmp,$g=New-FigCanvas $W $H
$pen=MkPen 3 $false
$penDash=MkPen 2.6 $true
$penThin=MkPen 2.2 $false
$brushWhite=MkBrush $script:White
$brushGray=MkBrush $script:Gray6
$brushHatch=MkHatch ([System.Drawing.Drawing2D.HatchStyle]::LightUpwardDiagonal)
$brushBlack=MkBrush $script:Black

Txt $g '（a）三档阈值与正 / 负例 top1 分数分布（instruct）' 110 36 1550 56 44 $true 'left' 'center'
$x0=190; $x1=1660; $vMin=0.40; $vMax=0.95
$scale=($x1-$x0)/($vMax-$vMin)
function XOf([double]$v){ return $x0+($v-$vMin)*$scale }

$axisY=566
# B 档底色
$bx1=XOf 0.70; $bx2=XOf 0.77
$g.FillRectangle($brushGray,[float]$bx1,[float]170,[float]($bx2-$bx1),[float]($axisY-170))
$g.DrawLine($penDash,[float]$bx1,[float]150,[float]$bx1,[float]($axisY+14))
$g.DrawLine($penDash,[float]$bx2,[float]150,[float]$bx2,[float]($axisY+14))
Txt $g 'T=0.70' ($bx1-270) 100 250 50 40 $true 'right' 'center'
Txt $g 'T+软带=0.77' ($bx2+14) 100 380 50 40 $true 'left' 'center'
$g.DrawLine($pen,[float]$x0,[float]$axisY,[float]$x1,[float]$axisY)
foreach($v in @(0.40,0.50,0.60,0.70,0.80,0.90)){
  $x=XOf $v
  $g.DrawLine($penThin,[float]$x,[float]$axisY,[float]$x,[float]($axisY+14))
  Txt $g $v.ToString('0.00') ($x-90) ($axisY+18) 180 48 38 $false 'center' 'center'
}
Txt $g 'C 档：不推送（清空 items）' ($x0+2) 650 ($bx1-$x0-4) 56 40 $true 'center' 'center'
Txt $g 'B 档' $bx1 650 ($bx2-$bx1) 56 38 $true 'center' 'center'
Txt $g 'A 档：推送' $bx2 650 ($x1-$bx2) 56 40 $true 'center' 'center'

function Draw-Whisker($g,[double]$y,[double]$mn,[double]$p10,[double]$md,[double]$p90,[double]$mx,[string]$name,[string]$medLab,[bool]$labAbove){
  $g.DrawLine($penThin,[float](XOf $mn),[float]$y,[float](XOf $mx),[float]$y)
  $g.DrawLine($penThin,[float](XOf $mn),[float]($y-16),[float](XOf $mn),[float]($y+16))
  $g.DrawLine($penThin,[float](XOf $mx),[float]($y-16),[float](XOf $mx),[float]($y+16))
  $p8=MkPen 9 $false
  $g.DrawLine($p8,[float](XOf $p10),[float]$y,[float](XOf $p90),[float]$y)
  $p8.Dispose()
  $g.FillEllipse($brushBlack,[float]((XOf $md)-11),[float]($y-11),[float]22,[float]22)
  Txt $g $name 0 ($y-30) 210 60 40 $true 'right' 'center'
  if($labAbove){ Txt $g $medLab ((XOf $md)+18) ($y-78) 360 48 38 $false 'left' 'center' }
  else{ Txt $g $medLab ((XOf $md)+18) ($y+30) 360 48 38 $false 'left' 'center' }
}
Draw-Whisker $g 350 0.5179 0.6375 0.7974 0.8868 0.9224 '正例 P' '中位 0.7974' $true
Draw-Whisker $g 452 0.4439 0.5301 0.7073 0.8224 0.9008 '负例 N' '中位 0.7073' $false
Txt $g '细线 min–max　粗线 p10–p90　圆点 中位' 50 724 700 48 38 $false 'left' 'center'

# 下方分档
Txt $g '（b）T=0.70 下三池 A/B/C 分档条数（instruct，每池 n=100）' 110 824 1550 56 44 $true 'left' 'center'
$rx0=330; $rx1=1660; $rw=$rx1-$rx0
$rows=@(
  @('正例 P','61','21','18',61,21,18),
  @('负例 N','21','32','47',21,32,47),
  @('留一法 LG','18','38','44',18,38,44)
)
$ry=900; $rh=96
foreach($r in $rows){
  $a=$r[4]/100.0*$rw; $b=$r[5]/100.0*$rw; $c=$r[6]/100.0*$rw
  $g.FillRectangle($brushWhite,[float]$rx0,[float]$ry,[float]$a,[float]$rh)
  $g.FillRectangle($brushGray,[float]($rx0+$a),[float]$ry,[float]$b,[float]$rh)
  $g.FillRectangle($brushHatch,[float]($rx0+$a+$b),[float]$ry,[float]$c,[float]$rh)
  $g.DrawRectangle($pen,[float]$rx0,[float]$ry,[float]$rw,[float]$rh)
  $g.DrawLine($pen,[float]($rx0+$a),[float]$ry,[float]($rx0+$a),[float]($ry+$rh))
  $g.DrawLine($pen,[float]($rx0+$a+$b),[float]$ry,[float]($rx0+$a+$b),[float]($ry+$rh))
  Txt $g $r[0] 50 ($ry+8) 260 40 40 $true 'right' 'center'
  Txt $g 'n=100' 50 ($ry+50) 260 34 38 $false 'right' 'center'
  Txt $g $r[1] $rx0 ($ry-2) $a $rh 40 $true 'center' 'center'
  Txt $g $r[2] ($rx0+$a) ($ry-2) $b $rh 40 $true 'center' 'center'
  Txt $g $r[3] ($rx0+$a+$b) ($ry-2) $c $rh 40 $true 'center' 'center'
  $ry+=$rh+18
}

# 图例
$lx=110; $ly=1300
$items=@(@('A 推送',$brushWhite),@('B 仅供参考',$brushGray),@('C 不推送',$brushHatch))
foreach($it in $items){
  $g.FillRectangle($it[1],[float]$lx,[float]$ly,[float]54,[float]36)
  $g.DrawRectangle($pen,[float]$lx,[float]$ly,[float]54,[float]36)
  Txt $g $it[0] ($lx+70) ($ly-12) 260 60 38 $false 'left' 'center'
  $lx+=340
}
Txt $g '注：P 池错误推送率以推送数为分母（82 推 / 2 错 = 2.4%）；LG 池凡推必错，属构造结果。' 110 1366 1550 50 38 $false 'left' 'center'

$g.Dispose()
Save-Fig $bmp (Join-Path $PSScriptRoot 'fig5_5_gate_workpoint.png') (Join-Path $PSScriptRoot 'fig5_5_gate_workpoint_preview15cm.png') 567
$bmp.Dispose()
$brushWhite.Dispose(); $brushGray.Dispose(); $brushHatch.Dispose(); $brushBlack.Dispose()
Write-Output '字号: 面板标题 44px=10.56pt, 档位/池名 40px=9.60pt, 数值/刻度/注 38px=9.12pt'
