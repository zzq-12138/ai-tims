package com.tims.system.config;

import com.baomidou.mybatisplus.annotation.DbType;
import com.baomidou.mybatisplus.extension.plugins.MybatisPlusInterceptor;
import com.baomidou.mybatisplus.extension.plugins.handler.TenantLineHandler;
import com.baomidou.mybatisplus.extension.plugins.inner.PaginationInnerInterceptor;
import com.baomidou.mybatisplus.extension.plugins.inner.TenantLineInnerInterceptor;
import net.sf.jsqlparser.expression.Expression;
import net.sf.jsqlparser.expression.LongValue;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

import java.util.Set;

/**
 * MyBatis-Plus 插件配置（M2 批一启用）：
 * - TenantLineInnerInterceptor：自动为 SQL 追加 tenant_id 条件/填充。
 *   忽略表：sys_tenant（租户元数据公共表）+ 字典类公共表（预留 M2 批二 sys_dict_*）。
 * - PaginationInnerInterceptor：物理分页（工单分页查询要用，提前就位）。
 */
@Configuration
public class MybatisPlusConfig {

    /** 公共表：不参与租户隔离 */
    private static final Set<String> IGNORE_TABLES = Set.of(
            "sys_tenant",
            "sys_dict_type",
            "sys_dict_data"
    );

    @Bean
    public MybatisPlusInterceptor mybatisPlusInterceptor() {
        MybatisPlusInterceptor interceptor = new MybatisPlusInterceptor();
        interceptor.addInnerInterceptor(new TenantLineInnerInterceptor(new TenantLineHandler() {
            @Override
            public Expression getTenantId() {
                Long tenantId = TenantContext.resolve();
                return new LongValue(tenantId == null ? 1L : tenantId);
            }

            @Override
            public String getTenantIdColumn() {
                return "tenant_id";
            }

            @Override
            public boolean ignoreTable(String tableName) {
                return IGNORE_TABLES.contains(tableName.toLowerCase());
            }
        }));
        interceptor.addInnerInterceptor(new PaginationInnerInterceptor(DbType.MYSQL));
        return interceptor;
    }
}
