package com.tims.system.service;

import cn.dev33.satoken.stp.StpUtil;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.tims.common.api.PageResult;
import com.tims.common.enums.ErrorCode;
import com.tims.common.exception.BizException;
import com.tims.system.config.TenantContext;
import com.tims.system.dto.UserUpsertDTO;
import com.tims.system.entity.SysRole;
import com.tims.system.entity.SysUser;
import com.tims.system.entity.SysUserRole;
import com.tims.system.mapper.SysRoleMapper;
import com.tims.system.mapper.SysUserMapper;
import com.tims.system.mapper.SysUserRoleMapper;
import com.tims.system.vo.UserVO;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;

/**
 * 用户管理（§6.2 #3-6，M2 批二）：分页/新增/编辑/逻辑删除，ADMIN 守卫。
 * 密码策略与注册一致（≥8 位，含大小写+数字+特殊字符），BCrypt 加密；
 * 新增未指定角色时默认挂 USER 角色（按 role_code 查，不硬编码 roleId）。
 */
@Service
public class UserService {

    /** 与 RegisterService 同规则：≥8 位，含大写/小写/数字/特殊字符 */
    private static final String PASSWORD_REGEX =
            "^(?=.*[a-z])(?=.*[A-Z])(?=.*\\d)(?=.*[^0-9a-zA-Z]).{8,64}$";

    private static final String DEFAULT_ROLE_CODE = "USER";

    private final SysUserMapper userMapper;
    private final SysUserRoleMapper userRoleMapper;
    private final SysRoleMapper roleMapper;
    private final BCryptPasswordEncoder passwordEncoder;

    public UserService(SysUserMapper userMapper,
                       SysUserRoleMapper userRoleMapper,
                       SysRoleMapper roleMapper,
                       BCryptPasswordEncoder passwordEncoder) {
        this.userMapper = userMapper;
        this.userRoleMapper = userRoleMapper;
        this.roleMapper = roleMapper;
        this.passwordEncoder = passwordEncoder;
    }

    /** ADMIN 守卫：非管理员一律 10403 */
    public void requireAdmin() {
        long userId = StpUtil.getLoginIdAsLong();
        Long tenantId = TenantContext.resolve();
        List<String> roles = userMapper.selectRoleCodes(tenantId, userId);
        if (!roles.contains("ADMIN")) {
            throw new BizException(ErrorCode.FORBIDDEN, "仅系统管理员可执行用户管理操作");
        }
    }

    /** 分页：keyword 模糊匹配 用户名/姓名/手机号/邮箱 */
    public PageResult<UserVO> page(String keyword, long page, long size) {
        requireAdmin();
        LambdaQueryWrapper<SysUser> w = new LambdaQueryWrapper<>();
        if (keyword != null && !keyword.isBlank()) {
            String kw = keyword.trim();
            w.and(x -> x.like(SysUser::getUsername, kw)
                    .or().like(SysUser::getNickname, kw)
                    .or().like(SysUser::getPhone, kw)
                    .or().like(SysUser::getEmail, kw));
        }
        w.orderByDesc(SysUser::getCreateTime);
        Page<SysUser> p = userMapper.selectPage(new Page<>(page, size), w);
        List<UserVO> records = p.getRecords().stream().map(this::toVO).toList();
        return PageResult.of(records, p.getTotal(), page, size);
    }

    @Transactional
    public Long create(UserUpsertDTO dto) {
        requireAdmin();
        validate(dto, true);
        String username = dto.getUsername().trim();
        if (userMapper.selectCount(new LambdaQueryWrapper<SysUser>()
                .eq(SysUser::getUsername, username)) > 0) {
            throw new BizException(ErrorCode.CONFLICT, "用户名已存在");
        }
        if (dto.getPhone() != null && !dto.getPhone().isBlank()
                && userMapper.selectCount(new LambdaQueryWrapper<SysUser>()
                .eq(SysUser::getPhone, dto.getPhone().trim())) > 0) {
            throw new BizException(ErrorCode.CONFLICT, "手机号已被使用");
        }
        if (dto.getEmail() != null && !dto.getEmail().isBlank()
                && userMapper.selectCount(new LambdaQueryWrapper<SysUser>()
                .eq(SysUser::getEmail, dto.getEmail().trim())) > 0) {
            throw new BizException(ErrorCode.CONFLICT, "邮箱已被使用");
        }

        SysUser u = new SysUser();
        u.setUsername(username);
        u.setPassword(passwordEncoder.encode(dto.getPassword()));
        u.setNickname(dto.getNickname().trim());
        u.setDeptId(dto.getDeptId());
        u.setFactory(dto.getFactory());
        u.setPhone(dto.getPhone() == null || dto.getPhone().isBlank() ? null : dto.getPhone().trim());
        u.setEmail(dto.getEmail() == null || dto.getEmail().isBlank() ? null : dto.getEmail().trim());
        u.setStatus(dto.getStatus() == null ? 1 : dto.getStatus());
        u.setTenantId(TenantContext.resolve());
        userMapper.insert(u);

        saveRoles(u.getId(), u.getTenantId(), dto.getRoleIds());
        return u.getId();
    }

    @Transactional
    public void update(Long id, UserUpsertDTO dto) {
        requireAdmin();
        SysUser u = userMapper.selectById(id);
        if (u == null) {
            throw new BizException(ErrorCode.NOT_FOUND, "用户不存在");
        }
        if (dto.getPassword() != null && !dto.getPassword().isBlank()) {
            if (!dto.getPassword().matches(PASSWORD_REGEX)) {
                throw new BizException(ErrorCode.BAD_REQUEST,
                        "密码需≥8位且同时包含大写字母、小写字母、数字和特殊字符");
            }
            u.setPassword(passwordEncoder.encode(dto.getPassword()));
        }
        if (dto.getNickname() != null) u.setNickname(dto.getNickname().trim());
        if (dto.getDeptId() != null) u.setDeptId(dto.getDeptId());
        if (dto.getFactory() != null) u.setFactory(dto.getFactory());
        if (dto.getPhone() != null) u.setPhone(dto.getPhone().trim());
        if (dto.getEmail() != null) u.setEmail(dto.getEmail().trim());
        if (dto.getStatus() != null) u.setStatus(dto.getStatus());
        userMapper.updateById(u);
        if (dto.getRoleIds() != null) {
            saveRoles(id, u.getTenantId(), dto.getRoleIds());
        }
    }

    /** 逻辑删除用户 + 清理角色关联 */
    @Transactional
    public void delete(Long id) {
        requireAdmin();
        if (userMapper.selectById(id) == null) {
            throw new BizException(ErrorCode.NOT_FOUND, "用户不存在");
        }
        userMapper.deleteById(id);
        userRoleMapper.delete(new LambdaQueryWrapper<SysUserRole>()
                .eq(SysUserRole::getUserId, id));
    }

    /** 保存用户-角色关联；空列表时默认挂 USER 角色（按 role_code 查） */
    private void saveRoles(Long userId, Long tenantId, List<Long> roleIds) {
        userRoleMapper.delete(new LambdaQueryWrapper<SysUserRole>()
                .eq(SysUserRole::getUserId, userId));
        List<Long> ids = roleIds;
        if (ids == null || ids.isEmpty()) {
            SysRole role = roleMapper.selectOne(new LambdaQueryWrapper<SysRole>()
                    .eq(SysRole::getRoleCode, DEFAULT_ROLE_CODE));
            if (role == null) {
                throw new BizException(ErrorCode.INTERNAL_ERROR, "默认角色缺失，请检查种子数据");
            }
            ids = List.of(role.getId());
        }
        for (Long roleId : ids) {
            SysUserRole ur = new SysUserRole();
            ur.setTenantId(tenantId);
            ur.setUserId(userId);
            ur.setRoleId(roleId);
            userRoleMapper.insert(ur);
        }
    }

    /** 新增时的必填与密码策略校验 */
    private void validate(UserUpsertDTO dto, boolean isCreate) {
        if (isCreate) {
            if (dto.getUsername() == null || dto.getUsername().isBlank()) {
                throw new BizException(ErrorCode.BAD_REQUEST, "用户名不能为空");
            }
            if (dto.getNickname() == null || dto.getNickname().isBlank()) {
                throw new BizException(ErrorCode.BAD_REQUEST, "姓名不能为空");
            }
        }
        if (isCreate && (dto.getPassword() == null || dto.getPassword().isBlank())) {
            throw new BizException(ErrorCode.BAD_REQUEST, "密码不能为空");
        }
        if (dto.getPassword() != null && !dto.getPassword().isBlank()
                && !dto.getPassword().matches(PASSWORD_REGEX)) {
            throw new BizException(ErrorCode.BAD_REQUEST,
                    "密码需≥8位且同时包含大写字母、小写字母、数字和特殊字符");
        }
    }

    private UserVO toVO(SysUser u) {
        UserVO vo = new UserVO();
        vo.setId(u.getId());
        vo.setUsername(u.getUsername());
        vo.setNickname(u.getNickname());
        vo.setDeptId(u.getDeptId());
        vo.setFactory(u.getFactory());
        vo.setPhone(u.getPhone());
        vo.setEmail(u.getEmail());
        vo.setStatus(u.getStatus());
        vo.setCreateTime(u.getCreateTime());
        vo.setRoleIds(userRoleMapper.selectList(new LambdaQueryWrapper<SysUserRole>()
                        .eq(SysUserRole::getUserId, u.getId()))
                .stream().map(SysUserRole::getRoleId).toList());
        return vo;
    }
}
