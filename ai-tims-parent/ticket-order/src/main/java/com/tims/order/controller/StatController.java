package com.tims.order.controller;

import com.tims.common.api.Result;
import com.tims.order.service.StatService;
import com.tims.order.vo.OverviewVO;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;
import java.util.Map;

/**
 * 统计接口（任务书 §6.3 #17 #18）。
 */
@RestController
@RequestMapping("/api/order")
public class StatController {

    private final StatService statService;

    public StatController(StatService statService) {
        this.statService = statService;
    }

    /** #17 模拟指标最新值（M2 stub：Redis 直读，M4 由模拟引擎写入） */
    @GetMapping("/metric/latest")
    public Result<List<Map<String, Object>>> metricLatest() {
        return Result.ok(statService.metricLatest());
    }

    /** #18 统计概览：todoCount/todayCreated/closedRate/adoptionRate */
    @GetMapping("/stat/overview")
    public Result<OverviewVO> overview() {
        return Result.ok(statService.overview());
    }
}
