package com.tims.knowledge.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.tims.knowledge.entity.KbCategory;
import org.apache.ibatis.annotations.Mapper;

/** 知识分类 Mapper（MyBatis-Plus BaseMapper，禁 XML） */
@Mapper
public interface KbCategoryMapper extends BaseMapper<KbCategory> {
}
