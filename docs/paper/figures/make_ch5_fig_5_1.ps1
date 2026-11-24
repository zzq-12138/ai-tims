# 图 5-1 三步链式抽取流程（方法示意，无实验数值）
# 依据：docs/paper/创新点.md §X.2「三步链式」；docs/paper/问题二/链式抽取/链式抽取评测.md 「方法/口径说明」
. (Join-Path $PSScriptRoot 'ch5_common.ps1')

$W=1772; $H=1400
$bmp,$g=New-FigCanvas $W $H
$pen=MkPen 3.2 $false
$penDash=MkPen 2.4 $true

# 入口
RBox $g 80 46 1612 116 14 $script:White $pen
BoxContent $g 80 46 1612 116 '工单关闭事件' @('工单正文 + 工单元数据（设备型号 / 故障码）') 44 40
ArrowDown $g 886 162 218 $pen 22

# 三步
$cols=@(
  @(80,'第 1 步　现象定位',@('输出：现象','证据：原文截取','只写原文，不推断')),
  @(637,'第 2 步　根因与验证',@('输出：根因 / 验证方式','反向项：排除假设','　　　有无最终结论','排除项不得进根因','维修动作不得当验证')),
  @(1194,'第 3 步　措施与条件',@('输出：措施条目','条件：型号·工艺段','材料或批次','参数区间·前置状态','元数据只喂第 3 步'))
)
foreach($c in $cols){
  RBox $g $c[0] 218 497 430 16 $script:White $pen
  BoxContent $g $c[0] 218 497 430 $c[1] $c[2] 44 38
}
# 步间箭头
ArrowRight $g 577 433 637 433 $pen 22
ArrowRight $g 1134 433 1194 433 $pen 22

# 链路说明
Txt $g '每步单独输出 JSON，上一步结果作为下一步输入；单步失败即停，不跳步补写。' 80 676 1612 52 40 $false 'center' 'center'

# 校验门
RBox $g 80 744 1612 196 16 $script:Gray6 $pen
BoxContent $g 80 744 1612 196 '逐步校验门（每步之后执行）' @('① JSON + schema 校验　② 证据原文回溯　③ 反向项规则','未过即停；证据不足时留空并标注「证据不足」，作为合法输出') 44 40
ArrowDown $g 886 940 996 $pen 22

# 输出
RBox $g 80 996 1612 150 16 $script:White $pen
BoxContent $g 80 996 1612 150 '五元组知识（带证据指针与 trace）' @('现象 / 根因 / 措施 / 验证 / 适用条件　—— 每条结论可逐条回指原文') 44 40

# 与一次性抽取的区别
RBox $g 80 1196 1612 154 16 $script:White $penDash
BoxContent $g 80 1196 1612 154 '与「一次性填满槽位」的区别' @('每步只回答一个问题；前一步结论不参与下一步的证据判定，避免根因抢注意力、维修动作污染验证。') 40 38

$g.Dispose()
Save-Fig $bmp (Join-Path $PSScriptRoot 'fig5_1_chain_extract.png') (Join-Path $PSScriptRoot 'fig5_1_chain_extract_preview15cm.png') 567
$bmp.Dispose()
Write-Output ('字号: 标题 44px=10.56pt, 正文 40px=9.60pt, 注释 38px=9.12pt')
