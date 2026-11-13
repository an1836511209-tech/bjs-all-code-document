"""
本地页面方向检测器

使用 PaddleOCR 的 PP-LCNet_x1_0_doc_ori 模型检测 PDF/图像的页面方向（0°/90°/180°/270°），
在发送给 Paddle API 之前完成方向矫正，避免 Paddle 内部旋转导致 OCR 精度损失。

模型信息：
- 来源：PaddleOCR PP-LCNet_x1_0_doc_ori
- 输入：224x224 BGR 图像
- 输出：4 类（0=正常, 1=90°CW, 2=180°, 3=270°CW）
- 准确率：99.06%，CPU 推理 ~3ms/页

单例管理：
- get_rotation_detector() 获取进程级单例，模型只加载一次
- 加载失败时记录永久失败标记，后续调用直接返回 None（避免重复报错）
- reset_rotation_detector() 用于测试/调试时重置
"""

from typing import Dict, Optional, Tuple

import cv2
import fitz  # PyMuPDF
import numpy as np
from loguru import logger


# 模型类别到旋转角度的映射
LABEL_TO_ANGLE = {"0": 0, "90": 90, "180": 180, "270": 270}

# --- 进程级单例 ---
_detector_instance: Optional["RotationDetector"] = None
_detector_load_failed: bool = False


class RotationDetector:
    """
    基于 PaddleOCR PP-LCNet 的页面方向检测器。

    用于在发送给 Paddle API 之前检测并矫正 PDF 页面方向，
    使 Paddle 可以用 useDocOrientationClassify=False 调用，避免旋转插值损失 OCR 精度。
    """

    RENDER_DPI = 72  # 低 DPI 渲染，方向检测不需要高分辨率

    # 置信度阈值：低于此值视为模型不确定，不做旋转纠正
    MIN_CONFIDENCE = 0.5

    def __init__(self, model_name: str = "PP-LCNet_x1_0_doc_ori"):
        """
        初始化检测器。

        优先使用项目根目录下的本地模型文件（离线部署场景），
        本地不存在时回退到 paddleocr 默认的 ~/.paddlex/official_models/ 缓存路径。

        Args:
            model_name: PaddleOCR 模型名称
        """
        from pathlib import Path

        from paddleocr import DocImgOrientationClassification

        # 项目根目录下的本地模型目录
        project_root = Path(__file__).resolve().parent.parent.parent
        local_model_dir = project_root / model_name

        if local_model_dir.is_dir() and (local_model_dir / "inference.pdiparams").is_file():
            logger.info(f"加载旋转检测模型（本地）: {local_model_dir}")
            self.model = DocImgOrientationClassification(
                model_name=model_name, model_dir=str(local_model_dir)
            )
        else:
            logger.info(f"本地模型目录不存在，从缓存/远程加载: {model_name}")
            self.model = DocImgOrientationClassification(model_name=model_name)

        logger.info("旋转检测模型加载完成")

    def detect_rotation(self, image: np.ndarray) -> int:
        """
        检测图像的旋转角度。

        模型标签含义：内容相对于"正向阅读"顺时针偏转的角度。
        - "0" = 正常
        - "90" = 内容已顺时针偏转 90°（图像右侧朝上）
        - "180" = 内容已顺时针偏转 180°（倒置）
        - "270" = 内容已顺时针偏转 270°（图像左侧朝上）

        置信度低于 MIN_CONFIDENCE 时视为不确定，返回 0（不做纠正）。

        Args:
            image: BGR 格式的 numpy 数组

        Returns:
            内容顺时针偏转角度：0, 90, 180, 270
        """
        output = self.model.predict(input=image, batch_size=1)

        for res in output:
            label = res["label_names"][0]
            score = float(res["scores"][0])
            angle = LABEL_TO_ANGLE.get(label, 0)

            if score < self.MIN_CONFIDENCE:
                logger.debug(
                    f"旋转检测置信度不足: label={label}, angle={angle}°, "
                    f"score={score:.2%} < threshold={self.MIN_CONFIDENCE}，跳过纠正"
                )
                return 0

            if angle != 0:
                logger.info(f"检测到页面旋转: {angle}° (置信度: {score:.2%})")
            else:
                logger.debug(f"页面方向正常 (置信度: {score:.2%})")

            return angle

        return 0

    def preprocess_pdf(self, file_content: bytes) -> Tuple[bytes, Dict[int, int]]:
        """
        预处理 PDF：逐页检测方向，调整 /Rotate 元数据。

        检测策略（绝对旋转）：
        1. 暂存当前 /Rotate 值
        2. 将 /Rotate 设为 0，渲染页面的"原始内容"
        3. 对原始内容做方向检测
        4. 将检测结果转换为 /Rotate 值并设置

        方向约定：
        - 模型输出 detected_angle = 内容顺时针偏转角度（如 "90"=内容已顺时针偏转 90°）
        - PDF /Rotate = 显示时顺时针旋转角度
        - 内容已顺时针偏转 90° → 需要逆时针 90°（=顺时针 270°）才能纠正 → /Rotate=270
        - 公式：/Rotate = (360 - detected_angle) % 360

        Args:
            file_content: PDF 文件的字节内容

        Returns:
            (修改后的 PDF 字节, {页码: 内容顺时针偏转角度})
        """
        doc = fitz.open(stream=file_content, filetype="pdf")
        rotation_map: Dict[int, int] = {}
        modified = False

        for page_idx in range(doc.page_count):
            page = doc.load_page(page_idx)
            original_rotation = page.rotation  # 保存原始 /Rotate

            # 先将 /Rotate 归零，渲染页面的原始内容做方向检测
            # 这样模型看到的是页面的"物理方向"，不受现有元数据影响
            page.set_rotation(0)

            # 渲染页面为小图（72 DPI，方向检测够用）
            zoom = self.RENDER_DPI / 72.0
            mat = fitz.Matrix(zoom, zoom)
            pix = page.get_pixmap(matrix=mat, alpha=False)

            # 转为 OpenCV BGR 格式
            img_data = pix.tobytes("ppm")
            nparr = np.frombuffer(img_data, np.uint8)
            image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

            if image is None:
                logger.warning(f"页面 {page_idx} 渲染失败，跳过旋转检测")
                page.set_rotation(original_rotation)  # 恢复原始旋转
                rotation_map[page_idx] = 0
                continue

            # 检测原始内容的顺时针偏转角度
            detected_angle = self.detect_rotation(image)
            rotation_map[page_idx] = detected_angle

            # 转换为 PDF /Rotate 值（顺时针显示旋转）
            # 内容偏转 X° → 需要 (360-X)° 的显示旋转来纠正
            new_rotation = (360 - detected_angle) % 360 if detected_angle != 0 else 0

            if new_rotation != original_rotation:
                page.set_rotation(new_rotation)
                modified = True
                logger.info(
                    f"页面 {page_idx}: 内容偏转 {detected_angle}° → "
                    f"/Rotate {original_rotation}° → {new_rotation}°"
                )
            else:
                # 检测结果与原始一致，恢复
                page.set_rotation(original_rotation)
                logger.debug(
                    f"页面 {page_idx}: 方向正常 (内容偏转={detected_angle}°, /Rotate={original_rotation}°)"
                )

        if modified:
            output_bytes = doc.tobytes()
            doc.close()
            return output_bytes, rotation_map

        doc.close()
        return file_content, rotation_map

    def preprocess_image(self, file_content: bytes) -> Tuple[bytes, int]:
        """
        预处理图像：检测方向，必要时物理旋转图像。

        方向约定：detected_angle = 内容顺时针偏转角度。
        - 内容顺时针偏转 90° → 需要逆时针旋转 90° 来纠正 → ROTATE_90_COUNTERCLOCKWISE
        - 内容顺时针偏转 180° → 需要旋转 180° → ROTATE_180
        - 内容顺时针偏转 270° → 需要顺时针旋转 90° 来纠正 → ROTATE_90_CLOCKWISE

        与 PDF 不同，图像无法通过元数据控制旋转，必须物理旋转。

        Args:
            file_content: 图像文件的字节内容

        Returns:
            (修改后的图像字节, 内容顺时针偏转角度)
        """
        nparr = np.frombuffer(file_content, np.uint8)
        image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        if image is None:
            logger.warning("图像解码失败，跳过旋转检测")
            return file_content, 0

        detected_angle = self.detect_rotation(image)

        if detected_angle == 0:
            logger.debug("图像方向正常")
            return file_content, 0

        logger.info(f"检测到图像旋转: 内容顺时针偏转 {detected_angle}°，执行物理旋转")

        # 物理旋转图像（纠正内容偏转）
        # 内容已顺时针偏转 X° → 需要逆时针旋转 X°（= 顺时针旋转 360-X°）
        if detected_angle == 90:
            rotated = cv2.rotate(image, cv2.ROTATE_90_COUNTERCLOCKWISE)
        elif detected_angle == 180:
            rotated = cv2.rotate(image, cv2.ROTATE_180)
        elif detected_angle == 270:
            rotated = cv2.rotate(image, cv2.ROTATE_90_CLOCKWISE)
        else:
            logger.warning(f"不支持的旋转角度: {detected_angle}°，跳过旋转")
            return file_content, 0

        # 编码为 PNG（无损，保持质量）
        success, encoded = cv2.imencode('.png', rotated)
        if not success:
            logger.warning("图像编码失败，返回原始图像")
            return file_content, 0

        logger.info(f"图像旋转完成: 纠正了 {detected_angle}° 的顺时针偏转")
        return encoded.tobytes(), detected_angle


# ============ 单例工厂函数 ============

def get_rotation_detector() -> Optional[RotationDetector]:
    """
    获取 RotationDetector 进程级单例（懒加载）。

    模型只加载一次，后续调用返回同一实例，避免重复初始化开销。
    加载失败时记录永久失败标记，后续调用直接返回 None。

    Returns:
        RotationDetector 实例，或 None（模型加载失败时）
    """
    global _detector_instance, _detector_load_failed

    if _detector_load_failed:
        return None

    if _detector_instance is not None:
        return _detector_instance

    try:
        _detector_instance = RotationDetector()
        logger.info("RotationDetector 单例初始化完成")
        return _detector_instance
    except Exception as e:
        _detector_load_failed = True
        logger.error(f"RotationDetector 初始化失败（已永久跳过后续加载）: {e}")
        return None


def reset_rotation_detector() -> None:
    """
    重置 RotationDetector 单例（用于测试/调试）。

    清除缓存的实例和失败标记，允许下次调用重新加载模型。
    """
    global _detector_instance, _detector_load_failed
    _detector_instance = None
    _detector_load_failed = False
    logger.debug("RotationDetector 单例已重置")
