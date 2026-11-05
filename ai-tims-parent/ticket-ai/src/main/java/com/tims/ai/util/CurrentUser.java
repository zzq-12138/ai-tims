package com.tims.ai.util;

import cn.dev33.satoken.stp.StpUtil;
import com.tims.common.enums.ErrorCode;
import com.tims.common.exception.BizException;

/**
 * 当前登录用户（M6 安全修正）。
 * userId 一律从 Sa-Token 登录会话解析，不再信任客户端声明的 userId；
 * tenantId 优先取网关透传的 X-Tenant-Id（网关已剥离客户端伪造值），缺失时回退登录会话，最后兜底 1。
 * 未登录统一抛 10401（HTTP 401，走全局异常处理口径）。
 */
public final class CurrentUser {

    private CurrentUser() {
    }

    public static Long id() {
        try {
            if (StpUtil.isLogin()) {
                return StpUtil.getLoginIdAsLong();
            }
        } catch (Exception ignored) {
            // token 无效/会话缺失，统一按未登录处理
        }
        throw new BizException(ErrorCode.UNAUTHORIZED.getCode(), ErrorCode.UNAUTHORIZED.getMessage());
    }

    public static Long tenantId() {
        Long fromHeader = RequestUtils.tenantIdOrNull();
        if (fromHeader != null) {
            return fromHeader;
        }
        try {
            if (StpUtil.isLogin()) {
                Object v = StpUtil.getSession().get("tenantId");
                if (v instanceof Long l) return l;
                if (v instanceof Integer i) return i.longValue();
                if (v != null) return Long.parseLong(String.valueOf(v));
            }
        } catch (Exception ignored) {
            // 无会话时走兜底
        }
        return 1L;
    }
}
