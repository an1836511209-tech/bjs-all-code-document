from pathlib import Path
p=Path(__file__).resolve().parent.parent/'详细设计.md'
t=p.read_text('utf-8')
t=t.replace('鉴权和项目权限 → 参数校验 → 业务上下文 → 固定规则快照\n→ 输入指纹和幂等 → 持久化任务并入队 → Worker认领','鉴权和项目权限 → 参数校验 → 规范请求及已有幂等记录检查\n→ 已有同请求直接返回原任务及快照\n→ 首次请求解析业务上下文及规则快照 → 原子幂等占位与入队 → Worker认领')
t=t.replace('结果外壳data包含第3.3节结构并新增next_cursor和has_more，只切分vehicles数组；','结果外壳data包含第3.3节结构并新增next_cursor、has_more及evidence_map。evidence_map按evidence_id索引本页实体及公共字段所引用的证据，包含file_id、source_file_name、page_idx、page_number、bbox、coordinate_space、page_width、page_height、source_content、trace_supported、preview_url及不可溯源原因。所有evidence_refs必须在本页evidence_map中可解析，或给出受控证据查询引用；预览URL经调用方权限授权后生成。只切分vehicles数组；')
t=t.replace('| 403 | TASK_ACCESS_DENIED FILE_ACCESS_DENIED | 核对项目权限 不返回他项目信息 |','| 403或404 | FILE_ACCESS_DENIED TASK_NOT_FOUND | 文件授权失败403 不可见任务统一404以避免枚举 |')
p.write_text(t,'utf-8')
print('Review fixes applied')
