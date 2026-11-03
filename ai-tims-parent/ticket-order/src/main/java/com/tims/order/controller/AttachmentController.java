package com.tims.order.controller;

import com.tims.common.api.Result;
import com.tims.order.entity.WoAttachment;
import com.tims.order.service.AttachmentService;
import org.springframework.core.io.FileSystemResource;
import org.springframework.http.ContentDisposition;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestPart;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.multipart.MultipartFile;

import java.nio.charset.StandardCharsets;
import java.util.List;

/**
 * 工单附件接口（2026-11-03 拍板补齐）：
 * POST   /api/order/ticket/{id}/attachment            上传（≤20MB，白名单）
 * GET    /api/order/ticket/{id}/attachment            列表
 * GET    /api/order/ticket/{id}/attachment/{aid}      下载
 * DELETE /api/order/ticket/{id}/attachment/{aid}      删除（上传人本人或 ADMIN）
 */
@RestController
@RequestMapping("/api/order")
public class AttachmentController {

    private final AttachmentService attachmentService;

    public AttachmentController(AttachmentService attachmentService) {
        this.attachmentService = attachmentService;
    }

    /** 上传附件 */
    @PostMapping("/ticket/{id}/attachment")
    public Result<WoAttachment> upload(@PathVariable Long id,
                                       @RequestPart("file") MultipartFile file) {
        return Result.ok(attachmentService.upload(id, file));
    }

    /** 附件列表 */
    @GetMapping("/ticket/{id}/attachment")
    public Result<List<WoAttachment>> list(@PathVariable Long id) {
        return Result.ok(attachmentService.list(id));
    }

    /** 下载附件（Content-Disposition 回显原始文件名，RFC 5987 UTF-8） */
    @GetMapping("/ticket/{id}/attachment/{aid}")
    public ResponseEntity<FileSystemResource> download(@PathVariable Long id,
                                                       @PathVariable Long aid) {
        WoAttachment a = attachmentService.locateForDownload(id, aid);
        var path = attachmentService.resolveStoragePath(a);
        HttpHeaders headers = new HttpHeaders();
        headers.setContentDisposition(ContentDisposition.attachment()
                .filename(a.getOriginalName(), StandardCharsets.UTF_8)
                .build());
        return ResponseEntity.ok()
                .headers(headers)
                .contentType(MediaType.parseMediaType(
                        a.getMimeType() == null ? "application/octet-stream" : a.getMimeType()))
                .body(new FileSystemResource(path));
    }

    /** 删除附件（上传人本人或 ADMIN） */
    @DeleteMapping("/ticket/{id}/attachment/{aid}")
    public Result<Void> delete(@PathVariable Long id, @PathVariable Long aid) {
        attachmentService.delete(id, aid);
        return Result.ok();
    }
}
