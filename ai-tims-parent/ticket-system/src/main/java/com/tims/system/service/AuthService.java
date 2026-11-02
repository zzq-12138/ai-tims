package com.tims.system.service;

import cn.dev33.satoken.secure.BCrypt;
import cn.dev33.satoken.stp.StpUtil;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.tims.common.enums.ErrorCode;
import com.tims.common.exception.BizException;
import com.tims.system.entity.SysUser;
import com.tims.system.mapper.SysUserMapper;
import org.springframework.stereotype.Service;

import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * 认证服务：登录（Sa-Token + Redis 会话）/ 登出 / 当前用户信息。
 * 多租户：登录成功后把 tenantId 签进会话（M2 起网关校验后透传 X-Tenant-Id，
 * 绝不信任客户端直接传的租户值）。
 */
@Service
public class AuthService {

    private final SysUserMapper userMapper;

    public AuthService(SysUserMapper userMapper) {
        this.userMapper = userMapper;
    }

    public Map<String, Object> login(String username, String password) {
        SysUser user = userMapper.selectOne(new LambdaQueryWrapper<SysUser>()
                .eq(SysUser::getUsername, username));
        if (user == null || !BCrypt.checkpw(password, user.getPassword())) {
            throw new BizException(ErrorCode.UNAUTHORIZED, "用户名或密码错误");
        }
        if (user.getStatus() != null && user.getStatus() != 1) {
            throw new BizException(ErrorCode.FORBIDDEN, "账号已停用");
        }
        // 先登录建立会话，再把 tenantId 签进会话（M2 网关透传时以此为准）
        StpUtil.login(user.getId());
        StpUtil.getSession().set("tenantId", user.getTenantId() == null ? 1L : user.getTenantId());
        Map<String, Object> data = new HashMap<>();
        data.put("token", StpUtil.getTokenValue());
        data.put("nickname", user.getNickname());
        return data;
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
