package com.tims.system.config;

import cn.dev33.satoken.stp.StpUtil;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.web.context.request.RequestAttributes;
import org.springframework.web.context.request.RequestContextHolder;
import org.springframework.web.context.request.ServletRequestAttributes;

/**
 * 租户上下文解析（M2 批一）。
 * 取值优先级（防止伪造，宁可取可信来源）：
 * 1. 登录态 Sa-Token 会话中的 tenantId（登录成功时由 AuthService 签入，最权威）
 * 2. 网关透传头 X-Tenant-Id（网关 TenantHeaderFilter 从会话取出后覆盖写入，
 *    客户端传入的该头在网关侧被无条件剥离，不可伪造）
 * 3. 兜底 1：登录/注册等匿名阶段（单租户阶段恒为 1）
 */
public final class TenantContext {

    private TenantContext() {
    }

    public static Long resolve() {
        // 1) 登录态会话
        try {
            if (StpUtil.isLogin()) {
                Object v = StpUtil.getSession().get("tenantId");
                if (v instanceof Long l) return l;
                if (v instanceof Integer i) return i.longValue();
            }
        } catch (Exception ignored) {
            // 无 Web 上下文（异步线程/定时任务等）时忽略
        }
        // 2) 网关透传头（仅接受纯数字，且该头已由网关覆盖，客户端值不可达）
        RequestAttributes ra = RequestContextHolder.getRequestAttributes();
        if (ra instanceof ServletRequestAttributes sra) {
            HttpServletRequest req = sra.getRequest();
            String h = req.getHeader("X-Tenant-Id");
            if (h != null && h.matches("\\d+")) {
                return Long.parseLong(h);
            }
        }
        // 3) 兜底
        return 1L;
    }
}
