package com.tims.order.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;

/** 挂起/终止入参（需填原因） */
public class ReasonDTO {

    @NotBlank(message = "原因不能为空")
    @Size(max = 512, message = "原因最长 512 字")
    private String reason;

    public String getReason() { return reason; }
    public void setReason(String reason) { this.reason = reason; }
}
