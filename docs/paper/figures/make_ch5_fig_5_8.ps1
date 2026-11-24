# 图 5-8 外部三集验证（只测不训，S1 / S3）
# 数据来源：docs/paper/问题二/外部验证报告.md
#   §4.1 总表：现象语义一致率 MaintNet 89.3/96.5、Fujitsu 89.1/89.3、电梯 76.7/66.8（S1/S3）
#              措施 F1 MaintNet 77.7/77.7、Fujitsu 3.2/1.5、电梯 10.2/4.6（S1/S3）
#   §4.1 根因：Fujitsu S1 59.8%（n=100）；S3 主协议 0.0%；
#   §3.2 诊断：S3 换训练同款 SYSTEM_PROMPT 后 56.9%（n=100，诊断性证据）
#   状态：S1 定稿；S3 已跑完、复核中（图中以斜线区分）。
. (Join-Path $PSScriptRoot 'ch5_common.ps1')

$W=1772; $H=1520
$bmp,$g=New-FigCanvas $W $H
$pen=MkPen 2.8 $false
$penGrid=MkPenColor ([System.Drawing.Color]::FromArgb(215,215,215)) 1.4 $false
$brushWhite=MkBrush $script:White
$brushGray=MkBrush $script:Gray6
$brushHatch=MkHatch ([System.Drawing.Drawing2D.HatchStyle]::LightUpwardDiagonal)

$cats=@('MaintNet','Fujitsu','中文电梯')
$s1a=@(89.3,89.1,76.7); $s3a=@(96.5,89.3,66.8)
$s1b=@(77.7,3.2,10.2);  $s3b=@(77.7,1.5,4.6)

function Panel($g,[string]$title,[double]$yTop,[double[]]$v1,[double[]]$v2){
  Txt $g $title 110 $yTop 1500 52 42 $true 'left' 'center'
  $plotTop=$yTop+100; $plotBot=$yTop+400
  $x0=230; $x1=1660; $sy=($plotBot-$plotTop)/100.0
  foreach($v in @(0,20,40,60,80,100)){
    $yy=$plotBot-$v*$sy
    $g.DrawLine($penGrid,[float]$x0,[float]$yy,[float]$x1,[float]$yy)
    Txt $g ([string]$v) ($x0-92) ($yy-26) 80 52 38 $false 'right' 'center'
  }
  $g.DrawLine($pen,[float]$x0,[float]$plotBot,[float]$x1,[float]$plotBot)
  $g.DrawLine($pen,[float]$x0,[float]$plotTop,[float]$x0,[float]$plotBot)
  $centers=@(480,940,1400)
  $bw=118; $gap=26
  for($i=0;$i -lt 3;$i++){
    $sx=$centers[$i]-($bw+$gap/2)
    foreach($pair in @(@($sx,$v1[$i],$brushWhite),@(($sx+$bw+$gap),$v2[$i],$brushHatch))){
      $bx=$pair[0]; $v=$pair[1]; $br=$pair[2]
      $h=$v*$sy; if($h -lt 2){$h=2}
      $g.FillRectangle($br,[float]$bx,[float]($plotBot-$h),[float]$bw,[float]$h)
      $g.DrawRectangle($pen,[float]$bx,[float]($plotBot-$h),[float]$bw,[float]$h)
      Txt $g ('{0:N1}' -f $v) ($bx-20) ($plotBot-$h-54) ($bw+40) 44 38 $true 'center' 'center'
    }
    Txt $g $cats[$i] ($centers[$i]-220) ($plotBot+8) 440 44 38 $false 'center' 'center'
  }
  Txt $g '百分比（%）' ($x0-150) ($plotTop-58) 260 44 38 $false 'left' 'center'
}

Panel $g '（a）现象语义一致率（S1 定稿 / S3 复核中）' 40 $s1a $s3a
Panel $g '（b）措施 F1（S1 定稿 / S3 复核中）' 540 $s1b $s3b

# 图例（放 (a) 右上）
$lx=1250; $ly=78
$g.FillRectangle($brushWhite,[float]$lx,[float]$ly,[float]44,[float]30)
$g.DrawRectangle($pen,[float]$lx,[float]$ly,[float]44,[float]30)
Txt $g 'S1 零样本（定稿）' ($lx+56) ($ly-14) 420 52 38 $false 'left' 'center'
$ly=126
$g.FillRectangle($brushHatch,[float]$lx,[float]$ly,[float]44,[float]30)
$g.DrawRectangle($pen,[float]$lx,[float]$ly,[float]44,[float]30)
Txt $g 'S3 微调（复核中）' ($lx+56) ($ly-14) 420 52 38 $false 'left' 'center'

# (c) Fujitsu 根因
Txt $g '（c）Fujitsu 根因语义一致率（n=100）' 110 1040 1500 52 42 $true 'left' 'center'
$pTop=1120; $pBot=1360; $sy=($pBot-$pTop)/100.0
$x0=230; $x1=1660
foreach($v in @(0,20,40,60,80,100)){
  $yy=$pBot-$v*$sy
  $g.DrawLine($penGrid,[float]$x0,[float]$yy,[float]$x1,[float]$yy)
  Txt $g ([string]$v) ($x0-92) ($yy-26) 80 52 38 $false 'right' 'center'
}
$g.DrawLine($pen,[float]$x0,[float]$pBot,[float]$x1,[float]$pBot)
$g.DrawLine($pen,[float]$x0,[float]$pTop,[float]$x0,[float]$pBot)
$bars=@(
  @(520,'S1 零样本',59.8,$brushWhite),
  @(860,'S3 主协议',0.0,$brushHatch),
  @(1200,'S3 训练同款',56.9,$brushGray)
)
$bw=150
foreach($b in $bars){
  $bx=$b[0]-$bw/2; $h=$b[2]*$sy; if($h -lt 2){$h=2}
  $g.FillRectangle($b[3],[float]$bx,[float]($pBot-$h),[float]$bw,[float]$h)
  $g.DrawRectangle($pen,[float]$bx,[float]($pBot-$h),[float]$bw,[float]$h)
  Txt $g ('{0:N1}' -f $b[2]) ($bx-40) ($pBot-$h-54) ($bw+80) 44 38 $true 'center' 'center'
  Txt $g $b[1] ($b[0]-260) ($pBot+8) 520 44 38 $false 'center' 'center'
}
Txt $g '注：S3 主协议 0.0% 是 system prompt 与训练不一致所致；' 110 1424 1550 42 38 $false 'left' 'center'
Txt $g '换训练同款 SYSTEM_PROMPT 后为 56.9%，属诊断性证据。' 110 1466 1550 42 38 $false 'left' 'center'

$g.Dispose()
Save-Fig $bmp (Join-Path $PSScriptRoot 'fig5_8_external_validation.png') (Join-Path $PSScriptRoot 'fig5_8_external_validation_preview15cm.png') 567
$bmp.Dispose()
$brushWhite.Dispose(); $brushGray.Dispose(); $brushHatch.Dispose()
Write-Output '字号: 面板标题 42px=10.08pt, 数值/类别/注 38px=9.12pt'
