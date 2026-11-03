package com.tims.order.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.tims.order.entity.WoTicket;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.util.List;

@Mapper
public interface WoTicketMapper extends BaseMapper<WoTicket> {

    /**
     * 相似历史工单（§6.3 #14）：MySQL 全文索引 MATCH AGAINST（ngram）。
     * TenantLineInnerInterceptor 自动追加 tenant_id 条件。
     */
    @Select("""
            SELECT * FROM wo_ticket
             WHERE deleted = 0
               AND id != #{excludeId}
               AND MATCH(title, description) AGAINST(#{keywords} IN NATURAL LANGUAGE MODE)
             ORDER BY MATCH(title, description) AGAINST(#{keywords} IN NATURAL LANGUAGE MODE) DESC
             LIMIT #{limit}
            """)
    List<WoTicket> searchSimilar(@Param("keywords") String keywords,
                                 @Param("excludeId") Long excludeId,
                                 @Param("limit") int limit);
}
