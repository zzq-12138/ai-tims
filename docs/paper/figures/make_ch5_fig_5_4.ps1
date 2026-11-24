# 图 5-4 关系判别：构造集与反构造集对比（数据图）
# 数据来源：docs/paper/问题二/关系判别/metrics.json
#   orig.sim.macro_f1 0.8923；orig.rule.macro_f1 1.0000；orig.full.macro_f1 1.0000
#   anti.sim.macro_f1 0.8560；anti.rule.macro_f1 0.6600；anti.full.macro_f1 0.7189
#   anti.sim per_class: variant 0.6567 / conflict 0.7729
#   anti.rule per_class: variant 0.0000 / conflict 0.6400
#   anti.full per_class: variant 0.5616 / conflict 0.3566
. (Join-Path $PSScriptRoot 'ch5_common.ps1')

$W=1772; $H=1120
$bmp,$g=New-FigCanvas $W $H
$pen=MkPen 2.6 $false
$penGrid=MkPenColor ([System.Drawing.Color]::FromArgb(215,215,215)) 1.4 $false
$brushWhite=MkBrush $script:White
$brushGray=MkBrush $script:Gray6
$brushHatch=MkHatch ([System.Drawing.Drawing2D.HatchStyle]::LightUpwardDiagonal)

function Draw-Bar($g,[double]$x,[double]$yBase,[double]$w,[double]$v,[double]$scale,$brush,[double]$lift){
  $h=$v*$scale
  if($h -lt 2){ $h=2 }
  $g.FillRectangle($brush,[float]$x,[float]($yBase-$h),[float]$w,[float]$h)
  $g.DrawRectangle($pen,[float]$x,[float]($yBase-$h),[float]$w,[float]$h)
  $lab=('{0:N3}' -f $v)
  Txt $g $lab ($x-20) ($yBase-$h-58-$lift) ($w+40) 48 38 $true 'center' 'center'
}

Txt $g '（a）四类关系 Macro-F1' 120 52 760 56 44 $true 'left' 'center'
$x0=140; $x1=880; $y0=300; $y1=930; $scale=$y1-$y0
foreach($v in @(0.0,0.2,0.4,0.6,0.8,1.0)){
  $yy=$y1-$v*$scale
  $g.DrawLine($penGrid,[float]$x0,[float]$yy,[float]$x1,[float]$yy)
  Txt $g $v.ToString('0.0') ($x0-100) ($yy-30) 86 58 38 $false 'right' 'center'
}
$g.DrawLine($pen,[float]$x0,[float]$y1,[float]$x1,[float]$y1)
$g.DrawLine($pen,[float]$x0,[float]$y0,[float]$x0,[float]$y1)

$groupsA=@(
  @(330,'构造集',@(@('sim',0.8923,$brushWhite),@('rule',1.0000,$brushGray),@('full',1.0000,$brushHatch))),
  @(690,'反构造集',@(@('sim',0.8560,$brushWhite),@('rule',0.6600,$brushGray),@('full',0.7189,$brushHatch)))
)
$barW=72; $gap=16
foreach($grp in $groupsA){
  $cx=$grp[0]; $bars=$grp[2]
  $start=$cx-(($bars.Count*$barW+($bars.Count-1)*$gap)/2)
  for($i=0;$i -lt $bars.Count;$i++){
    $bx=$start+$i*($barW+$gap)
    $lift=if($i -eq 2){58}else{0}
    Draw-Bar $g $bx $y1 $barW $bars[$i][1] $scale $bars[$i][2] $lift
  }
  Txt $g $grp[1] ($cx-160) 942 320 50 40 $true 'center' 'center'
}

Txt $g '（b）反构造集两类 F1' 1030 52 660 56 44 $true 'left' 'center'
$rx0=1060; $rx1=1706
foreach($v in @(0.0,0.2,0.4,0.6,0.8,1.0)){
  $yy=$y1-$v*$scale
  $g.DrawLine($penGrid,[float]$rx0,[float]$yy,[float]$rx1,[float]$yy)
}
$g.DrawLine($pen,[float]$rx0,[float]$y1,[float]$rx1,[float]$y1)
$g.DrawLine($pen,[float]$rx0,[float]$y0,[float]$rx0,[float]$y1)

$groupsB=@(
  @(1210,'variant',@(@('sim',0.6567,$brushWhite),@('rule',0.0000,$brushGray),@('full',0.5616,$brushHatch))),
  @(1540,'conflict',@(@('sim',0.7729,$brushWhite),@('rule',0.6400,$brushGray),@('full',0.3566,$brushHatch)))
)
foreach($grp in $groupsB){
  $cx=$grp[0]; $bars=$grp[2]
  $start=$cx-(($bars.Count*$barW+($bars.Count-1)*$gap)/2)
  for($i=0;$i -lt $bars.Count;$i++){
    $bx=$start+$i*($barW+$gap)
    $lift=if($i -eq 2){58}else{0}
    Draw-Bar $g $bx $y1 $barW $bars[$i][1] $scale $bars[$i][2] $lift
  }
  Txt $g $grp[1] ($cx-160) 942 320 50 40 $true 'center' 'center'
}

# 图例
$lx=180; $ly=1032
$items=@(@('sim（纯余弦）',$brushWhite),@('rule（规则）',$brushGray),@('full（规则 + LLM）',$brushHatch))
foreach($it in $items){
  $g.FillRectangle($it[1],[float]$lx,[float]$ly,[float]52,[float]34)
  $g.DrawRectangle($pen,[float]$lx,[float]$ly,[float]52,[float]34)
  Txt $g $it[0] ($lx+68) ($ly-14) 420 60 38 $false 'left' 'center'
  $lx+=520
}

$g.Dispose()
Save-Fig $bmp (Join-Path $PSScriptRoot 'fig5_4_relation_metrics.png') (Join-Path $PSScriptRoot 'fig5_4_relation_metrics_preview15cm.png') 567
$bmp.Dispose()
$brushWhite.Dispose(); $brushGray.Dispose(); $brushHatch.Dispose()
Write-Output '字号: 面板标题 44px=10.56pt, 组名 40px=9.60pt, 数值/刻度 38px=9.12pt'
