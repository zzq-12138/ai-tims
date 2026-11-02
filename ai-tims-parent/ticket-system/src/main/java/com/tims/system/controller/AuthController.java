package com.tims.system.controller;

import com.tims.common.api.Result;
import com.tims.system.service.AuthService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.Map;

/**
 * 认证接口（任务书 M1）：/api/auth/login、/api/auth/logout、/api/auth/me。
 * 登录在网关白名单内，logout/me 需携带 token。
 */
@RestController
@RequestMapping("/api/auth")
public class AuthController {

    private final AuthService authService;

    public AuthController(AuthService authService) {
        this.authService = authService;
    }

    public record LoginRequest(String username, String password) {
    }

    @PostMapping("/login")
    public Result<Map<String, Object>> login(@RequestBody LoginRequest req) {
        return Result.ok(authService.login(req.username(), req.password()));
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
