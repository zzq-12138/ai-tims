import com.tims.ai.route.ModelRouter;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;

/**
 * 路由离线评测入口：直接调用生产代码 ModelRouter，输出每条 query 的分流结果。
 * 用法：java -cp <build> RouteEvalMain <route_set.tsv> [threshold] [simpleModel] [complexModel]
 * 输出：id \t tier \t score \t model \t signals
 */
public class RouteEvalMain {

    public static void main(String[] args) throws Exception {
        if (args.length < 1) {
            System.err.println("usage: RouteEvalMain <tsv> [threshold] [simpleModel] [complexModel]");
            System.exit(2);
        }
        Path f = Path.of(args[0]);
        double thr = args.length > 1 ? Double.parseDouble(args[1]) : 0.5;
        String simpleModel = args.length > 2 ? args[2] : "glm-4-flash";
        String complexModel = args.length > 3 ? args[3] : "glm-5.3-flash";
        ModelRouter router = new ModelRouter(thr, simpleModel, complexModel);

        List<String> lines = Files.readAllLines(f, StandardCharsets.UTF_8);
        for (String line : lines) {
            if (line.isBlank()) {
                continue;
            }
            String[] r = line.split("\t", -1);
            if (r.length < 8) {
                continue;
            }
            ModelRouter.Input in = new ModelRouter.Input(r[3], Integer.parseInt(r[6]), "1".equals(r[7]), 0);
            ModelRouter.Decision d = router.route(in);
            StringBuilder sig = new StringBuilder();
            d.signals().forEach(s -> {
                if (sig.length() > 0) {
                    sig.append('|');
                }
                sig.append(s.name()).append(':').append(s.weight());
            });
            System.out.println(String.join("\t", r[0], d.simple() ? "simple" : "complex",
                    String.valueOf(d.score()), d.model(), sig.toString()));
        }
    }
}
