package com.tims.order.config;

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
 * MyBatis-Plus 插件配置（M2 批二，与 ticket-system 同口径）：
 * - TenantLineInnerInterceptor：wo_ 五表 + sys_* 共享表自动追加 tenant_id。
 *   忽略表：sys_tenant（租户元数据）+ 字典类公共表（预留）。
 * - PaginationInnerInterceptor：工单分页。
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
