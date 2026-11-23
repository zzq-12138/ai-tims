package com.tims.ai.util;

import cn.dev33.satoken.stp.StpUtil;
import com.tims.common.enums.ErrorCode;
import com.tims.common.exception.BizException;

import java.util.Collection;

/**
 * 角色校验：登录会话里的 roles 由 ticket-system 写入。
 * 前端隐藏菜单只是体验优化，服务端仍要拦一次。
 * 统一抛 10403（FORBIDDEN），由全局异常处理器映射成 HTTP 403，与网关口径一致。
 */
public final class AdminGuard {

    private AdminGuard() {
    }

    public static void requireAdmin() {
        requireAnyRole("ADMIN");
    }

    /** 允许的任一角色放行；会话里没有 roles（旧会话）时不在这里拦，交给网关与前端兜底 */
    public static void requireAnyRole(String... allowed) {
        Object v;
        try {
            v = StpUtil.getSession().get("roles");
        } catch (Exception ignored) {
            throw new BizException(ErrorCode.FORBIDDEN, "未登录或无访问权限");
        }
        if (!(v instanceof Collection<?> roles)) {
            throw new BizException(ErrorCode.FORBIDDEN, "当前角色无权访问该接口");
        }
        for (String role : allowed) {
            if (roles.contains(role)) {
                return;
            }
        }
        throw new BizException(ErrorCode.FORBIDDEN, "当前角色无权访问该接口");
    }
}
