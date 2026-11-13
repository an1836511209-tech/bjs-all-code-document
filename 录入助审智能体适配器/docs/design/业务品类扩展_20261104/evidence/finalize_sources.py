from pathlib import Path
root=Path(__file__).resolve().parent.parent

def replace_line(text,prefix,new):
    lines=text.splitlines()
    idx=[i for i,x in enumerate(lines) if x.startswith(prefix)]
    assert len(idx)==1,(prefix,idx)
    lines[idx[0]]=new
    return '\n'.join(lines)+'\n'

p=root/'概要设计.md'
t=p.read_text('utf-8')
t=t.replace('对外接口和中台包装基线','录入助审API基线')
t=t.replace('复用extraction/sync和task/status','复用extraction/sync和task/{task_id}')
t=t.replace('S2使用中台网关包装，原生接口使用/api/v1路径。','S2第一章录入助审接口使用数值code=200的原生外壳，原生路径为/api/v1。仓库src/platform_gw提供中台适配，默认路径为/api/platform/v1，Body保持原生格式并增加提供方业务响应头。')
p.write_text(t,'utf-8')

p=root/'详细设计.md'
t=p.read_text('utf-8')
t=replace_line(t,'| 400或422','| 400 | INVALID_SCENARIO RULE_CONFIG_MISMATCH VALIDATION_ERROR | 修正参数 保留现有400校验外壳 |')
t=replace_line(t,'request_id在caller_id','request_id在caller_id作用域内唯一。创建幂等指纹基于规范化原始请求，包括业务、显式配置ID或默认选择意图、稳定附件引用、确认字段和选择参数，不包含会因后续发布改变的实际默认规则。先检查已有幂等记录；同指纹返回原task_id及其已固定快照，异指纹返回409 IDEMPOTENCY_CONFLICT；仅首次请求解析和锁定当前规则快照并原子创建任务。调用方传task_id时也核对调用方、业务和输入，不能附着到其他任务。下载后使用服务端SHA-256计算业务处理指纹，兼容file_content_hash仍按MD5核验，不信任自报哈希。稳定file_id及受管对象版本用于幂等，不能随意去除签名URL参数来假定内容相同。')
t=replace_line(t,'| 提取结果 |','| 提取结果 | 调用方/项目 场景 规则快照 提示词/模型 级联hash 文件身份及角色/归属 | 不跨类型 阶段 模式 |')
t=t.replace('"identity_status": "identified", "fields": [], "audit_results": []}\n  ],','"identity_status": "identified", "fields": [], "audit_results": []},\n    {"entity_id": "vehicle-002", "plate_number": null, "identity_status": "missing", "fields": [], "audit_results": []}\n  ],')
t=t.replace('"unresolved_records": [{"file_id": "file-list", "page_number": 2,','"unresolved_records": [{"entity_id": "vehicle-002", "source_row_id": "row-002", "file_id": "file-list", "page_number": 2,')
t=replace_line(t,'最终vehicles数组','最终vehicles数组保留无法确认的记录，允许plate_number为null，以entity_id关联。unresolved_records引用其entity_id和原始行，保证基准原始行数可对账；统计区分行数、已识别记录数及去重号牌数。')
t=replace_line(t,'基准集合B由','基准集合B由已识别的规范号牌形成，同时保留基准未识别记录U。每份其他材料形成观察集合O_f及未识别页，计算missing=B-O_f、candidate_extra=O_f-B、matched=B∩O_f。仅对该材料按规则应覆盖的车辆范围计算缺失，单车行驶证不要求覆盖整批车辆。U非空时candidate_extra可能对应尚未识别的基准行，只能输出候选额外与待确认；只有基准完整且归属明确时确认为extra。统计按材料组并集覆盖与单文件观察两层输出，重复页不重复计算车辆数。')
t=replace_line(t,'同组判定为重复','同组判定为重复或已确认机构替代经办版本时，effective选择agency，operator保留为suppressed并记录理由。仅单方存在的文件直接保留，同类型不同名不自动替代。同名同类型但内容差异或车辆归属不明时保留双方且不抑制经办材料，输出归并冲突；只有确认同一材料替代关系后才机构优先。冲突未解决的受影响字段和审核项置pending，不能仅凭机构优先产生通过结论。')
t=t.replace('上述编码为设计示例，应和业务系统字段表对照后冻结。批准状态为false时关联字段按规则置空并标注不适用，不解释为提取失败；状态未知时保留待确认，不能默认批准。','上述编码为设计示例，应和业务系统字段表对照后冻结。提取结果增加可选applicable布尔值。批准状态为false时关联字段value=null、applicable=false、field_status=success，表示成功判定不适用，不计入有效值提取成功数，单列not_applicable_count；不把审核not_applicable混入提取状态枚举。批准状态未知则applicable=null、field_status=pending，不能默认批准。旧字段统计保持原口径，新统计属性只对明确声明的新场景使用。')
t=t.replace('数值例子来自需规，','年检规则按需规分支处理：材料体现年检信息时“是否有年检”应为是；材料未体现且未上传交管12123我的机动车页截图时应为否；已上传截图但无法解析或识别时进入待确认，不能当作未上传。其他未明确分支按审核要点表配置。\n\n数值例子来自需规，')
t=replace_line(t,'pending在Worker','pending在Worker认领后变processing，也可以在排队期间直接变cancelled；Worker领取前检查取消状态。processing最终变completed、failed、cancelled或timeout。新增stage依次为queued、downloading、parsing、validating、extracting、checking、tracing、finalizing，审核和拆页补充auditing、splitting并按实际阶段裁剪。进度取已完成工作量/固定计划工作量，新增子阶段不能让已返回进度倒退；阶段内进度是估算值，只有结果提交完成才为1。')
t=t.replace('Worker消费持久队列，使用原子认领、租约心跳和run_id版本号，','run_id表示一次业务运行的不可变标识，技术重试或故障恢复不改变run_id，重新助审生成新task_id与run_id。Worker消费持久队列，使用原子认领、租约心跳、内部attempt_no和fencing_token，')
appendix=root/'evidence'/'api_final.md'
if '## 16 对外接口详细契约' not in t:
    t+='\n'+appendix.read_text('utf-8')
p.write_text(t,'utf-8')
print('Finalized overview and detail sources')
