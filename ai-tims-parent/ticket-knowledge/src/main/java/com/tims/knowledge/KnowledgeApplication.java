package com.tims.knowledge;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.scheduling.annotation.EnableScheduling;

/**
 * ticket-knowledge 启动类：知识库服务（:8103，任务书 3.4）。
 * EnableScheduling：向量增量同步任务（PUBLISHED → Milvus）。
 */
@SpringBootApplication(scanBasePackages = "com.tims")
@EnableScheduling
public class KnowledgeApplication {

    public static void main(String[] args) {
        SpringApplication.run(KnowledgeApplication.class, args);
    }
}
