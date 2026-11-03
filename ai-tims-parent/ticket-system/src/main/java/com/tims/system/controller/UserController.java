package com.tims.system.controller;

import com.tims.common.api.PageResult;
import com.tims.common.api.Result;
import com.tims.system.dto.UserUpsertDTO;
import com.tims.system.service.UserService;
import com.tims.system.vo.UserVO;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/**
 * 用户管理接口（§6.2 #3-6，M2 批二）：分页/新增/编辑/逻辑删除，全部 ADMIN 守卫。
 */
@RestController
@RequestMapping("/api/system/user")
public class UserController {

    private final UserService userService;

    public UserController(UserService userService) {
        this.userService = userService;
    }

    @GetMapping("/page")
    public Result<PageResult<UserVO>> page(@RequestParam(required = false) String keyword,
                                           @RequestParam(defaultValue = "1") long page,
                                           @RequestParam(defaultValue = "10") long size) {
        return Result.ok(userService.page(keyword, page, size));
    }

    @PostMapping
    public Result<Long> create(@RequestBody UserUpsertDTO dto) {
        return Result.ok(userService.create(dto));
    }

    @PutMapping
    public Result<Void> update(@RequestBody UserUpsertDTO dto) {
        userService.update(dto.getId(), dto);
        return Result.ok();
    }

    @DeleteMapping("/{id}")
    public Result<Void> delete(@PathVariable Long id) {
        userService.delete(id);
        return Result.ok();
    }
}
