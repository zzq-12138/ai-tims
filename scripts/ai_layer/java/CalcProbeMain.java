import com.tims.ai.route.ModelRouter;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;

/**
 * A1-v1 判定探针：直接调用生产 ModelRouter.calcVerifiable，输出 id \t 1/0。
 * 离线评测脚本用它代替自己写的判定，保证「评测用的规则」就是「线上用的规则」。
 * 用法：java -cp <build> CalcProbeMain <tsv> <questionCol>
 */
public class CalcProbeMain {

    public static void main(String[] args) throws Exception {
        if (args.length < 2) {
            System.err.println("usage: CalcProbeMain <tsv> <questionCol>");
            System.exit(2);
        }
        int col = Integer.parseInt(args[1]);
        List<String> lines = Files.readAllLines(Path.of(args[0]), StandardCharsets.UTF_8);
        for (String line : lines) {
            if (line.isBlank()) {
                continue;
            }
            String[] r = line.split("\t", -1);
            if (r.length <= col) {
                continue;
            }
            System.out.println(r[0] + "\t" + (ModelRouter.calcVerifiable(r[col]) ? "1" : "0"));
        }
    }
}
