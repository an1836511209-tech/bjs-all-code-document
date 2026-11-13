"""
图像质量检测服务

提供图像质量评估功能，包括：
1. 清晰度检测（多指标融合：Laplacian + Tenengrad + 方差系数）
2. 分辨率检测
3. 遮挡/噪点检测

支持进程池并行处理，提供顶层函数用于跨进程调用。
"""

import io
from typing import Dict, List, Tuple, Union
import warnings
warnings.filterwarnings("ignore")

import cv2
import numpy as np
from PIL import Image
from skimage import measure
from loguru import logger

from src.utils.exceptions import QualityCheckError
from config import quality_config


# ============================================================
# 进程池友好的顶层函数（用于 ProcessPoolExecutor）
# ============================================================

def check_image_quality_from_bytes(image_bytes: bytes, trace_id: str = "unknown") -> Dict:
    """
    从图像字节数据检测质量（进程池友好版本）
    
    此函数是顶层函数，可以被 ProcessPoolExecutor 序列化和调用。
    用于在子进程中执行 CPU 密集型的图像质量检测。
    
    Args:
        image_bytes: 图像的字节数据（PNG/JPEG等格式）
        trace_id: 追踪ID用于日志关联
        
    Returns:
        Dict: 质量检测结果，包含 clarity, resolution, occlusion, overall_status, message
        
    Raises:
        QualityCheckError: 图像处理失败时抛出
    """
    try:
        # 从字节数据加载图像
        image = Image.open(io.BytesIO(image_bytes))
        # 调用 QualityChecker 进行检测
        return QualityChecker.check_image_quality(image, trace_id)
    except Exception as e:
        raise QualityCheckError(f"图像质量检测失败: {str(e)}")


class QualityChecker:
    """图像质量检测器"""
    
    @classmethod
    def _normalize_image_size(cls, image: np.ndarray, trace_id: str = "unknown") -> np.ndarray:
        """
        归一化图像尺寸到标准评估尺寸
        
        Args:
            image: 图像数组
            trace_id: 追踪ID
            
        Returns:
            np.ndarray: 归一化后的图像
        """
        quality_logger = logger.bind(trace_id=trace_id, quality_check=True)
        
        height, width = image.shape[:2]
        max_dim = max(height, width)
        
        standard_size = quality_config.PREPROCESSING['standard_size']
        skip_threshold = quality_config.PREPROCESSING['skip_resize_threshold']
        
        # 如果图像尺寸接近标准尺寸（±20%），则不缩放
        if abs(max_dim - standard_size) / standard_size < skip_threshold:
            return image
        
        # 计算缩放比例
        scale = standard_size / max_dim
        new_width = int(width * scale)
        new_height = int(height * scale)
        
        # 使用高质量插值方法缩放
        if scale < 1:
            # 缩小：使用区域插值（更好的抗锯齿）
            resized = cv2.resize(image, (new_width, new_height), interpolation=cv2.INTER_AREA)
        else:
            # 放大：使用三次插值
            resized = cv2.resize(image, (new_width, new_height), interpolation=cv2.INTER_CUBIC)
        
        return resized
    
    @classmethod
    def _detect_image_type(cls, image: np.ndarray, trace_id: str = "unknown") -> str:
        """
        检测图像类型(彩色/灰度/黑白扫描件)
        
        Args:
            image: 图像数组
            trace_id: 追踪ID
            
        Returns:
            str: 图像类型 'color'/'grayscale'/'binary_scan'
        """
        quality_logger = logger.bind(trace_id=trace_id, quality_check=True)
        
        # 判断是否彩色
        if len(image.shape) == 2:
            gray = image
            is_color = False
        elif len(image.shape) == 3:
            if image.shape[2] == 1:
                gray = image[:, :, 0]
                is_color = False
            else:
                # 计算色彩饱和度
                gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
                color_diff = np.mean(np.std(image, axis=2))
                is_color = color_diff > 5  # 如果RGB通道差异大于5,认为是彩色
        else:
            gray = image
            is_color = False
        
        if is_color:
            return 'color'
        
        # 判断是否为二值化扫描件
        # 统计灰度直方图,如果主要集中在黑白两端,认为是扫描件
        hist, _ = np.histogram(gray, bins=256, range=(0, 256))
        hist_normalized = hist / gray.size
        
        # 计算黑色(0-50)和白色(200-255)像素占比
        black_ratio = np.sum(hist_normalized[:50])
        white_ratio = np.sum(hist_normalized[200:])
        middle_ratio = 1 - black_ratio - white_ratio
        
        # 如果黑白像素占比超过阈值,中间灰度少,认为是二值扫描件
        if black_ratio + white_ratio > 0.78 and middle_ratio < 0.22:
            return 'binary_scan'
        else:
            return 'grayscale'
    
    @classmethod
    def check_image_quality(cls, image: Union[Image.Image, np.ndarray], trace_id: str = "unknown") -> Dict:
        """
        综合图像质量检测
        
        Args:
            image: PIL图像或NumPy数组
            trace_id: 追踪ID用于日志关联
            
        Returns:
            Dict: 质量检测结果
        """
        quality_logger = logger.bind(trace_id=trace_id, quality_check=True)
        
        try:
            # 统一转换为NumPy数组
            if isinstance(image, Image.Image):
                img_array = np.array(image)
            else:
                img_array = image
            
            # 记录原始尺寸
            orig_height, orig_width = img_array.shape[:2]
            
            # 检测图像类型
            image_type = cls._detect_image_type(img_array, trace_id)
            
            # 归一化图像尺寸用于清晰度评估（消除分辨率差异影响）
            normalized_img = cls._normalize_image_size(img_array, trace_id)
            
            # 检测各项质量指标
            clarity_result = cls.check_clarity(normalized_img, trace_id)
            resolution_result = cls.check_resolution(img_array, trace_id)
            occlusion_result = cls.check_occlusion(img_array, trace_id, image_type)
            
            # 综合评估
            overall_status = cls._determine_overall_status(
                clarity_result, resolution_result, occlusion_result
            )
            
            # 只在失败或警告时记录详细信息
            if overall_status != 'passed':
                quality_logger.info(
                    f"质量检测结果: {overall_status} | "
                    f"清晰度:{clarity_result['status']}({clarity_result.get('score', 'N/A')}) | "
                    f"分辨率:{resolution_result['status']} | "
                    f"遮挡度:{occlusion_result['status']}({occlusion_result.get('occlusion_score', 'N/A')})"
                )
            
            result = {
                'clarity': clarity_result,
                'resolution': resolution_result,
                'occlusion': occlusion_result,
                'overall_status': overall_status,
                'message': cls._generate_message(overall_status, clarity_result, resolution_result, occlusion_result)
            }
            
            return result
            
        except Exception as e:
            quality_logger.error(f"图像质量检测失败: {str(e)}")
            raise QualityCheckError(f"图像质量检测失败: {str(e)}")
    
    @classmethod
    def check_clarity(cls, image: np.ndarray, trace_id: str = "unknown") -> Dict:
        """
        检测图像清晰度（多指标融合：Laplacian + Tenengrad + 方差系数）
        
        Args:
            image: 图像数组（建议已归一化尺寸）
            trace_id: 追踪ID
            
        Returns:
            Dict: 清晰度检测结果
        """
        quality_logger = logger.bind(trace_id=trace_id, quality_check=True)
        
        try:
            # 转换为灰度图像
            if len(image.shape) == 3:
                gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            else:
                gray = image
            
            # === 指标1：拉普拉斯方差（边缘清晰度）===
            laplacian = cv2.Laplacian(gray, cv2.CV_64F)
            laplacian_var = laplacian.var()
            
            # === 指标2：Tenengrad梯度（高频细节）===
            # 使用Sobel算子计算梯度
            grad_x = cv2.Sobel(gray, cv2.CV_64F, 1, 0, ksize=3)
            grad_y = cv2.Sobel(gray, cv2.CV_64F, 0, 1, ksize=3)
            gradient_magnitude = np.sqrt(grad_x**2 + grad_y**2)
            
            # Tenengrad: 梯度幅值的平方和
            tenengrad = np.sum(gradient_magnitude**2) / gray.size
            
            # === 指标3：灰度方差系数（对比度）===
            gray_mean = np.mean(gray)
            gray_std = np.std(gray)
            variance_coeff = (gray_std / gray_mean) * 100 if gray_mean > 0 else 0
            
            # === 多指标融合评分（归一化到0-100）===
            # 归一化各指标（基于真实扫描文档的经验参考值）
            lap_ref = quality_config.CLARITY_NORMALIZATION['laplacian_ref']
            ten_ref = quality_config.CLARITY_NORMALIZATION['tenengrad_ref']
            var_ref = quality_config.CLARITY_NORMALIZATION['variance_ref']

            lap_norm = min(laplacian_var / (lap_ref / 100), 100)
            ten_norm = min(tenengrad / (ten_ref / 100), 100)
            var_norm = min(variance_coeff / (var_ref / 100), 100)
            
            # 加权融合
            weights = quality_config.CLARITY_FUSION_WEIGHTS
            fusion_score = (
                lap_norm * weights['laplacian'] +
                ten_norm * weights['tenengrad'] +
                var_norm * weights['variance']
            )
            
            # 自适应调整：如果图像对比度很低（可能是过曝/欠曝），降低评分
            penalty_config = quality_config.LOW_CONTRAST_PENALTY
            if variance_coeff < penalty_config['threshold']:
                fusion_score *= penalty_config['factor']
            
            # === 根据阈值判断清晰度等级 ===
            thresholds = quality_config.CLARITY_THRESHOLDS
            if fusion_score >= thresholds['excellent']:
                status = 'passed'
                level = 'excellent'
            elif fusion_score >= thresholds['good']:
                status = 'passed'
                level = 'good'
            elif fusion_score >= thresholds['fair']:
                status = 'warning'
                level = 'fair'
            else:
                status = 'failed'
                level = 'poor'
            
            return {
                'status': status,
                'score': round(float(fusion_score), 2),
                'level': level,
                'threshold': thresholds['good'],
                'method': 'multi_metric_fusion',
                'details': {
                    'laplacian_variance': round(float(laplacian_var), 2),
                    'tenengrad': round(float(tenengrad), 2),
                    'variance_coefficient': round(float(variance_coeff), 2),
                    'normalized_scores': {
                        'laplacian': round(float(lap_norm), 2),
                        'tenengrad': round(float(ten_norm), 2),
                        'variance': round(float(var_norm), 2)
                    }
                }
            }
            
        except Exception as e:
            quality_logger.error(f"清晰度检测失败: {str(e)}")
            raise QualityCheckError(f"清晰度检测失败: {str(e)}")
    
    
    @classmethod
    def check_resolution(cls, image: np.ndarray, trace_id: str = "unknown") -> Dict:
        """
        检测图像分辨率
        
        Args:
            image: 图像数组
            trace_id: 追踪ID
            
        Returns:
            Dict: 分辨率检测结果
        """
        quality_logger = logger.bind(trace_id=trace_id, quality_check=True)
        
        height, width = image.shape[:2]
        
        thresholds = quality_config.RESOLUTION_THRESHOLDS
        
        # 判断分辨率等级
        if (width >= thresholds['recommended_width'] and 
            height >= thresholds['recommended_height']):
            status = 'passed'
            level = 'excellent'
        elif (width >= thresholds['min_width'] and 
              height >= thresholds['min_height']):
            status = 'passed'
            level = 'good'
        else:
            status = 'failed'
            level = 'poor'
        
        return {
            'status': status,
            'width': width,
            'height': height,
            'resolution': f"{width}x{height}",
            'level': level,
            'min_required': f"{thresholds['min_width']}x{thresholds['min_height']}"
        }
    
    @classmethod
    def check_occlusion(cls, image: np.ndarray, trace_id: str = "unknown", image_type: str = "grayscale") -> Dict:
        """
        检测图像遮挡/噪点(针对不同图像类型自适应调整)
        
        Args:
            image: 图像数组
            trace_id: 追踪ID
            image_type: 图像类型 'color'/'grayscale'/'binary_scan'
            
        Returns:
            Dict: 遮挡检测结果
        """
        quality_logger = logger.bind(trace_id=trace_id, quality_check=True)
        
        try:
            # 转换为灰度图像
            if len(image.shape) == 3:
                gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            else:
                gray = image
            
            height, width = gray.shape
            total_pixels = height * width
            
            thresholds = quality_config.OCCLUSION_THRESHOLDS
            threshold_info: Dict[str, float] = {}

            edge_map = cv2.Canny(gray, 50, 150)
            edge_ratio = np.count_nonzero(edge_map) / total_pixels
            
            # 针对黑白扫描件的特殊处理
            if image_type == 'binary_scan':
                # 1. 检测极黑区域(真正的扫描缺陷,不是文字)
                extreme_black_threshold = thresholds.get('extreme_black_threshold', 10)
                extreme_black_pixels = np.sum(gray < extreme_black_threshold)
                extreme_black_ratio = extreme_black_pixels / total_pixels
                
                # 2. 检测边缘黑边(扫描仪边缘)
                border_size = max(int(min(height, width) * 0.05), 1)
                top_border = gray[:border_size, :]
                bottom_border = gray[-border_size:, :]
                left_border = gray[:, :border_size]
                right_border = gray[:, -border_size:]
                
                border_pixels = top_border.size + bottom_border.size + left_border.size + right_border.size
                border_black = (np.sum(top_border < 30) + np.sum(bottom_border < 30) + 
                               np.sum(left_border < 30) + np.sum(right_border < 30))
                border_black_ratio = border_black / border_pixels
                
                # 3. 跳过噪点检测(文字笔画会被误判)
                noise_ratio = 0.0
                noise_pixels = 0
                
                black_ratio = extreme_black_ratio
                black_pixels = extreme_black_pixels
                large_occlusions = []
                
                # 综合判断(宽松策略)
                issues = []
                warnings = []
                
                scan_max_black = thresholds.get('scan_max_black_ratio', thresholds['max_black_ratio'])
                scan_warning_black = thresholds.get('scan_warning_black_ratio', thresholds['warning_black_ratio'])
                
                if extreme_black_ratio > scan_max_black:
                    issues.append(f"图像存在大面积黑色区域 ({extreme_black_ratio:.2%})")
                elif extreme_black_ratio > scan_warning_black:
                    warnings.append(f"图像边缘可能存在黑边 ({extreme_black_ratio:.2%})")
                
                # 边缘黑边检测
                scan_border_ratio = thresholds.get('scan_border_black_ratio', 0.60)
                if border_black_ratio > scan_border_ratio:
                    warnings.append(f"检测到扫描边缘黑边 ({border_black_ratio:.2%})")
                
                threshold_info = {
                    'black_warning': round(scan_warning_black, 4),
                    'black_fail': round(scan_max_black, 4),
                    'border_warning': round(scan_border_ratio, 4)
                }
                
            else:
                # 原始检测逻辑(用于彩色图和灰度图)
                black_warning_threshold = thresholds['warning_black_ratio']
                black_fail_threshold = thresholds['max_black_ratio']
                noise_warning_threshold = thresholds['warning_noise_ratio']
                noise_fail_threshold = thresholds['max_noise_ratio']
                min_contour_area = thresholds['min_contour_area']
                small_area_warning_ratio = thresholds['small_area_warning_ratio']
                large_occlusion_fail_ratio = thresholds['max_large_occlusion_ratio']
                
                # 1. 检测黑色区域（可能是扫描缺陷）
                black_threshold = thresholds['black_pixel_threshold']
                black_pixels = np.sum(gray < black_threshold)
                black_ratio = black_pixels / total_pixels
                
                # 2. 检测噪点（小的异常区域）
                kernel = np.ones((3, 3), np.uint8)
                otsu_threshold, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
                opened = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel, iterations=2)
                noise = cv2.absdiff(binary, opened)
                noise_pixels = np.sum(noise > 0)
                noise_ratio = noise_pixels / total_pixels
                
                if edge_ratio > 0.025:
                    adjust_factor = min(2.0, 1 + (edge_ratio - 0.025) * 15)
                    texture_scale = 1 + (adjust_factor - 1) * 0.85
                    area_scale = 1 + (adjust_factor - 1) * 0.75
                    
                    black_warning_threshold = min(black_warning_threshold * adjust_factor, 0.9)
                    black_fail_threshold = min(black_fail_threshold * adjust_factor, 0.95)
                    noise_warning_threshold = min(noise_warning_threshold * texture_scale, 0.9)
                    noise_fail_threshold = min(noise_fail_threshold * texture_scale, 0.95)
                    min_contour_area = int(min_contour_area * area_scale)
                    small_area_warning_ratio = min(small_area_warning_ratio * texture_scale, 0.30)
                    large_occlusion_fail_ratio = min(large_occlusion_fail_ratio * texture_scale, 0.40)
                
                # 3. 检测大面积遮挡
                contours, _ = cv2.findContours(noise, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                
                large_occlusions = []
                for contour in contours:
                    area = cv2.contourArea(contour)
                    if area > min_contour_area:
                        large_occlusions.append({
                            'area': area,
                            'ratio': area / total_pixels
                        })
                
                # 综合判断
                issues = []
                warnings = []
                
                # 检查黑色区域
                if black_ratio > black_fail_threshold:
                    issues.append(f"黑色区域过多 ({black_ratio:.2%})")
                elif black_ratio > black_warning_threshold:
                    warnings.append(f"黑色区域较多 ({black_ratio:.2%})")
                
                # 检查噪点
                if noise_ratio > noise_fail_threshold:
                    issues.append(f"噪点过多 ({noise_ratio:.2%})")
                elif noise_ratio > noise_warning_threshold:
                    warnings.append(f"检测到轻微噪点 ({noise_ratio:.2%})")
                
                # 检查大面积遮挡
                if large_occlusions:
                    large_count = len(large_occlusions)
                    total_large_area = sum(occ['area'] for occ in large_occlusions)
                    large_area_ratio = total_large_area / total_pixels
                    
                    if large_area_ratio > large_occlusion_fail_ratio:
                        issues.append(f"检测到 {large_count} 个大面积异常区域")
                    elif large_area_ratio > small_area_warning_ratio:
                        warnings.append(f"检测到 {large_count} 个小异常区域 ({large_area_ratio:.2%})")
                
                threshold_info = {
                    'black_warning': round(black_warning_threshold, 4),
                    'black_fail': round(black_fail_threshold, 4),
                    'noise_warning': round(noise_warning_threshold, 4),
                    'noise_fail': round(noise_fail_threshold, 4),
                    'contour_warning': round(small_area_warning_ratio, 4),
                    'contour_fail': round(large_occlusion_fail_ratio, 4),
                    'min_contour_area': float(min_contour_area)
                }
            
            # 确定状态
            if issues:
                status = 'failed'
            elif warnings:
                status = 'warning'  
            else:
                status = 'passed'
            
            return {
                'status': status,
                'black_ratio': round(black_ratio, 4),
                'noise_ratio': round(noise_ratio, 4),
                'edge_ratio': round(edge_ratio, 4),
                'large_occlusions': large_occlusions,
                'issues': issues + warnings,  # 合并问题和警告
                'occlusion_score': round(black_ratio + noise_ratio, 4),
                'detail': {
                    'serious_issues': issues,
                    'warnings': warnings,
                    'total_pixels': total_pixels,
                    'black_pixels': black_pixels,
                    'noise_pixels': noise_pixels,
                    'edge_ratio': round(edge_ratio, 4),
                    'thresholds': threshold_info
                }
            }
            
        except Exception as e:
            quality_logger.error(f"遮挡检测失败: {str(e)}")
            raise QualityCheckError(f"遮挡检测失败: {str(e)}")
    
    @classmethod
    def _determine_overall_status(
        cls, 
        clarity_result: Dict, 
        resolution_result: Dict, 
        occlusion_result: Dict
    ) -> str:
        """
        根据各项检测结果确定整体状态
        
        Args:
            clarity_result: 清晰度检测结果
            resolution_result: 分辨率检测结果  
            occlusion_result: 遮挡检测结果
            
        Returns:
            str: 整体状态 (passed/warning/failed)
        """
        statuses = [
            clarity_result['status'],
            resolution_result['status'], 
            occlusion_result['status']
        ]
        
        # 如果任何一项失败，整体失败
        if 'failed' in statuses:
            return 'failed'
        
        # 如果有警告项，整体警告
        if 'warning' in statuses:
            return 'warning'
        
        # 全部通过
        return 'passed'
    
    @classmethod
    def _generate_message(
        cls, 
        overall_status: str,
        clarity_result: Dict,
        resolution_result: Dict, 
        occlusion_result: Dict
    ) -> str:
        """
        生成质量检测消息
        
        Args:
            overall_status: 整体状态
            clarity_result: 清晰度结果
            resolution_result: 分辨率结果
            occlusion_result: 遮挡结果
            
        Returns:
            str: 质量检测消息
        """
        if overall_status == 'passed':
            return "文件质量校验通过"
        
        issues = []
        
        if clarity_result['status'] == 'failed':
            issues.append("图片清晰度不足，请重新上传清晰图片文件")
        elif clarity_result['status'] == 'warning':
            issues.append("图片清晰度较低，建议重新上传更清晰的文件")
        
        if resolution_result['status'] == 'failed':
            issues.append("图片分辨率较低，请重新上传高分辨率图片文件")
        
        if occlusion_result['status'] == 'failed':
            issues.append("图片存在遮挡，请重新上传无遮挡图片文件")
        elif occlusion_result['status'] == 'warning':
            issues.append("图片可能存在轻微遮挡或噪点")
        
        return "; ".join(issues) if issues else "文件质量存在问题"


# ============================================================
# PDF 页面处理函数（进程池友好）
# ============================================================

def process_pdf_page(pdf_bytes: bytes, page_num: int, dpi: int = 200) -> Dict:
    """
    处理单个 PDF 页面：转换为图像并检测质量（进程池友好版本）
    
    此函数是顶层函数，可以被 ProcessPoolExecutor 序列化和调用。
    在子进程中执行 PDF 页面渲染和质量检测。
    
    Args:
        pdf_bytes: PDF 文件的字节数据
        page_num: 要处理的页码（0-based）
        dpi: 渲染 DPI
        
    Returns:
        Dict: 该页面的质量检测结果
        
    Raises:
        QualityCheckError: 处理失败时抛出
    """
    import fitz  # PyMuPDF
    
    try:
        # 打开 PDF 文档
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        
        if page_num >= len(doc):
            doc.close()
            raise QualityCheckError(f"页码 {page_num} 超出 PDF 页数范围")
        
        # 加载指定页面
        page = doc.load_page(page_num)
        
        # 设置渲染参数
        zoom = dpi / 72.0  # PyMuPDF 使用 72 DPI 作为基准
        mat = fitz.Matrix(zoom, zoom)
        
        # 渲染页面为图像
        pix = page.get_pixmap(matrix=mat, alpha=False)
        
        # 转换为 PIL Image
        img_data = pix.tobytes("ppm")
        image = Image.open(io.BytesIO(img_data))
        
        doc.close()
        
        # 执行质量检测
        trace_id = f"pdf_page_{page_num}"
        return QualityChecker.check_image_quality(image, trace_id)
        
    except fitz.FileDataError as e:
        raise QualityCheckError(f"PDF 文件损坏或格式不正确: {str(e)}")
    except Exception as e:
        raise QualityCheckError(f"PDF 页面 {page_num} 处理失败: {str(e)}")
