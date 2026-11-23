package com.tims.ai.route;

import java.util.ArrayList;
import java.util.List;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * 可解释的模型路由器：只依据表面信号做加权打分，不调用任何模型、不做黑盒推断。
 * <p>
 * 分数 = 各命中信号权重之和，裁剪到 [0,1]；{@code score >= threshold} 判为复杂，走大模型，否则走小模型。
 * 命中信号随决策一起返回，便于在响应 meta、日志和论文里逐条解释“为什么走这个模型”。
 * <p>
 * 纯本地类（无 Spring 依赖），离线评测脚本可直接编译生产代码复现路由结果。
 */
public class ModelRouter {

    /** A1 计算题判定规则版本；规则一旦冻结，留出集评测不得回改 */
    public static final String CALC_RULE_VERSION = "A1-v1";

    /** 单个命中信号：名称、对该次决策的权重贡献、可读说明 */
    public record Signal(String name, double weight, String detail) { }

    /** 路由输入：只看问题文本、历史轮次、是否需要工具、知识命中条数 */
    public record Input(String question, int historyTurns, boolean needsTool, int knowledgeHits) { }

    /** 路由决策：simple=true 走小模型 */
    public record Decision(boolean simple, String model, double score, List<Signal> signals) {
        public String reason() {
            if (signals.isEmpty()) {
                return "无信号命中，按默认档位";
            }
            StringBuilder sb = new StringBuilder();
            for (Signal s : signals) {
                if (sb.length() > 0) {
                    sb.append("；");
                }
                sb.append(s.name()).append(s.weight() > 0 ? "+" : "").append(s.weight())
                        .append('(').append(s.detail()).append(')');
            }
            return sb.toString();
        }
    }

    private static final Pattern MULTI_HOP = Pattern.compile(
            "并且|以及|同时|分别|对比|比较|然后|接着|再查|如果|那么|；|;");
    private static final Pattern REASONING = Pattern.compile(
            "为什么|原因|根因|分析|判断|影响|风险|方案|步骤|顺序|取舍|区别|如何|怎么解决"
                    + "|建议|评估|会不会|优先级|排查|定位|推理|推算|预算|估算");
    private static final Pattern SIMPLE_FACT = Pattern.compile(
            "是多少|是什么|标准值|规格|参数是|多久|在哪|状态|多少|几个|是否|能不能|有没有|叫什么");
    private static final Pattern QUESTION_MARK = Pattern.compile("[?？]");

    // ---- A1-v1：可复算多步计算的冻结判定（只认这 5 类题面结构）----
    private static final Pattern INIT_NUM = Pattern.compile("初始[^\\d]{0,8}-?\\d+(?:\\.\\d+)?");
    private static final Pattern CUR_NUM = Pattern.compile("现测\\s*-?\\d+(?:\\.\\d+)?");
    private static final Pattern LIMIT_UPPER = Pattern.compile("要求不超过\\s*-?\\d+(?:\\.\\d+)?");
    private static final Pattern LIMIT_RANGE = Pattern.compile(
            "要求\\s*-?\\d+(?:\\.\\d+)?\\s*-\\s*-?\\d+(?:\\.\\d+)?");
    private static final Pattern VALUE_LIST = Pattern.compile("）：\\s*-?\\d");
    private static final Pattern AVG_OVER = Pattern.compile("超过上限[^。？?]{0,6}几次");
    private static final Pattern MS_OVER = Pattern.compile("超出上限[^。？?]{0,6}几次");

    private final double threshold;
    private final String simpleModel;
    private final String complexModel;
    private final int longChars;
    private final int veryLongChars;

    public ModelRouter(double threshold, String simpleModel, String complexModel) {
        this(threshold, simpleModel, complexModel, 60, 120);
    }

    public ModelRouter(double threshold, String simpleModel, String complexModel,
                       int longChars, int veryLongChars) {
        this.threshold = threshold;
        this.simpleModel = simpleModel;
        this.complexModel = complexModel;
        this.longChars = longChars;
        this.veryLongChars = veryLongChars;
    }

    public Decision route(Input in) {
        String q = in.question() == null ? "" : in.question().trim();
        int len = q.length();
        List<Signal> signals = new ArrayList<>();
        double score = 0.0;

        // 1. 长度：长问题常含多个子任务
        if (len >= veryLongChars) {
            score += 0.30;
            signals.add(new Signal("long_query", 0.30, len + "字"));
        } else if (len >= longChars) {
            score += 0.18;
            signals.add(new Signal("long_query", 0.18, len + "字"));
        }

        // 2. 多跳：连接词出现次数
        int hops = count(MULTI_HOP, q);
        if (hops >= 2) {
            score += 0.35;
            signals.add(new Signal("multi_hop", 0.35, hops + "处连接词"));
        } else if (hops == 1) {
            score += 0.22;
            signals.add(new Signal("multi_hop", 0.22, "1处连接词"));
        }

        // 3. 推理意图：原因/方案/顺序等
        int reasons = count(REASONING, q);
        Matcher rm = REASONING.matcher(q);
        String firstReason = rm.find() ? rm.group() : "";
        if (reasons >= 2) {
            score += 0.40;
            signals.add(new Signal("reasoning", 0.40, reasons + "处推理词:" + firstReason));
        } else if (reasons == 1) {
            score += 0.28;
            signals.add(new Signal("reasoning", 0.28, firstReason));
        }

        // 4. 多问句：一句话里问了两件事
        int marks = count(QUESTION_MARK, q);
        if (marks >= 2) {
            score += 0.12;
            signals.add(new Signal("multi_question", 0.12, marks + "个问号"));
        }

        // 5. 需要工具：现查工单/设备，多步调度更适合大模型
        if (in.needsTool()) {
            score += 0.18;
            signals.add(new Signal("needs_tool", 0.18, "需要调用工具"));
        }

        // 6. 历史轮次：多轮追问通常指代复杂
        if (in.historyTurns() >= 3) {
            score += 0.15;
            signals.add(new Signal("history", 0.15, in.historyTurns() + "轮历史"));
        }

        // 7. 知识命中多条：需要跨条目综合
        if (in.knowledgeHits() >= 2) {
            score += 0.10;
            signals.add(new Signal("multi_knowledge", 0.10, in.knowledgeHits() + "条知识"));
        }

        // 8. 简单事实词：压回简单档
        Matcher sm = SIMPLE_FACT.matcher(q);
        if (sm.find()) {
            score -= 0.22;
            signals.add(new Signal("simple_fact", -0.22, sm.group()));
        }

        // 9. 短且单问：典型单点事实查询
        if (len <= 25 && hops == 0 && marks <= 1) {
            score -= 0.20;
            signals.add(new Signal("short_single", -0.20, len + "字单问"));
        }

        // 10. 可复算多步计算（A1-v1）：题面自带全部数值且要求两个以上可复算答案，必须走大模型
        if (calcVerifiable(q)) {
            score += 1.0;
            signals.add(new Signal("calc_verifiable", 1.0, "题面可复算多步数值"));
        }

        double finalScore = Math.max(0.0, Math.min(1.0, round2(score)));
        boolean simple = finalScore < threshold;
        return new Decision(simple, simple ? simpleModel : complexModel, finalScore, signals);
    }

    /**
     * A1-v1 冻结规则：题面同时满足「可复算数字」与「计数/占比语义」，且能从题面确定性地算出
     * 两个以上答案时返回 true。这类题一律走大模型（离线级联中即为“必须验证”）。
     * <p>
     * 只认 5 类结构：T1 下降百分点+占初始百分比、T2 超标次数+占比、T3 合格次数+占比、
     * T4 平均值+超限次数、T5 毫秒平均值+超限次数。单步减法（“相差多少”）不在此列。
     * <p>
     * 本方法与离线评测脚本共用同一份实现：脚本通过 {@code CalcProbeMain} 调用它，
     * 避免评测代码与线上代码各写一套判定而结论漂移。
     */
    public static boolean calcVerifiable(String question) {
        if (question == null) {
            return false;
        }
        String q = question.trim();
        boolean cue = q.contains("几次") || q.contains("占比")
                || q.contains("百分点") || q.contains("平均");
        if (!cue) {
            return false;
        }
        boolean hasList = VALUE_LIST.matcher(q).find();
        // T1：下降百分点 + 现测值是初始值的百分之几
        if (q.contains("下降了多少个百分点") && q.contains("百分之几")
                && INIT_NUM.matcher(q).find() && CUR_NUM.matcher(q).find()) {
            return true;
        }
        // T2：超标几次 + 超标占比
        if (hasList && q.contains("超标几次") && q.contains("超标占比")
                && LIMIT_UPPER.matcher(q).find()) {
            return true;
        }
        // T3：合格几次 + 合格占比
        if (hasList && q.contains("合格几次") && q.contains("合格占比")
                && LIMIT_RANGE.matcher(q).find()) {
            return true;
        }
        // T4：平均值 + 超过上限次数
        if (hasList && q.contains("平均值") && AVG_OVER.matcher(q).find()
                && LIMIT_UPPER.matcher(q).find()) {
            return true;
        }
        // T5：毫秒平均 + 超出上限次数
        if (hasList && q.contains("毫秒") && q.contains("平均")
                && MS_OVER.matcher(q).find() && LIMIT_UPPER.matcher(q).find()) {
            return true;
        }
        return false;
    }

    private static int count(Pattern p, String text) {
        Matcher m = p.matcher(text);
        int n = 0;
        while (m.find()) {
            n++;
        }
        return n;
    }

    private static double round2(double v) {
        return Math.round(v * 100.0) / 100.0;
    }
}
