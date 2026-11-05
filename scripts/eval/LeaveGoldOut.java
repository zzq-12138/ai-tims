import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.milvus.client.MilvusServiceClient;
import io.milvus.param.ConnectParam;
import io.milvus.param.R;
import io.milvus.param.collection.FlushParam;
import io.milvus.param.dml.DeleteParam;
import io.milvus.param.dml.InsertParam;
import io.milvus.param.dml.QueryParam;
import io.milvus.response.QueryResultsWrapper;

import java.io.BufferedReader;
import java.io.BufferedWriter;
import java.io.FileWriter;
import java.net.URI;
import java.net.URLEncoder;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.concurrent.TimeUnit;

/**
 * leave-gold-out 执行器（M7 追加任务）。
 * 用法:
 *   status                 打印集合条数与前 10 个主键
 *   run <in.tsv> <out.tsv>  逐条：快照 gold -> 删除 -> 验证已消失 -> HTTP VECTOR topK=5 -> 恢复 -> 验证
 * in.tsv 每行: idx \t query \t goldId1,goldId2
 */
public class LeaveGoldOut {
    static final String COLL = "kb_knowledge_vec";
    static final String BASE = "http://127.0.0.1:8103";
    static final ObjectMapper MAPPER = new ObjectMapper();

    static MilvusServiceClient client;

    public static void main(String[] args) throws Exception {
        client = new MilvusServiceClient(ConnectParam.newBuilder()
                .withHost("127.0.0.1").withPort(19530)
                .withConnectTimeout(5, TimeUnit.SECONDS)
                .withRpcDeadline(10, TimeUnit.SECONDS)
                .build());
        try {
            if (args[0].equals("status")) {
                System.out.println("count=" + count());
                List<Long> ids = new ArrayList<>();
                R<io.milvus.grpc.QueryResults> r = client.query(QueryParam.newBuilder()
                        .withCollectionName(COLL).withExpr("knowledge_id >= 0")
                        .withOutFields(List.of("knowledge_id")).withLimit(200L).build());
                QueryResultsWrapper w = new QueryResultsWrapper(r.getData());
                for (Object o : w.getFieldWrapper("knowledge_id").getFieldData()) ids.add((Long) o);
                System.out.println("ids=" + ids);
            } else if (args[0].equals("run")) {
                run(args[1], args[2]);
            } else if (args[0].equals("purge")) {
                purge(args[1]);
            }
        } finally {
            client.close();
        }
    }

    static long count() {
        R<io.milvus.grpc.QueryResults> r = client.query(QueryParam.newBuilder()
                .withCollectionName(COLL).withExpr("knowledge_id >= 0")
                .withOutFields(List.of("count(*)")).build());
        QueryResultsWrapper w = new QueryResultsWrapper(r.getData());
        return ((Number) w.getFieldWrapper("count(*)").getFieldData().get(0)).longValue();
    }

    /** 按主键取回整行（含 1024 维向量），用于快照 */
    @SuppressWarnings("unchecked")
    static List<Object> fetch(List<Long> ids) {
        R<io.milvus.grpc.QueryResults> r = client.query(QueryParam.newBuilder()
                .withCollectionName(COLL)
                .withExpr("knowledge_id in " + ids.toString())
                .withOutFields(Arrays.asList("knowledge_id", "tenant_id", "device_type", "embedding"))
                .withLimit(200L).build());
        QueryResultsWrapper w = new QueryResultsWrapper(r.getData());
        List<Long> kid = (List<Long>) w.getFieldWrapper("knowledge_id").getFieldData();
        List<Long> tid = (List<Long>) w.getFieldWrapper("tenant_id").getFieldData();
        Object devRaw = w.getFieldWrapper("device_type").getFieldData();
        Object vecRaw = w.getFieldWrapper("embedding").getFieldData();
        return Arrays.asList(kid, tid, devRaw, vecRaw);
    }

    @SuppressWarnings("unchecked")
    static void restore(List<Object> snap) {
        List<Long> kid = (List<Long>) snap.get(0);
        List<Long> tid = (List<Long>) snap.get(1);
        List<String> dev = (List<String>) snap.get(2);
        List<List<Float>> vec = (List<List<Float>>) snap.get(3);
        List<InsertParam.Field> fields = new ArrayList<>();
        fields.add(new InsertParam.Field("knowledge_id", kid));
        fields.add(new InsertParam.Field("tenant_id", tid));
        fields.add(new InsertParam.Field("device_type", dev));
        fields.add(new InsertParam.Field("embedding", vec));
        R<?> ir = client.insert(InsertParam.newBuilder()
                .withCollectionName(COLL).withFields(fields).build());
        if (ir.getStatus() != R.Status.Success.getCode()) {
            throw new IllegalStateException("restore insert failed: " + ir.getMessage());
        }
    }

    static void delete(List<Long> ids) {
        R<?> r = client.delete(DeleteParam.newBuilder()
                .withCollectionName(COLL).withExpr("knowledge_id in " + ids.toString()).build());
        if (r.getStatus() != R.Status.Success.getCode()) {
            throw new IllegalStateException("delete failed: " + r.getMessage());
        }
    }

    static void flush() {
        client.flush(FlushParam.newBuilder().withCollectionNames(List.of(COLL)).build());
    }

    /** 清理残留向量：按主键删除 + flush + 校验消失（仅用于逻辑删除的知识条目） */
    static void purge(String csv) throws Exception {
        List<Long> ids = new ArrayList<>();
        for (String x : csv.split(",")) ids.add(Long.parseLong(x.trim()));
        long before = count();
        delete(ids);
        flush();
        long after = count();
        for (int i = 0; i < 30 && after == before; i++) {
            Thread.sleep(1000);
            flush();
            after = count();
        }
        System.out.println("[PURGE] count " + before + " -> " + after + " (removed=" + (before - after) + ")");
        for (Long id : ids) System.out.println("[PURGE] id=" + id + " present=" + present(id));
    }

    static boolean present(long id) {
        R<io.milvus.grpc.QueryResults> r = client.query(QueryParam.newBuilder()
                .withCollectionName(COLL).withExpr("knowledge_id == " + id)
                .withOutFields(List.of("knowledge_id")).withLimit(1L).build());
        QueryResultsWrapper w = new QueryResultsWrapper(r.getData());
        return !w.getFieldWrapper("knowledge_id").getFieldData().isEmpty();
    }

    static boolean waitAbsent(long id, long ms) throws Exception {
        long t0 = System.currentTimeMillis();
        while (System.currentTimeMillis() - t0 < ms) {
            if (!present(id)) return true;
            Thread.sleep(150);
        }
        return false;
    }

    static boolean waitPresent(long id, long ms) throws Exception {
        long t0 = System.currentTimeMillis();
        while (System.currentTimeMillis() - t0 < ms) {
            if (present(id)) return true;
            Thread.sleep(150);
        }
        return false;
    }

    static String searchTop(String query) throws Exception {
        String url = BASE + "/api/kb/search?mode=VECTOR&topK=5&query="
                + URLEncoder.encode(query, StandardCharsets.UTF_8);
        HttpClient hc = HttpClient.newBuilder().connectTimeout(java.time.Duration.ofSeconds(5)).build();
        HttpRequest req = HttpRequest.newBuilder(URI.create(url))
                .timeout(java.time.Duration.ofSeconds(15)).GET().build();
        HttpResponse<String> resp = hc.send(req, HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
        JsonNode root = MAPPER.readTree(resp.body());
        JsonNode data = root.path("data");
        JsonNode items = data.path("items");
        StringBuilder sb = new StringBuilder();
        for (int i = 0; i < items.size(); i++) {
            if (i > 0) sb.append(',');
            sb.append(items.get(i).path("id").asLong()).append(':').append(items.get(i).path("score").asDouble());
        }
        String top1 = items.size() == 0 ? "NA" : items.get(0).path("score").asDouble() + "";
        String top1id = items.size() == 0 ? "NA" : items.get(0).path("id").asLong() + "";
        return top1 + "\t" + top1id + "\t" + data.path("fallback").asBoolean() + "\t" + sb;
    }

    static void run(String in, String out) throws Exception {
        long n0 = count();
        System.out.println("[START] vector count N0=" + n0);
        List<String> lines = Files.readAllLines(Paths.get(in), StandardCharsets.UTF_8);
        try (BufferedWriter bw = new BufferedWriter(new FileWriter(out, StandardCharsets.UTF_8))) {
            bw.write("idx\tgold_removed\tstatus\ttop1_score\ttop1_id\tfallback\ttop5\n");
            int n = 0;
            for (String line : lines) {
                if (line.trim().isEmpty() || line.startsWith("idx\t")) continue;
                String[] p = line.split("\t");
                long idx = Long.parseLong(p[0].trim());
                String q = p[1];
                List<Long> gids = new ArrayList<>();
                for (String s : p[2].split(",")) gids.add(Long.parseLong(s.trim()));

                List<Object> snap = fetch(gids);
                if (((List<?>) snap.get(0)).isEmpty()) {
                    bw.write(idx + "\t0\tNOT_IN_VECTOR\tNA\tNA\tNA\tNA\n");
                    n++;
                    continue;
                }
                delete(gids);
                boolean gone = true;
                for (Long g : gids) gone &= waitAbsent(g, 4000);
                String row = searchTop(q);
                restore(snap);
                boolean back = true;
                for (Long g : gids) back &= waitPresent(g, 5000);
                if (n % 10 == 0) flush();
                bw.write(idx + "\t" + (gone ? 1 : 0) + "\t" + (back ? "OK" : "RESTORE_FAILED") + "\t" + row + "\n");
                bw.flush();
                n++;
                System.out.println("[LOGOUT] idx=" + idx + " gone=" + gone + " back=" + back + " " + row.split("\t")[0]);
            }
            flush();
            long n1 = count();
            System.out.println("[END] vector count N1=" + n1 + " restoredRows=" + n);
            bw.write("#N0\t" + n0 + "\n#N1\t" + n1 + "\n");
        }
    }
}
