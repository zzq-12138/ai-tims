package com.tims.system.controller;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.tims.common.api.Result;
import com.tims.system.entity.SysRole;
import com.tims.system.mapper.SysRoleMapper;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

/** 角色列表（§6.2 #7，M2 批二） */
@RestController
@RequestMapping("/api/system/role")
public class RoleController {

    private final SysRoleMapper roleMapper;

    public RoleController(SysRoleMapper roleMapper) {
        this.roleMapper = roleMapper;
    }

    @GetMapping("/list")
    public Result<List<SysRole>> list() {
        return Result.ok(roleMapper.selectList(
                new LambdaQueryWrapper<SysRole>().orderByAsc(SysRole::getId)));
    }
}
