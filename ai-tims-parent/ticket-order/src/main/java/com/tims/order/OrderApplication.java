package com.tims.order;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

/**
 * ticket-order 启动类：工单服务（:8102，任务书 3.4）。
 */
@SpringBootApplication(scanBasePackages = "com.tims")
public class OrderApplication {

    public static void main(String[] args) {
        SpringApplication.run(OrderApplication.class, args);
    }
}
