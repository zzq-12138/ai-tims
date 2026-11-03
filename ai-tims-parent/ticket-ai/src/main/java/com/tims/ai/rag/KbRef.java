package com.tims.ai.rag;

/** 引用知识条目（前端展示 + RAG 上下文） */
public record KbRef(Long id, String title, String summary, String deviceType, Long categoryId, Double score) {
}
