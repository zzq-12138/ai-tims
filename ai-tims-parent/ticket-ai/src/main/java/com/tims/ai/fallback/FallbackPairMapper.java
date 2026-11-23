package com.tims.ai.fallback;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import org.apache.ibatis.annotations.Mapper;

/** C 档兜底建议配对 Mapper（MyBatis-Plus BaseMapper，无 XML） */
@Mapper
public interface FallbackPairMapper extends BaseMapper<FallbackPair> {
}
