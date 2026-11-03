package com.tims.knowledge.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.tims.knowledge.entity.KbKnowledge;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.util.List;
import java.util.Map;

/** 知识点 Mapper（MyBatis-Plus BaseMapper，禁 XML） */
@Mapper
public interface KbKnowledgeMapper extends BaseMapper<KbKnowledge> {

    /**
     * FULLTEXT 全文检索（ngram 分词），返回命中 id + 相关度得分，按得分降序。
     * 【禁 XML 例外理由】MATCH...AGAINST 为 MySQL 全文专有语法，MyBatis-Plus
     * Wrapper 与 BaseMapper 均无法表达，按约定采用注解 SQL（不落 XML）。
     * tenant_id 显式过滤（TenantLineInnerInterceptor 对注解 SQL 仍会追加，双重条件无害）。
     */
    @Select("SELECT k.id AS id, "
            + "MATCH(k.title, k.content) AGAINST(#{kw} IN NATURAL LANGUAGE MODE) AS ft_score "
            + "FROM kb_knowledge k "
            + "WHERE k.deleted = 0 AND k.status = 'PUBLISHED' AND k.tenant_id = #{tenantId} "
            + "AND MATCH(k.title, k.content) AGAINST(#{kw} IN NATURAL LANGUAGE MODE) "
            + "ORDER BY ft_score DESC LIMIT #{topK}")
    List<Map<String, Object>> selectFulltextIdScore(@Param("tenantId") Long tenantId,
                                                    @Param("kw") String kw,
                                                    @Param("topK") int topK);
}
