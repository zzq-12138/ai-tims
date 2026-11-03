package com.tims.ai.tool;

import java.util.ArrayList;
import java.util.List;

/**
 * 工具调用记录器：Spring AI 在请求线程内同步执行 @Tool，ThreadLocal 即可收集“调了哪个工具/参数/耗时”。
 */
public final class ToolCallRecorder {

    /** 单次工具调用记录 */
    public record Record(String name, String args, long elapsedMs, String status, String summary, boolean degraded) { }

    private static final ThreadLocal<List<Record>> HOLDER = ThreadLocal.withInitial(ArrayList::new);

    private ToolCallRecorder() {
    }

    public static void begin() {
        HOLDER.set(new ArrayList<>());
    }

    public static void add(Record record) {
        HOLDER.get().add(record);
    }

    public static List<Record> snapshot() {
        return new ArrayList<>(HOLDER.get());
    }

    public static void clear() {
        HOLDER.remove();
    }
}
