package com.tims.order.service;

import cn.dev33.satoken.stp.StpUtil;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.tims.common.enums.ErrorCode;
import com.tims.common.exception.BizException;
import com.tims.order.config.TenantContext;
import com.tims.order.dto.TicketCreateDTO;
import com.tims.order.entity.WoMockConfig;
import com.tims.order.mapper.WoMockConfigMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDateTime;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ThreadLocalRandom;

/**
 * 数据模拟服务（M2 批二）：
 * - 批量建单：加权随机生成不同设备类型/工单类型/紧急程度的样本工单（M3 评测、M4 压测复用）；
 * - mock config CRUD 与启停（§6.3 #16）。
 * 说明：接口为任务书 #18 清单外的新增辅助接口（/api/order/mock/batch），任务书仅要求
 * 「模拟数据 + 自动建单」，此处提供命令行/接口双触发的批量样本能力。
 */
@Service
public class MockService {

    private static final Logger log = LoggerFactory.getLogger(MockService.class);

    /** 设备类型池（正态加权：贴片机占比最高） */
    private static final String[] DEVICE_TYPES =
            {"贴片机", "AOI检测机", "涂布机", "贴合机", "蚀刻机"};
    private static final int[] DEVICE_WEIGHTS = {30, 25, 20, 15, 10};
    /** 工单类型池（加权） */
    private static final String[] TICKET_TYPES = {"设备异常", "品质异常", "系统异常", "其他"};
    private static final int[] TYPE_WEIGHTS = {50, 25, 15, 10};
    /** 紧急程度分布：1高 20% / 2中 50% / 3低 30% */
    private static final int[] URGENCY_POOL = {1, 1, 2, 2, 2, 2, 2, 3, 3, 3};

    private final WoMockConfigMapper configMapper;
    private final TicketService ticketService;
    private final DispatchService dispatchService;

    @Value("${tims.order.mock-batch-max:500}")
    private int batchMax;

    public MockService(WoMockConfigMapper configMapper,
                       TicketService ticketService,
                       DispatchService dispatchService) {
        this.configMapper = configMapper;
        this.ticketService = ticketService;
        this.dispatchService = dispatchService;
    }

    /**
     * 批量建样本工单：trigger_type=RULE，全部走规则预填派发，状态 SUBMITTED。
     *
     * @return 实际创建条数
     */
    @Transactional
    public int batchCreate(int count, String factory) {
        if (count > batchMax) {
            throw new BizException(ErrorCode.BAD_REQUEST,
                    "单次批量上限 " + batchMax + " 条，当前请求 " + count + " 条");
        }
        Long tenantId;
        try {
            StpUtil.getLoginIdAsLong(); // 未登录时抛出，落到 UNAUTHORIZED
            tenantId = TenantContext.resolve();
        } catch (BizException e) {
            throw e;
        } catch (Exception e) {
            throw new BizException(ErrorCode.UNAUTHORIZED, "未登录或凭证失效");
        }
        ThreadLocalRandom rnd = ThreadLocalRandom.current();
        int created = 0;
        for (int i = 0; i < count; i++) {
            String deviceType = weightedPick(DEVICE_TYPES, DEVICE_WEIGHTS, rnd);
            String ticketType = weightedPick(TICKET_TYPES, TYPE_WEIGHTS, rnd);
            int urgency = URGENCY_POOL[rnd.nextInt(URGENCY_POOL.length)];

            TicketCreateDTO dto = new TicketCreateDTO();
            dto.setTitle(deviceType + ticketType + "-模拟#" + (System.nanoTime() % 100000));
            dto.setTicketType(ticketType);
            dto.setFactory(factory);
            dto.setPlant("P1");
            dto.setDeviceType(deviceType);
            dto.setGlassId("GLS" + String.format("%010d", rnd.nextLong(1_000_000_000L)));
            dto.setAbnormalTime(LocalDateTime.now().minusMinutes(rnd.nextLong(1, 7 * 24 * 60)));
            dto.setUrgency(urgency);
            dto.setDescription("模拟工单：" + deviceType + "发生" + ticketType
                    + "，指标越限触发自动上报，请尽快安排处理。");
            dto.setDraft(false);

            ticketService.create(dto);
            created++;
        }
        log.info("模拟批量建单完成 count={} factory={} tenant={}", created, factory, tenantId);
        return created;
    }

    private String weightedPick(String[] values, int[] weights, ThreadLocalRandom rnd) {
        int total = 0;
        for (int w : weights) total += w;
        int x = rnd.nextInt(total);
        for (int i = 0; i < values.length; i++) {
            x -= weights[i];
            if (x < 0) return values[i];
        }
        return values[values.length - 1];
    }

    // ------------------------------------------------------------------
    // mock config（§6.3 #16）
    // ------------------------------------------------------------------

    public List<WoMockConfig> listConfig() {
        return configMapper.selectList(new LambdaQueryWrapper<WoMockConfig>()
                .orderByAsc(WoMockConfig::getId));
    }

    public WoMockConfig createConfig(WoMockConfig config) {
        config.setId(null);
        config.setEnabled(config.getEnabled() == null ? 0 : config.getEnabled());
        configMapper.insert(config);
        return config;
    }

    /** 启停切换，返回切换后的状态（1/0） */
    public int toggleConfig(Long id) {
        WoMockConfig c = configMapper.selectById(id);
        if (c == null) {
            throw new BizException(ErrorCode.NOT_FOUND, "模拟配置不存在");
        }
        int next = (c.getEnabled() != null && c.getEnabled() == 1) ? 0 : 1;
        WoMockConfig patch = new WoMockConfig();
        patch.setId(id);
        patch.setEnabled(next);
        configMapper.updateById(patch);
        return next;
    }
}
