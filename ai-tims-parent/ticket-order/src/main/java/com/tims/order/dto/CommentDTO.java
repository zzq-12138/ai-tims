package com.tims.order.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;

/** 处理意见/沟通入参（§6.3 #15） */
public class CommentDTO {

    @NotBlank(message = "内容不能为空")
    @Size(max = 1024, message = "内容最长 1024 字")
    private String content;

    /** USER/AI_ASSISTANT，默认 USER */
    private String source = "USER";

    public String getContent() { return content; }
    public void setContent(String content) { this.content = content; }
    public String getSource() { return source; }
    public void setSource(String source) { this.source = source; }
}
