package com.tims.knowledge.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.tims.common.exception.BizException;

import java.text.Normalizer;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * 五类适用条件的解析/校验/扁平键工具（P2 条件化知识表示）。
 *
 * 五类口径与离线链式抽取一致：device_model / process_stage / material_or_batch /
 * param_range / precondition。condition_keys 形如
 * {@code device_model=LAM-600|process_stage=贴合}，供检索侧条件过滤。
 */
public final class ConditionSupport {

    private static final ObjectMapper MAPPER = new ObjectMapper();

    public static final List<String> TYPES = List.of(
            "device_model", "process_stage", "material_or_batch", "param_range", "precondition");

    /** 五类中文标签（审核页展示用，前端同名映射） */
    public static final Map<String, String> TYPE_LABELS = new LinkedHashMap<>();

    static {
        TYPE_LABELS.put("device_model", "设备型号");
        TYPE_LABELS.put("process_stage", "工艺段");
        TYPE_LABELS.put("material_or_batch", "物料/批次");
        TYPE_LABELS.put("param_range", "参数区间");
        TYPE_LABELS.put("precondition", "前置条件");
    }

    private static final Set<String> PLACEHOLDERS = Set.of(
            "未提及", "无", "不适用", "未知", "暂无", "none", "n/a", "na", "-", "null");

    private ConditionSupport() {
    }

    /** 解析 JSON 数组 [{type,value}]；非法/空返回空列表（读取侧按空值降级） */
    public static List<Map<String, String>> parse(String json) {
        List<Map<String, String>> list = new ArrayList<>();
        if (json == null || json.isBlank()) {
            return list;
        }
        try {
            JsonNode n = MAPPER.readTree(json);
            if (n == null || !n.isArray()) {
                return list;
            }
            for (JsonNode x : n) {
                if (!x.isObject()) {
                    continue;
                }
                String t = x.path("type").asText("").trim();
                String v = x.path("value").asText("").trim();
                if (TYPES.contains(t) && !v.isEmpty()) {
                    Map<String, String> m = new LinkedHashMap<>();
                    m.put("type", t);
                    m.put("value", v);
                    list.add(m);
                }
            }
        } catch (Exception ignored) {
            // 非法 JSON 视为无条件
        }
        return list;
    }

    /**
     * 校验并序列化为 JSON 数组：类型必须属于五类，占位值剔除，按 (type,value) 去重。
     * 输入非法 JSON / 未知类型抛 BizException（人工修正入口需要明确报错，不静默吞掉）。
     */
    public static String toJson(String json) {
        if (json == null || json.isBlank()) {
            return "[]";
        }
        JsonNode n;
        try {
            n = MAPPER.readTree(json);
        } catch (Exception e) {
            throw new BizException(10400, "适用条件必须是 JSON 数组");
        }
        if (n == null || !n.isArray()) {
            throw new BizException(10400, "适用条件必须是 JSON 数组");
        }
        List<Map<String, String>> clean = new ArrayList<>();
        Set<String> seen = new LinkedHashSet<>();
        for (JsonNode x : n) {
            if (!x.isObject()) {
                throw new BizException(10400, "适用条件元素必须是 {type,value} 对象");
            }
            String t = x.path("type").asText("").trim();
            String v = x.path("value").asText("").trim();
            if (!TYPES.contains(t)) {
                throw new BizException(10400, "适用条件类型非法：" + t + "（仅支持 " + String.join("/", TYPES) + "）");
            }
            if (v.isEmpty() || PLACEHOLDERS.contains(v.toLowerCase())) {
                continue;
            }
            if (seen.add(t + "\u0000" + v)) {
                Map<String, String> m = new LinkedHashMap<>();
                m.put("type", t);
                m.put("value", v);
                clean.add(m);
            }
        }
        try {
            return MAPPER.writeValueAsString(clean);
        } catch (Exception e) {
            throw new BizException(10400, "适用条件序列化失败");
        }
    }

    /** 条件扁平键：type=value，按类型顺序输出；无有效条件返回 null */
    public static String keys(String json) {
        List<Map<String, String>> list = parse(json);
        if (list.isEmpty()) {
            return null;
        }
        Map<String, String> byType = new LinkedHashMap<>();
        for (String t : TYPES) {
            for (Map<String, String> c : list) {
                if (t.equals(c.get("type"))) {
                    byType.putIfAbsent(t, c.get("value"));
                }
            }
        }
        return keysOf(byType);
    }

    /** type→value 映射（同类多值取第一个），供关系判别使用 */
    public static Map<String, String> asMap(String applyConditionsJson, String conditionKeys) {
        Map<String, String> map = new LinkedHashMap<>();
        List<Map<String, String>> list = parse(applyConditionsJson);
        if (!list.isEmpty()) {
            for (Map<String, String> c : list) {
                map.putIfAbsent(c.get("type"), c.get("value"));
            }
            return map;
        }
        // 回退解析扁平键（旧数据只有 condition_keys 的场景）
        if (conditionKeys == null || conditionKeys.isBlank()) {
            return map;
        }
        for (String part : conditionKeys.split("\\|")) {
            int i = part.indexOf('=');
            if (i > 0) {
                String t = part.substring(0, i).trim();
                String v = part.substring(i + 1).trim();
                if (TYPES.contains(t) && !v.isEmpty()) {
                    map.putIfAbsent(t, v);
                }
            }
        }
        return map;
    }

    /** 归一化：NFKC + 小写 + 去掉空白与常见标点，用于条件值等价比较 */
    public static String norm(String s) {
        if (s == null) {
            return "";
        }
        String n = Normalizer.normalize(s, Normalizer.Form.NFKC).toLowerCase();
        StringBuilder sb = new StringBuilder(n.length());
        for (int i = 0; i < n.length(); i++) {
            char c = n.charAt(i);
            if (Character.isLetterOrDigit(c) || (c >= '\u4e00' && c <= '\u9fff')) {
                sb.append(c);
            }
        }
        return sb.toString();
    }

    private static String keysOf(Map<String, String> byType) {
        List<String> parts = new ArrayList<>();
        for (String t : TYPES) {
            String v = byType.get(t);
            if (v != null && !v.isBlank()) {
                parts.add(t + "=" + v.trim().replaceAll("\\s+", " "));
            }
        }
        return parts.isEmpty() ? null : String.join("|", parts);
    }
}
