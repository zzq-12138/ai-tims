package com.tims.system.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.tims.common.enums.ErrorCode;
import com.tims.common.exception.BizException;
import com.tims.system.entity.SysRole;
import com.tims.system.entity.SysUser;
import com.tims.system.entity.SysUserRole;
import com.tims.system.mapper.SysRoleMapper;
import com.tims.system.mapper.SysUserMapper;
import com.tims.system.mapper.SysUserRoleMapper;
import jakarta.validation.constraints.NotBlank;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.Duration;
import java.time.LocalDate;
import java.time.format.DateTimeFormatter;
import java.util.concurrent.ThreadLocalRandom;

/**
 * 注册服务（M1 第二段，M2 批一修订，2026-11-03）：
 * - 手机号必填：格式校验 ^1[3-9]\d{9}$ + (tenant_id, phone) 唯一约束（DB 兜底）
 * - 注册前必须通过邮箱验证码：Redis 5 分钟 TTL、一次性消费、同邮箱 60s 一次 + 每日上限 10 条；
 *   M2 批一起同一验证码输错 ≥5 次即作废（防暴力试码）
 * - 默认角色不再硬编码 roleId=4，按 role_code=USER 查 sys_role（租户隔离由插件自动追加）
 * - 密码规则：≥8 位，同时含大写、小写、数字、特殊字符（后端为准）
 * - Mapper 一律 BaseMapper/LambdaQueryWrapper，无 XML SQL
 */
@Service
public class RegisterService {

    /** 验证码 Redis 键：5 分钟 TTL */
    private static final String KEY_CODE = "tims:reg:code:";
    /** 发送频控键：同邮箱 60s 一次 */
    private static final String KEY_LOCK = "tims:reg:lock:";
    /** 每日上限键：按自然日计数 */
    private static final String KEY_DAILY = "tims:reg:daily:";
    /** 验证码试错计数键：与验证码同生命周期（5 分钟） */
    private static final String KEY_CODE_FAIL = "tims:reg:codefail:";
    private static final long DAILY_LIMIT = 10;
    /** 同一验证码最大试错次数，超过即作废 */
    private static final int CODE_MAX_FAIL = 5;

    private static final String PHONE_REGEX = "^1[3-9]\\d{9}$";
    private static final String EMAIL_REGEX = "^[\\w.+-]+@[\\w-]+(\\.[\\w-]+)+$";
    private static final String USERNAME_REGEX = "^[a-zA-Z0-9_]{3,32}$";
    /** ≥8 位，同时含大写、小写、数字、特殊字符 */
    private static final String PASSWORD_REGEX = "^(?=.*[a-z])(?=.*[A-Z])(?=.*\\d)(?=.*[^0-9a-zA-Z]).{8,64}$";

    /** 默认注册角色码（sql/init.sql 种子，按 role_code 查询，不再硬编码 roleId） */
    private static final String DEFAULT_ROLE_CODE = "USER";

    private final SysUserMapper userMapper;
    private final SysUserRoleMapper userRoleMapper;
    private final SysRoleMapper roleMapper;
    private final StringRedisTemplate redis;
    private final VerificationCodeSender codeSender;
    private final org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder passwordEncoder;

    public RegisterService(SysUserMapper userMapper,
                           SysUserRoleMapper userRoleMapper,
                           SysRoleMapper roleMapper,
                           StringRedisTemplate redis,
                           VerificationCodeSender codeSender,
                           org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder passwordEncoder) {
        this.userMapper = userMapper;
        this.userRoleMapper = userRoleMapper;
        this.roleMapper = roleMapper;
        this.redis = redis;
        this.codeSender = codeSender;
        this.passwordEncoder = passwordEncoder;
    }

    public record RegisterRequest(
            @NotBlank(message = "用户名不能为空") String username,
            @NotBlank(message = "密码不能为空") String password,
            @NotBlank(message = "昵称不能为空") String nickname,
            @NotBlank(message = "手机号不能为空") String phone,
            @NotBlank(message = "邮箱不能为空") String email,
            @NotBlank(message = "验证码不能为空") String code) {
    }

    /** 发送注册验证码（频控：同邮箱 60s 一次、每日上限 10 条） */
    public void sendCode(String email) {
        if (email == null || !email.matches(EMAIL_REGEX)) {
            throw new BizException(ErrorCode.BAD_REQUEST, "邮箱格式不正确");
        }
        if (Boolean.TRUE.equals(redis.hasKey(KEY_LOCK + email))) {
            throw new BizException(ErrorCode.VALIDATE_CODE_LIMIT, "获取验证码间隔过短，请 60 秒后再试");
        }
        String dailyKey = KEY_DAILY + email + ":" + LocalDate.now().format(DateTimeFormatter.BASIC_ISO_DATE);
        Long count = redis.opsForValue().increment(dailyKey);
        if (count != null && count == 1L) {
            redis.expire(dailyKey, Duration.ofHours(24));
        }
        if (count != null && count > DAILY_LIMIT) {
            throw new BizException(ErrorCode.VALIDATE_CODE_LIMIT, "今日获取验证码次数已达上限");
        }
        String code = String.format("%06d", ThreadLocalRandom.current().nextInt(1_000_000));
        redis.opsForValue().set(KEY_CODE + email, code, Duration.ofMinutes(5));
        redis.opsForValue().set(KEY_LOCK + email, "1", Duration.ofSeconds(60));
        codeSender.send(email, code);
    }

    @Transactional
    public void register(RegisterRequest req) {
        // 1. 后端为准的格式校验
        if (req.username() == null || !req.username().matches(USERNAME_REGEX)) {
            throw new BizException(ErrorCode.BAD_REQUEST, "用户名须为 3-32 位字母、数字或下划线");
        }
        if (req.phone() == null || !req.phone().matches(PHONE_REGEX)) {
            throw new BizException(ErrorCode.BAD_REQUEST, "手机号格式不正确");
        }
        if (req.email() == null || !req.email().matches(EMAIL_REGEX)) {
            throw new BizException(ErrorCode.BAD_REQUEST, "邮箱格式不正确");
        }
        checkPasswordPolicy(req.password());

        // 2. 唯一性校验（逻辑删除自动过滤；DB 侧另有 uk_tenant_phone/uk_tenant_email/uk_tenant_username 兜底）
        if (userMapper.selectCount(new LambdaQueryWrapper<SysUser>().eq(SysUser::getUsername, req.username())) > 0) {
            throw new BizException(ErrorCode.CONFLICT, "用户名已被注册");
        }
        if (userMapper.selectCount(new LambdaQueryWrapper<SysUser>().eq(SysUser::getPhone, req.phone())) > 0) {
            throw new BizException(ErrorCode.CONFLICT, "手机号已被注册");
        }
        if (userMapper.selectCount(new LambdaQueryWrapper<SysUser>().eq(SysUser::getEmail, req.email())) > 0) {
            throw new BizException(ErrorCode.CONFLICT, "邮箱已被注册");
        }

        // 3. 验证码校验：错误累计 ≥5 次作废（防暴力试码），正确则一次性消费
        String codeKey = KEY_CODE + req.email();
        String failKey = KEY_CODE_FAIL + req.email();
        String cached = redis.opsForValue().get(codeKey);
        if (cached == null) {
            throw new BizException(ErrorCode.VALIDATE_CODE_INVALID);
        }
        if (!cached.equals(req.code())) {
            Long fails = redis.opsForValue().increment(failKey);
            if (fails != null && fails == 1L) {
                redis.expire(failKey, Duration.ofMinutes(5));
            }
            if (fails != null && fails >= CODE_MAX_FAIL) {
                redis.delete(codeKey);
                redis.delete(failKey);
                throw new BizException(ErrorCode.VALIDATE_CODE_INVALID, "验证码错误次数过多已作废，请重新获取");
            }
            throw new BizException(ErrorCode.VALIDATE_CODE_INVALID);
        }
        redis.delete(codeKey);
        redis.delete(failKey);

        // 4. 默认角色：按 role_code 查询（租户条件由 TenantLineInnerInterceptor 自动追加）
        SysRole role = roleMapper.selectOne(new LambdaQueryWrapper<SysRole>()
                .eq(SysRole::getRoleCode, DEFAULT_ROLE_CODE));
        if (role == null) {
            throw new BizException(ErrorCode.INTERNAL_ERROR, "默认角色缺失，请检查种子数据");
        }

        // 5. 落库：tenant_id 恒为 1（单租户阶段），默认 USER 角色
        SysUser user = new SysUser();
        user.setTenantId(1L);
        user.setUsername(req.username());
        user.setPassword(passwordEncoder.encode(req.password()));
        user.setNickname(req.nickname());
        user.setPhone(req.phone());
        user.setEmail(req.email());
        user.setStatus(1);
        userMapper.insert(user);

        SysUserRole ur = new SysUserRole();
        ur.setTenantId(1L);
        ur.setUserId(user.getId());
        ur.setRoleId(role.getId());
        userRoleMapper.insert(ur);
    }

    /** 密码规则：≥8 位，同时含大写、小写、数字、特殊字符（任务书 M1 硬性要求） */
    public static void checkPasswordPolicy(String password) {
        if (password == null || !password.matches(PASSWORD_REGEX)) {
            throw new BizException(ErrorCode.BAD_REQUEST,
                    "密码须至少 8 位，且同时包含大写字母、小写字母、数字和特殊字符");
        }
    }
}
