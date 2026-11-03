package com.tims.order.controller;

import com.tims.common.api.PageResult;
import com.tims.common.api.Result;
import com.tims.order.dto.AssignDTO;
import com.tims.order.dto.CommentDTO;
import com.tims.order.dto.ReasonDTO;
import com.tims.order.dto.ResolveDTO;
import com.tims.order.dto.TicketCreateDTO;
import com.tims.order.dto.TicketPageQuery;
import com.tims.order.entity.WoTicket;
import com.tims.order.entity.WoTicketComment;
import com.tims.order.entity.WoTicketFlow;
import com.tims.order.service.TicketService;
import com.tims.order.vo.TicketDetailVO;
import jakarta.validation.Valid;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

/**
 * 工单接口（任务书 §6.3 #1-#15）：建单/分页/详情/受理/开工/挂起/恢复/转派/
 * 解决/确认关闭/驳回/终止/时间线/相似工单/评论。
 * 网关已验签并透传登录态，本服务从 Sa-Token 会话取 userId。
 */
@RestController
@RequestMapping("/api/order")
public class TicketController {

    private final TicketService ticketService;

    public TicketController(TicketService ticketService) {
        this.ticketService = ticketService;
    }

    /** #1 建单（draft=true 存草稿） */
    @PostMapping("/ticket")
    public Result<WoTicket> create(@Valid @RequestBody TicketCreateDTO dto) {
        return Result.ok(ticketService.create(dto));
    }

    /** #2 分页查询（tab=TODO/DONE/MINE/CC/ALL） */
    @GetMapping("/ticket/page")
    public Result<PageResult<WoTicket>> page(TicketPageQuery query) {
        return Result.ok(ticketService.page(query));
    }

    /** #3 详情（含时间线 + 评论 + pushIds stub） */
    @GetMapping("/ticket/{id}")
    public Result<TicketDetailVO> detail(@PathVariable Long id) {
        return Result.ok(ticketService.detail(id));
    }

    /** #4 受理 */
    @PostMapping("/ticket/{id}/accept")
    public Result<Void> accept(@PathVariable Long id) {
        ticketService.accept(id);
        return Result.ok();
    }

    /** #5 开工 */
    @PostMapping("/ticket/{id}/start")
    public Result<Void> start(@PathVariable Long id) {
        ticketService.start(id);
        return Result.ok();
    }

    /** #6 挂起（需原因） */
    @PostMapping("/ticket/{id}/suspend")
    public Result<Void> suspend(@PathVariable Long id, @Valid @RequestBody ReasonDTO dto) {
        ticketService.suspend(id, dto);
        return Result.ok();
    }

    /** #7 恢复 */
    @PostMapping("/ticket/{id}/resume")
    public Result<Void> resume(@PathVariable Long id) {
        ticketService.resume(id);
        return Result.ok();
    }

    /** #8 转派 */
    @PostMapping("/ticket/{id}/assign")
    public Result<Void> assign(@PathVariable Long id, @Valid @RequestBody AssignDTO dto) {
        ticketService.assign(id, dto);
        return Result.ok();
    }

    /** #9 提交验证/解决（需解决说明，M3 知识提炼输入） */
    @PostMapping("/ticket/{id}/resolve")
    public Result<Void> resolve(@PathVariable Long id, @Valid @RequestBody ResolveDTO dto) {
        ticketService.resolve(id, dto);
        return Result.ok();
    }

    /** #10 确认关闭（发布 ticket.closed） */
    @PostMapping("/ticket/{id}/confirm")
    public Result<Void> confirm(@PathVariable Long id) {
        ticketService.confirm(id);
        return Result.ok();
    }

    /** #11 驳回重办（RESOLVED → PROCESSING） */
    @PostMapping("/ticket/{id}/reject")
    public Result<Void> reject(@PathVariable Long id) {
        ticketService.reject(id);
        return Result.ok();
    }

    /** #12 终止（ADMIN，需原因） */
    @PostMapping("/ticket/{id}/terminate")
    public Result<Void> terminate(@PathVariable Long id, @Valid @RequestBody ReasonDTO dto) {
        ticketService.terminate(id, dto);
        return Result.ok();
    }

    /** #13 流转时间线 */
    @GetMapping("/ticket/{id}/timeline")
    public Result<List<WoTicketFlow>> timeline(@PathVariable Long id) {
        return Result.ok(ticketService.timeline(id));
    }

    /** #14 相似历史工单（FULLTEXT MATCH AGAINST） */
    @GetMapping("/ticket/{id}/similar")
    public Result<List<WoTicket>> similar(@PathVariable Long id) {
        return Result.ok(ticketService.similar(id));
    }

    /** #15 发表评论/处理记录 */
    @PostMapping("/comment/{ticketId}")
    public Result<WoTicketComment> comment(@PathVariable Long ticketId,
                                           @Valid @RequestBody CommentDTO dto) {
        return Result.ok(ticketService.comment(ticketId, dto));
    }
}
