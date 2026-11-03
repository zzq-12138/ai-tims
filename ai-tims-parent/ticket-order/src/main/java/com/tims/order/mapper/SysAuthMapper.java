package com.tims.order.mapper;

import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.util.List;
import java.util.Map;

/**
 * 跨域鉴权/用户信息查询（只读 sys_user/sys_role/sys_user_role）。
 * 网关已验签，本服务只做业务权限判断（受理/转派/终止等）。
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

    /** 用户简单信息（id/nickname/status） */
    @Select("""
            SELECT id, nickname, status FROM sys_user
             WHERE tenant_id = #{tenantId} AND id = #{userId} AND deleted = 0
            """)
    Map<String, Object> selectUserSimple(@Param("tenantId") Long tenantId, @Param("userId") Long userId);
}
