package com.tims.push;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

/**
 * ticket-push 启动类：推送服务（:8105，任务书 3.7）。
 */
@SpringBootApplication(scanBasePackages = "com.tims")
public class PushApplication {

    public static void main(String[] args) {
        SpringApplication.run(PushApplication.class, args);
    }
}
