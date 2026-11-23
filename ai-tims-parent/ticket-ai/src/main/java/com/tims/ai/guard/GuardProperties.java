package com.tims.ai.guard;

import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.stereotype.Component;

/**
 * AI 护栏配置。总开关默认关闭，保证上线前行为与现有接口完全一致。
 * 打开后按子开关分别控制：注入检测 / 入站脱敏 / 出站过滤 / 出站脱敏。
 */
@Component
@ConfigurationProperties(prefix = "tims.ai.guard")
public class GuardProperties {

    /** 总开关（默认关闭，保持现状） */
    private boolean enabled = false;

    /** prompt 注入检测 */
    private boolean injectionEnabled = true;

    /** 判定阈值：规则加权得分 ≥ 阈值即拦截（0-1） */
    private double injectionThreshold = 0.5;

    /** 送 LLM 前对用户问题/历史/工单上下文做 PII 脱敏 */
    private boolean maskInput = true;

    /** 工具返回值送 LLM 前做 PII 脱敏 */
    private boolean maskToolOutput = true;

    /** 模型输出过滤（系统提示词泄露 / 凭据 / 内部堆栈） */
    private boolean outputEnabled = true;

    /** 模型输出中的 PII 脱敏 */
    private boolean maskOutput = true;

    /** 输出被拦截时的替代文案 */
    private String blockReply = "抱歉，该回答涉及内部信息或敏感数据，已被安全护栏拦截。";

    /** 流式输出按句缓冲的最大字符数（超过则强制冲刷） */
    private int streamBufferChars = 240;

    public boolean isEnabled() { return enabled; }
    public void setEnabled(boolean enabled) { this.enabled = enabled; }
    public boolean isInjectionEnabled() { return injectionEnabled; }
    public void setInjectionEnabled(boolean injectionEnabled) { this.injectionEnabled = injectionEnabled; }
    public double getInjectionThreshold() { return injectionThreshold; }
    public void setInjectionThreshold(double injectionThreshold) { this.injectionThreshold = injectionThreshold; }
    public boolean isMaskInput() { return maskInput; }
    public void setMaskInput(boolean maskInput) { this.maskInput = maskInput; }
    public boolean isMaskToolOutput() { return maskToolOutput; }
    public void setMaskToolOutput(boolean maskToolOutput) { this.maskToolOutput = maskToolOutput; }
    public boolean isOutputEnabled() { return outputEnabled; }
    public void setOutputEnabled(boolean outputEnabled) { this.outputEnabled = outputEnabled; }
    public boolean isMaskOutput() { return maskOutput; }
    public void setMaskOutput(boolean maskOutput) { this.maskOutput = maskOutput; }
    public String getBlockReply() { return blockReply; }
    public void setBlockReply(String blockReply) { this.blockReply = blockReply; }
    public int getStreamBufferChars() { return streamBufferChars; }
    public void setStreamBufferChars(int streamBufferChars) { this.streamBufferChars = streamBufferChars; }
}
