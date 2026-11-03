package com.tims.knowledge.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.tims.knowledge.entity.KbKnowledge;
import org.apache.ibatis.annotations.Mapper;

/** 知识点 Mapper（MyBatis-Plus BaseMapper，禁 XML） */
@Mapper
public interface KbKnowledgeMapper extends BaseMapper<KbKnowledge> {
}
