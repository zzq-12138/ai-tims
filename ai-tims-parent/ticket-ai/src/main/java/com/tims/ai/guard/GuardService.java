package com.tims.ai.guard;

import com.tims.ai.dto.ChatRequest;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;

import java.util.ArrayList;
import java.util.List;

/**
 * AI 护栏统一入口：入站注入检测 + 入站 PII 脱敏 + 出站过滤/脱敏。
 * 所有能力受 tims.ai.guard.* 开关控制，默认全关，接口契约不变。
 */
@Service
public class GuardService {

    private static final Logger log = LoggerFactory.getLogger(GuardService.class);

    private final GuardProperties props;

    public GuardService(GuardProperties props) {
        this.props = props;
    }

    public boolean enabled() {
        return props.isEnabled();
    }

    public GuardProperties props() {
        return props;
    }

    /** 入站判定结果 */
    public record Decision(boolean blocked, double score, List<String> reasons, String sanitizedText) {
        public static Decision pass(String text) {
            return new Decision(false, 0.0, List.of(), text);
        }
    }

    /** 出站过滤结果 */
    public record Filtered(boolean blocked, String text, List<String> reasons) { }

    /**
     * 入站检测：多段文本合并判定（问题 + 历史 + 工单描述），
     * 任一段命中即拦截；未拦截时按需做 PII 脱敏后返回可送模型文本。
     */
    public Decision inspectInput(String... texts) {
        if (!enabled() || texts == null || texts.length == 0) {
            return Decision.pass(join(texts));
        }
        String joined = join(texts);
        double maxScore = 0.0;
        List<String> reasons = new ArrayList<>();
        if (props.isInjectionEnabled()) {
            InjectionDetector.Verdict v = InjectionDetector.detect(joined, props.getInjectionThreshold());
            maxScore = v.score();
            reasons.addAll(v.hits());
            if (v.blocked()) {
                log.warn("[guard] 输入拦截 score={} rules={} snippets={}", v.score(), v.hits(), v.snippets());
                return new Decision(true, maxScore, reasons, joined);
            }
        }
        String out = joined;
        if (props.isMaskInput()) {
            PiiRedactor.Result r = PiiRedactor.redact(joined);
            if (r.hit()) {
                out = r.text();
                reasons.add("pii_masked:" + r.hits().keySet());
            }
        }
        return new Decision(false, maxScore, reasons, out);
    }

    /** 入站脱敏后的 ChatRequest 副本（不修改调用方对象） */
    public ChatRequest maskRequest(ChatRequest req) {
        if (!enabled() || !props.isMaskInput()) {
            return req;
        }
        ChatRequest copy = new ChatRequest();
        copy.setQuestion(mask(req.getQuestion()));
        copy.setTicketId(req.getTicketId());
        copy.setTopK(req.getTopK());
        if (req.getHistory() != null) {
            List<ChatRequest.HistoryMsg> hs = new ArrayList<>();
            for (ChatRequest.HistoryMsg h : req.getHistory()) {
                ChatRequest.HistoryMsg nh = new ChatRequest.HistoryMsg();
                nh.setRole(h.getRole());
                nh.setContent(mask(h.getContent()));
                hs.add(nh);
            }
            copy.setHistory(hs);
        }
        return copy;
    }

    /** 文本 PII 脱敏（工具出参送模型前使用） */
    public String mask(String text) {
        if (!enabled() || !props.isMaskInput() || !StringUtils.hasText(text)) {
            return text;
        }
        PiiRedactor.Result r = PiiRedactor.redact(text);
        return r.hit() ? r.text() : text;
    }

    /** 工具出参脱敏（独立开关，默认跟随 maskToolOutput） */
    public String maskToolOutput(String text) {
        if (!enabled() || !props.isMaskToolOutput() || !StringUtils.hasText(text)) {
            return text;
        }
        PiiRedactor.Result r = PiiRedactor.redact(text);
        return r.hit() ? r.text() : text;
    }

    /** 出站过滤：提示词泄露整段替换；凭据/堆栈/ PII 就地遮盖 */
    public Filtered filterOutput(String text) {
        if (!enabled() || !props.isOutputEnabled()) {
            return new Filtered(false, text, List.of());
        }
        OutputGuard.Verdict v = OutputGuard.inspect(text, props.isMaskOutput());
        if (v.blocked()) {
            log.warn("[guard] 输出拦截 score={} reasons={}", v.leakScore(), v.reasons());
            return new Filtered(true, props.getBlockReply(), v.reasons());
        }
        return new Filtered(false, v.sanitized(), v.reasons());
    }

    /** 流式过滤：按句缓冲，逐句脱敏/过滤后再下发，避免 PII 跨 chunk 漏网 */
    public StreamFilter newStreamFilter() {
        return new StreamFilter(this);
    }

    /** 流式过滤器 */
    public static final class StreamFilter {

        private final GuardService guard;
        private final StringBuilder buf = new StringBuilder();
        private boolean blocked = false;

        StreamFilter(GuardService guard) {
            this.guard = guard;
        }

        public boolean blocked() {
            return blocked;
        }

        public String blockReply() {
            return guard.props().getBlockReply();
        }

        /** 喂入一个增量，返回可立即下发的文本（可能为空字符串） */
        public String accept(String delta) {
            if (delta != null) {
                buf.append(delta);
            }
            int flushLen = safeFlushLength(false);
            if (flushLen <= 0) {
                return "";
            }
            return flush(flushLen);
        }

        /** 结束时冲刷剩余内容 */
        public String finish() {
            return buf.isEmpty() ? "" : flush(buf.length());
        }

        private String flush(int len) {
            String chunk = buf.substring(0, len);
            buf.delete(0, len);
            if (blocked) {
                return "";
            }
            Filtered f = guard.filterOutput(chunk);
            if (f.blocked()) {
                blocked = true;
                return guard.props().getBlockReply();
            }
            return f.text();
        }

        /**
         * 计算可安全冲刷的位置：优先句末标点/换行；没有句末标点时，
         * 超过缓冲上限则保留末尾 24 字符（避免把手机号/身份证从中间截断）。
         */
        private int safeFlushLength(boolean all) {
            if (all) {
                return buf.length();
            }
            int last = -1;
            for (int i = buf.length() - 1; i >= 0; i--) {
                char c = buf.charAt(i);
                if (c == '。' || c == '！' || c == '？' || c == '\n' || c == '；' || c == ';' || c == '.' || c == '!' || c == '?') {
                    last = i + 1;
                    break;
                }
            }
            if (last > 0) {
                return last;
            }
            int max = Math.max(64, guard.props().getStreamBufferChars());
            if (buf.length() > max) {
                return Math.max(0, buf.length() - 24);
            }
            return 0;
        }
    }

    private static String join(String... texts) {
        if (texts == null) {
            return "";
        }
        StringBuilder sb = new StringBuilder();
        for (String t : texts) {
            if (StringUtils.hasText(t)) {
                if (!sb.isEmpty()) {
                    sb.append('\n');
                }
                sb.append(t);
            }
        }
        return sb.toString();
    }
}
