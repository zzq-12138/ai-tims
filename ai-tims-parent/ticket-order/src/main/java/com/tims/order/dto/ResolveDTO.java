package com.tims.order.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;

/** 提交解决入参（§6.3 #9，解决说明必填=知识提炼核心输入） */
public class ResolveDTO {

    @NotBlank(message = "解决说明不能为空")
    @Size(max = 2000, message = "解决说明最长 2000 字")
    private String resolveNote;

    public String getResolveNote() { return resolveNote; }
    public void setResolveNote(String resolveNote) { this.resolveNote = resolveNote; }
}
