package com.tims.system.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableLogic;
import com.baomidou.mybatisplus.annotation.TableName;

import java.time.LocalDateTime;

/**
 * 用户实体（sys_user）。多租户：tenant_id 字段 M1 先落库/进实体（默认 1），
 * TenantLineInnerInterceptor M2 启用。
 */
@TableName("sys_user")
public class SysUser {

    /** 主键（雪花ID） */
    @TableId(type = IdType.ASSIGN_ID)
    private Long id;

    /** 租户ID，单租户阶段恒为 1 */
    private Long tenantId;

    private String username;

    /** BCrypt 摘要，永不返回给前端 */
    private String password;

    private String nickname;

    private Long deptId;

    private String factory;

    private String phone;

    private String email;

    /** 1启用 0停用 */
    private Integer status;

    private LocalDateTime createTime;

    private LocalDateTime updateTime;

    /** 逻辑删除 */
    @TableLogic
    private Integer deleted;

    public Long getId() { return id; }
    public void setId(Long id) { this.id = id; }
    public Long getTenantId() { return tenantId; }
    public void setTenantId(Long tenantId) { this.tenantId = tenantId; }
    public String getUsername() { return username; }
    public void setUsername(String username) { this.username = username; }
    public String getPassword() { return password; }
    public void setPassword(String password) { this.password = password; }
    public String getNickname() { return nickname; }
    public void setNickname(String nickname) { this.nickname = nickname; }
    public Long getDeptId() { return deptId; }
    public void setDeptId(Long deptId) { this.deptId = deptId; }
    public String getFactory() { return factory; }
    public void setFactory(String factory) { this.factory = factory; }
    public String getPhone() { return phone; }
    public void setPhone(String phone) { this.phone = phone; }
    public String getEmail() { return email; }
    public void setEmail(String email) { this.email = email; }
    public Integer getStatus() { return status; }
    public void setStatus(Integer status) { this.status = status; }
    public LocalDateTime getCreateTime() { return createTime; }
    public void setCreateTime(LocalDateTime createTime) { this.createTime = createTime; }
    public LocalDateTime getUpdateTime() { return updateTime; }
    public void setUpdateTime(LocalDateTime updateTime) { this.updateTime = updateTime; }
    public Integer getDeleted() { return deleted; }
    public void setDeleted(Integer deleted) { this.deleted = deleted; }
}
