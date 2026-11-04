package com.tims.knowledge.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.tims.knowledge.entity.KbKnowledgeHistory;
import org.apache.ibatis.annotations.Mapper;

/**
 * M6 知识历史快照 Mapper。全部 MyBatis-Plus 注解/BaseMapper，无 XML。
 */
@Mapper
public interface KbKnowledgeHistoryMapper extends BaseMapper<KbKnowledgeHistory> {
}
