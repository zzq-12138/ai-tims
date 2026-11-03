package com.tims.order.dto;

import jakarta.validation.constraints.NotBlank;

import java.time.LocalDateTime;

/** 创建工单入参（任务书 §6.3 TicketCreateDTO） */
public class TicketCreateDTO {

    @NotBlank(message = "工单名称不能为空")
    private String title;

    @NotBlank(message = "工单类型不能为空")
    private String ticketType;

    private String factory;
    private String plant;
    private String sceneName;
    private String deviceType;
    private String glassId;
    private LocalDateTime abnormalTime;

    /** 1高 2中 3低，默认 2 */
    private Integer urgency;

    @NotBlank(message = "现象描述不能为空")
    private String description;

    /** 保存为草稿 */
    private Boolean draft = false;

    public String getTitle() { return title; }
    public void setTitle(String title) { this.title = title; }
    public String getTicketType() { return ticketType; }
    public void setTicketType(String ticketType) { this.ticketType = ticketType; }
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
    public Boolean getDraft() { return draft; }
    public void setDraft(Boolean draft) { this.draft = draft; }
}
