# 图 5-3 去重与冲突判别流程（方法示意，无实验数值）
# 依据：docs/paper/研究方向/标注手册_v1.md §5.1 判定表；docs/paper/问题二/关系判别/关系判别评测.md §方法
. (Join-Path $PSScriptRoot 'ch5_common.ps1')

$W=1772; $H=1350
$bmp,$g=New-FigCanvas $W $H
$pen=MkPen 3.2 $false
$penDash=MkPen 2.4 $true

RBox $g 80 44 1612 112 14 $script:White $pen
BoxContent $g 80 44 1612 112 '两条候选知识' @('现象 / 根因 / 措施 / 验证 / 适用条件') 44 40

$xs=@(80,492,904,1316); $bw=376
$heads=@('相似度召回','结构化规则','条件互斥判定','LLM 复核')
$bodies=@(
  @('BGE-M3 余弦','只作召回特征','不作关系标签'),
  @('现象 / 根因同异','措施重叠度','条件状态：','重叠/互斥/未知'),
  @('同类型条件值不同','即判 variant','条件重叠或缺失','允许 conflict','规则冲突时收口'),
  @('仅条件未知或灰区','glm-4-flash 复核','条件明确以规则为准')
)
for($i=0;$i -lt 4;$i++){
  RBox $g $xs[$i] 216 $bw 330 16 $script:White $pen
  BoxContent $g $xs[$i] 216 $bw 330 $heads[$i] $bodies[$i] 44 38
  if($i -lt 3){ ArrowRight $g ($xs[$i]+$bw+2) 381 ($xs[$i+1]-2) 381 $pen 20 }
}

Txt $g '条件明确时由结构化规则直接定；条件未知或规则落入灰区时才交 LLM 复核。' 80 570 1612 50 40 $false 'center' 'center'
ArrowDown $g 886 624 682 $pen 20

# 四类关系与入库动作
$heads2=@('duplicate','conflict','variant','unrelated')
$bodies2=@(
  @('同设备、同现象','同根因、条件等价','措施重叠','→ 合并（人工确认）'),
  @('同设备、同现象','根因互斥','条件重叠','→ 冲突队列','保留双方来源'),
  @('同现象族','条件互斥','或措施/粒度不同','→ 建 variant 边'),
  @('不同设备 / 现象','不同工序','且无共享根因','→ 不建关系')
)
for($i=0;$i -lt 4;$i++){
  RBox $g $xs[$i] 690 $bw 356 16 $script:White $pen
  BoxContent $g $xs[$i] 690 $bw 356 $heads2[$i] $bodies2[$i] 44 38
}

RBox $g 80 1090 1612 196 16 $script:White $penDash
BoxContent $g 80 1090 1612 196 '判定顺序（先满足先定）' @('duplicate → conflict → variant → 其余 unrelated','不允许用余弦分数直接当关系标签；条件字段缺失时，纯余弦在反构造集上更稳（图 5-4）。') 42 38

$g.Dispose()
Save-Fig $bmp (Join-Path $PSScriptRoot 'fig5_3_relation_flow.png') (Join-Path $PSScriptRoot 'fig5_3_relation_flow_preview15cm.png') 567
$bmp.Dispose()
Write-Output '字号: 标题 44px=10.56pt, 正文 38px=9.12pt'
