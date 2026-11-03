package com.tims.order.dto;

import jakarta.validation.constraints.DecimalMin;
import jakarta.validation.constraints.NotNull;

/** 模拟器批量建单入参（M2 批二新增，任务书 #18 之外的演示/压测辅助接口） */
public class MockBatchDTO {

    /** 批量条数，默认 200 */
    @NotNull(message = "count 不能为空")
    @DecimalMin(value = "1", message = "count 至少为 1")
    private Integer count = 200;

    /** 厂区，默认 F1 */
    private String factory = "F1";

    public Integer getCount() { return count; }
    public void setCount(Integer count) { this.count = count; }
    public String getFactory() { return factory; }
    public void setFactory(String factory) { this.factory = factory; }
}
