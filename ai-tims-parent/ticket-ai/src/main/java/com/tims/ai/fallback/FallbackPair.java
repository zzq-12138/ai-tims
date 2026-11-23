package com.tims.ai.fallback;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;

import java.math.BigDecimal;
import java.time.LocalDateTime;

/**
 * C 档兜底建议 × 实际处置 配对记录（仅记录，不自动入库、不回流）。
 * DDL 见 docs/sql/20261111_ai_fallback_pair.sql。
 */
@TableName("ai_fallback_pair")
public class FallbackPair {

    @TableId(type = IdType.ASSIGN_ID)
    private Long id;

    private Long tenantId;

    private Long ticketId;

    private String ticketNo;

    /** 触发档位，目前固定 C */
    private String tier;

    /** 模型自由建议原文（不含“仅供参考”前缀） */
    private String suggestionText;

    private String model;

    private String promptVersion;

    /** 是否无知识库依据：1 是，0 否 */
    private Integer noKbBasis;

    private LocalDateTime suggestTime;

    private String actualDisposition;

    /** 回填人（登录用户 ID） */
    private Long dispositionBy;

    private LocalDateTime dispositionTime;

    /** 1 一致，0 不一致，null 未回填/无法判定 */
    private Integer consistent;

    /** 字符二元组 Dice 相似度 0-1（旧口径，保留对照） */
    private BigDecimal consistencyScore;

    /** 处置侧覆盖率 0-1：命中片段数 / 处置片段总数（新口径） */
    private BigDecimal coverageScore;

    private Integer coverageHits;

    private Integer coverageSegments;

    /** 逐段明细 JSON：片段、是否命中、覆盖度、命中的建议句子 */
    private String coverageDetail;

    /** 新口径判定：CONSISTENT / INCONSISTENT / INSUFFICIENT（片段不足） */
    private String coverageVerdict;

    /** 是否测试数据：0 真实，1 复测噪音，2 合成样本 */
    private Integer isTest;

    /** 数据来源：real / synthetic */
    private String dataSource;

    /** 合成样本类别：1 实质一致，2 部分一致，3 同设备另一方案，4 答非所问 */
    private Integer syntheticClass;

    /** 合成样本归类理由（人工可读） */
    private String classNote;

    public Long getId() { return id; }
    public void setId(Long id) { this.id = id; }
    public Long getTenantId() { return tenantId; }
    public void setTenantId(Long tenantId) { this.tenantId = tenantId; }
    public Long getTicketId() { return ticketId; }
    public void setTicketId(Long ticketId) { this.ticketId = ticketId; }
    public String getTicketNo() { return ticketNo; }
    public void setTicketNo(String ticketNo) { this.ticketNo = ticketNo; }
    public String getTier() { return tier; }
    public void setTier(String tier) { this.tier = tier; }
    public String getSuggestionText() { return suggestionText; }
    public void setSuggestionText(String suggestionText) { this.suggestionText = suggestionText; }
    public String getModel() { return model; }
    public void setModel(String model) { this.model = model; }
    public String getPromptVersion() { return promptVersion; }
    public void setPromptVersion(String promptVersion) { this.promptVersion = promptVersion; }
    public Integer getNoKbBasis() { return noKbBasis; }
    public void setNoKbBasis(Integer noKbBasis) { this.noKbBasis = noKbBasis; }
    public LocalDateTime getSuggestTime() { return suggestTime; }
    public void setSuggestTime(LocalDateTime suggestTime) { this.suggestTime = suggestTime; }
    public String getActualDisposition() { return actualDisposition; }
    public void setActualDisposition(String actualDisposition) { this.actualDisposition = actualDisposition; }
    public Long getDispositionBy() { return dispositionBy; }
    public void setDispositionBy(Long dispositionBy) { this.dispositionBy = dispositionBy; }
    public LocalDateTime getDispositionTime() { return dispositionTime; }
    public void setDispositionTime(LocalDateTime dispositionTime) { this.dispositionTime = dispositionTime; }
    public Integer getConsistent() { return consistent; }
    public void setConsistent(Integer consistent) { this.consistent = consistent; }
    public BigDecimal getConsistencyScore() { return consistencyScore; }
    public void setConsistencyScore(BigDecimal consistencyScore) { this.consistencyScore = consistencyScore; }
    public BigDecimal getCoverageScore() { return coverageScore; }
    public void setCoverageScore(BigDecimal coverageScore) { this.coverageScore = coverageScore; }
    public Integer getCoverageHits() { return coverageHits; }
    public void setCoverageHits(Integer coverageHits) { this.coverageHits = coverageHits; }
    public Integer getCoverageSegments() { return coverageSegments; }
    public void setCoverageSegments(Integer coverageSegments) { this.coverageSegments = coverageSegments; }
    public String getCoverageDetail() { return coverageDetail; }
    public void setCoverageDetail(String coverageDetail) { this.coverageDetail = coverageDetail; }
    public String getCoverageVerdict() { return coverageVerdict; }
    public void setCoverageVerdict(String coverageVerdict) { this.coverageVerdict = coverageVerdict; }
    public Integer getIsTest() { return isTest; }
    public void setIsTest(Integer isTest) { this.isTest = isTest; }
    public String getDataSource() { return dataSource; }
    public void setDataSource(String dataSource) { this.dataSource = dataSource; }
    public Integer getSyntheticClass() { return syntheticClass; }
    public void setSyntheticClass(Integer syntheticClass) { this.syntheticClass = syntheticClass; }
    public String getClassNote() { return classNote; }
    public void setClassNote(String classNote) { this.classNote = classNote; }
}
