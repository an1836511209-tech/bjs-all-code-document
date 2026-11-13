"""
省市区数据助手

提供省市区行政区划数据的查询和匹配功能，用于级联字段提取。
"""

import json
from pathlib import Path
from typing import List, Optional, Dict, Any
from loguru import logger


class RegionDataHelper:
    """省市区数据助手类"""
    
    def __init__(self):
        """初始化并加载区域数据"""
        self.data: Dict[str, Any] = self._load_region_data()
        self._province_cache: Dict[str, Dict] = {}
        self._build_cache()
    
    def _load_region_data(self) -> Dict[str, Any]:
        """
        加载省市区数据
        
        Returns:
            Dict: 区域数据字典
        """
        # 获取数据文件路径（相对于项目根目录）
        current_file = Path(__file__)
        project_root = current_file.parent.parent.parent
        data_file = project_root / "data" / "region_data.json"
        
        logger.debug(f"尝试加载区域数据文件: {data_file}")
        logger.debug(f"当前文件: {current_file}")
        logger.debug(f"项目根目录: {project_root}")
        logger.debug(f"data 目录是否存在: {(project_root / 'data').exists()}")
        
        if not data_file.exists():
            logger.error(f"区域数据文件不存在: {data_file}")
            logger.error(f"请确保在 Docker 构建时已复制该文件")
            return {"provinces": []}
        
        try:
            with open(data_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            logger.info(f"成功加载区域数据: {len(data.get('provinces', []))} 个省份")
            return data
        except Exception as e:
            logger.error(f"加载区域数据失败: {e}")
            return {"provinces": []}
    
    def _build_cache(self):
        """构建省份缓存，便于快速查找"""
        for province in self.data.get('provinces', []):
            name = province.get('name', '')
            if name:
                self._province_cache[name] = province
                # 同时缓存标准化后的名称
                normalized = self._normalize_name(name)
                if normalized != name:
                    self._province_cache[normalized] = province
    
    def _normalize_name(self, name: str) -> str:
        """
        标准化名称：去除常见后缀
        
        Args:
            name: 原始名称
            
        Returns:
            str: 标准化后的名称
        """
        if not name:
            return ""
        
        name = name.strip()
        
        # 定义后缀列表（按长度从长到短排序，避免误匹配）
        suffixes = [
            '特别行政区',
            '自治区',
            '省',
            '市',
            '区',
            '县'
        ]
        
        for suffix in suffixes:
            if name.endswith(suffix):
                name = name[:-len(suffix)]
                break  # 只去除一个后缀
        
        return name.strip()
    
    def _find_province(self, province_name: str) -> Optional[Dict]:
        """
        查找省份（支持模糊匹配）
        
        Args:
            province_name: 省份名称
            
        Returns:
            Optional[Dict]: 省份数据字典，未找到返回 None
        """
        if not province_name:
            return None
        
        province_name = province_name.strip()
        
        # 1. 精确匹配
        if province_name in self._province_cache:
            return self._province_cache[province_name]
        
        # 2. 标准化后匹配
        normalized = self._normalize_name(province_name)
        if normalized in self._province_cache:
            return self._province_cache[normalized]
        
        # 3. 模糊匹配（包含关系）
        for province in self.data.get('provinces', []):
            name = province.get('name', '')
            if not name:
                continue
            
            # 省份名包含输入 或 输入包含省份名
            if normalized in name or name in province_name:
                logger.debug(f"模糊匹配省份: {province_name} -> {name}")
                return province
            
            # 去除后缀后再比较
            province_normalized = self._normalize_name(name)
            if normalized == province_normalized:
                logger.debug(f"标准化匹配省份: {province_name} -> {name}")
                return province
        
        logger.warning(f"未找到省份: {province_name}")
        return None
    
    def _find_city(self, province: Dict, city_name: str) -> Optional[Dict]:
        """
        在指定省份中查找城市（支持模糊匹配）
        
        Args:
            province: 省份数据字典
            city_name: 城市名称
            
        Returns:
            Optional[Dict]: 城市数据字典，未找到返回 None
        """
        if not city_name or not province:
            return None
        
        city_name = city_name.strip()
        normalized_city = self._normalize_name(city_name)
        
        cities = province.get('cities', [])
        
        # 1. 精确匹配
        for city in cities:
            name = city.get('name', '')
            if name == city_name:
                return city
        
        # 2. 标准化后匹配
        for city in cities:
            name = city.get('name', '')
            if self._normalize_name(name) == normalized_city:
                logger.debug(f"标准化匹配城市: {city_name} -> {name}")
                return city
        
        # 3. 模糊匹配
        for city in cities:
            name = city.get('name', '')
            if normalized_city in name or name in city_name:
                logger.debug(f"模糊匹配城市: {city_name} -> {name}")
                return city
        
        logger.warning(f"在 {province.get('name')} 中未找到城市: {city_name}")
        return None
    
    def get_all_provinces(self) -> List[str]:
        """
        获取所有省份名称列表
        
        Returns:
            List[str]: 省份名称列表
        """
        provinces = [p.get('name', '') for p in self.data.get('provinces', []) if p.get('name')]
        logger.debug(f"获取所有省份: {len(provinces)} 个")
        return provinces
    
    def get_cities_by_province(self, province_name: str) -> List[str]:
        """
        根据省份名称获取城市列表
        
        Args:
            province_name: 省份名称
            
        Returns:
            List[str]: 城市名称列表
        """
        province = self._find_province(province_name)
        if not province:
            logger.warning(f"获取城市失败: 未找到省份 {province_name}")
            return []
        
        cities = [c.get('name', '') for c in province.get('cities', []) if c.get('name')]
        logger.debug(f"获取 {province_name} 的城市: {len(cities)} 个")
        return cities
    
    def get_districts_by_city(self, province_name: str, city_name: str) -> List[str]:
        """
        根据省份和城市名称获取区县列表
        
        Args:
            province_name: 省份名称
            city_name: 城市名称
            
        Returns:
            List[str]: 区县名称列表
        """
        province = self._find_province(province_name)
        if not province:
            logger.warning(f"获取区县失败: 未找到省份 {province_name}")
            return []
        
        city = self._find_city(province, city_name)
        if not city:
            logger.warning(f"获取区县失败: 在 {province_name} 中未找到城市 {city_name}")
            return []
        
        districts = [d.get('name', '') for d in city.get('districts', []) if d.get('name')]
        logger.debug(f"获取 {province_name} {city_name} 的区县: {len(districts)} 个")
        return districts


# 全局单例实例
_region_helper_instance: Optional[RegionDataHelper] = None


def get_region_helper() -> RegionDataHelper:
    """
    获取 RegionDataHelper 单例
    
    Returns:
        RegionDataHelper: 区域数据助手实例
    """
    global _region_helper_instance
    if _region_helper_instance is None:
        _region_helper_instance = RegionDataHelper()
        logger.debug("创建 RegionDataHelper 单例")
    return _region_helper_instance







