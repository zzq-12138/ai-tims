package com.tims.knowledge.service;

import com.tims.knowledge.entity.AiExtracted;
import com.tims.knowledge.entity.KbKnowledge;
import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * P1 四类关系判别（duplicate / variant / conflict / unrelated）生产判别类。
 *
 * 与离线 scripts/annotation/relation_classify.py 的 rule 档同口径：
 * 现象/根因字面一致性 + 措施重叠 + 条件互斥（condition_keys/apply_conditions）。
 *
 * 关键兜底（反构造集结论）：结构化条件字段缺失时，规则不如余弦相似度
 * （反构造集 sim 0.8560 > full 0.7189 > rule 0.6600），因此本类在
 * 「任一侧无结构化条件 或 任一侧无根因」时直接退回余弦三分档，不硬套规则。
 *
 * 本类不做合并/覆盖动作，只输出关系标签与置信度，最终处置仍由审核人确认。
 */
@Service
public class RelationJudgeService {

    /** 判定灰区 → 退回余弦 */
    private static final double GRAY_SIM = 0.75;
    /** 余弦三分档映射（与离线 sim 档一致；仅用于关系标签，不改变入库闸门阈值） */
    private static final double SIM_DUPLICATE = 0.97;
    private static final double SIM_CONFLICT = 0.85;
    private static final double SIM_VARIANT = 0.75;

    /** 判别结论：relation + confidence + 条件状态 + 来源（rule / cosine_fallback / cosine_gray） */
    public record Verdict(String relation, double confidence, String conditionState,
                          String source, String reason) {
    }

    /**
     * @param row     本次抽取结果（含条件与根因）
     * @param target  相似度命中的已有条目
     * @param cosine  向量余弦相似度（0-1）
     */
    public Verdict judge(AiExtracted row, KbKnowledge target, double cosine) {
        Map<String, String> condA = ConditionSupport.asMap(row.getApplyConditions(), row.getConditionKeys());
        Map<String, String> condB = ConditionSupport.asMap(target.getApplyConditions(), target.getConditionKeys());
        String causeA = text(row.getRootCause());
        String causeB = text(target.getRootCause());

        // 字段不全 → 退回余弦（不臆断 variant/conflict）
        if (condA.isEmpty() || condB.isEmpty() || causeA.isEmpty() || causeB.isEmpty()) {
            return cosineVerdict(cosine, condA.isEmpty() || condB.isEmpty() ? "unknown" : "incomplete",
                    "cosine_fallback", "结构化条件/根因不全，退回余弦三分档");
        }

        KbFields fa = rowFields(row);
        KbFields fb = targetFields(target);
        String cs = condState(condA, condB);
        double symD = dice(fa.symptom, fb.symptom);
        double causeD = dice(causeA, causeB);
        boolean symSame = same(fa.symptom, fb.symptom, 0.8);
        boolean causeSame = same(causeA, causeB, 0.7);
        double mov = measureOverlap(fa.measures, fb.measures);
        double verD = dice(row.getVerification(), target.getVerification());

        if (symSame && causeSame && (mov >= 0.5 || (fa.measures.isEmpty() && fb.measures.isEmpty()))) {
            return new Verdict("duplicate", 0.95, cs, "rule",
                    String.format("现象/根因一致且措施重叠(sym=%.2f,cause=%.2f,meas=%.2f)", symD, causeD, mov));
        }
        // 换词改写会拉低字面重合，用「高余弦 + 措施/验证同源」兜底
        if (cosine >= 0.95 && mov >= 0.5 && verD >= 0.6) {
            return new Verdict("duplicate", 0.85, cs, "rule",
                    String.format("高相似且措施/验证同源(sim=%.2f,meas=%.2f,ver=%.2f)", cosine, mov, verD));
        }
        if (symSame && !causeSame) {
            if ("one_sided".equals(cs) || "exclusive".equals(cs)) {
                return new Verdict("variant", 0.85, cs, "rule",
                        String.format("同现象不同根因且适用条件不同(%s,cause=%.2f)", cs, causeD));
            }
            return new Verdict("conflict", 0.85, cs, "rule",
                    String.format("同现象不同根因且条件不互斥(%s,cause=%.2f)", cs, causeD));
        }
        if (!symSame && cosine < GRAY_SIM && !causeSame && mov < 0.2) {
            return new Verdict("unrelated", 0.9, cs, "rule",
                    String.format("现象不同且无共享根因/措施(sim=%.2f)", cosine));
        }
        return cosineVerdict(cosine, cs, "cosine_gray",
                String.format("规则灰区(sym=%.2f,cause=%.2f,sim=%.2f)", symD, causeD, cosine));
    }

    /** 纯余弦三分档（现网等价物）：字段不全或规则灰区时的唯一兜底 */
    private Verdict cosineVerdict(double cosine, String cs, String source, String reason) {
        double sim = Math.max(0.0, Math.min(1.0, cosine));
        String relation;
        if (sim >= SIM_DUPLICATE) {
            relation = "duplicate";
        } else if (sim >= SIM_CONFLICT) {
            relation = "conflict";
        } else if (sim >= SIM_VARIANT) {
            relation = "variant";
        } else {
            relation = "unrelated";
        }
        return new Verdict(relation, sim, cs, source, reason + String.format("(cos=%.4f)", sim));
    }

    /**
     * 条件状态：overlap / exclusive / one_sided / compatible / unknown。
     * 缺失按 unknown 处理，不臆断互斥；一方有条件一方无 → one_sided（条件不同）。
     */
    static String condState(Map<String, String> a, Map<String, String> b) {
        if (a.isEmpty() && b.isEmpty()) {
            return "unknown";
        }
        if (a.isEmpty() != b.isEmpty()) {
            return "one_sided";
        }
        int shared = 0;
        for (String t : a.keySet()) {
            String vb = b.get(t);
            if (vb == null) {
                continue;
            }
            shared++;
            if (!ConditionSupport.norm(a.get(t)).equals(ConditionSupport.norm(vb))) {
                return "exclusive";
            }
        }
        if (shared > 0 && shared == a.size() && shared == b.size()) {
            return "overlap";
        }
        return "compatible";
    }

    /** 措施重叠率（双向最优配对，Dice≥0.6 记命中） */
    static double measureOverlap(List<String> a, List<String> b) {
        if (a.isEmpty() || b.isEmpty()) {
            return 0.0;
        }
        int hit = 0;
        Set<Integer> used = new java.util.HashSet<>();
        for (String x : a) {
            double best = 0.0;
            int bi = -1;
            for (int j = 0; j < b.size(); j++) {
                if (used.contains(j)) {
                    continue;
                }
                double d = dice(x, b.get(j));
                if (d > best) {
                    best = d;
                    bi = j;
                }
            }
            if (best >= 0.6 && bi >= 0) {
                used.add(bi);
                hit++;
            }
        }
        return (double) hit / Math.max(a.size(), b.size());
    }

    /** 字面一致：Dice≥阈值，或较短串被较长串包含且长度比≥0.6 */
    static boolean same(String a, String b, double threshold) {
        if (dice(a, b) >= threshold) {
            return true;
        }
        String na = ConditionSupport.norm(a);
        String nb = ConditionSupport.norm(b);
        if (na.isEmpty() || nb.isEmpty()) {
            return false;
        }
        return (na.contains(nb) || nb.contains(na))
                && (double) Math.min(na.length(), nb.length()) / Math.max(na.length(), nb.length()) >= 0.6;
    }

    /** 字二元组 Dice（与离线同口径） */
    static double dice(String a, String b) {
        String na = ConditionSupport.norm(a);
        String nb = ConditionSupport.norm(b);
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

    private KbFields rowFields(AiExtracted row) {
        KbFields f = new KbFields();
        f.symptom = text(row.getFaultPhenomenon());
        f.measures = splitNumbered(row.getSolutionSteps());
        return f;
    }

    /** 已有条目：字段列优先，正文解析兜底（历史数据无新列） */
    private KbFields targetFields(KbKnowledge k) {
        KbFields f = new KbFields();
        String symptom = "";
        List<String> measures = new ArrayList<>();
        String section = "";
        for (String line : text(k.getContent()).split("\n")) {
            String s = line.trim();
            if (s.startsWith("故障现象：") || s.startsWith("故障现象:")) {
                symptom = s.substring(5).trim();
                section = "symptom";
            } else if (s.startsWith("解决步骤：") || s.startsWith("解决步骤:")) {
                section = "solution";
            } else if (s.startsWith("排查步骤：") || s.startsWith("排查步骤:")
                    || s.startsWith("关键要点：") || s.startsWith("关键要点:")) {
                section = "";
            } else if ("solution".equals(section) && !s.isEmpty()) {
                measures.add(s.replaceFirst("^\\d+[.、]\\s*", ""));
            }
        }
        f.symptom = !symptom.isEmpty() ? symptom : text(k.getSummary());
        f.measures = measures;
        return f;
    }

    private static List<String> splitNumbered(String text) {
        List<String> list = new ArrayList<>();
        if (text == null || text.isBlank()) {
            return list;
        }
        for (String line : text.split("\n")) {
            String s = line.trim().replaceFirst("^\\d+[.、]\\s*", "");
            if (!s.isEmpty()) {
                list.add(s);
            }
        }
        return list;
    }

    private static String text(String s) {
        return s == null ? "" : s.trim();
    }

    private static final class KbFields {
        String symptom = "";
        List<String> measures = new ArrayList<>();
    }
}
