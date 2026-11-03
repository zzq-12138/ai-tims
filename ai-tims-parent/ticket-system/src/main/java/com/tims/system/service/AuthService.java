package com.tims.system.service;

import cn.dev33.satoken.stp.StpUtil;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.tims.common.enums.ErrorCode;
import com.tims.common.exception.BizException;
import com.tims.system.entity.SysUser;
import com.tims.system.mapper.SysUserMapper;
import org.springframework.beans.factory.annotation.Value;
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
 * M2 批一（2026-11-03）：登录防爆破升级为双维度，阈值可配（tims.login-protection.*）：
 * - 用户名维度：同一用户名失败 ≥5 次，锁定 15 分钟
 * - IP 维度：同一 IP 失败 ≥10 次（10 分钟窗口），封禁 30 分钟
 * 两者任一触发即拒绝登录。
 */
@Service
public class AuthService {

    /** 用户名维度：失败计数 / 锁定标记 */
    private static final String KEY_FAIL_USER = "tims:login:fail:user:";
    private static final String KEY_LOCK_USER = "tims:login:lock:user:";
    /** IP 维度：失败计数（滑动窗口内累计）/ 封禁标记 */
    private static final String KEY_FAIL_IP = "tims:login:fail:ip:";
    private static final String KEY_BAN_IP = "tims:login:ban:ip:";

    @Value("${tims.login-protection.username-max-fail:5}")
    private int usernameMaxFail;
    @Value("${tims.login-protection.username-lock-minutes:15}")
    private int usernameLockMinutes;
    @Value("${tims.login-protection.username-window-minutes:15}")
    private int usernameWindowMinutes;
    @Value("${tims.login-protection.ip-max-fail:10}")
    private int ipMaxFail;
    @Value("${tims.login-protection.ip-window-minutes:10}")
    private int ipWindowMinutes;
    @Value("${tims.login-protection.ip-ban-minutes:30}")
    private int ipBanMinutes;

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

    public Map<String, Object> login(String username, String password, String ip) {
        // 双维度前置检查：IP 封禁 / 用户名锁定，任一触发即拒
        if (Boolean.TRUE.equals(redis.hasKey(KEY_BAN_IP + ip))) {
            throw new BizException(ErrorCode.LOGIN_LOCKED,
                    "该 IP 登录失败次数过多，已被封禁 " + ipBanMinutes + " 分钟");
        }
        if (Boolean.TRUE.equals(redis.hasKey(KEY_LOCK_USER + username))) {
            throw new BizException(ErrorCode.LOGIN_LOCKED,
                    "登录失败次数过多，账号已锁定，请 " + usernameLockMinutes + " 分钟后再试");
        }
        SysUser user = userMapper.selectOne(new LambdaQueryWrapper<SysUser>()
                .eq(SysUser::getUsername, username));
        if (user == null || !passwordEncoder.matches(password, user.getPassword())) {
            recordUserFail(username);
            recordIpFail(ip);
            throw new BizException(ErrorCode.UNAUTHORIZED, "用户名或密码错误");
        }
        if (user.getStatus() != null && user.getStatus() != 1) {
            throw new BizException(ErrorCode.FORBIDDEN, "账号已停用");
        }
        redis.delete(KEY_FAIL_USER + username);
        // 先登录建立会话，再把 tenantId 签进会话（网关透传时以此为准）
        StpUtil.login(user.getId());
        StpUtil.getSession().set("tenantId", user.getTenantId() == null ? 1L : user.getTenantId());
        Map<String, Object> data = new HashMap<>();
        data.put("token", StpUtil.getTokenValue());
        data.put("nickname", user.getNickname());
        return data;
    }

    /** 用户名维度失败计数：窗口内达到上限即锁定并清零计数 */
    private void recordUserFail(String username) {
        String failKey = KEY_FAIL_USER + username;
        Long fails = redis.opsForValue().increment(failKey);
        if (fails != null && fails == 1L) {
            redis.expire(failKey, Duration.ofMinutes(usernameWindowMinutes));
        }
        if (fails != null && fails >= usernameMaxFail) {
            redis.opsForValue().set(KEY_LOCK_USER + username, "1",
                    Duration.ofMinutes(usernameLockMinutes));
            redis.delete(failKey);
        }
    }

    /** IP 维度失败计数：窗口内达到上限即封禁并清零计数 */
    private void recordIpFail(String ip) {
        if (ip == null || ip.isBlank()) {
            return;
        }
        String failKey = KEY_FAIL_IP + ip;
        Long fails = redis.opsForValue().increment(failKey);
        if (fails != null && fails == 1L) {
            redis.expire(failKey, Duration.ofMinutes(ipWindowMinutes));
        }
        if (fails != null && fails >= ipMaxFail) {
            redis.opsForValue().set(KEY_BAN_IP + ip, "1",
                    Duration.ofMinutes(ipBanMinutes));
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
