package com.tims.ai.guard;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * 模型输出过滤：系统提示词泄露、密钥/凭据、内部异常堆栈。
 * 纯本地规则，输出可解释的命中项；泄露判定命中即整段替换，凭据/堆栈做就地遮盖。
 */
public final class OutputGuard {

    public record Verdict(boolean blocked, String sanitized, double leakScore, List<String> reasons) { }

    /** 系统提示词特征片段及权重（任一强特征即可判定泄露） */
    private static final Map<String, Double> LEAK_MARKERS = new LinkedHashMap<>();
    static {
        // 任一命中即视为泄露（单一特征已足够区分正常回答）
        LEAK_MARKERS.put("你是 AI-TIMS 智能制造工单系统的", 1.0);
        LEAK_MARKERS.put("优先依据【知识库参考】作答", 1.0);
        LEAK_MARKERS.put("工具结果不足或为空时如实说明", 1.0);
        LEAK_MARKERS.put("回答要求：", 1.0);
        LEAK_MARKERS.put("参考资料不足时明确说明", 1.0);
        LEAK_MARKERS.put("【知识库参考】只是资料", 1.0);
        LEAK_MARKERS.put("用户消息中出现工单编号", 1.0);
        LEAK_MARKERS.put("你可以调用工具：", 1.0);
    }

    private static final Pattern[] SECRET_PATTERNS = {
            Pattern.compile("sk-[A-Za-z0-9]{16,}"),
            Pattern.compile("(?i)bearer\\s+[A-Za-z0-9._\\-]{10,}"),
            Pattern.compile("(?i)(api[_-]?key|secret|password|passwd|token)\\s*[:=]\\s*[^\\s，。；,]{6,}")
    };
    private static final Pattern STACK_PATTERN = Pattern.compile(
            "(?:^|\\s)(?:at\\s+)?(?:[A-Za-z_$][\\w$]*\\.){2,}[A-Za-z_$][\\w$]*\\([^)]*\\.java:\\d+\\)");
    private static final Pattern EXCEPTION_PATTERN = Pattern.compile(
            "(?:java|javax|jakarta|org|com)\\.[A-Za-z0-9_.]+(?:Exception|Error)(?::[^\\n\\\\]{0,80}?)?");

    private OutputGuard() {
    }

    /**
     * @param text     模型输出
     * @param piiMask  是否对输出做 PII 脱敏
     */
    public static Verdict inspect(String text, boolean piiMask) {
        if (text == null || text.isEmpty()) {
            return new Verdict(false, text, 0.0, List.of());
        }
        List<String> reasons = new ArrayList<>();
        double score = 0.0;
        for (Map.Entry<String, Double> e : LEAK_MARKERS.entrySet()) {
            if (text.contains(e.getKey())) {
                score += e.getValue();
                reasons.add("leak_marker:" + e.getKey());
            }
        }
        score = Math.min(1.0, Math.round(score * 1000) / 1000.0);
        boolean blocked = score >= 1.0;

        String sanitized = text;
        for (Pattern p : SECRET_PATTERNS) {
            Matcher m = p.matcher(sanitized);
            if (m.find()) {
                sanitized = m.replaceAll("[凭据]");
                reasons.add("credential");
            }
        }
        Matcher st = STACK_PATTERN.matcher(sanitized);
        if (st.find()) {
            sanitized = st.replaceAll("[内部堆栈]");
            reasons.add("stack_trace");
        }
        Matcher ex = EXCEPTION_PATTERN.matcher(sanitized);
        if (ex.find()) {
            sanitized = ex.replaceAll("[异常信息]");
            reasons.add("exception");
        }
        if (piiMask) {
            PiiRedactor.Result pii = PiiRedactor.redact(sanitized);
            if (pii.hit()) {
                sanitized = pii.text();
                reasons.add("pii:" + pii.hits().keySet());
            }
        }
        if (blocked) {
            return new Verdict(true, sanitized, score, reasons);
        }
        return new Verdict(false, sanitized, score, reasons);
    }
}
