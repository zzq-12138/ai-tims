package com.tims.order.dto;

import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Size;

/** 转派入参（§6.3 #8） */
public class AssignDTO {

    @NotNull(message = "目标处理人不能为空")
    private Long targetUserId;

    @Size(max = 512, message = "转派意见最长 512 字")
    private String comment;

    public Long getTargetUserId() { return targetUserId; }
    public void setTargetUserId(Long targetUserId) { this.targetUserId = targetUserId; }
    public String getComment() { return comment; }
    public void setComment(String comment) { this.comment = comment; }
}
