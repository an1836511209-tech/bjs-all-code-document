"""Generate publication-sized design diagrams with the bundled Pillow runtime.

Run with the Codex bundled Python, not system Python. Existing output files are
preserved unless --replace-generated is explicitly supplied.
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
FONT = r"C:\Windows\Fonts\msyh.ttc"
BOLD = r"C:\Windows\Fonts\msyhbd.ttc"
NAVY = "#17324D"
INK = "#263849"
GRAY = "#82909E"
PALE = "#F3F6F9"
BLUE = "#EAF1F8"
LINE = "#B4BEC8"
WHITE = "#FFFFFF"


def font(size: int, bold: bool = False):
    return ImageFont.truetype(BOLD if bold else FONT, size)


def text_center(draw, box, lines, size=42, fill=INK, bold=False, gap=14):
    if isinstance(lines, str):
        lines = lines.split("\n")
    f = font(size, bold)
    heights = [draw.textbbox((0, 0), line, font=f)[3] - draw.textbbox((0, 0), line, font=f)[1] for line in lines]
    total = sum(heights) + gap * (len(lines) - 1)
    y = (box[1] + box[3] - total) / 2
    for line, h in zip(lines, heights):
        bounds = draw.textbbox((0, 0), line, font=f)
        w = bounds[2] - bounds[0]
        draw.text(((box[0] + box[2] - w) / 2, y - bounds[1]), line, font=f, fill=fill)
        y += h + gap


def node(draw, box, title, body=None, tag=None, fill=WHITE, title_size=43):
    draw.rounded_rectangle(box, radius=22, fill=fill, outline=LINE, width=3)
    if body is None:
        text_center(draw, box, title, size=title_size, bold=True)
        return
    pad = 18
    title_bottom = box[1] + 78
    text_center(draw, (box[0] + pad, box[1] + 12, box[2] - pad, title_bottom), title, size=title_size, bold=True)
    body_bottom = box[3] - (53 if tag else 10)
    text_center(draw, (box[0] + pad, title_bottom, box[2] - pad, body_bottom), body, size=35, gap=12)
    if tag:
        text_center(draw, (box[0] + pad, box[3] - 54, box[2] - pad, box[3] - 9), tag, size=31, fill=NAVY)


def arrow(draw, points, color=GRAY, width=5, dashed=False, head=18):
    if dashed:
        for a, b in zip(points, points[1:]):
            dx, dy = b[0] - a[0], b[1] - a[1]
            distance = math.hypot(dx, dy)
            if not distance:
                continue
            for k in range(0, int(distance), 26):
                end = min(k + 14, distance)
                draw.line([(a[0] + dx * k / distance, a[1] + dy * k / distance), (a[0] + dx * end / distance, a[1] + dy * end / distance)], fill=color, width=width)
    else:
        draw.line(points, fill=color, width=width, joint="curve")
    a, b = points[-2:]
    angle = math.atan2(b[1] - a[1], b[0] - a[0])
    spread = 0.48
    triangle = [b, (b[0] - head * math.cos(angle - spread), b[1] - head * math.sin(angle - spread)), (b[0] - head * math.cos(angle + spread), b[1] - head * math.sin(angle + spread))]
    draw.polygon(triangle, fill=color)


def canvas(height, title, subtitle):
    im = Image.new("RGB", (2400, height), WHITE)
    draw = ImageDraw.Draw(im)
    text_center(draw, (50, 28, 2350, 113), title, 61, NAVY, True)
    text_center(draw, (80, 119, 2320, 177), subtitle, 33, INK)
    return im, draw


def save(im, name, replace):
    ASSETS.mkdir(parents=True, exist_ok=True)
    out = ASSETS / name
    if out.exists() and not replace:
        raise FileExistsError(f"Output already exists: {out}")
    im.save(out, dpi=(380, 380))
    print(f"{out} ({im.width} x {im.height})")


def architecture(replace):
    im, d = canvas(1770, "三品类扩展目标架构", "在现有技术底座上扩展业务策略；各节点标注建设方式")
    band_y = [(215, 440), (510, 735), (805, 1050), (1120, 1355), (1425, 1660)]
    layers = ["接入层", "编排层", "领域层", "能力层", "存储层"]
    boxes = [
        [("原生 API", "/api/v1", "复用"), ("中台网关适配", "/api/platform/v1", "复用"), ("任务与结果接入", "业务系统调用与结果回填", "改造")],
        [("业务上下文", "品类 / 阶段 / 处置模式 / 节点", "新增"), ("规则快照与发布", "固定版本 / 可追溯 / 可回滚", "新增"), ("任务与幂等", "原子受理 / 检查点 / 终态控制", "改造")],
        [("产权转让 · 企业增资", "预披露 / 正式披露辅助录入", "新增业务规则"), ("机动车录入", "公共信息 / 多车明细 / 材料匹配", "新增"), ("机动车助审与拆页", "拍卖 / 解体 · 两节点 · 材料归并", "新增")],
        [("文档解析与 OCR", "Paddle / MinerU / Tika / Excel", "复用"), ("模型与规则计算", "LLM 提取 / 语义审核 / 确定性校验", "复用并新增计算规则"), ("证据溯源与 PDF", "锚点 / 坐标 / 高亮 / 原页映射", "复用并改造")],
        [("Redis", "运行状态 / 幂等键 / 缓存隔离", "复用并改造"), ("对象存储", "原件 / 预览 / 拆页派生文件", "复用"), ("持久任务与规则版本", "任务恢复 / 不可变规则快照", "新增")],
    ]
    x_positions = [(325, 950), (995, 1620), (1665, 2290)]
    for i, ((y1, y2), layer, row) in enumerate(zip(band_y, layers, boxes)):
        d.rounded_rectangle((75, y1, 2325, y2), radius=22, fill=PALE, outline=LINE, width=2)
        text_center(d, (85, y1, 300, y2), layer, 44, NAVY, True)
        for (x1, x2), (title, body, tag) in zip(x_positions, row):
            node(d, (x1, y1 + 20, x2, y2 - 20), title, body, tag, title_size=39)
        if i < 4:
            arrow(d, [(1320, y2 + 6), (1320, band_y[i + 1][0] - 8)], width=6)
    text_center(d, (95, 1684, 2305, 1740), "建设方式以代码现状为基线；持久任务、发布快照和车辆领域编排为拟建能力", 31, INK)
    save(im, "architecture.png", replace)


def data_model(replace):
    im, d = canvas(1600, "任务、实体、结果与证据关系", "统一保存业务归属与版本；结构名称为详细设计中的逻辑模型")
    task = (75, 590, 505, 825)
    material = (675, 215, 1125, 440)
    snapshot = (675, 585, 1125, 810)
    entity = (675, 1010, 1125, 1235)
    split = (1300, 215, 1760, 440)
    field = (1300, 820, 1760, 1045)
    audit = (1300, 1240, 1760, 1465)
    evidence = (1900, 1010, 2325, 1235)
    node(d, task, "Task", ["业务上下文 / 执行状态", "输入指纹 / 快照 ID"], "父任务与子任务可关联", BLUE)
    node(d, material, "Material", ["原件 / 材料类型 / 上传角色", "实体归属 / 报告期 / 哈希"], "原件保留版本")
    node(d, snapshot, "RuleSnapshot", ["业务策略 / 规则与字典版本", "模型及提示词版本 / 哈希"], "任务开始时固定")
    node(d, entity, "Entity", ["项目 / 转让方 / 车辆等", "稳定 entity_id / 对象路径"], "多行数据保留独立身份")
    node(d, split, "SplitArtifact", ["拆页文件 / 车辆归属", "原材料 ID + 原页映射"], "派生文件不覆盖原件")
    node(d, field, "FieldResult", ["实体 + 字段 / 规范值", "多来源值 / 不一致提示"], "逐实体、逐字段输出")
    node(d, audit, "AuditResult", ["实体 + 规则 / 审核节点", "结论 / 要点说明 / 版本"], "逐实体、逐规则输出")
    node(d, evidence, "Evidence", ["原材料 ID / 页码 / 锚点", "坐标或单元格 / 原文"], "所有结论可回看原文")
    arrow(d, [(505, 707), (580, 707), (580, 327), (675, 327)])
    arrow(d, [(580, 707), (675, 697)])
    arrow(d, [(580, 707), (580, 1122), (675, 1122)])
    arrow(d, [(1300, 327), (1125, 327)])
    text_center(d, (1130, 245, 1295, 300), "原页映射", 29)
    arrow(d, [(1125, 1122), (1205, 1122), (1205, 932), (1300, 932)])
    arrow(d, [(1205, 1122), (1205, 1352), (1300, 1352)])
    arrow(d, [(1760, 932), (1830, 932), (1830, 1122), (1900, 1122)])
    arrow(d, [(1760, 1352), (1830, 1352), (1830, 1122), (1900, 1122)])
    arrow(d, [(2112, 1010), (2112, 180), (900, 180), (900, 215)], dashed=True)
    d.rectangle((1790, 220, 2350, 280), fill=WHITE)
    text_center(d, (1790, 220, 2350, 280), "证据引用原件与原页", 31)
    text_center(d, (105, 1515, 2300, 1570), "实线：任务归属、结果生成或证据引用；虚线：Evidence 回溯 Material；表名为逻辑设计，非现有表", 31)
    save(im, "data_model.png", replace)


def vehicle_flow(replace):
    im, d = canvas(1540, "机动车业务处理流程", "有纸业务 · 拍卖 / 解体 · 智能处理与业务审批衔接")
    columns = [(110, 770), (870, 1530), (1630, 2290)]
    ys = [(240, 485), (660, 905), (1080, 1325)]
    entries = [
        [("经办批量上传", "选择拍卖 / 解体及主体性质", "业务系统"), ("材料匹配与质量检测", "识别材料 / 校验数量与号牌", "智能体"), ("公共信息与逐车提取", "返回字段建议、来源及差异", "智能体")],
        [("经办人工确认", "补充字段 / 勾选按车拆页", "业务系统触发；拆页由智能体执行"), ("任务派发与机构补传", "服务机构填写并补充附件", "业务系统"), ("材料归并与助审节点 1", "保留版本、替代原因与审核证据", "智能体")],
        [("补充项目及竞价信息", "字段或附件变更后重新助审", "业务系统"), ("助审节点 2", "按模式 / 节点执行规则并输出结论", "智能体"), ("人工逐级审批", "经理、交易审核部查看节点 2", "业务系统")],
    ]
    for row, ((y1, y2), group) in enumerate(zip(ys, entries)):
        for col, ((x1, x2), (title, body, tag)) in enumerate(zip(columns, group)):
            node(d, (x1, y1, x2, y2), title, body, tag, fill=PALE if tag == "智能体" else WHITE, title_size=39)
            if col < 2:
                arrow(d, [(x2 + 10, (y1 + y2) // 2), (columns[col + 1][0] - 10, (y1 + y2) // 2)])
        if row < 2:
            # Route outside the cards to make the reading order unambiguous.
            mid = (y2 + ys[row + 1][0]) // 2
            arrow(d, [(1960, y2 + 8), (1960, mid), (440, mid), (440, ys[row + 1][0] - 10)])
    text_center(d, (100, 1380, 2300, 1500), ["审核结论：通过 / 不通过 / 待确认 / 无需审核；全部结论保留材料与版本证据", "智能助审结果由业务人员使用，业务系统负责审批状态流转"], 33)
    save(im, "vehicle_flow.png", replace)


def task_state(replace):
    im, d = canvas(1080, "任务执行状态与请求等待窗口", "执行状态与业务审核结论独立；请求返回 pending 不表示执行失败")
    pending = (150, 300, 650, 510)
    processing = (950, 300, 1450, 510)
    completed = (1750, 300, 2250, 510)
    node(d, pending, "pending", "等待认领", "初始状态", PALE)
    node(d, processing, "processing", "执行阶段与检查点", "租约与心跳", BLUE)
    node(d, completed, "completed", "结果提交成功", "合法终态", PALE)
    arrow(d, [(650, 405), (950, 405)])
    arrow(d, [(1450, 405), (1750, 405)])
    text_center(d, (650, 332, 950, 385), "Worker 认领", 30)
    text_center(d, (1450, 332, 1750, 385), "原子提交结果", 30)
    states = [(350, 700, 850, 880, "failed", "技术处理失败"), (950, 700, 1450, 880, "timeout", "超过任务执行期限"), (1550, 700, 2050, 880, "cancelled", "取消完成")]
    for x1, y1, x2, y2, title, body in states:
        node(d, (x1, y1, x2, y2), title, body, title_size=40)
        arrow(d, [(1200, 510), (1200, 620), ((x1 + x2) // 2, 620), ((x1 + x2) // 2, 700)])
    text_center(d, (110, 938, 2290, 1045), ["同步等待窗口到期：返回 task_id，后台继续；任务执行期限到期：进入 timeout", "pending 也可取消；终态原子提交，取消与成功竞争仅接受一个合法终态（拟建规范）"], 33)
    save(im, "task_state.png", replace)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--replace-generated", action="store_true")
    args = parser.parse_args()
    architecture(args.replace_generated)
    data_model(args.replace_generated)
    vehicle_flow(args.replace_generated)
    task_state(args.replace_generated)
