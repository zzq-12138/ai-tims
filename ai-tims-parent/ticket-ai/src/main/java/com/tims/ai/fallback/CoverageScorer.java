package com.tims.ai.fallback;

import java.text.Normalizer;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * “处置侧覆盖率”打分：分母固定取实际处置（师傅写的那段）。
 *
 * <p>做法：把处置按分句/逗号切成片段 → 逐段在建议原文里找对应表述 → 命中片段数 / 处置片段总数。
 * <p>片段匹配用“片段侧字符二元组覆盖率”：{@code |bigrams(片段) ∩ bigrams(建议)| / |bigrams(片段)|}。
 * 分母只跟片段自身长度有关，因此不受建议长度稀释（旧 Dice 正是被长建议稀释）。
 * 取 0.5 作为单段命中线：如“更换了电源模块”对“建议更换电源模块并复测”，命中 4/6 个二元组 ≈ 0.67，算命中。
 *
 * <p>已知漏判：同义改写（“电源模块” vs “电源板”）二元组几乎不重合，会被判为未命中；
 * 只做到“字面可追溯”，不做语义匹配。选用二元组而非关键词，是为了免维护词典、对中文分词错误不敏感。
 */
final class CoverageScorer {

    /** 单段命中线：片段自身的二元组有 50% 能在建议里找到 */
    static final double SEGMENT_HIT_THRESHOLD = 0.50;

    /** 少于该字符数的片段不计入分母，避免“已处理”“正常”这类噪声把分数拉高 */
    static final int MIN_SEGMENT_CHARS = 4;

    private static final String DISPOSITION_SPLIT = "[，,。；;、\\n\\r!！?？：:]+";
    private static final String SENTENCE_SPLIT = "[。；;\\n\\r!！?？]+";

    private CoverageScorer() {
    }

    /** 单个处置片段的比对结果 */
    public record Segment(String text, double coverage, boolean hit, String matchedSentence) {
    }

    /** 整体结果；segments=0 表示无法判定 */
    public record Result(double score, int hits, int segments, List<Segment> detail) {
    }

    static Result score(String suggestion, String disposition) {
        if (suggestion == null || disposition == null) {
            return null;
        }
        List<String> sentences = split(suggestion, SENTENCE_SPLIT);
        List<String> segments = split(disposition, DISPOSITION_SPLIT);
        if (segments.isEmpty()) {
            return null;
        }
        Map<String, Integer> suggestionsBigrams = new HashMap<>();
        for (String s : sentences) {
            mergeBigrams(suggestionsBigrams, normalize(s));
        }
        List<Segment> detail = new ArrayList<>();
        int hits = 0;
        for (String seg : segments) {
            String ns = normalize(seg);
            if (ns.length() < MIN_SEGMENT_CHARS) {
                continue;
            }
            double cov = bigramCoverage(ns, suggestionsBigrams);
            String best = bestSentence(ns, sentences);
            boolean hit = cov >= SEGMENT_HIT_THRESHOLD;
            if (hit) {
                hits++;
            }
            detail.add(new Segment(seg, round(cov), hit, best));
        }
        if (detail.isEmpty()) {
            return null;
        }
        double score = (double) hits / detail.size();
        return new Result(round(score), hits, detail.size(), detail);
    }

    /** 逐句算覆盖率，取最高的一句作为“命中的建议句子” */
    private static String bestSentence(String normalizedSegment, List<String> sentences) {
        String best = null;
        double bestCov = 0;
        for (String s : sentences) {
            Map<String, Integer> grams = new HashMap<>();
            mergeBigrams(grams, normalize(s));
            if (grams.isEmpty()) {
                continue;
            }
            double cov = bigramCoverage(normalizedSegment, grams);
            if (cov > bestCov) {
                bestCov = cov;
                best = s;
            }
        }
        return best == null ? null : (best.length() > 80 ? best.substring(0, 80) + "…" : best);
    }

    /** 片段二元组被候选文本覆盖的比例（多重集，避免同一二元组被重复计） */
    private static double bigramCoverage(String normalizedSegment, Map<String, Integer> candidateBigrams) {
        int total = 0;
        int hit = 0;
        Map<String, Integer> pool = new HashMap<>(candidateBigrams);
        for (int i = 0; i < normalizedSegment.length() - 1; i++) {
            String g = normalizedSegment.substring(i, i + 2);
            total++;
            Integer c = pool.get(g);
            if (c != null && c > 0) {
                hit++;
                pool.put(g, c - 1);
            }
        }
        if (total == 0) {
            return 0;
        }
        return (double) hit / total;
    }

    private static void mergeBigrams(Map<String, Integer> target, String s) {
        for (int i = 0; i < s.length() - 1; i++) {
            target.merge(s.substring(i, i + 2), 1, Integer::sum);
        }
    }

    private static List<String> split(String text, String regex) {
        List<String> out = new ArrayList<>();
        for (String part : text.split(regex)) {
            String t = part.trim();
            if (!t.isEmpty()) {
                out.add(t);
            }
        }
        return out;
    }

    static String normalize(String s) {
        String n = Normalizer.normalize(s, Normalizer.Form.NFKC).toLowerCase();
        StringBuilder sb = new StringBuilder(n.length());
        for (int i = 0; i < n.length(); i++) {
            char c = n.charAt(i);
            if (Character.isLetterOrDigit(c)) {
                sb.append(c);
            }
        }
        return sb.toString();
    }

    private static double round(double v) {
        return Math.round(v * 10000d) / 10000d;
    }

    /** 明细转可读结构（存库前由调用方序列化） */
    static List<Map<String, Object>> toPlain(List<Segment> detail) {
        List<Map<String, Object>> list = new ArrayList<>();
        for (Segment s : detail) {
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("segment", s.text());
            m.put("hit", s.hit());
            m.put("coverage", s.coverage());
            m.put("matched", s.matchedSentence());
            list.add(m);
        }
        return list;
    }
}
