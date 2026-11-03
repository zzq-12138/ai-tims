package com.tims.knowledge.controller;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.tims.common.api.Result;
import com.tims.knowledge.entity.KbCategory;
import com.tims.knowledge.mapper.KbCategoryMapper;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

/**
 * 知识分类接口（M3）：
 * GET  /api/kb/category  列表（按 sort 升序）
 * POST /api/kb/category  新建（ADMIN/DISPATCHER 场景由前端控制，此处不设权限护栏）
 */
@RestController
@RequestMapping("/api/kb/category")
public class KbCategoryController {

    private final KbCategoryMapper categoryMapper;

    public KbCategoryController(KbCategoryMapper categoryMapper) {
        this.categoryMapper = categoryMapper;
    }

    @GetMapping
    public Result<List<KbCategory>> list() {
        return Result.ok(categoryMapper.selectList(
                new LambdaQueryWrapper<KbCategory>().orderByAsc(KbCategory::getSort)));
    }

    @PostMapping
    public Result<KbCategory> create(@RequestBody KbCategory in) {
        in.setId(null);
        categoryMapper.insert(in);
        return Result.ok(in);
    }
}
