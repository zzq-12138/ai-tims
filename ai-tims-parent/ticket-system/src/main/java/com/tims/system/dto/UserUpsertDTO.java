package com.tims.system.dto;

import java.util.List;

/**
 * 用户新增/编辑入参（§6.2 #3-5，M2 批二）。
 * 新增时 password 必填；编辑时 password 留空表示不改密码。
 */
public class UserUpsertDTO {

    /** 编辑时的目标用户ID，新增时忽略 */
    private Long id;

    private String username;

    /** 编辑时可留空（不改密码） */
    private String password;

    private String nickname;

    private Long deptId;

    private String factory;

    private String phone;

    private String email;

    /** 1启用 0停用，默认 1 */
    private Integer status;

    /** 角色ID列表；新增时为空则默认 USER 角色 */
    private List<Long> roleIds;

    public Long getId() { return id; }
    public void setId(Long id) { this.id = id; }
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
    public List<Long> getRoleIds() { return roleIds; }
    public void setRoleIds(List<Long> roleIds) { this.roleIds = roleIds; }
}
