package com.tims.knowledge.mapper;

import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.util.List;

/**
 * 跨域鉴权查询（只读 sys_user_role/sys_role）。
 * 例外说明：注解 @Select（非 XML），与 ticket-order SysAuthMapper 同口径——
 * 仅一条跨表角色查询，走 BaseMapper 需两查 + 内存拼装，不划算。
 */
@Mapper
public interface SysAuthMapper {

    /** 查当前租户下用户角色码 */
    @Select("""
            SELECT r.role_code
              FROM sys_user_role ur
              JOIN sys_role r ON r.id = ur.role_id AND r.deleted = 0
             WHERE ur.tenant_id = #{tenantId} AND ur.user_id = #{userId}
            """)
    List<String> selectRoleCodes(@Param("tenantId") Long tenantId, @Param("userId") Long userId);
}
