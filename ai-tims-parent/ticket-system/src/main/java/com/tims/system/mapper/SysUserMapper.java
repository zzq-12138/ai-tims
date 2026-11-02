package com.tims.system.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.tims.system.entity.SysUser;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.util.List;

@Mapper
public interface SysUserMapper extends BaseMapper<SysUser> {

    /** 查用户角色码（同租户内） */
    @Select("""
            SELECT r.role_code
              FROM sys_user_role ur
              JOIN sys_role r ON r.id = ur.role_id AND r.deleted = 0
             WHERE ur.tenant_id = #{tenantId} AND ur.user_id = #{userId}
            """)
    List<String> selectRoleCodes(@Param("tenantId") Long tenantId, @Param("userId") Long userId);
}
