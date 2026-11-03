package com.tims.order.service;

import cn.dev33.satoken.stp.StpUtil;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.tims.common.api.PageResult;
import com.tims.common.enums.ErrorCode;
import com.tims.common.exception.BizException;
import com.tims.order.config.TenantContext;
import com.tims.order.dto.AssignDTO;
import com.tims.order.dto.CommentDTO;
import com.tims.order.dto.ReasonDTO;
import com.tims.order.dto.ResolveDTO;
import com.tims.order.dto.TicketCreateDTO;
import com.tims.order.dto.TicketPageQuery;
import com.tims.order.entity.WoTicket;
import com.tims.order.entity.WoTicketComment;
import com.tims.order.entity.WoTicketFlow;
import com.tims.order.mapper.SysAuthMapper;
import com.tims.order.mapper.WoTicketCommentMapper;
import com.tims.order.mapper.WoTicketFlowMapper;
import com.tims.order.mapper.WoTicketMapper;
import com.tims.order.statemachine.TicketAction;
import com.tims.order.statemachine.TicketStateMachine;
import com.tims.order.vo.TicketDetailVO;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.Duration;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * 工单核心服务（M2 批二）：
 * - 建单：流水号 Redis INCR + DuplicateKey 重试；按 §4.3 规则预填处理人；
 * - 状态迁移：TicketStateMachine 迁移表校验，非法迁移 20401；每次迁移写流转日志；
 * - 权限：accept=ADMIN/DISPATCHER/当前处理人，confirm/reject=创建人/ADMIN，terminate=ADMIN。
 */
@Service
public class TicketService {

    private static final Logger log = LoggerFactory.getLogger(TicketService.class);

    private static final DateTimeFormatter DAY_FMT = DateTimeFormatter.ofPattern("yyyyMMdd");
    /** 工单流水号 Redis key 前缀，按天递增，25 小时过期 */
    private static final String SEQ_KEY_PREFIX = "tims:order:seq:";

    /** 待处理状态集合（TODO tab / 统计 todoCount） */
    private static final List<String> OPEN_STATUSES =
            List.of("SUBMITTED", "ACCEPTED", "PROCESSING", "SUSPENDED");
    private static final List<String> DONE_STATUSES = List.of("RESOLVED", "CLOSED", "TERMINATED");

    private final WoTicketMapper ticketMapper;
    private final WoTicketFlowMapper flowMapper;
    private final WoTicketCommentMapper commentMapper;
    private final SysAuthMapper authMapper;
    private final DispatchService dispatchService;
    private final EventPublisher eventPublisher;
    private final StringRedisTemplate redis;

    public TicketService(WoTicketMapper ticketMapper,
                         WoTicketFlowMapper flowMapper,
                         WoTicketCommentMapper commentMapper,
                         SysAuthMapper authMapper,
                         DispatchService dispatchService,
                         EventPublisher eventPublisher,
                         StringRedisTemplate redis) {
        this.ticketMapper = ticketMapper;
        this.flowMapper = flowMapper;
        this.commentMapper = commentMapper;
        this.authMapper = authMapper;
        this.dispatchService = dispatchService;
        this.eventPublisher = eventPublisher;
        this.redis = redis;
    }

    // ------------------------------------------------------------------
    // 当前登录态
    // ------------------------------------------------------------------

    private long currentUserId() {
        try {
            return StpUtil.getLoginIdAsLong();
        } catch (Exception e) {
            throw new BizException(ErrorCode.UNAUTHORIZED, "未登录或凭证失效");
        }
    }

    private Long tenantId() {
        return TenantContext.resolve();
    }

    private boolean isAdmin(Long tenantId, long userId) {
        return authMapper.selectRoleCodes(tenantId, userId).contains("ADMIN");
    }

    private String userNickname(Long tenantId, long userId) {
        Map<String, Object> simple = authMapper.selectUserSimple(tenantId, userId);
        return simple == null ? ("用户" + userId) : String.valueOf(simple.get("nickname"));
    }

    // ------------------------------------------------------------------
    // 建单（§6.3 #1）
    // ------------------------------------------------------------------

    @Transactional
    public WoTicket create(TicketCreateDTO dto) {
        long userId = currentUserId();
        Long tenantId = tenantId();

        WoTicket t = new WoTicket();
        t.setTenantId(tenantId);
        t.setTitle(dto.getTitle());
        t.setTicketType(dto.getTicketType());
        t.setTriggerType("MANUAL");
        t.setFactory(dto.getFactory());
        t.setPlant(dto.getPlant());
        t.setSceneName(dto.getSceneName());
        t.setDeviceType(dto.getDeviceType());
        t.setGlassId(dto.getGlassId());
        t.setAbnormalTime(dto.getAbnormalTime());
        t.setUrgency(dto.getUrgency() == null ? 2 : dto.getUrgency());
        t.setDescription(dto.getDescription());
        t.setAiExtracted(0);
        t.setCreateBy(userId);

        boolean draft = Boolean.TRUE.equals(dto.getDraft());
        String toStatus = draft ? "DRAFT" : TicketStateMachine.transition(null, TicketAction.CREATE);
        t.setStatus(toStatus);
        t.setCurrentNode(TicketStateMachine.nodeOf(toStatus));

        // 统一编号（草稿也编，ticket_no NOT NULL；提交草稿沿用原编号）
        t.setTicketNo(nextTicketNo());
        try {
            ticketMapper.insert(t);
        } catch (DuplicateKeyException e) {
            // 流水号并发冲突：重取一次
            t.setTicketNo(nextTicketNo());
            ticketMapper.insert(t);
        }

        // 派发预填（草稿不派）：规则命中或兜底，工单停留 SUBMITTED 等待受理
        if (!draft) {
            Long handler = dispatchService.matchHandler(tenantId, t);
            t.setHandlerId(handler);
            t.setHandlerName(dispatchService.userName(tenantId, handler));
            WoTicket patch = new WoTicket();
            patch.setId(t.getId());
            patch.setHandlerId(handler);
            patch.setHandlerName(t.getHandlerName());
            ticketMapper.updateById(patch);
        }

        writeFlow(t, draft ? TicketAction.SUBMIT : TicketAction.CREATE, null, toStatus,
                userId, userNickname(tenantId, userId), draft ? "保存草稿" : null);
        log.info("工单创建 id={} no={} status={} handler={}", t.getId(), t.getTicketNo(), toStatus, t.getHandlerId());
        return t;
    }

    /** WO + yyyyMMdd + - + 4位流水（Redis INCR，25h 过期） */
    private String nextTicketNo() {
        String day = LocalDate.now().format(DAY_FMT);
        String key = SEQ_KEY_PREFIX + day;
        Long seq = redis.opsForValue().increment(key);
        if (seq != null && seq == 1L) {
            redis.expire(key, Duration.ofHours(25));
        }
        return "WO" + day + "-" + String.format("%04d", seq);
    }

    // ------------------------------------------------------------------
    // 分页（#2）
    // ------------------------------------------------------------------

    public PageResult<WoTicket> page(TicketPageQuery q) {
        long userId = currentUserId();
        Long tenantId = tenantId();
        LambdaQueryWrapper<WoTicket> w = new LambdaQueryWrapper<>();
        switch (q.getTab() == null ? "ALL" : q.getTab()) {
            case "TODO" -> w.in(WoTicket::getStatus, OPEN_STATUSES).eq(WoTicket::getHandlerId, userId);
            case "DONE" -> w.in(WoTicket::getStatus, DONE_STATUSES).eq(WoTicket::getHandlerId, userId);
            case "MINE", "CC" -> w.eq(WoTicket::getCreateBy, userId); // CC 抄送 M4 接入，暂同 MINE
            case "ALL" -> { }
            default -> throw new BizException(ErrorCode.BAD_REQUEST, "非法 tab：" + q.getTab());
        }
        if (notBlank(q.getStatus())) w.eq(WoTicket::getStatus, q.getStatus());
        if (notBlank(q.getTicketType())) w.eq(WoTicket::getTicketType, q.getTicketType());
        if (notBlank(q.getTriggerType())) w.eq(WoTicket::getTriggerType, q.getTriggerType());
        if (notBlank(q.getFactory())) w.eq(WoTicket::getFactory, q.getFactory());
        if (notBlank(q.getKeyword())) {
            String kw = q.getKeyword();
            w.and(x -> x.like(WoTicket::getTicketNo, kw)
                    .or().like(WoTicket::getTitle, kw)
                    .or().like(WoTicket::getDescription, kw));
        }
        w.orderByDesc(WoTicket::getCreateTime);
        Page<WoTicket> p = ticketMapper.selectPage(new Page<>(q.getPage(), q.getSize()), w);
        return PageResult.of(p.getRecords(), p.getTotal(), q.getPage(), q.getSize());
    }

    private static boolean notBlank(String s) {
        return s != null && !s.isBlank();
    }

    // ------------------------------------------------------------------
    // 详情 / 时间线 / 相似工单（#3 #13 #14）
    // ------------------------------------------------------------------

    public WoTicket get(Long id) {
        WoTicket t = ticketMapper.selectById(id);
        if (t == null) {
            throw new BizException(ErrorCode.NOT_FOUND, "工单不存在");
        }
        return t;
    }

    public TicketDetailVO detail(Long id) {
        WoTicket t = get(id);
        TicketDetailVO vo = new TicketDetailVO();
        vo.setTicket(t);
        vo.setFlows(flowMapper.selectList(new LambdaQueryWrapper<WoTicketFlow>()
                .eq(WoTicketFlow::getTicketId, id)
                .orderByAsc(WoTicketFlow::getCreateTime)));
        vo.setComments(commentMapper.selectList(new LambdaQueryWrapper<WoTicketComment>()
                .eq(WoTicketComment::getTicketId, id)
                .orderByAsc(WoTicketComment::getCreateTime)));
        vo.setPushIds(List.of()); // M3/M4 推送回执，stub 空数组
        return vo;
    }

    public List<WoTicketFlow> timeline(Long id) {
        get(id); // 存在性校验
        return flowMapper.selectList(new LambdaQueryWrapper<WoTicketFlow>()
                .eq(WoTicketFlow::getTicketId, id)
                .orderByAsc(WoTicketFlow::getCreateTime));
    }

    public List<WoTicket> similar(Long id) {
        WoTicket t = get(id);
        String keywords = (notBlank(t.getTitle()) ? t.getTitle() : "") + " "
                + (notBlank(t.getDescription()) ? t.getDescription() : "");
        if (keywords.isBlank()) {
            return List.of();
        }
        return ticketMapper.searchSimilar(keywords.trim(), id, 5);
    }

    // ------------------------------------------------------------------
    // 状态迁移（#4-#12）
    // ------------------------------------------------------------------

    @Transactional
    public void accept(Long id) {
        long userId = currentUserId();
        Long tenantId = tenantId();
        WoTicket t = get(id);
        List<String> roles = authMapper.selectRoleCodes(tenantId, userId);
        boolean adminOrDispatcher = roles.contains("ADMIN") || roles.contains("DISPATCHER");
        boolean isHandler = t.getHandlerId() != null && t.getHandlerId() == userId;
        if (!adminOrDispatcher && !isHandler) {
            throw new BizException(ErrorCode.FORBIDDEN, "仅管理员/调度员/当前处理人可受理");
        }
        applyTransition(t, TicketAction.ACCEPT, userId, null);
    }

    @Transactional
    public void start(Long id) {
        applyTransitionWithHandlerGuard(id, TicketAction.START, null);
    }

    @Transactional
    public void suspend(Long id, ReasonDTO dto) {
        applyTransitionWithHandlerGuard(id, TicketAction.SUSPEND, dto.getReason());
    }

    @Transactional
    public void resume(Long id) {
        applyTransitionWithHandlerGuard(id, TicketAction.RESUME, null);
    }

    @Transactional
    public void assign(Long id, AssignDTO dto) {
        long userId = currentUserId();
        Long tenantId = tenantId();
        boolean admin = isAdmin(tenantId, userId);
        if (!admin && !authMapper.selectRoleCodes(tenantId, userId).contains("DISPATCHER")) {
            throw new BizException(ErrorCode.FORBIDDEN, "仅管理员/调度员可转派");
        }
        WoTicket t = get(id);
        TicketStateMachine.check(t.getStatus(), TicketAction.ASSIGN);
        Map<String, Object> simple = authMapper.selectUserSimple(tenantId, dto.getTargetUserId());
        if (simple == null) {
            throw new BizException(ErrorCode.NOT_FOUND, "目标处理人不存在");
        }
        t.setHandlerId(dto.getTargetUserId());
        t.setHandlerName((String) simple.get("nickname"));
        WoTicket patch = new WoTicket();
        patch.setId(t.getId());
        patch.setHandlerId(t.getHandlerId());
        patch.setHandlerName(t.getHandlerName());
        ticketMapper.updateById(patch);
        writeFlow(t, TicketAction.ASSIGN, t.getStatus(), t.getStatus(), userId,
                userNickname(tenantId, userId), dto.getComment());
        log.info("工单转派 id={} → {}", id, dto.getTargetUserId());
    }

    @Transactional
    public void resolve(Long id, ResolveDTO dto) {
        applyTransitionWithHandlerGuard(id, TicketAction.RESOLVE, dto.getResolveNote());
    }

    @Transactional
    public void confirm(Long id) {
        long userId = currentUserId();
        Long tenantId = tenantId();
        WoTicket t = get(id);
        if (!isAdmin(tenantId, userId) && !(t.getCreateBy() != null && t.getCreateBy() == userId)) {
            throw new BizException(ErrorCode.FORBIDDEN, "仅创建人/管理员可确认关闭");
        }
        applyTransition(t, TicketAction.CONFIRM, userId, null);
    }

    @Transactional
    public void reject(Long id) {
        long userId = currentUserId();
        Long tenantId = tenantId();
        WoTicket t = get(id);
        if (!isAdmin(tenantId, userId) && !(t.getCreateBy() != null && t.getCreateBy() == userId)) {
            throw new BizException(ErrorCode.FORBIDDEN, "仅创建人/管理员可驳回");
        }
        applyTransition(t, TicketAction.REJECT, userId, null);
    }

    @Transactional
    public void terminate(Long id, ReasonDTO dto) {
        long userId = currentUserId();
        Long tenantId = tenantId();
        if (!isAdmin(tenantId, userId)) {
            throw new BizException(ErrorCode.FORBIDDEN, "仅管理员可终止工单");
        }
        WoTicket t = get(id);
        if (dto == null || !notBlank(dto.getReason())) {
            throw new BizException(ErrorCode.BAD_REQUEST, "终止必须填写原因");
        }
        applyTransition(t, TicketAction.TERMINATE, userId, dto.getReason());
    }

    /** 处理人守卫（start/suspend/resume/resolve）：当前处理人或 ADMIN */
    private void applyTransitionWithHandlerGuard(Long id, TicketAction action, String comment) {
        long userId = currentUserId();
        Long tenantId = tenantId();
        WoTicket t = get(id);
        if (!isAdmin(tenantId, userId) && !(t.getHandlerId() != null && t.getHandlerId() == userId)) {
            throw new BizException(ErrorCode.FORBIDDEN, "仅当前处理人或管理员可执行该操作");
        }
        applyTransition(t, action, userId, comment);
    }

    /** 迁移表校验 → 更新状态/节点 → 写流转日志 → confirm 时发布 ticket.closed */
    private void applyTransition(WoTicket t, TicketAction action, long operatorId, String comment) {
        Long tenantId = t.getTenantId() == null ? tenantId() : t.getTenantId();
        String from = t.getStatus();
        String to = TicketStateMachine.transition(from, action);

        WoTicket patch = new WoTicket();
        patch.setId(t.getId());
        patch.setStatus(to);
        patch.setCurrentNode(TicketStateMachine.nodeOf(to));
        if (action == TicketAction.RESOLVE) {
            patch.setResolveNote(comment); // 解决说明是 M3 知识提炼输入
        }
        ticketMapper.updateById(patch);

        t.setStatus(to);
        t.setCurrentNode(TicketStateMachine.nodeOf(to));
        writeFlow(t, action, from, to, operatorId, userNickname(tenantId, operatorId), comment);

        if (action == TicketAction.CONFIRM) {
            Map<String, Object> payload = new HashMap<>();
            payload.put("ticketId", t.getId());
            payload.put("ticketNo", t.getTicketNo());
            payload.put("handlerId", t.getHandlerId());
            eventPublisher.publish("ticket.closed", payload);
        }
        log.info("工单迁移 id={} {} --{}--> {}", t.getId(), from, action, to);
    }

    /** 写流转日志（所有迁移必须落 wo_ticket_flow） */
    private void writeFlow(WoTicket t, TicketAction action, String from, String to,
                           long operatorId, String operatorName, String comment) {
        WoTicketFlow f = new WoTicketFlow();
        f.setTenantId(t.getTenantId() == null ? tenantId() : t.getTenantId());
        f.setTicketId(t.getId());
        f.setAction(action.name());
        f.setFromStatus(from);
        f.setToStatus(to);
        f.setNodeName(t.getCurrentNode());
        f.setOperatorId(operatorId);
        f.setOperatorName(operatorName);
        f.setComment(comment);
        flowMapper.insert(f);
    }

    // ------------------------------------------------------------------
    // 评论（#15）
    // ------------------------------------------------------------------

    public WoTicketComment comment(Long ticketId, CommentDTO dto) {
        long userId = currentUserId();
        Long tenantId = tenantId();
        get(ticketId); // 存在性校验
        WoTicketComment c = new WoTicketComment();
        c.setTenantId(tenantId);
        c.setTicketId(ticketId);
        c.setUserId(userId);
        c.setUserName(userNickname(tenantId, userId));
        c.setContent(dto.getContent());
        c.setSource(notBlank(dto.getSource()) ? dto.getSource() : "USER");
        commentMapper.insert(c);
        return c;
    }
}
