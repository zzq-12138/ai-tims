package com.tims.ai.guard;

import java.util.LinkedHashMap;
import java.util.Map;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * 出站/入站 PII 脱敏（纯本地规则）。
 * 覆盖：手机号、固话、身份证、邮箱、客户/报修人姓名、地址。
 * 脱敏采用固定占位符（如 [手机号]），不可逆、不改变句子结构，便于模型继续理解上下文。
 */
public final class PiiRedactor {

    public static final String PHONE = "手机号";
    public static final String LANDLINE = "固话";
    public static final String ID_CARD = "身份证";
    public static final String EMAIL = "邮箱";
    public static final String NAME = "姓名";
    public static final String ADDRESS = "地址";

    /** 脱敏结果：text 为替换后文本，hits 为各类型命中次数 */
    public record Result(String text, Map<String, Integer> hits) {
        public boolean hit() {
            return !hits.isEmpty();
        }
    }

    private static final Pattern EMAIL_P = Pattern.compile(
            "[A-Za-z0-9._%+\\-]+@[A-Za-z0-9.\\-]+\\.[A-Za-z]{2,}");
    private static final Pattern ID_P = Pattern.compile(
            "(?<!\\d)\\d{17}[\\dXx](?!\\d)");
    private static final Pattern PHONE_P = Pattern.compile(
            "(?<!\\d)(?:\\+?86[- ]?)?1[3-9]\\d(?:[- ]?\\d){8}(?![\\dA-Za-z])");
    private static final Pattern LANDLINE_P = Pattern.compile(
            "(?<!\\d)0\\d{2,3}[- ]?\\d{7,8}(?!\\d)");

    /** 带前缀的姓名（客户：张三 / 报修人 李四） */
    private static final Pattern NAME_PREFIX_P = Pattern.compile(
            "(客户|报修人|联系人|业主|机主|申请人|负责人|处理人|来电人|用户|员工)(姓名)?\\s*[：:]\\s*([\\u4e00-\\u9fa5]{2,4})");
    /** 姓名：张三 */
    private static final Pattern NAME_LABEL_P = Pattern.compile(
            "(姓名)\\s*[：:]\\s*([\\u4e00-\\u9fa5]{2,4})");
    /** 客户张三（排除 客户反馈/客户表示 这类非姓名搭配；允许“联系人 王五”这种空格写法） */
    private static final Pattern NAME_INLINE_P = Pattern.compile(
            "(客户|报修人|联系人|业主|机主)\\s*([\\u4e00-\\u9fa5]{2,4})(?=[，。、；;\\s]|$)");
    private static final Pattern NAME_STOP = Pattern.compile(
            "^(反馈|表示|反映|要求|投诉|来电|咨询|现场|设备|工单|信息|资料|意见|建议|问题|服务|人员|单位|公司"
                    + "|电话|手机|邮箱|地址|姓名|方式|联系|负责|处理|到达|确认|同意|拒绝)$");

    /** 结构化地址 */
    private static final Pattern ADDRESS_LABEL_P = Pattern.compile(
            "(地址|住址|安装位置|所在位置|厂址|收货地址)\\s*[：:]\\s*([^，。；;、]{4,60})");
    /** 自然语言地址（贪婪到最后一个地址后缀，避免只遮盖到“区/路”就截断） */
    private static final Pattern ADDRESS_INLINE_P = Pattern.compile(
            "(位于|住在|安装在|坐落于)\\s*([\\u4e00-\\u9fa5A-Za-z0-9\\-\\s]{6,60}(?:号|栋|室|园区|路|街|道|巷))");

    /** 序列号/编号类长数字不是身份证，命中这些前缀时跳过身份证脱敏 */
    private static final Pattern ID_PREFIX_P = Pattern.compile(
            "(序列号|设备序列号|批次号|订单号|工单号|编号|设备号|模具编号)\\s*[：:]?\\s*$");

    private PiiRedactor() {
    }

    /** 全量脱敏 */
    public static Result redact(String text) {
        if (text == null || text.isEmpty()) {
            return new Result(text, Map.of());
        }
        Map<String, Integer> hits = new LinkedHashMap<>();
        String s = text;
        s = replace(s, EMAIL_P, "[" + EMAIL + "]", EMAIL, hits);
        s = replaceId(s, hits);
        s = replace(s, PHONE_P, "[" + PHONE + "]", PHONE, hits);
        s = replace(s, LANDLINE_P, "[" + LANDLINE + "]", LANDLINE, hits);
        s = replaceName(s, NAME_PREFIX_P, 3, hits);
        s = replaceName(s, NAME_LABEL_P, 2, hits);
        s = replaceInlineName(s, hits);
        s = replaceAddress(s, ADDRESS_LABEL_P, 2, hits);
        s = replaceInlineAddress(s, hits);
        return new Result(s, hits);
    }

    /** 只脱敏指定类型（评测/按场景裁剪用） */
    public static Result redactOnly(String text, String type) {
        if (text == null || text.isEmpty()) {
            return new Result(text, Map.of());
        }
        Map<String, Integer> hits = new LinkedHashMap<>();
        String s = text;
        switch (type) {
            case PHONE -> s = replace(s, PHONE_P, "[手机号]", PHONE, hits);
            case LANDLINE -> s = replace(s, LANDLINE_P, "[固话]", LANDLINE, hits);
            case ID_CARD -> s = replaceId(s, hits);
            case EMAIL -> s = replace(s, EMAIL_P, "[邮箱]", EMAIL, hits);
            case NAME -> {
                s = replaceName(s, NAME_PREFIX_P, 3, hits);
                s = replaceName(s, NAME_LABEL_P, 2, hits);
                s = replaceInlineName(s, hits);
            }
            case ADDRESS -> {
                s = replaceAddress(s, ADDRESS_LABEL_P, 2, hits);
                s = replaceInlineAddress(s, hits);
            }
            default -> { }
        }
        return new Result(s, hits);
    }

    /** 身份证脱敏：跳过“序列号/批次号/订单号”等编号语境 */
    private static String replaceId(String s, Map<String, Integer> hits) {
        Matcher m = ID_P.matcher(s);
        StringBuilder sb = new StringBuilder();
        int count = 0;
        while (m.find()) {
            int from = Math.max(0, m.start() - 12);
            String before = s.substring(from, m.start());
            if (ID_PREFIX_P.matcher(before).find()) {
                m.appendReplacement(sb, Matcher.quoteReplacement(m.group()));
                continue;
            }
            m.appendReplacement(sb, Matcher.quoteReplacement("[" + ID_CARD + "]"));
            count++;
        }
        m.appendTail(sb);
        if (count > 0) {
            hits.merge(ID_CARD, count, Integer::sum);
        }
        return sb.toString();
    }

    private static String replace(String s, Pattern p, String mask, String type, Map<String, Integer> hits) {
        Matcher m = p.matcher(s);
        StringBuilder sb = new StringBuilder();
        int count = 0;
        while (m.find()) {
            m.appendReplacement(sb, Matcher.quoteReplacement(mask));
            count++;
        }
        m.appendTail(sb);
        if (count > 0) {
            hits.merge(type, count, Integer::sum);
        }
        return sb.toString();
    }

    /** 姓名：保留前缀与标签，仅替换姓名本身 */
    private static String replaceName(String s, Pattern p, int nameGroup, Map<String, Integer> hits) {
        Matcher m = p.matcher(s);
        StringBuilder sb = new StringBuilder();
        int count = 0;
        while (m.find()) {
            String name = m.group(nameGroup);
            if (NAME_STOP.matcher(name).matches()) {
                m.appendReplacement(sb, Matcher.quoteReplacement(m.group()));
                continue;
            }
            String whole = m.group();
            String replaced = whole.substring(0, whole.length() - name.length()) + "[姓名]";
            m.appendReplacement(sb, Matcher.quoteReplacement(replaced));
            count++;
        }
        m.appendTail(sb);
        if (count > 0) {
            hits.merge(NAME, count, Integer::sum);
        }
        return sb.toString();
    }

    private static String replaceInlineName(String s, Map<String, Integer> hits) {
        Matcher m = NAME_INLINE_P.matcher(s);
        StringBuilder sb = new StringBuilder();
        int count = 0;
        while (m.find()) {
            String name = m.group(2);
            if (NAME_STOP.matcher(name).matches()) {
                m.appendReplacement(sb, Matcher.quoteReplacement(m.group()));
                continue;
            }
            m.appendReplacement(sb, Matcher.quoteReplacement(m.group(1) + "[姓名]"));
            count++;
        }
        m.appendTail(sb);
        if (count > 0) {
            hits.merge(NAME, count, Integer::sum);
        }
        return sb.toString();
    }

    /** 地址：保留前缀，替换地址内容 */
    private static String replaceAddress(String s, Pattern p, int addrGroup, Map<String, Integer> hits) {
        Matcher m = p.matcher(s);
        StringBuilder sb = new StringBuilder();
        int count = 0;
        while (m.find()) {
            String addr = m.group(addrGroup);
            String whole = m.group();
            String replaced = whole.substring(0, whole.length() - addr.length()) + "[地址]";
            m.appendReplacement(sb, Matcher.quoteReplacement(replaced));
            count++;
        }
        m.appendTail(sb);
        if (count > 0) {
            hits.merge(ADDRESS, count, Integer::sum);
        }
        return sb.toString();
    }

    private static String replaceInlineAddress(String s, Map<String, Integer> hits) {
        Matcher m = ADDRESS_INLINE_P.matcher(s);
        StringBuilder sb = new StringBuilder();
        int count = 0;
        while (m.find()) {
            m.appendReplacement(sb, Matcher.quoteReplacement(m.group(1) + "[地址]"));
            count++;
        }
        m.appendTail(sb);
        if (count > 0) {
            hits.merge(ADDRESS, count, Integer::sum);
        }
        return sb.toString();
    }
}
