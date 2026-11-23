import com.tims.ai.guard.InjectionDetector;
import com.tims.ai.guard.OutputGuard;
import com.tims.ai.guard.PiiRedactor;

import java.io.BufferedReader;
import java.io.FileReader;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/**
 * 护栏离线评测入口（不依赖 Spring / 数据库，直接复用生产核心类）。
 *
 * 用法：
 *   java GuardEvalMain injection <injection_set.tsv> <threshold>
 *   java GuardEvalMain normal    <normal_set.tsv>    <threshold>
 *   java GuardEvalMain pii       <pii_set.tsv>
 *   java GuardEvalMain output    <output_set.tsv>
 *
 * 输出：TAB 分隔，交给 scripts/ai_layer/guardrail_eval.py 聚合并生成报告。
 */
public final class GuardEvalMain {

    public static void main(String[] args) throws Exception {
        if (args.length < 2) {
            System.err.println("usage: GuardEvalMain <injection|normal|pii|output> <tsv> [threshold]");
            System.exit(2);
        }
        String mode = args[0];
        String path = args[1];
        double threshold = args.length > 2 ? Double.parseDouble(args[2]) : 0.5;
        List<String[]> rows = readTsv(path);
        for (String[] r : rows) {
            switch (mode) {
                case "injection", "normal" -> {
                    // injection: id, family, lang, text   normal: id, category, text
                    boolean isInj = "injection".equals(mode);
                    String text = isInj ? r[3] : r[2];
                    String family = r[1];
                    String lang = isInj ? r[2] : "zh";
                    InjectionDetector.Verdict v = InjectionDetector.detect(text, threshold);
                    System.out.println(String.join("\t",
                            "INJ", clean(r[0]), clean(family), clean(lang),
                            v.blocked() ? "1" : "0", String.valueOf(v.score()),
                            clean(String.join("|", v.hits()))));
                }
                case "pii" -> {
                    // id, type, text, expect
                    Map<String, String> typeToLabel = Map.of(
                            "phone", PiiRedactor.PHONE,
                            "landline", PiiRedactor.LANDLINE,
                            "idcard", PiiRedactor.ID_CARD,
                            "email", PiiRedactor.EMAIL,
                            "name", PiiRedactor.NAME,
                            "address", PiiRedactor.ADDRESS);
                    String type = r[1].trim();
                    String label = typeToLabel.getOrDefault(type, type);
                    PiiRedactor.Result res = "none".equals(type)
                            ? PiiRedactor.redact(r[2])
                            : PiiRedactor.redactOnly(r[2], label);
                    boolean detected = "none".equals(type) ? res.hit() : res.hits().containsKey(label);
                    System.out.println(String.join("\t",
                            "PII", clean(r[0]), clean(type), clean(r[3]),
                            detected ? "1" : "0", clean(res.text())));
                }
                case "output" -> {
                    // id, type, expect_blocked, expect_mask, text
                    OutputGuard.Verdict v = OutputGuard.inspect(r[4], true);
                    System.out.println(String.join("\t",
                            "OUT", clean(r[0]), clean(r[1]), clean(r[2]), clean(r[3]),
                            v.blocked() ? "1" : "0", clean(String.join("|", v.reasons())),
                            clean(v.sanitized())));
                }
                default -> throw new IllegalArgumentException("unknown mode: " + mode);
            }
        }
    }

    private static List<String[]> readTsv(String path) throws Exception {
        List<String[]> rows = new ArrayList<>();
        try (BufferedReader br = new BufferedReader(
                new FileReader(path, StandardCharsets.UTF_8))) {
            String line;
            boolean header = true;
            while ((line = br.readLine()) != null) {
                if (header) {
                    header = false;
                    continue;
                }
                if (line.isBlank()) {
                    continue;
                }
                rows.add(line.split("\t", -1));
            }
        }
        return rows;
    }

    private static String clean(String s) {
        if (s == null) {
            return "";
        }
        return s.replace('\t', ' ').replace('\n', ' ').replace('\r', ' ');
    }
}
