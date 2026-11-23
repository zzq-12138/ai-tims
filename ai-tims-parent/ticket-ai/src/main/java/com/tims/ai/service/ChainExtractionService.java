package com.tims.ai.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.tims.ai.config.AiProperties;
import com.tims.ai.dto.ExtractRequest;
import com.tims.ai.dto.ExtractResult;
import com.tims.ai.llm.LlmException;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.ai.chat.messages.Message;
import org.springframework.ai.chat.messages.SystemMessage;
import org.springframework.ai.chat.messages.UserMessage;
import org.springframework.ai.chat.metadata.Usage;
import org.springframework.ai.chat.model.ChatResponse;
import org.springframework.ai.chat.prompt.Prompt;
import org.springframework.ai.openai.OpenAiChatModel;
import org.springframework.ai.openai.OpenAiChatOptions;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;

import java.text.Normalizer;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * P0 五元组链式抽取（现象 → 根因/验证 → 措施/条件）。
 *
 * 与 scripts/annotation/chain_extract.py 一一对应：三步 system prompt 逐字移植，
 * 每步独立解析 + 校验，任一步失败只清空该步字段并写入 trace.error（降级而非重跑整链），
 * 且置 chainDegraded=true 交由 ticket-knowledge 打标，绝不把降级结果当正常结果。
 *
 * 由 tims.ai.extract.chain-enabled 控制，默认关闭；关闭时本类不会被调用，
 * 单轮链路（ExtractionService#extractSingleRound）行为完全不变。
 * 元数据（设备型号/故障码）只喂第 3 步：第 1/2 步必须贴近原文。
 */
@Service
public class ChainExtractionService {

    private static final Logger log = LoggerFactory.getLogger(ChainExtractionService.class);
    private static final ObjectMapper MAPPER = new ObjectMapper();

    private static final Set<String> CONDITION_TYPES = Set.of(
            "device_model", "process_stage", "material_or_batch", "param_range", "precondition");
    private static final Set<String> COND_PLACEHOLDERS = Set.of(
            "未提及", "无", "不适用", "未知", "暂无", "none", "n/a", "na", "-", "null");

    /** trace 中单步 raw 截断长度，避免 chain_trace 列过大 */
    private static final int RAW_KEEP = 3000;

    static final String STEP1_SYSTEM = """
            你是设备维修工单知识抽取器。本次只执行第 1 步：定位故障现象。
            规则：
            1) symptom 写用户可观察到的异常表现，不写原因、不写处理动作。
            2) symptom_evidence 必须逐字摘自工单原文；找不到可支撑的原文时，该字段为空串。
            3) 只输出一个 JSON 对象，不要解释、不要代码块：
            {"symptom": "...", "symptom_evidence": "..."}
            """;

    static final String STEP2_SYSTEM = """
            你是设备维修工单知识抽取器。本次只执行第 2 步：定位根因与验证方式。
            输入包含工单原文与第 1 步已定位的故障现象。
            原文常见段落标签：故障现象、处理经过、维修动作、结果验证、归档说明。
            规则：
            1) 只有原文给出明确结论时才填 root_cause；出现“怀疑/待查/暂未定位/等厂家/继续跟踪”时，
               root_cause 必须为空串，has_final_root_cause=0。
            2) 原文明确排除的假设（“排除 X”“按 X 方向排查后无改善”）只能写入 excluded_hypotheses，
               严禁写入 root_cause；排除项的 evidence 逐字摘自原文。
            3) verification 只取「结果验证」段（或复测/结果记录）里的结果值，如“温度稳定 85±2℃，连续 4 小时”；
               **严禁把「维修动作」段（更换/调整/重新整定）当作 verification**；未验证则为空串。
            4) 数字与单位照抄原文，不换算、不编造。
            5) 只输出一个 JSON 对象：
            {"root_cause": "", "root_cause_evidence": "", "verification": "",
            "verification_evidence": "", "excluded_hypotheses": [{"hypothesis": "", "evidence": ""}],
            "has_final_root_cause": 0}
            """;

    static final String STEP3_SYSTEM = """
            你是设备维修工单知识抽取器。本次只执行第 3 步：抽取处理措施与适用条件。
            输入包含工单原文、已定位的现象、根因与验证。
            规则：
            1) measures 只写已执行的维修/调整动作；同一句中的并列动作保持为一个条目，不要拆条；
               “先降速跑着/等厂家”这类临时处置不算措施。
            2) conditions 是「这条知识适用的条件」，取**故障发生时**的设备/工艺状态，不是维修后的目标值。
               type 只能取 device_model/process_stage/material_or_batch/param_range/precondition；
               只写原文明确出现或可直接推出的条件，禁止编造；没有条件输出空数组。
            3) 各类型取值口径：
               - device_model：取「工单元数据-设备型号」或原文「设备：」行的型号（如 LAM-600、SIPLACE SX），
                 不写产线名，也不写「贴合机/贴片机/AOI 检测机」这类设备别名；
               - param_range：故障发生时的参数与阈值（如 温度 65℃、两端压力 0.2MPa）；
                 **维修后调整到的目标值（如 调整到 85℃、压力改为 0.45MPa）不得写入**；
                 **「结果验证/复测」段里的验证值（如 稳定在 -78kPa 至 -82kPa）也不得写入**；
               - process_stage：写工序/工步名称（如 0402 贴装、波峰焊、回流焊），
                 不写「取料后/贴合后/调整后」这类时序词；
               - material_or_batch/precondition：只写原文明确给出的批次或前置条件。
               禁止输出“未提及/无/不适用/未知”这类占位值。
            4) 只输出一个 JSON 对象：
            {"measures": ["..."], "conditions": [{"type": "device_model", "value": "..."}]}
            """;

    private final OpenAiChatModel chatModel;
    private final AiProperties props;

    public ChainExtractionService(OpenAiChatModel chatModel, AiProperties props) {
        this.chatModel = chatModel;
        this.props = props;
    }

    /**
     * 执行三步链式抽取。返回结果含五元组字段、conditionKeys、chainTrace、chainDegraded。
     * 三步全部失败时抛 LlmException（与单轮一致的失败语义，由上层落“待人工补录”）。
     */
    public ExtractResult run(Long tenantId, ExtractRequest req) {
        long t0 = System.currentTimeMillis();
        String model = props.getExtractModel();
        String text = buildSourceText(req);
        String meta = buildMeta(req);

        Map<String, Object> trace = new LinkedHashMap<>();
        List<String> errors = new ArrayList<>();
        int[] tokens = new int[2];

        JsonNode o1 = step(1, STEP1_SYSTEM, "工单原文：\n" + text, model, tokens, trace, errors);
        Map<String, Object> s1 = validateStep1(o1, text);

        JsonNode o2 = step(2, STEP2_SYSTEM,
                "工单原文：\n" + text + "\n\n第 1 步已定位现象：\n" + s1.get("symptom"),
                model, tokens, trace, errors);
        Map<String, Object> s2 = validateStep2(o2, text);

        JsonNode o3 = step(3, STEP3_SYSTEM,
                (meta.isEmpty() ? "" : "工单元数据：\n" + meta + "\n\n")
                        + "工单原文：\n" + text
                        + "\n\n已定位现象：" + s1.get("symptom")
                        + "\n根因：" + (StringUtils.hasText((String) s2.get("root_cause"))
                        ? s2.get("root_cause") : "（无最终根因）")
                        + "\n验证：" + (StringUtils.hasText((String) s2.get("verification"))
                        ? s2.get("verification") : "（未验证）"),
                model, tokens, trace, errors);
        Map<String, Object> s3 = validateStep3(o3);

        // 验证方式若与维修动作同源 → 视为把维修动作误当结果验证，清空并留痕
        if (StringUtils.hasText((String) s2.get("verification")) && !((List<?>) s3.get("measures")).isEmpty()) {
            String joined = String.join("", castList(s3.get("measures")));
            String ver = (String) s2.get("verification");
            if (norm(ver).contains(norm(joined)) || dice(ver, joined) >= 0.8) {
                s2.put("verification", "");
                s2.put("verification_evidence", "");
                s2.put("ver_misattributed", 1);
                trace.put("ver_misattributed", true);
            }
        }

        // 三步全部无 JSON → 与单轮失败同语义
        if (o1 == null && o2 == null && o3 == null) {
            throw new LlmException(40203, "链式抽取三步均未返回合法 JSON：" + String.join("; ", errors));
        }

        ExtractResult r = new ExtractResult();
        String symptom = (String) s1.get("symptom");
        r.setFaultPhenomenon(symptom);
        r.setRootCause((String) s2.get("root_cause"));
        r.setRootCauseEvidence((String) s2.get("root_cause_evidence"));
        r.setVerification((String) s2.get("verification"));
        r.setVerificationEvidence((String) s2.get("verification_evidence"));
        r.setExcludedHypotheses(castMaps(s2.get("excluded_hypotheses")));
        r.setHasFinalRootCause(((Integer) s2.get("has_final_root_cause")) == 1);
        r.setApplyConditions(castMaps(s3.get("conditions")));
        r.setConditionKeys(buildConditionKeys(r.getApplyConditions()));

        List<String> measures = castList(s3.get("measures"));
        r.setSolutionSteps(numbered(measures));
        r.setTroubleshootSteps("");
        r.setKeyPoints(excludedText(r.getExcludedHypotheses()));
        // 链式模式不产出标题/标签：按设备类型 + 现象派生，审核页可人工修正
        String deviceType = StringUtils.hasText(req.getDeviceType()) ? req.getDeviceType() : "设备";
        r.setDeviceType(req.getDeviceType());
        r.setTitle(truncate(deviceType + "：" + (symptom == null ? "" : symptom), 30));
        List<String> tags = new ArrayList<>();
        if (StringUtils.hasText(req.getDeviceType())) {
            tags.add(req.getDeviceType());
        }
        r.setTags(tags);

        boolean degraded = !errors.isEmpty();
        r.setChainDegraded(degraded);
        r.setChainErrors(errors);
        trace.put("degraded", degraded);
        trace.put("errors", errors);
        try {
            r.setChainTrace(MAPPER.writeValueAsString(trace));
        } catch (Exception e) {
            r.setChainTrace("{\"degraded\":true,\"errors\":[\"trace_serialize_failed\"]}");
        }

        r.setModel(model);
        r.setPromptTokens(tokens[0]);
        r.setCompletionTokens(tokens[1]);
        r.setTotalTokens(tokens[0] + tokens[1]);
        r.setLatencyMs(System.currentTimeMillis() - t0);
        log.info("[extract-chain] ticket={} steps=3 degraded={} errors={} {}ms",
                req.getTicketNo(), degraded, errors, r.getLatencyMs());
        return r;
    }

    /** 单步调用 + trace 记录；异常/无 JSON 只记错误，不中断后续步骤 */
    private JsonNode step(int no, String system, String user, String model, int[] tokens,
                          Map<String, Object> trace, List<String> errors) {
        Map<String, Object> node = new LinkedHashMap<>();
        String raw = null;
        String err = null;
        try {
            List<Message> messages = List.of(new SystemMessage(system), new UserMessage(user));
            OpenAiChatOptions options = OpenAiChatOptions.builder()
                    .model(model)
                    .temperature(0.0)
                    .maxTokens(props.getExtractMaxTokens())
                    .build();
            ChatResponse resp = chatModel.call(new Prompt(messages, options));
            raw = resp.getResult() == null ? "" : resp.getResult().getOutput().getText();
            Usage u = resp.getMetadata() == null ? null : resp.getMetadata().getUsage();
            tokens[0] += u == null || u.getPromptTokens() == null ? 0 : u.getPromptTokens();
            tokens[1] += u == null || u.getCompletionTokens() == null ? 0 : u.getCompletionTokens();
        } catch (Exception e) {
            err = e.getClass().getSimpleName() + ": " + truncate(e.getMessage(), 160);
        }
        JsonNode obj = err == null ? parseJson(raw) : null;
        if (err == null && obj == null) {
            err = "no_json";
        }
        node.put("json_ok", obj == null ? 0 : 1);
        node.put("schema_ok", obj != null && schemaOk(no, obj) ? 1 : 0);
        node.put("error", err);
        node.put("raw", raw == null ? null : truncate(raw, RAW_KEEP));
        trace.put(String.valueOf(no), node);
        if (err != null) {
            errors.add("step" + no + ":" + err);
        }
        return obj;
    }

    private static boolean schemaOk(int step, JsonNode obj) {
        if (obj == null || !obj.isObject()) {
            return false;
        }
        if (step == 1) {
            return obj.has("symptom") && obj.has("symptom_evidence");
        }
        if (step == 2) {
            return obj.has("root_cause") && obj.has("root_cause_evidence")
                    && obj.has("verification") && obj.has("verification_evidence")
                    && obj.has("excluded_hypotheses") && obj.has("has_final_root_cause");
        }
        return obj.has("measures") && obj.has("conditions");
    }

    // ---------------- 逐步校验（与离线同口径） ----------------

    private Map<String, Object> validateStep1(JsonNode obj, String text) {
        Map<String, Object> f = new HashMap<>();
        String symptom = textOf(obj, "symptom");
        f.put("symptom", symptom);
        f.put("symptom_evidence", textOf(obj, "symptom_evidence"));
        return f;
    }

    private Map<String, Object> validateStep2(JsonNode obj, String text) {
        Map<String, Object> f = new HashMap<>();
        String rc = textOf(obj, "root_cause");
        String rce = textOf(obj, "root_cause_evidence");
        String ver = textOf(obj, "verification");
        String vere = textOf(obj, "verification_evidence");
        List<Map<String, String>> excl = new ArrayList<>();
        JsonNode arr = obj == null ? null : obj.get("excluded_hypotheses");
        if (arr != null && arr.isArray()) {
            for (JsonNode x : arr) {
                String h;
                String e;
                if (x.isObject()) {
                    h = x.path("hypothesis").asText("").trim();
                    e = x.path("evidence").asText("").trim();
                } else {
                    h = x.asText("").trim();
                    e = "";
                }
                if (!h.isEmpty()) {
                    Map<String, String> m = new LinkedHashMap<>();
                    m.put("hypothesis", h);
                    m.put("evidence", e);
                    excl.add(m);
                }
            }
        }
        // 根因与某排除假设等价 → 视为误用排除项，清空根因
        for (Map<String, String> x : excl) {
            if (!rc.isEmpty() && (norm(rc).contains(norm(x.get("hypothesis")))
                    || norm(x.get("hypothesis")).contains(norm(rc)))) {
                rc = "";
                break;
            }
        }
        f.put("root_cause", rc);
        f.put("root_cause_evidence", rce);
        f.put("verification", ver);
        f.put("verification_evidence", vere);
        f.put("excluded_hypotheses", excl);
        f.put("has_final_root_cause", rc.isEmpty() ? 0 : 1);
        return f;
    }

    private Map<String, Object> validateStep3(JsonNode obj) {
        Map<String, Object> f = new HashMap<>();
        List<String> measures = new ArrayList<>();
        JsonNode ms = obj == null ? null : obj.get("measures");
        if (ms != null && ms.isArray()) {
            for (JsonNode m : ms) {
                String s = m.asText("").trim();
                if (!s.isEmpty()) {
                    measures.add(s);
                }
            }
        }
        List<Map<String, String>> conditions = new ArrayList<>();
        Set<String> seen = new LinkedHashSet<>();
        JsonNode cs = obj == null ? null : obj.get("conditions");
        if (cs != null && cs.isArray()) {
            for (JsonNode c : cs) {
                if (!c.isObject()) {
                    continue;
                }
                String t = c.path("type").asText("").trim();
                String v = c.path("value").asText("").trim();
                String key = t + "\u0000" + v;
                if (CONDITION_TYPES.contains(t) && !v.isEmpty()
                        && !COND_PLACEHOLDERS.contains(v.toLowerCase()) && seen.add(key)) {
                    Map<String, String> m = new LinkedHashMap<>();
                    m.put("type", t);
                    m.put("value", v);
                    conditions.add(m);
                }
            }
        }
        f.put("measures", measures);
        f.put("conditions", conditions);
        return f;
    }

    // ---------------- 工具 ----------------

    /** 条件扁平键：type=value 以 | 分隔，供检索过滤（值内空白压缩） */
    static String buildConditionKeys(List<Map<String, String>> conditions) {
        if (conditions == null || conditions.isEmpty()) {
            return null;
        }
        LinkedHashSet<String> keys = new LinkedHashSet<>();
        for (Map<String, String> c : conditions) {
            String t = c.get("type");
            String v = c.get("value");
            if (t == null || v == null || v.isBlank()) {
                continue;
            }
            keys.add(t + "=" + v.trim().replaceAll("\\s+", " "));
        }
        return keys.isEmpty() ? null : String.join("|", keys);
    }

    private String buildSourceText(ExtractRequest req) {
        StringBuilder sb = new StringBuilder(512);
        sb.append("工单编号：").append(nvl(req.getTicketNo())).append('\n');
        sb.append("工单标题：").append(nvl(req.getTitle())).append('\n');
        sb.append("设备类型：").append(nvl(req.getDeviceType())).append('\n');
        sb.append("故障描述：").append(nvl(req.getDescription())).append('\n');
        sb.append("解决说明：").append(nvl(req.getResolveNote())).append('\n');
        if (req.getFlows() != null) {
            for (String f : req.getFlows()) {
                if (StringUtils.hasText(f)) {
                    sb.append("流转记录：").append(f).append('\n');
                }
            }
        }
        if (req.getComments() != null) {
            for (String c : req.getComments()) {
                if (StringUtils.hasText(c)) {
                    sb.append("沟通记录：").append(c).append('\n');
                }
            }
        }
        return sb.toString();
    }

    private String buildMeta(ExtractRequest req) {
        List<String> meta = new ArrayList<>();
        if (StringUtils.hasText(req.getDeviceType())) {
            meta.add("设备型号：" + req.getDeviceType());
        }
        return String.join("\n", meta);
    }

    private static JsonNode parseJson(String raw) {
        if (!StringUtils.hasText(raw)) {
            return null;
        }
        String s = raw.trim();
        s = s.replaceAll("^```(?:json)?", "").replaceAll("```$", "").trim();
        int start = s.indexOf('{');
        int end = s.lastIndexOf('}');
        if (start < 0 || end <= start) {
            return null;
        }
        try {
            JsonNode n = MAPPER.readTree(s.substring(start, end + 1));
            return n != null && n.isObject() ? n : null;
        } catch (Exception e) {
            return null;
        }
    }

    private static String textOf(JsonNode obj, String field) {
        return obj == null ? "" : obj.path(field).asText("").trim();
    }

    private static List<String> castList(Object o) {
        List<String> list = new ArrayList<>();
        if (o instanceof List<?> l) {
            for (Object x : l) {
                list.add(String.valueOf(x));
            }
        }
        return list;
    }

    @SuppressWarnings("unchecked")
    private static List<Map<String, String>> castMaps(Object o) {
        return o instanceof List<?> ? (List<Map<String, String>>) o : new ArrayList<>();
    }

    private static String numbered(List<String> items) {
        StringBuilder sb = new StringBuilder();
        int i = 1;
        for (String s : items) {
            sb.append(i++).append(". ").append(s).append('\n');
        }
        return sb.toString().trim();
    }

    private static String excludedText(List<Map<String, String>> excl) {
        if (excl == null || excl.isEmpty()) {
            return "";
        }
        StringBuilder sb = new StringBuilder("已排除假设：\n");
        for (Map<String, String> x : excl) {
            sb.append("- ").append(x.get("hypothesis"));
            if (StringUtils.hasText(x.get("evidence"))) {
                sb.append("（依据：").append(x.get("evidence")).append("）");
            }
            sb.append('\n');
        }
        return sb.toString().trim();
    }

    /** NFKC + 小写 + 仅保留字母数字与汉字（与离线 chains 的 norm 一致） */
    static String norm(String s) {
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

    /** 字二元组 Dice 相似度 */
    static double dice(String a, String b) {
        String na = norm(a);
        String nb = norm(b);
        if (na.isEmpty() && nb.isEmpty()) {
            return 1.0;
        }
        if (na.isEmpty() || nb.isEmpty()) {
            return 0.0;
        }
        Map<String, Integer> ga = bigrams(na);
        Map<String, Integer> gb = bigrams(nb);
        int inter = 0;
        for (Map.Entry<String, Integer> e : ga.entrySet()) {
            Integer v = gb.get(e.getKey());
            if (v != null) {
                inter += Math.min(e.getValue(), v);
            }
        }
        int total = 0;
        for (int v : ga.values()) {
            total += v;
        }
        for (int v : gb.values()) {
            total += v;
        }
        return total == 0 ? 0.0 : 2.0 * inter / total;
    }

    private static Map<String, Integer> bigrams(String s) {
        Map<String, Integer> m = new HashMap<>();
        if (s.length() == 1) {
            m.put(s, 1);
            return m;
        }
        for (int i = 0; i < s.length() - 1; i++) {
            m.merge(s.substring(i, i + 2), 1, Integer::sum);
        }
        return m;
    }

    private static String nvl(String s) {
        return s == null ? "" : s;
    }

    private static String truncate(String s, int max) {
        if (s == null) {
            return "";
        }
        return s.length() <= max ? s : s.substring(0, max);
    }
}
