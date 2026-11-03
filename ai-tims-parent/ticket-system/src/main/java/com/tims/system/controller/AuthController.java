package com.tims.system.controller;

import com.tims.common.api.Result;
import com.tims.system.service.AuthService;
import com.tims.system.service.RegisterService;
import jakarta.validation.Valid;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.Map;

/**
 * 认证接口（任务书 M1）：/api/auth/login、/api/auth/logout、/api/auth/me，
 * M1 第二段新增 /api/auth/register、/api/auth/code。
 * login/register/code 在网关白名单内，logout/me 需携带 token。
 */
@RestController
@RequestMapping("/api/auth")
public class AuthController {

    private final AuthService authService;
    private final RegisterService registerService;

    public AuthController(AuthService authService, RegisterService registerService) {
        this.authService = authService;
        this.registerService = registerService;
    }

    public record LoginRequest(String username, String password) {
    }

    @PostMapping("/login")
    public Result<Map<String, Object>> login(@RequestBody LoginRequest req) {
        return Result.ok(authService.login(req.username(), req.password()));
    }

    @PostMapping("/register")
    public Result<Void> register(@Valid @RequestBody RegisterService.RegisterRequest req) {
        registerService.register(req);
        return Result.ok();
    }

    /** 发送注册验证码（邮箱，60s 频控 + 每日上限） */
    @PostMapping("/code")
    public Result<Void> sendCode(@RequestParam String email) {
        registerService.sendCode(email);
        return Result.ok();
    }

    @PostMapping("/logout")
    public Result<Void> logout() {
        authService.logout();
        return Result.ok();
    }

    @GetMapping("/me")
    public Result<Map<String, Object>> me() {
        return Result.ok(authService.me());
    }
}
