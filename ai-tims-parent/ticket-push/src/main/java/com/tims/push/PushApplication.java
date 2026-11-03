package com.tims.push;

import org.mybatis.spring.annotation.MapperScan;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.scheduling.annotation.EnableScheduling;

/**
 * ticket-push 启动类：推送服务（:8105，任务书 3.7 / M4）。
 * WS 端点 /ws/push、MQ 消费 ticket.created|closed、知识卡片组装、四时间戳埋点、P95 统计。
 */
@SpringBootApplication(scanBasePackages = "com.tims")
@MapperScan("com.tims.push.mapper")
@EnableScheduling
public class PushApplication {

    public static void main(String[] args) {
        SpringApplication.run(PushApplication.class, args);
    }
}
