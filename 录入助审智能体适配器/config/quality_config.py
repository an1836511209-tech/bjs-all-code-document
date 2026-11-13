"""
图像质量检测配置文件
"""

# --- 清晰度检测配置 ---
CLARITY_THRESHOLDS = {
    'excellent': 65.0,    # 优秀：融合分数 >= 65
    'good': 35.0,         # 良好：融合分数 >= 35
    'fair': 15.0,         # 一般：融合分数 >= 15
    'poor': 0.0           # 较差：融合分数 < 15
}

# 清晰度指标归一化参数 (用于将原始指标值映射到 0-100 的评分)
# 参考值是基于大量真实扫描文档统计得出的经验值
CLARITY_NORMALIZATION = {
    'laplacian_ref': 800,   # 拉普拉斯方差参考值
    'tenengrad_ref': 20000, # Tenengrad梯度参考值
    'variance_ref': 35.0    # 方差系数参考值 (%)
}

# 清晰度多指标融合权重
CLARITY_FUSION_WEIGHTS = {
    'laplacian': 0.4,
    'tenengrad': 0.4,
    'variance': 0.2
}

# 低对比度惩罚配置
LOW_CONTRAST_PENALTY = {
    'threshold': 8.0,  # 当方差系数低于此值时，触发惩罚
    'factor': 0.85     # 分数乘以该因子
}


# --- 分辨率检测配置 ---
RESOLUTION_THRESHOLDS = {
    'min_width': 600,
    'min_height': 800,
    'recommended_width': 1200,
    'recommended_height': 1600
}


# --- 遮挡/噪点检测配置 ---
OCCLUSION_THRESHOLDS = {
    # 通用检测阈值(用于彩色图和灰度图)
    'black_pixel_threshold': 30,     # 定义"黑色"像素的亮度阈值
    'max_noise_ratio': 0.25,         # 最大噪点占比（25%），超过则失败
    'warning_noise_ratio': 0.18,     # 噪点警告阈值（18%）
    'max_black_ratio': 0.50,         # 最大黑色区域占比 (50%)，超过则失败
    'warning_black_ratio': 0.35,     # 黑色区域警告阈值（35%）
    'min_contour_area': 1200,        # 识别为大块遮挡的最小轮廓面积（像素）
    'small_area_warning_ratio': 0.08,  # 小异常区域累计面积 > 8% 则警告
    'max_large_occlusion_ratio': 0.15, # 大面积异常区域累计占比 > 15% 则失败
    
    # 黑白扫描件专用阈值(宽松策略,避免文字被误判)
    'extreme_black_threshold': 10,   # 极黑区域阈值(真正的扫描缺陷)
    'scan_max_black_ratio': 0.50,     # 黑白扫描件允许50%极黑区域
    'scan_warning_black_ratio': 0.35, # 黑白扫描件35%以上给警告
    'scan_border_black_ratio': 0.70,  # 扫描件边缘区域黑色占比超过70%给警告
}


# --- 图像预处理配置 ---
PREPROCESSING = {
    'standard_size': 1500, # 归一化评估尺寸（长边）
    'skip_resize_threshold': 0.2 # 如果图像尺寸与标准尺寸差异小于此比例(20%)，则不缩放
}


