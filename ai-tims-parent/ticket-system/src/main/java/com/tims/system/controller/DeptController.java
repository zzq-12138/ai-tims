package com.tims.system.controller;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.tims.common.api.Result;
import com.tims.system.entity.SysDept;
import com.tims.system.mapper.SysDeptMapper;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/** 部门树（§6.2 #8，M2 批二）：内存组装 parent_id 层级 */
@RestController
@RequestMapping("/api/system/dept")
public class DeptController {

    private final SysDeptMapper deptMapper;

    public DeptController(SysDeptMapper deptMapper) {
        this.deptMapper = deptMapper;
    }

    @GetMapping("/tree")
    public Result<List<Map<String, Object>>> tree() {
        List<SysDept> all = deptMapper.selectList(
                new LambdaQueryWrapper<SysDept>().orderByAsc(SysDept::getSort));
        Map<Long, Map<String, Object>> nodeById = new LinkedHashMap<>();
        for (SysDept d : all) {
            nodeById.put(d.getId(), toNode(d));
        }
        List<Map<String, Object>> roots = new ArrayList<>();
        for (SysDept d : all) {
            Map<String, Object> node = nodeById.get(d.getId());
            Long parentId = d.getParentId();
            Map<String, Object> parent = parentId == null ? null : nodeById.get(parentId);
            if (parent == null || parent == node) {
                roots.add(node);
            } else {
                @SuppressWarnings("unchecked")
                List<Map<String, Object>> children = (List<Map<String, Object>>)
                        parent.computeIfAbsent("children", k -> new ArrayList<>());
                children.add(node);
            }
        }
        return Result.ok(roots);
    }

    private Map<String, Object> toNode(SysDept d) {
        Map<String, Object> n = new LinkedHashMap<>();
        n.put("id", d.getId());
        n.put("parentId", d.getParentId());
        n.put("deptName", d.getDeptName());
        n.put("factory", d.getFactory());
        n.put("sort", d.getSort());
        return n;
    }
}
