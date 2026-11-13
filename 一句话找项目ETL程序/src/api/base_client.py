#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
基础API客户端模块
提供通用的HTTP请求和重试机制
"""

import logging
import requests
import time
import json
from typing import Dict, Any, Optional
from src.core.config import get_config


class APIException(Exception):
    """
    API异常类
    """
    pass


class BaseAPIClient:
    """
    基础API客户端
    提供通用的HTTP请求功能
    """
    
    def __init__(self, config_section: str):
        """
        初始化基础API客户端
        
        Args:
            config_section: 配置节名称
        """
        self.logger = logging.getLogger(__name__)
        self.config = get_config(config_section, {})
        self.session = self._create_session()
    
    def _create_session(self) -> requests.Session:
        """
        创建HTTP会话
        
        Returns:
            requests.Session对象
        """
        session = requests.Session()
        
        # 设置默认headers
        headers = self.config.get('headers', {})
        # 添加连接保持活动headers
        headers.update({
            'Connection': 'keep-alive',
            'Keep-Alive': 'timeout=120, max=100'
        })
        session.headers.update(headers)
        
        # 设置超时
        session.timeout = self.config.get('timeout', 30)
        
        # 配置适配器以支持连接池
        from requests.adapters import HTTPAdapter
        from urllib3.util.retry import Retry
        
        # 配置重试策略
        retry_strategy = Retry(
            total=0,  # 禁用requests自带的重试，使用我们自己的重试逻辑
            backoff_factor=0.1,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        
        adapter = HTTPAdapter(
            pool_connections=10,
            pool_maxsize=20,
            max_retries=retry_strategy
        )
        
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        
        return session
    
    def _make_request_with_retry(self, method: str, url: str, **kwargs) -> requests.Response:
        """
        带重试机制的HTTP请求
        
        Args:
            method: HTTP方法
            url: 请求URL
            **kwargs: 其他请求参数
            
        Returns:
            响应对象
        """
        retry_times = self.config.get('retry_times', 3)
        retry_delay = self.config.get('retry_delay', 5)
        
        last_exception = None
        
        for attempt in range(retry_times + 1):
            try:
                self.logger.debug(f"发起HTTP请求，尝试次数: {attempt + 1}/{retry_times + 1}")
                
                response = self.session.request(method, url, **kwargs)
                
                # 检查HTTP状态码
                if response.status_code == 200:
                    return response
                else:
                    self.logger.warning(f"HTTP请求返回非200状态码: {response.status_code}")
                    response.raise_for_status()
                    
            except requests.exceptions.RequestException as e:
                last_exception = e
                self.logger.warning(f"HTTP请求失败，尝试次数: {attempt + 1}, 错误: {e}")
                
                if attempt < retry_times:
                    self.logger.info(f"等待 {retry_delay} 秒后重试...")
                    time.sleep(retry_delay)
                else:
                    self.logger.error(f"HTTP请求重试次数已用完，最终失败")
                    break
        
        # 如果所有重试都失败，抛出最后一个异常
        if last_exception:
            raise last_exception
        else:
            raise requests.exceptions.RequestException("HTTP请求失败，未知错误")
    
    def post_json(self, url: str, data: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        """
        发送JSON POST请求
        
        Args:
            url: 请求URL
            data: 请求数据
            **kwargs: 其他请求参数
            
        Returns:
            响应数据字典
        """
        try:
            response = self._make_request_with_retry(
                'POST',
                url,
                json=data,
                timeout=self.config.get('timeout', 30),
                **kwargs
            )
            
            # 解析响应
            response_data = response.json()
            return response_data
            
        except requests.exceptions.RequestException as e:
            self.logger.error(f"HTTP请求失败: {e}")
            raise APIException(f"HTTP请求失败: {e}")
        except json.JSONDecodeError as e:
            self.logger.error(f"JSON解析失败: {e}")
            raise APIException(f"JSON解析失败: {e}")
        except Exception as e:
            self.logger.error(f"请求失败: {e}")
            raise APIException(f"请求失败: {e}")
    
    def get(self, url: str, params: Optional[Dict[str, Any]] = None, **kwargs) -> Dict[str, Any]:
        """
        发送GET请求
        
        Args:
            url: 请求URL
            params: 请求参数
            **kwargs: 其他请求参数
            
        Returns:
            响应数据字典
        """
        try:
            response = self._make_request_with_retry(
                'GET',
                url,
                params=params,
                timeout=self.config.get('timeout', 30),
                **kwargs
            )
            
            # 解析响应
            response_data = response.json()
            return response_data
            
        except requests.exceptions.RequestException as e:
            self.logger.error(f"HTTP请求失败: {e}")
            raise APIException(f"HTTP请求失败: {e}")
        except json.JSONDecodeError as e:
            self.logger.error(f"JSON解析失败: {e}")
            raise APIException(f"JSON解析失败: {e}")
        except Exception as e:
            self.logger.error(f"请求失败: {e}")
            raise APIException(f"请求失败: {e}")
    
    def test_connection(self, test_url: str = None, test_data: Dict[str, Any] = None) -> bool:
        """
        测试API连接
        
        Args:
            test_url: 测试URL，默认使用base_url
            test_data: 测试数据
            
        Returns:
            连接是否成功
        """
        try:
            self.logger.info("测试API连接...")
            
            url = test_url or self.config.get('base_url')
            if not url:
                self.logger.error("未配置API URL")
                return False
            
            if test_data:
                response = self.post_json(url, test_data)
            else:
                response = self.get(url)
            
            self.logger.info("API连接测试成功")
            return True
                
        except Exception as e:
            self.logger.error(f"API连接测试失败: {e}")
            return False
    
    def close(self):
        """
        关闭会话
        """
        if self.session:
            self.session.close()
            self.logger.info("API客户端会话已关闭")
