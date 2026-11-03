package com.tims.order.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.tims.order.entity.WoAttachment;
import org.apache.ibatis.annotations.Mapper;

/** 工单附件 Mapper（MyBatis-Plus BaseMapper，无 XML） */
@Mapper
public interface WoAttachmentMapper extends BaseMapper<WoAttachment> {
}
