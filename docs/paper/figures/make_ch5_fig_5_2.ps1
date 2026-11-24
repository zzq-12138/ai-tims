# 图 5-2 链式抽取分步指标与适用条件召回（数据图）
# 数据来源：docs/paper/问题二/链式抽取/metrics.json（all）
#   step_json_ok 100.0; symptom_match 100.0; evidence_grounded 99.5; verification_match 95.5;
#   meas_f1 0.953; root_match 90.0; cond_f1 0.536
# 条件分类型（docs/paper/问题二/链式抽取/链式抽取评测.md §适用条件）：
#   device_model gold 200 / pred 200 / R 1.000；process_stage 72 / 171 / 0.292；
#   param_range 131 / 167 / 0.389；material_or_batch 11 / 12 / 0.000；precondition 27 / 7 / 0.000
. (Join-Path $PSScriptRoot 'ch5_common.ps1')

$W=1772; $H=1440
$bmp,$g=New-FigCanvas $W $H
$pen=MkPen 3 $false
$penGrid=MkPenColor ([System.Drawing.Color]::FromArgb(210,210,210)) 1.5 $false
$x0=600; $x1=1690; $scale=($x1-$x0)/100.0

Txt $g '（a）200 条留出集分步指标（%）' 80 36 1600 56 44 $true 'left' 'center'

$rowsA=@(
  @('三步 JSON 解析',100.0,$false),
  @('现象匹配',100.0,$false),
  @('证据原文回溯',99.5,$false),
  @('验证方式匹配',95.5,$false),
  @('措施条目 F1',95.3,$false),
  @('根因匹配',90.0,$false),
  @('适用条件 F1',53.6,$true)
)
$y=122; $rowH=86
foreach($v in @(0,20,40,60,80,100)){
  $x=$x0+$v*$scale
  $g.DrawLine($penGrid,[float]$x,105,[float]$x,($y+$rowsA.Count*$rowH+6))
  Txt $g ([string]$v) ($x-45) ($y+$rowsA.Count*$rowH+8) 90 46 38 $false 'center' 'center'
}
Txt $g '百分比' ($x0+($x1-$x0)/2) ($y+$rowsA.Count*$rowH+52) 300 44 38 $false 'center' 'center'
for($i=0;$i -lt $rowsA.Count;$i++){
  $r=$rowsA[$i]; $yy=$y+$i*$rowH; $bw=$r[1]*$scale
  $fill=if($r[2]){$script:Gray6}else{$script:White}
  RBox $g $x0 $yy $bw 58 4 $fill $pen
  Txt $g $r[0] 80 $yy 500 58 40 $false 'right' 'center'
  $lab=('{0:N1}' -f $r[1])
  if($r[1] -ge 85){ Txt $g $lab ($x0+$bw-130) $yy 120 58 38 $true 'right' 'center' }
  else{ Txt $g $lab ($x0+$bw+10) $yy 120 58 38 $true 'left' 'center' }
}

# 下方面板
Txt $g '（b）适用条件分类型召回（%）' 80 790 1600 56 44 $true 'left' 'center'
$rowsB=@(
  @('设备型号',100.0,'gold 200 / 预测 200',$false),
  @('参数区间',38.9,'gold 131 / 预测 167',$false),
  @('工艺段',29.2,'gold 72 / 预测 171',$false),
  @('材料或批次',0.0,'gold 11 / 预测 12',$true),
  @('前置状态',0.0,'gold 27 / 预测 7',$true)
)
$y=850; $rowH=104
foreach($v in @(0,20,40,60,80,100)){
  $x=$x0+$v*$scale
  $g.DrawLine($penGrid,[float]$x,832,[float]$x,($y+$rowsB.Count*$rowH+6))
  Txt $g ([string]$v) ($x-45) ($y+$rowsB.Count*$rowH+8) 90 46 38 $false 'center' 'center'
}
Txt $g '百分比' ($x0+($x1-$x0)/2) ($y+$rowsB.Count*$rowH+52) 300 44 38 $false 'center' 'center'
for($i=0;$i -lt $rowsB.Count;$i++){
  $r=$rowsB[$i]; $yy=$y+$i*$rowH; $bw=$r[1]*$scale
  $fill=if($r[3]){$script:Gray6}else{$script:White}
  if($bw -gt 0){ RBox $g $x0 $yy $bw 58 4 $fill $pen } else { RBox $g $x0 $yy 6 58 2 $fill $pen }
  Txt $g $r[0] 80 ($yy-2) 500 40 40 $false 'right' 'center'
  Txt $g $r[2] 80 ($yy+38) 500 36 38 $false 'right' 'center'
  $lab=('{0:N1}' -f $r[1])
  if($r[1] -ge 85){ Txt $g $lab ($x0+$bw-130) $yy 120 58 38 $true 'right' 'center' }
  else{ Txt $g $lab ($x0+$bw+10) $yy 120 58 38 $true 'left' 'center' }
}

$g.Dispose()
Save-Fig $bmp (Join-Path $PSScriptRoot 'fig5_2_chain_metrics.png') (Join-Path $PSScriptRoot 'fig5_2_chain_metrics_preview15cm.png') 567
$bmp.Dispose()
Write-Output '字号: 面板标题 44px=10.56pt, 指标名 40px=9.60pt, 数值/刻度 38px=9.12pt'
