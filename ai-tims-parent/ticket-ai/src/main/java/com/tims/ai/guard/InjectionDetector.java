package com.tims.ai.guard;

import java.text.Normalizer;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Prompt 注入检测（可解释规则加权分类器，纯本地、无外部依赖、可离线评测）。
 *
 * 设计取舍：不引入模型分类器，避免新增推理调用与不可解释性；用「归一化 + 规则族 + 权重求和」
 * 产出 0-1 风险分与命中明细，便于答辩时逐条解释为什么拦截。权重 0.5 以上视为强信号，
 * 默认阈值 0.5：任一强规则即拦截，两条弱规则叠加也拦截。
 */
public final class InjectionDetector {

    /** 单条规则 */
    public record Rule(String id, String family, double weight, Pattern pattern) { }

    /** 判定结果 */
    public record Verdict(boolean blocked, double score, List<String> hits, List<String> snippets) { }

    private static final List<Rule> RULES = new ArrayList<>();

    private static void rule(String id, String family, double weight, String regex) {
        RULES.add(new Rule(id, family, weight, Pattern.compile(regex, Pattern.CASE_INSENSITIVE | Pattern.UNICODE_CASE)));
    }

    static {
        // ===== 指令覆盖 =====
        rule("override_zh", "instruction_override", 0.90,
                "(忽略|无视|忘记|跳过|不要理会|不必遵守)[^。\\n]{0,12}"
                        + "(指令|指示|命令|规则|限制|要求|提示词|设定|约束|审查|instructions?|rules?|prompts?)");
        rule("override_en", "instruction_override", 0.90,
                "(ignore|disregard|forget|bypass|override)\\s+(all\\s+|any\\s+|the\\s+)*(previous|prior|above|earlier|system)?\\s*"
                        + "(instructions?|prompts?|rules?|directives?|guidelines?|指令|规则|要求)");
        rule("reset_context_zh", "instruction_override", 0.82,
                "(清空|重置|作废|删除|取消|解除)[^。\\n]{0,10}(提示词|设定|上下文|约束|限制|规则|指令)");
        rule("reset_context_rev_zh", "instruction_override", 0.82,
                "(提示词|设定|上下文|约束|限制|规则|指令)[^。\\n]{0,8}(清空|重置|作废|删除|取消|解除)");
        rule("comply_any_zh", "instruction_override", 0.80,
                "无论[^。\\n]{0,12}(之前|以前|上面)[^。\\n]{0,16}(都|必须|一律)[^。\\n]{0,10}(服从|执行|按我说)");
        // ===== 角色劫持 =====
        rule("role_hijack_zh", "role_hijack", 0.88,
                "(你现在|从现在(开始|起)|接下来你)(是|扮演|充当|作为)[^。\\n]{0,16}(不受|没有|无)[^。\\n]{0,6}(限制|约束|审查|道德)");
        rule("role_switch_zh", "role_hijack", 0.55,
                "从现在(开始|起)[，,]?\\s*(你是|你扮演|你将扮演|你将成为)");
        rule("role_assume_zh", "role_hijack", 0.80,
                "(假设|假装|认为)[^。\\n]{0,12}(你|自己)[^。\\n]{0,10}(没有|不受|无)[^。\\n]{0,6}(限制|约束|审查)");
        rule("role_play_unbounded_zh", "role_hijack", 0.80,
                "(扮演|充当)[^。\\n]{0,10}(不受|没有|无)[^。\\n]{0,4}(限制|约束|审查)");
        rule("role_set_unbounded_zh", "role_hijack", 0.80,
                "(设定|设置)成[^。\\n]{0,8}(没有|不受|无)[^。\\n]{0,4}(限制|约束|审查)");
        rule("role_cease_zh", "role_hijack", 0.80,
                "你不再是[^。\\n]{0,10}(助手|AI|模型|机器人|工单)");
        rule("role_hijack_en", "role_hijack", 0.88,
                "(you\\s+are\\s+now|from\\s+now\\s+on[,\\s]+you\\s+are|act\\s+as)\\s+(a\\s+|an\\s+)?"
                        + "(dan|developer\\s+mode|unrestricted|jailbroken|evil|without\\s+restrictions)");
        rule("role_assume_en", "role_hijack", 0.80,
                "pretend\\s+(you\\s+are|to\\s+be)[^.\\n]{0,30}(without|no)\\s+(safety|rules|restrictions|limits)");
        // ===== 系统提示词套取 =====
        rule("prompt_extract_zh", "prompt_extraction", 0.92,
                "(输出|打印|显示|告诉我|重复|复述|泄露|透露|粘贴)[^。\\n]{0,12}"
                        + "(系统提示词|系统指令|提示词|prompt|初始指令|开发者指令|设定内容|你的规则)");
        rule("prompt_extract_en", "prompt_extraction", 0.92,
                "(reveal|show|print|repeat|output|leak|tell\\s+me)[^.\\n]{0,24}"
                        + "(system\\s+prompt|initial\\s+instructions?|developer\\s+(message|prompt)|your\\s+instructions?)");
        rule("prompt_repeat_en", "prompt_extraction", 0.85,
                "(repeat|recite|echo)[^.\\n]{0,12}(everything|all)\\s+(above|before)");
        rule("prompt_meta_zh", "prompt_extraction", 0.60,
                "(系统|开发者)(提示词|指令|prompt)[^。\\n]{0,8}(是什么|内容|原文|输出|打印)");
        rule("prompt_translate_zh", "prompt_extraction", 0.72,
                "(系统提示词|系统指令|提示词|prompt)[^。\\n]{0,12}(翻译|转述|发给我|贴出来|输出|打印|复述)");
        rule("prompt_fulltext_zh", "prompt_extraction", 0.75,
                "(完整|全文|原文|逐字|原样|一字不差)[^。\\n]{0,8}(提示词|指令|设定|规则)");
        rule("prompt_repeat_zh", "prompt_extraction", 0.80,
                "(重复|复述)[^。\\n]{0,20}(上面|以上|全部|系统消息|系统指令|对话开始前)[^。\\n]{0,10}"
                        + "(内容|指令|规则|设定|消息)?");
        rule("prompt_mix", "prompt_extraction", 0.85,
                "(output|print|show|reveal|repeat)[^.\\n]{0,20}"
                        + "(系统提示词|系统\\s*prompt|提示词|prompt|initial\\s+instructions?|your\\s+instructions?)");
        rule("prompt_rule_file", "prompt_extraction", 0.70,
                "(规则文件|配置文件|设定文件)[^。\\n]{0,10}(内容|粘贴|输出|列出|给我)");
        rule("prompt_hidden", "prompt_extraction", 0.60,
                "(隐藏|内部)[^。\\n]{0,6}(规则|设定|指令)");
        // ===== 越狱 / 绕过安全 =====
        rule("jailbreak", "safety_bypass", 0.85,
                "(越狱|jailbreak|dan\\s*模式|无审查模式|无限制模式|不受任何限制|绕过(安全|内容|合规)?(审查|过滤|限制))");
        rule("bypass_zh", "safety_bypass", 0.80,
                "(不要|不必|停止)(再)?(遵守|执行)[^。\\n]{0,10}(规则|限制|约束|指令|政策)");
        rule("disable_filter_zh", "safety_bypass", 0.80,
                "(关闭|停用|禁用|不要执行|停止)[^。\\n]{0,6}(内容)?(过滤|审查|安全策略|安全规则)");
        rule("disable_filter_en", "safety_bypass", 0.78,
                "(bypass|disable|turn\\s+off|deactivate|switch\\s+off)[^.\\n]{0,16}"
                        + "(safety|content|security)\\s*(policy|filter|filters|check|checks)?");
        rule("dev_mode_zh", "safety_bypass", 0.80,
                "(进入|开启|启用|切换到)[^。\\n]{0,6}(开发者|调试|上帝|无限制|无审查)\\s*模式");
        rule("dev_mode_en", "safety_bypass", 0.80,
                "(enter|enable|turn\\s+on|activate)\\s+(developer|debug|god|unrestricted)\\s+mode");
        rule("authorized_bypass_zh", "safety_bypass", 0.75,
                "(可以|允许)[^。\\n]{0,4}(违反|绕过)[^。\\n]{0,6}(安全|规则|政策|审查)");
        // ===== 上下文/分隔符伪造（间接注入） =====
        rule("delimiter_spoof", "context_spoofing", 0.90,
                "(<\\|im_start\\|>|\\[\\s*system\\s*\\]|<\\s*system\\s*>|#{3,}\\s*(system|instruction)"
                        + "|\"role\"\\s*:\\s*\"system\"|begin\\s+system\\s+prompt)");
        rule("indirect_injection", "context_spoofing", 0.55,
                "(知识库|参考资料|文档|工单描述|检索结果)[^。\\n]{0,24}(忽略|执行以下|新的指令|system\\s*prompt|请输出)");
        // ===== 数据外泄 =====
        rule("exfil_bulk", "data_exfiltration", 0.82,
                "(输出|导出|列出|打印|给我|发我)[^。\\n]{0,16}(所有|全部|全量)[^。\\n]{0,12}"
                        + "(?<!统计)(客户|用户|员工|工单)[^。\\n]{0,10}(?<!统计)(信息|数据|手机号|身份证|地址|名单|隐私)");
        rule("exfil_sensitive_zh", "data_exfiltration", 0.82,
                "(所有|全部|全量)[^。\\n]{0,16}(客户|用户|员工|报修人|工单)[^。\\n]{0,12}"
                        + "(姓名|电话|手机号|身份证|地址|邮箱|联系方式)");
        rule("exfil_generic_zh", "data_exfiltration", 0.78,
                "(输出|导出|列出|打印|给我|发我|提供)[^。\\n]{0,10}(所有|全部|全量)[^。\\n]{0,10}"
                        + "(客户|用户|员工)[^。\\n]{0,8}(信息|数据|资料)");
        rule("exfil_ticket_zh", "data_exfiltration", 0.78,
                "(输出|导出|给我|发我|提供)[^。\\n]{0,10}(所有|全部|全量)[^。\\n]{0,10}工单[^。\\n]{0,8}"
                        + "(?<!统计)(信息|数据|隐私|资料|明细)");
        rule("exfil_en", "data_exfiltration", 0.82,
                "(dump|export|list)\\s+(all|every)\\s+");
        // ===== 伪装权限 =====
        rule("fake_authority", "authority_spoofing", 0.78,
                "(我是|作为)\\s*(系统管理员|超级管理员|开发者|root|平台管理员|审计员|管理员)[^。\\n]{0,16}"
                        + "(忽略|输出|提供|关闭|跳过|要求|命令|绕过)");
        rule("fake_authority_en", "authority_spoofing", 0.78,
                "(i\\s+am|as)\\s+(the\\s+)?(developer|admin|administrator|root|owner)[^.\\n]{0,30}"
                        + "(ignore|bypass|order|provide|disable)");
        // ===== 编码混淆 / 紧迫话术 / 多步套取 =====
        rule("encoding_obfuscation", "obfuscation", 0.35,
                "(base64\\s*(解码|decode)|rot13|十六进制解码|unicode\\s*解码|解码(以下|下面))");
        rule("decode_execute", "obfuscation", 0.75,
                "(解码|decode)[^。\\n]{0,24}(执行|照做|按它|按此|follow)|decode\\s+(the\\s+)?(following|below)");
        rule("urgency_override", "obfuscation", 0.60,
                "(紧急|马上|立刻|立即)[，,]?[^。\\n]{0,8}(忽略|跳过|不要管)[^。\\n]{0,8}(规则|限制|审查|流程)");
        rule("multi_step_extract", "obfuscation", 0.55,
                "(先|然后|接着)[^。\\n]{0,24}(输出|告诉我|打印)[^。\\n]{0,12}(系统|提示词|密码|密钥|指令)");

        // ===== 泛化规则：动词 + 目标词邻近匹配，避免只覆盖固定句式 =====
        // 覆盖“作废/清除/取消/别管”等改写，以及“忽略上述说明/忽略之前的要求”等宾语变化
        rule("gen_override", "instruction_override", 0.88,
                "(忽略|无视|忘记|跳过|别管|不管|不要理会|不必遵守|不要遵守|作废|取消|清除|清空|重置|解除|覆盖"
                        + "|ignore|disregard|forget|override|bypass)[^。\\n]{0,16}"
                        + "(指令|指示|命令|规则|限制|约束|要求|设定|上下文|提示词|说明|内容"
                        + "|rules?|instructions?|prompts?|guidance|policy|context)");
        rule("gen_override_rev", "instruction_override", 0.85,
                "(指令|指示|规则|限制|约束|要求|设定|上下文|提示词)[^。\\n]{0,10}"
                        + "(作废|取消|清除|清空|重置|解除|覆盖|ignore|disregard)");
        rule("gen_ignore_prefix", "instruction_override", 0.85,
                "(别管|不管|不要管|别理会)[^。\\n]{0,6}(前面|之前|以上|上述|上面)");
        // 覆盖“念一遍/列成清单/翻译/发我/原文”等套取动词
        rule("gen_extract", "prompt_extraction", 0.90,
                "(输出|打印|显示|告诉|重复|复述|泄露|透露|粘贴|翻译|念|朗读|列出|列成|发我|给我|是什么|原文"
                        + "|reveal|show|print|repeat|output|leak|tell)[^。\\n]{0,16}"
                        + "(系统提示词|系统指令|系统设定|提示词|初始指令|初始设定|隐藏规则|开发者"
                        + "|prompt|instructions?|system\\s+message)");
        rule("gen_extract_rev", "prompt_extraction", 0.88,
                "(系统提示词|系统指令|系统设定|提示词|初始设定|隐藏规则|prompt|instructions?)[^。\\n]{0,12}"
                        + "(输出|打印|复述|翻译|发我|贴|念|列出|原样|reveal|print|show|repeat)");
        // 覆盖“不受限制/无限制/没有任何约束/without restrictions”等角色改写
        rule("gen_role_unbounded", "role_hijack", 0.85,
                "(你|助手|模型|机器人|assistant|model|ai)[^。\\n]{0,24}"
                        + "(不受|没有|无)[^。\\n]{0,6}(限制|约束|审查|道德|restrictions?|limits?)");
        rule("gen_role_unbounded_rev", "role_hijack", 0.85,
                "(不受|没有|无)[^。\\n]{0,6}(限制|约束|审查|道德|restrictions?|limits?)[^。\\n]{0,24}"
                        + "(你|助手|模型|机器人|assistant|model|ai)");
        // 覆盖“作为 root 请关闭/我是 admin 给我”等权限伪装
        rule("gen_authority", "authority_spoofing", 0.80,
                "(我是|作为|i\\s+am|as)\\s*(the\\s+)?(系统管理员|超级管理员|管理员|开发者|审计员|root|admin|administrator)"
                        + "[^。\\n]{0,30}(忽略|输出|提供|关闭|跳过|绕过|要求|命令|给我|give|show|export|provide|ignore|bypass|disable)");
        // 覆盖“安全审查关掉/安全策略可以绕过/disable safety checks”正反语序
        rule("gen_filter_disable", "safety_bypass", 0.80,
                "(关闭|关掉|停用|禁用|绕过|撤销|disable|turn\\s+off|bypass|switch\\s+off)[^。\\n]{0,12}"
                        + "(安全|审查|过滤|filter|safety|check)");
        rule("gen_filter_disable_rev", "safety_bypass", 0.80,
                "(安全|审查|过滤|filter|safety|check)[^。\\n]{0,12}"
                        + "(关闭|关掉|停用|禁用|绕过|撤销|disable|turn\\s+off|bypass)");
        // 覆盖“资料/工单备注里要求忽略限制”的间接注入
        rule("gen_indirect", "context_spoofing", 0.72,
                "(资料|材料|文档|知识库|参考资料|检索结果|工单备注|工单描述|document|retrieved)[^。\\n]{0,30}"
                        + "(忽略|执行以下|新的指令|ignore|follow\\s+the\\s+instructions)");
        rule("gen_new_system", "context_spoofing", 0.75,
                "(新的|new)\\s*(system|系统)?\\s*(指令|instruction)");
        // 覆盖“全部报修人的手机号/所有用户数据/all user records”
        rule("gen_exfil", "data_exfiltration", 0.85,
                "(所有|全部|全量|all|every)[^。\\n]{0,24}"
                        + "(手机号|电话|身份证|邮箱|姓名|地址|联系方式|客户信息|用户数据|员工信息"
                        + "|user\\s+records?|contact\\s+details?)");
        rule("gen_exfil_rev", "data_exfiltration", 0.80,
                "(手机号|身份证|联系方式|客户信息|用户数据|员工信息)[^。\\n]{0,24}(所有|全部|全量)");
        // 覆盖“紧急！跳过审查”这类夹带标点的紧迫话术
        rule("gen_urgency", "obfuscation", 0.65,
                "(紧急|马上|立刻|立即)[^。\\n]{0,12}(忽略|跳过|不要管|绕过)[^。\\n]{0,12}(规则|限制|审查|流程)");
    }

    private InjectionDetector() {
    }

    /** 返回全部规则 id（供文档/评测对账） */
    public static List<String> ruleIds() {
        List<String> ids = new ArrayList<>();
        for (Rule r : RULES) {
            ids.add(r.id());
        }
        return ids;
    }

    /**
     * 检测一段文本是否包含 prompt 注入意图。
     *
     * @param text      待检测文本（用户问题 / 历史 / 工单描述均可）
     * @param threshold 拦截阈值（默认 0.5）
     */
    public static Verdict detect(String text, double threshold) {
        if (text == null || text.isBlank()) {
            return new Verdict(false, 0.0, List.of(), List.of());
        }
        String norm = normalize(text);
        Map<String, Double> hitWeights = new LinkedHashMap<>();
        List<String> hits = new ArrayList<>();
        List<String> snippets = new ArrayList<>();
        for (Rule r : RULES) {
            Matcher m = r.pattern().matcher(norm);
            if (m.find()) {
                // 同一规则多次命中不重复加权（避免长文本靠重复词刷分）
                hitWeights.putIfAbsent(r.id(), r.weight());
                String snip = m.group();
                snippets.add(r.id() + ":" + (snip.length() > 40 ? snip.substring(0, 40) + "..." : snip));
            }
        }
        double score = 0.0;
        for (double w : hitWeights.values()) {
            score += w;
        }
        score = Math.min(1.0, Math.round(score * 1000) / 1000.0);
        hits.addAll(hitWeights.keySet());
        return new Verdict(score >= threshold, score, hits, snippets);
    }

    /**
     * 归一化：全角转半角、去除零宽字符、小写、压缩空白，并去掉汉字之间的空格（对抗“忽 略 以 上 指 令”）。
     */
    public static String normalize(String text) {
        String s = Normalizer.normalize(text, Normalizer.Form.NFKC);
        s = s.replaceAll("[\\u200B-\\u200D\\uFEFF]", "");
        s = s.replaceAll("(?<=[\\u4e00-\\u9fa5])\\s+(?=[\\u4e00-\\u9fa5])", "");
        s = s.replaceAll("\\s+", " ").trim();
        return s.toLowerCase();
    }
}
