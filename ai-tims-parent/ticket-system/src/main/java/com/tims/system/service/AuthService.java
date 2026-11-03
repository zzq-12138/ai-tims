package com.tims.system.service;

import cn.dev33.satoken.stp.StpUtil;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.tims.common.enums.ErrorCode;
import com.tims.common.exception.BizException;
import com.tims.system.entity.SysUser;
import com.tims.system.mapper.SysUserMapper;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.stereotype.Service;

import java.time.Duration;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * 认证服务：登录（Sa-Token + Redis 会话）/ 登出 / 当前用户信息。
 * 多租户：登录成功后把 tenantId 签进会话（M2 起网关校验后透传 X-Tenant-Id，
 * 绝不信任客户端直接传的租户值）。
 *
 * M1 第二段（2026-11-03）：
 * - 密码校验切到标准 BCryptPasswordEncoder（spring-security-crypto），
 *   种子 hash $2a$10$... 与其兼容，数据不动
 * - 登录防爆破：同用户名失败 ≥5 次锁定 5 分钟（Redis 计数）
 */
@Service
public class AuthService {

    private static final String KEY_FAIL = "tims:login:fail:";
    private static final String KEY_LOCK = "tims:login:lock:";
    private static final int MAX_FAIL = 5;
    private static final Duration LOCK_DURATION = Duration.ofMinutes(5);
    private static final Duration FAIL_TTL = Duration.ofMinutes(15);

    private final SysUserMapper userMapper;
    private final StringRedisTemplate redis;
    private final BCryptPasswordEncoder passwordEncoder;

    public AuthService(SysUserMapper userMapper,
                       StringRedisTemplate redis,
                       BCryptPasswordEncoder passwordEncoder) {
        this.userMapper = userMapper;
        this.redis = redis;
        this.passwordEncoder = passwordEncoder;
    }

    public Map<String, Object> login(String username, String password) {
        if (Boolean.TRUE.equals(redis.hasKey(KEY_LOCK + username))) {
            throw new BizException(ErrorCode.LOGIN_LOCKED, "登录失败次数过多，账号已锁定，请 5 分钟后再试");
        }
        SysUser user = userMapper.selectOne(new LambdaQueryWrapper<SysUser>()
                .eq(SysUser::getUsername, username));
        if (user == null || !passwordEncoder.matches(password, user.getPassword())) {
            recordLoginFail(username);
            throw new BizException(ErrorCode.UNAUTHORIZED, "用户名或密码错误");
        }
        if (user.getStatus() != null && user.getStatus() != 1) {
            throw new BizException(ErrorCode.FORBIDDEN, "账号已停用");
        }
        redis.delete(KEY_FAIL + username);
        // 先登录建立会话，再把 tenantId 签进会话（M2 网关透传时以此为准）
        StpUtil.login(user.getId());
        StpUtil.getSession().set("tenantId", user.getTenantId() == null ? 1L : user.getTenantId());
        Map<String, Object> data = new HashMap<>();
        data.put("token", StpUtil.getTokenValue());
        data.put("nickname", user.getNickname());
        return data;
    }

    /** 失败计数：达到上限即锁定并清零计数，锁定窗口内拒绝登录 */
    private void recordLoginFail(String username) {
        String failKey = KEY_FAIL + username;
        Long fails = redis.opsForValue().increment(failKey);
        if (fails != null && fails == 1L) {
            redis.expire(failKey, FAIL_TTL);
        }
        if (fails != null && fails >= MAX_FAIL) {
            redis.opsForValue().set(KEY_LOCK + username, "1", LOCK_DURATION);
            redis.delete(failKey);
        }
    }

    public void logout() {
        StpUtil.logout();
    }

    public Map<String, Object> me() {
        long userId = StpUtil.getLoginIdAsLong();
        Long tenantId = (Long) StpUtil.getSession().get("tenantId");
        SysUser user = userMapper.selectById(userId);
        if (user == null) {
            throw new BizException(ErrorCode.NOT_FOUND, "用户不存在");
        }
        List<String> roles = userMapper.selectRoleCodes(tenantId, userId);
        Map<String, Object> data = new HashMap<>();
        data.put("userId", userId);
        data.put("username", user.getUsername());
        data.put("nickname", user.getNickname());
        data.put("tenantId", tenantId);
        data.put("roles", roles);
        return data;
    }
}
