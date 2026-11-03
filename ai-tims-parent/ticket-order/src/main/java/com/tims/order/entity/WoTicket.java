package com.tims.order.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableLogic;
import com.baomidou.mybatisplus.annotation.TableName;
import com.baomidou.mybatisplus.annotation.Version;

import java.time.LocalDateTime;

/** 工单主表（wo_ticket） */
@TableName("wo_ticket")
public class WoTicket {

    @TableId(type = IdType.ASSIGN_ID)
    private Long id;

    private Long tenantId;

    /** 工单编号 WOyyyyMMdd-XXXX，唯一 */
    private String ticketNo;

    private String title;

    /** 设备异常/品质异常/系统异常/其他 */
    private String ticketType;

    /** MANUAL/RULE */
    private String triggerType;

    private String factory;

    private String plant;

    private String sceneName;

    private String deviceType;

    private String glassId;

    private LocalDateTime abnormalTime;

    /** 1高 2中 3低 */
    private Integer urgency;

    private String description;

    /** 01 填报 / 02 处理 / 03 确认 */
    private String currentNode;

    /** 状态机状态 DRAFT/SUBMITTED/ACCEPTED/PROCESSING/SUSPENDED/RESOLVED/CLOSED/TERMINATED */
    private String status;

    private Long handlerId;

    private String handlerName;

    /** 解决说明（知识提炼输入） */
    private String resolveNote;

    /** 是否已 AI 提炼 0/1 */
    private Integer aiExtracted;

    /** 乐观锁版本号（M4：状态迁移并发控制，OptimisticLockerInnerInterceptor） */
    @Version
    private Integer version;

    private Long createBy;

    private LocalDateTime createTime;

    private LocalDateTime updateTime;

    @TableLogic
    private Integer deleted;

    public Long getId() { return id; }
    public void setId(Long id) { this.id = id; }
    public Long getTenantId() { return tenantId; }
    public void setTenantId(Long tenantId) { this.tenantId = tenantId; }
    public String getTicketNo() { return ticketNo; }
    public void setTicketNo(String ticketNo) { this.ticketNo = ticketNo; }
    public String getTitle() { return title; }
    public void setTitle(String title) { this.title = title; }
    public String getTicketType() { return ticketType; }
    public void setTicketType(String ticketType) { this.ticketType = ticketType; }
    public String getTriggerType() { return triggerType; }
    public void setTriggerType(String triggerType) { this.triggerType = triggerType; }
    public String getFactory() { return factory; }
    public void setFactory(String factory) { this.factory = factory; }
    public String getPlant() { return plant; }
    public void setPlant(String plant) { this.plant = plant; }
    public String getSceneName() { return sceneName; }
    public void setSceneName(String sceneName) { this.sceneName = sceneName; }
    public String getDeviceType() { return deviceType; }
    public void setDeviceType(String deviceType) { this.deviceType = deviceType; }
    public String getGlassId() { return glassId; }
    public void setGlassId(String glassId) { this.glassId = glassId; }
    public LocalDateTime getAbnormalTime() { return abnormalTime; }
    public void setAbnormalTime(LocalDateTime abnormalTime) { this.abnormalTime = abnormalTime; }
    public Integer getUrgency() { return urgency; }
    public void setUrgency(Integer urgency) { this.urgency = urgency; }
    public String getDescription() { return description; }
    public void setDescription(String description) { this.description = description; }
    public String getCurrentNode() { return currentNode; }
    public void setCurrentNode(String currentNode) { this.currentNode = currentNode; }
    public String getStatus() { return status; }
    public void setStatus(String status) { this.status = status; }
    public Long getHandlerId() { return handlerId; }
    public void setHandlerId(Long handlerId) { this.handlerId = handlerId; }
    public String getHandlerName() { return handlerName; }
    public void setHandlerName(String handlerName) { this.handlerName = handlerName; }
    public String getResolveNote() { return resolveNote; }
    public void setResolveNote(String resolveNote) { this.resolveNote = resolveNote; }
    public Integer getAiExtracted() { return aiExtracted; }
    public void setAiExtracted(Integer aiExtracted) { this.aiExtracted = aiExtracted; }
    public Integer getVersion() { return version; }
    public void setVersion(Integer version) { this.version = version; }
    public Long getCreateBy() { return createBy; }
    public void setCreateBy(Long createBy) { this.createBy = createBy; }
    public LocalDateTime getCreateTime() { return createTime; }
    public void setCreateTime(LocalDateTime createTime) { this.createTime = createTime; }
    public LocalDateTime getUpdateTime() { return updateTime; }
    public void setUpdateTime(LocalDateTime updateTime) { this.updateTime = updateTime; }
    public Integer getDeleted() { return deleted; }
    public void setDeleted(Integer deleted) { this.deleted = deleted; }
}
