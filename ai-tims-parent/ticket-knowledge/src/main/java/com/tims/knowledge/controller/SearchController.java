package com.tims.knowledge.controller;

import com.tims.common.api.Result;
import com.tims.knowledge.service.SearchService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.Map;

/**
 * 知识检索接口（M3，网关 /api/kb/** → 本服务）：
 * GET  /api/kb/search?query=&mode=VECTOR|KEYWORD|HYBRID&topK=5
 * POST /api/kb/search  body {query, mode, topK}
 * 返回体：{query, mode, fallback, total, items:[...]}，fallback=true 表示 Milvus 不可用已降级纯关键词。
 */
@RestController
@RequestMapping("/api/kb/search")
public class SearchController {

    private final SearchService searchService;

    public SearchController(SearchService searchService) {
        this.searchService = searchService;
    }

    @GetMapping
    public Result<Map<String, Object>> searchGet(@RequestParam String query,
                                                 @RequestParam(required = false) String mode,
                                                 @RequestParam(required = false) Integer topK) {
        return Result.ok(searchService.search(
                com.tims.knowledge.config.TenantContext.resolve(), query, mode, topK));
    }

    @PostMapping
    public Result<Map<String, Object>> searchPost(@RequestBody SearchBody body) {
        return Result.ok(searchService.search(
                com.tims.knowledge.config.TenantContext.resolve(),
                body.getQuery(), body.getMode(), body.getTopK()));
    }

    /** 检索入参 */
    public static class SearchBody {
        private String query;
        private String mode;
        private Integer topK;

        public String getQuery() { return query; }
        public void setQuery(String query) { this.query = query; }
        public String getMode() { return mode; }
        public void setMode(String mode) { this.mode = mode; }
        public Integer getTopK() { return topK; }
        public void setTopK(Integer topK) { this.topK = topK; }
    }
}
