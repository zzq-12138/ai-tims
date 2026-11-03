package com.tims.order.controller;

import com.tims.common.api.Result;
import com.tims.order.dto.MockBatchDTO;
import com.tims.order.entity.WoMockConfig;
import com.tims.order.service.MockService;
import jakarta.validation.Valid;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

/**
 * 数据模拟接口（任务书 §6.3 #16 + 批量建单辅助接口）。
 * /mock/batch 为任务书清单外新增：命令行或接口触发批量造数（M3 评测/M4 压测复用）。
 */
@RestController
@RequestMapping("/api/order/mock")
public class MockController {

    private final MockService mockService;

    public MockController(MockService mockService) {
        this.mockService = mockService;
    }

    /** 批量建样本工单（默认 200 条，上限 tims.order.mock-batch-max） */
    @PostMapping("/batch")
    public Result<Integer> batch(@Valid @RequestBody MockBatchDTO dto) {
        return Result.ok(mockService.batchCreate(dto.getCount(), dto.getFactory()));
    }

    /** 模拟配置列表 */
    @GetMapping("/config")
    public Result<List<WoMockConfig>> listConfig() {
        return Result.ok(mockService.listConfig());
    }

    /** 新增模拟配置 */
    @PostMapping("/config")
    public Result<WoMockConfig> createConfig(@RequestBody WoMockConfig config) {
        return Result.ok(mockService.createConfig(config));
    }

    /** 启停切换，返回切换后状态（1 启用 / 0 停用） */
    @PostMapping("/config/{id}/toggle")
    public Result<Integer> toggle(@PathVariable Long id) {
        return Result.ok(mockService.toggleConfig(id));
    }
}
