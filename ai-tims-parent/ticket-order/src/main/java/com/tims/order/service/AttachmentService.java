package com.tims.order.service;

import cn.dev33.satoken.stp.StpUtil;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.tims.common.api.PageResult;
import com.tims.common.enums.ErrorCode;
import com.tims.common.exception.BizException;
import com.tims.order.config.TenantContext;
import com.tims.order.entity.WoAttachment;
import com.tims.order.entity.WoTicket;
import com.tims.order.mapper.SysAuthMapper;
import com.tims.order.mapper.WoAttachmentMapper;
import com.tims.order.mapper.WoTicketMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.web.multipart.MultipartFile;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.StandardCopyOption;
import java.time.LocalDate;
import java.time.format.DateTimeFormatter;
import java.util.List;
import java.util.Locale;
import java.util.Set;
import java.util.UUID;

/**
 * 附件服务（2026-11-03 拍板补齐）：
 * - 上传：单文件 ≤20MB，扩展名白名单；存储名重命名为 uuid.ext（服务端生成，
 *   彻底杜绝路径穿越），原始文件名仅存库；存储目录走配置项，按月分目录；
 * - 下载：校验 aid 与 ticket_id 匹配，Content-Disposition 回显原始名（RFC 5987）；
 * - 删除：仅上传人本人或 ADMIN，逻辑删记录、磁盘文件保留。
 */
@Service
public class AttachmentService {

    private static final Logger log = LoggerFactory.getLogger(AttachmentService.class);

    private static final DateTimeFormatter MONTH_FMT = DateTimeFormatter.ofPattern("yyyyMM");

    /** 单文件上限 20MB */
    private static final long MAX_SIZE_BYTES = 20L * 1024 * 1024;

    /** 类型白名单：图片 / pdf / doc / xlsx / zip / log / txt */
    private static final Set<String> ALLOWED_EXT = Set.of(
            "jpg", "jpeg", "png", "gif", "bmp", "webp",
            "pdf", "doc", "docx", "xls", "xlsx",
            "zip", "log", "txt");

    /** 扩展名 → 兜底 MIME */
    private static final java.util.Map<String, String> MIME_MAP = java.util.Map.ofEntries(
            java.util.Map.entry("jpg", "image/jpeg"), java.util.Map.entry("jpeg", "image/jpeg"),
            java.util.Map.entry("png", "image/png"), java.util.Map.entry("gif", "image/gif"),
            java.util.Map.entry("bmp", "image/bmp"), java.util.Map.entry("webp", "image/webp"),
            java.util.Map.entry("pdf", "application/pdf"),
            java.util.Map.entry("doc", "application/msword"),
            java.util.Map.entry("docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
            java.util.Map.entry("xls", "application/vnd.ms-excel"),
            java.util.Map.entry("xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
            java.util.Map.entry("zip", "application/zip"),
            java.util.Map.entry("log", "text/plain"), java.util.Map.entry("txt", "text/plain"));

    private final WoAttachmentMapper attachmentMapper;
    private final WoTicketMapper ticketMapper;
    private final SysAuthMapper authMapper;

    /** 存储根目录（VM 本地盘，路径走配置项） */
    @Value("${tims.attachment.storage-dir:/home/dev/data/uploads}")
    private String storageDir;

    public AttachmentService(WoAttachmentMapper attachmentMapper,
                             WoTicketMapper ticketMapper,
                             SysAuthMapper authMapper) {
        this.attachmentMapper = attachmentMapper;
        this.ticketMapper = ticketMapper;
        this.authMapper = authMapper;
    }

    // ------------------------------------------------------------------
    // 上传
    // ------------------------------------------------------------------

    public WoAttachment upload(Long ticketId, MultipartFile file) {
        long userId = StpUtil.getLoginIdAsLong();
        Long tenantId = TenantContext.resolve();

        if (file == null || file.isEmpty()) {
            throw new BizException(ErrorCode.BAD_REQUEST, "上传文件为空");
        }
        if (file.getSize() > MAX_SIZE_BYTES) {
            throw new BizException(ErrorCode.BAD_REQUEST, "文件超过 20MB 上限");
        }

        // 工单必须存在（租户隔离由 TenantLine 保证）
        WoTicket ticket = ticketMapper.selectById(ticketId);
        if (ticket == null) {
            throw new BizException(ErrorCode.NOT_FOUND, "工单不存在");
        }

        String originalName = sanitizeOriginalName(file.getOriginalFilename());
        String ext = extractExt(originalName);
        if (ext.isEmpty() || !ALLOWED_EXT.contains(ext)) {
            throw new BizException(ErrorCode.BAD_REQUEST,
                    "不支持的文件类型，允许：" + String.join("/", ALLOWED_EXT));
        }

        // 服务端生成存储名：uuid.ext，用户输入不参与路径，杜绝 ../ 穿越
        String month = LocalDate.now().format(MONTH_FMT);
        String fileName = UUID.randomUUID().toString().replace("-", "") + "." + ext;
        String storageKey = month + "/" + fileName;
        Path target = Paths.get(storageDir, month, fileName).normalize();
        // 双保险：normalize 后必须仍位于存储根目录内
        if (!target.startsWith(Paths.get(storageDir).normalize())) {
            throw new BizException(ErrorCode.INTERNAL_ERROR, "存储路径异常");
        }
        try {
            Files.createDirectories(target.getParent());
            try (var in = file.getInputStream()) {
                Files.copy(in, target, StandardCopyOption.REPLACE_EXISTING);
            }
        } catch (IOException e) {
            log.error("附件写盘失败 ticket={} key={}", ticketId, storageKey, e);
            throw new BizException(ErrorCode.INTERNAL_ERROR, "文件保存失败");
        }

        WoAttachment a = new WoAttachment();
        a.setTenantId(tenantId);
        a.setTicketId(ticketId);
        a.setFileName(fileName);
        a.setOriginalName(originalName);
        a.setStorageKey(storageKey);
        a.setSize(file.getSize());
        a.setMimeType(resolveMime(ext, file.getContentType()));
        a.setUploaderId(userId);
        attachmentMapper.insert(a);
        log.info("附件上传 id={} ticket={} name={} size={}", a.getId(), ticketId, originalName, a.getSize());
        return a;
    }

    /** 去目录成分与控制字符，仅保留基础文件名 */
    private String sanitizeOriginalName(String name) {
        if (name == null || name.isBlank()) {
            return "unnamed";
        }
        String base = name.replace('\\', '/');
        int slash = base.lastIndexOf('/');
        base = slash >= 0 ? base.substring(slash + 1) : base;
        base = base.replaceAll("[\\x00-\\x1f]", "").trim();
        return base.isEmpty() ? "unnamed" : base;
    }

    private String extractExt(String name) {
        int dot = name.lastIndexOf('.');
        if (dot < 0 || dot == name.length() - 1) {
            return "";
        }
        return name.substring(dot + 1).toLowerCase(Locale.ROOT);
    }

    private String resolveMime(String ext, String provided) {
        String mapped = MIME_MAP.get(ext);
        if (provided != null && !provided.isBlank()) {
            return provided;
        }
        return mapped != null ? mapped : "application/octet-stream";
    }

    // ------------------------------------------------------------------
    // 列表 / 下载 / 删除
    // ------------------------------------------------------------------

    public List<WoAttachment> list(Long ticketId) {
        getTicketOrThrow(ticketId);
        return attachmentMapper.selectList(new LambdaQueryWrapper<WoAttachment>()
                .eq(WoAttachment::getTicketId, ticketId)
                .orderByDesc(WoAttachment::getCreateTime));
    }

    /** 下载定位：aid 必须属于该工单，返回记录与磁盘文件 */
    public WoAttachment locateForDownload(Long ticketId, Long attachmentId) {
        getTicketOrThrow(ticketId);
        WoAttachment a = attachmentMapper.selectById(attachmentId);
        if (a == null || !a.getTicketId().equals(ticketId)) {
            throw new BizException(ErrorCode.NOT_FOUND, "附件不存在");
        }
        return a;
    }

    /** 存储文件物理路径（normalize 后校验仍在根目录内） */
    public Path resolveStoragePath(WoAttachment a) {
        Path p = Paths.get(storageDir, a.getStorageKey()).normalize();
        if (!p.startsWith(Paths.get(storageDir).normalize()) || !Files.exists(p)) {
            throw new BizException(ErrorCode.NOT_FOUND, "附件文件已丢失");
        }
        return p;
    }

    /** 删除：上传人本人或 ADMIN；逻辑删记录，磁盘文件保留 */
    public void delete(Long ticketId, Long attachmentId) {
        long userId = StpUtil.getLoginIdAsLong();
        Long tenantId = TenantContext.resolve();
        getTicketOrThrow(ticketId);
        WoAttachment a = attachmentMapper.selectById(attachmentId);
        if (a == null || !a.getTicketId().equals(ticketId)) {
            throw new BizException(ErrorCode.NOT_FOUND, "附件不存在");
        }
        boolean admin = authMapper.selectRoleCodes(tenantId, userId).contains("ADMIN");
        if (!admin && !a.getUploaderId().equals(userId)) {
            throw new BizException(ErrorCode.FORBIDDEN, "仅上传人或管理员可删除附件");
        }
        attachmentMapper.deleteById(attachmentId);
        log.info("附件删除 id={} ticket={} operator={}", attachmentId, ticketId, userId);
    }

    private WoTicket getTicketOrThrow(Long ticketId) {
        WoTicket t = ticketMapper.selectById(ticketId);
        if (t == null) {
            throw new BizException(ErrorCode.NOT_FOUND, "工单不存在");
        }
        return t;
    }
}
