#!/usr/bin/env python3
"""
北交所录入助审系统 - 省市区数据抓取脚本
用于从API抓取全国省、市、区的层级数据并保存为JSON格式
"""

import json
import time
from pathlib import Path
from typing import Dict, List, Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


# 配置
BASE_URL = "http://fed6a953.natappfree.cc"
OUTPUT_DIR = Path(__file__).parent.parent / "data"
OUTPUT_FILE = OUTPUT_DIR / "region_data.json"

# 请求配置
TIMEOUT = 30
MAX_RETRIES = 3
RETRY_BACKOFF = 0.5


class RegionDataFetcher:
    """区域数据抓取器"""

    def __init__(self, base_url: str):
        self.base_url = base_url
        self.session = self._create_session()
        self.stats = {
            "provinces": 0,
            "cities": 0,
            "districts": 0,
            "failed_requests": 0
        }

    def _create_session(self) -> requests.Session:
        """创建带重试机制的Session"""
        session = requests.Session()
        retry_strategy = Retry(
            total=MAX_RETRIES,
            backoff_factor=RETRY_BACKOFF,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET"]
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        return session

    def _make_request(self, endpoint: str) -> Dict[str, Any]:
        """发送HTTP请求并处理响应"""
        url = f"{self.base_url}{endpoint}"
        try:
            print(f"  请求: {endpoint}")
            response = self.session.get(url, timeout=TIMEOUT)
            response.raise_for_status()
            data = response.json()

            if data.get("code") != 200:
                print(f"  ⚠ API返回错误: {data.get('msg', '未知错误')}")
                self.stats["failed_requests"] += 1
                return None

            return data.get("data", [])

        except requests.exceptions.Timeout:
            print(f"  ✗ 请求超时: {endpoint}")
            self.stats["failed_requests"] += 1
            return None
        except requests.exceptions.RequestException as e:
            print(f"  ✗ 请求失败: {e}")
            self.stats["failed_requests"] += 1
            return None
        except json.JSONDecodeError as e:
            print(f"  ✗ JSON解析失败: {e}")
            self.stats["failed_requests"] += 1
            return None

    def fetch_provinces(self) -> List[Dict[str, Any]]:
        """获取所有省份数据"""
        print("\n[步骤 1/3] 获取省份数据...")
        provinces = self._make_request("/bjs/region/provinces")
        
        if provinces is None:
            return []
        
        self.stats["provinces"] = len(provinces)
        print(f"✓ 获取到 {len(provinces)} 个省份")
        return provinces

    def fetch_cities(self, province_id: int, province_name: str) -> List[Dict[str, Any]]:
        """获取指定省份的所有城市数据"""
        print(f"  获取 {province_name} 的城市数据...")
        cities = self._make_request(f"/bjs/region/cities/{province_id}")
        
        if cities is None:
            return []
        
        self.stats["cities"] += len(cities)
        print(f"  ✓ 获取到 {len(cities)} 个城市")
        return cities

    def fetch_districts(self, city_id: int, city_name: str) -> List[Dict[str, Any]]:
        """获取指定城市的所有区县数据"""
        districts = self._make_request(f"/bjs/region/districts/{city_id}")
        
        if districts is None:
            return []
        
        self.stats["districts"] += len(districts)
        return districts

    def fetch_all(self) -> Dict[str, Any]:
        """抓取所有省市区数据"""
        print("=" * 60)
        print("开始抓取省市区数据")
        print("=" * 60)
        
        start_time = time.time()
        result = {
            "provinces": [],
            "metadata": {
                "fetch_time": time.strftime("%Y-%m-%d %H:%M:%S"),
                "base_url": self.base_url
            }
        }

        # 获取省份
        provinces = self.fetch_provinces()
        if not provinces:
            print("✗ 未能获取省份数据")
            return result

        # 遍历每个省份
        print("\n[步骤 2/3] 获取城市数据...")
        for province in provinces:
            province_data = {
                **province,
                "cities": []
            }

            # 获取该省份的所有城市
            cities = self.fetch_cities(province["id"], province["name"])
            
            # 遍历每个城市
            for city in cities:
                city_data = {
                    **city,
                    "districts": []
                }

                # 获取该城市的所有区县
                districts = self.fetch_districts(city["id"], city["name"])
                city_data["districts"] = districts

                province_data["cities"].append(city_data)

            result["provinces"].append(province_data)

        elapsed_time = time.time() - start_time

        # 更新统计信息
        result["metadata"]["statistics"] = self.stats
        result["metadata"]["elapsed_time_seconds"] = round(elapsed_time, 2)

        print("\n[步骤 3/3] 数据抓取完成")
        self._print_statistics(elapsed_time)

        return result

    def _print_statistics(self, elapsed_time: float):
        """打印统计信息"""
        print("\n" + "=" * 60)
        print("数据抓取统计")
        print("=" * 60)
        print(f"省份数量: {self.stats['provinces']}")
        print(f"城市数量: {self.stats['cities']}")
        print(f"区县数量: {self.stats['districts']}")
        print(f"失败请求: {self.stats['failed_requests']}")
        print(f"总耗时: {elapsed_time:.2f} 秒")
        print("=" * 60)

    def save_to_file(self, data: Dict[str, Any], output_file: Path):
        """保存数据到JSON文件"""
        print(f"\n保存数据到: {output_file}")
        
        # 确保输出目录存在
        output_file.parent.mkdir(parents=True, exist_ok=True)
        
        # 保存JSON文件（格式化输出，便于阅读）
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        # 计算文件大小
        file_size = output_file.stat().st_size
        file_size_mb = file_size / 1024 / 1024
        
        print(f"✓ 数据已保存")
        print(f"  文件大小: {file_size_mb:.2f} MB")


def main():
    """主函数"""
    try:
        # 创建抓取器
        fetcher = RegionDataFetcher(BASE_URL)
        
        # 抓取所有数据
        data = fetcher.fetch_all()
        
        # 保存到文件
        fetcher.save_to_file(data, OUTPUT_FILE)
        
        print("\n✨ 全部完成！")
        
    except KeyboardInterrupt:
        print("\n\n⚠ 用户中断操作")
        return 1
    except Exception as e:
        print(f"\n✗ 发生错误: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0


if __name__ == "__main__":
    exit(main())








