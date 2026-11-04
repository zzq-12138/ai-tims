package com.tims.ai.config;

import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.stereotype.Component;

/**
 * M5 AI 配置。切换模型只改环境变量 LLM_CHAT_MODEL（跑批/消融 glm-4-flash，演示 glm-5.3-flash），代码零改动。
 * M6 新增 extractModel：工单关闭后的知识抽取固定走 glm-4-flash 档，独立可配（LLM_EXTRACT_MODEL）。
 */
@Component
@ConfigurationProperties(prefix = "tims.ai")
public class AiProperties {

    /** 智谱 OpenAI 兼容端点根地址 */
    private String baseUrl = "https://open.bigmodel.cn/api/paas/v4";

    /** 兼容端点路径（智谱无 /v1 前缀） */
    private String completionsPath = "/chat/completions";

    /** 模型名（唯一切换点） */
    private String model = "glm-4-flash";

    /** 知识抽取专用模型（M6，默认 glm-4-flash 省配额；可配 LLM_EXTRACT_MODEL） */
    private String extractModel = "glm-4-flash";

    /** 知识抽取输出上限（结构化 JSON 足够） */
    private int extractMaxTokens = 4096;

    /** 直接注入的密钥（优先级高于文件） */
    private String apiKey;

    /** 密钥文件路径（默认 ~/secrets/zhipu_api_key，严禁入 Git） */
    private String apiKeyFile = "/home/dev/secrets/zhipu_api_key";

    /** 推理模型 reasoning 先耗 token，输出上限必须足够大 */
    private int maxTokens = 8192;

    private double temperature = 0.3;

    /** 读取超时（流式/同步统一），任务书要求 60-120s */
    private long readTimeoutMs = 120_000;

    private int connectTimeoutMs = 5_000;

    /** 知识库服务（lb:// 服务名寻址） */
    private String kbBaseUrl = "http://ticket-knowledge";

    /** 工单服务（lb:// 服务名寻址） */
    private String orderBaseUrl = "http://ticket-order";

    /** RAG 默认 TopK */
    private int topK = 5;

    /** 单条知识注入 LLM 的最大字符数，防止 prompt 膨胀 */
    private int snippetChars = 500;

    public String getBaseUrl() { return baseUrl; }
    public void setBaseUrl(String baseUrl) { this.baseUrl = baseUrl; }
    public String getCompletionsPath() { return completionsPath; }
    public void setCompletionsPath(String completionsPath) { this.completionsPath = completionsPath; }
    public String getModel() { return model; }
    public void setModel(String model) { this.model = model; }
    public String getExtractModel() { return extractModel; }
    public void setExtractModel(String extractModel) { this.extractModel = extractModel; }
    public int getExtractMaxTokens() { return extractMaxTokens; }
    public void setExtractMaxTokens(int extractMaxTokens) { this.extractMaxTokens = extractMaxTokens; }
    public String getApiKey() { return apiKey; }
    public void setApiKey(String apiKey) { this.apiKey = apiKey; }
    public String getApiKeyFile() { return apiKeyFile; }
    public void setApiKeyFile(String apiKeyFile) { this.apiKeyFile = apiKeyFile; }
    public int getMaxTokens() { return maxTokens; }
    public void setMaxTokens(int maxTokens) { this.maxTokens = maxTokens; }
    public double getTemperature() { return temperature; }
    public void setTemperature(double temperature) { this.temperature = temperature; }
    public long getReadTimeoutMs() { return readTimeoutMs; }
    public void setReadTimeoutMs(long readTimeoutMs) { this.readTimeoutMs = readTimeoutMs; }
    public int getConnectTimeoutMs() { return connectTimeoutMs; }
    public void setConnectTimeoutMs(int connectTimeoutMs) { this.connectTimeoutMs = connectTimeoutMs; }
    public String getKbBaseUrl() { return kbBaseUrl; }
    public void setKbBaseUrl(String kbBaseUrl) { this.kbBaseUrl = kbBaseUrl; }
    public String getOrderBaseUrl() { return orderBaseUrl; }
    public void setOrderBaseUrl(String orderBaseUrl) { this.orderBaseUrl = orderBaseUrl; }
    public int getTopK() { return topK; }
    public void setTopK(int topK) { this.topK = topK; }
    public int getSnippetChars() { return snippetChars; }
    public void setSnippetChars(int snippetChars) { this.snippetChars = snippetChars; }
}
