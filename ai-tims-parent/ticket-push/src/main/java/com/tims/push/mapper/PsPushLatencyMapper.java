package com.tims.push.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.tims.push.entity.PsPushLatency;

/** 时延埋点 Mapper（BaseMapper，禁 XML；统计聚合在 Java 侧计算，无自定义 SQL） */
public interface PsPushLatencyMapper extends BaseMapper<PsPushLatency> {
}
