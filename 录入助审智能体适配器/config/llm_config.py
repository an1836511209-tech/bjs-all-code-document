"""
LLM Agent配置

配置LLM Agent的接口地址、认证信息和并发参数
"""

from typing import Dict, Any
from pydantic import BaseModel, Field
from config.env_config import get_current_env


class AgentConfig(BaseModel):
    """单个Agent配置"""
    agent_id: str = Field(..., description="Agent ID")
    base_url: str = Field(..., description="API基础URL")
    api_key: str = Field(..., description="API密钥")
    timeout: int = Field(default=300, description="请求超时时间（秒）")
    max_retries: int = Field(default=3, description="最大重试次数")


class ConcurrencyConfig(BaseModel):
    """并发配置"""
    extraction_workers: int = Field(default=5, description="字段提取并发数")
    tracing_workers: int = Field(default=5, description="字段溯源并发数")
    audit_workers: int = Field(default=10, description="字段审核并发数")
    classification_workers: int = Field(default=10, description="文件分类并发数")
    unified_extraction_workers: int = Field(default=30, description="统一提取溯源并发数")
    highlight_workers: int = Field(default=40, description="高亮图生成并发数")
    
    # 批量提取配置
    batch_size: int = Field(default=5, description="批量提取时每批最多提取的字段数")
    batch_max_retry_times: int = Field(default=2, description="批量提取失败最大重试次数（快速降级策略：重试1次后失败则拆分为单字段）")


class LLMConfig:
    """LLM配置"""
    
    # 开发环境配置
    # DEV_CONFIG = {
    #     "extraction_agent": AgentConfig(
    #         agent_id="f526d16a58db42698d574adfba7fb397",
    #         base_url="https://uat.agentspro.cn/openapi/agents/chat/completions/v1",
    #         api_key="02d121e8db8d42f39b7a26d0843e4c12.HgdrT9qnyk1k584xpT0hhseGg3Q7u9at",
    #         timeout=300,
    #         max_retries=2
    #     ),
    #     "tracing_agent": AgentConfig(
    #         agent_id="34f65628b11c41a8ad16c5aa32c7b458",
    #         base_url="https://uat.agentspro.cn/openapi/agents/chat/completions/v1",
    #         api_key="02d121e8db8d42f39b7a26d0843e4c12.HgdrT9qnyk1k584xpT0hhseGg3Q7u9at",
    #         timeout=30,
    #         max_retries=1
    #     ),
    #     "audit_agent": AgentConfig(
    #         agent_id="0c3a2c543c234c20a20447c43420ce0f",
    #         base_url="https://uat.agentspro.cn/openapi/agents/chat/completions/v1",
    #         api_key="02d121e8db8d42f39b7a26d0843e4c12.HgdrT9qnyk1k584xpT0hhseGg3Q7u9at",
    #         timeout=300,
    #         max_retries=2
    #     ),
    #     "classification_agent": AgentConfig(
    #         agent_id="362a81dfdf0344deb8541e232b4eac34",
    #         base_url="https://uat.agentspro.cn/openapi/agents/chat/completions/v1",
    #         api_key="02d121e8db8d42f39b7a26d0843e4c12.HgdrT9qnyk1k584xpT0hhseGg3Q7u9at",
    #         timeout=300,
    #         max_retries=2
    #     ),
    #     # 统一提取溯源 Agent（合并提取和溯源为一次调用）
    #     "unified_extraction_agent": AgentConfig(
    #         agent_id="9c5ed10b9a82488ca2e6e36c189a8272",  
    #         base_url="https://uat.agentspro.cn/openapi/agents/chat/completions/v1",
    #         api_key="02d121e8db8d42f39b7a26d0843e4c12.HgdrT9qnyk1k584xpT0hhseGg3Q7u9at",
    #         timeout=300,
    #         max_retries=2
    #     )
    # }
    DEV_CONFIG = {
        "extraction_agent": AgentConfig(
            agent_id="a98b3ebd535c45baafbd54f17299ce93",  
            base_url="http://10.224.98.172/openapi/agents/chat/completions/v1", 
            api_key="ae80dcd4bf3c4180bc44d3df2f66143a.oLlO0tI981LDnhTtojAMBPqm3TF2ZZuA",  
            timeout=300,
            max_retries=2
        ),
        "tracing_agent": AgentConfig(
            agent_id="2e4be29068c54045bf24a658d6a6870c",  
            base_url="http://10.224.98.172/openapi/agents/chat/completions/v1",  
            api_key="ae80dcd4bf3c4180bc44d3df2f66143a.oLlO0tI981LDnhTtojAMBPqm3TF2ZZuA",  
            timeout=30,
            max_retries=1
        ),
        "audit_agent": AgentConfig(
            agent_id="afc389f0cde549dcaae74bdd4b1d9940",  
            base_url="http://10.224.98.172/openapi/agents/chat/completions/v1",  
            api_key="ae80dcd4bf3c4180bc44d3df2f66143a.oLlO0tI981LDnhTtojAMBPqm3TF2ZZuA",  
            timeout=300,
            max_retries=2
        ),
        "classification_agent": AgentConfig(
            agent_id="cfcddc053c19406283c9f25f69ee9094",  
            base_url="http://10.224.98.172/openapi/agents/chat/completions/v1",  
            api_key="ae80dcd4bf3c4180bc44d3df2f66143a.oLlO0tI981LDnhTtojAMBPqm3TF2ZZuA",  
            timeout=60,
            max_retries=2
        ),
        # 统一提取溯源 Agent（合并提取和溯源为一次调用）
        "unified_extraction_agent": AgentConfig(
            agent_id="b26b3b0577844471a54c110abb4c8982",  
            base_url="http://10.224.98.172/openapi/agents/chat/completions/v1",
            api_key="ae80dcd4bf3c4180bc44d3df2f66143a.oLlO0tI981LDnhTtojAMBPqm3TF2ZZuA",
            timeout=300,
            max_retries=2
        )
        # 测试外部模型
        # "unified_extraction_agent": AgentConfig(
        #     agent_id="7cc161ef1ff04d58b3cec0f74daf45eb",  
        #     base_url="https://uat.agentspro.cn/openapi/agents/chat/completions/v1",
        #     api_key="7cc161ef1ff04d58b3cec0f74daf45eb.j1rl5InIprt32kRgIzbo8j8TgBYczZCF",
        #     timeout=300,
        #     max_retries=2
        # )
    }


    # 生产环境配置
    PROD_CONFIG = {
        "extraction_agent": AgentConfig(
            agent_id="a98b3ebd535c45baafbd54f17299ce93",  
            base_url="http://10.224.98.172/openapi/agents/chat/completions/v1", 
            api_key="ae80dcd4bf3c4180bc44d3df2f66143a.oLlO0tI981LDnhTtojAMBPqm3TF2ZZuA",  
            timeout=300,
            max_retries=2
        ),
        "tracing_agent": AgentConfig(
            agent_id="2e4be29068c54045bf24a658d6a6870c",  
            base_url="http://10.224.98.172/openapi/agents/chat/completions/v1",  
            api_key="ae80dcd4bf3c4180bc44d3df2f66143a.oLlO0tI981LDnhTtojAMBPqm3TF2ZZuA",  
            timeout=30,
            max_retries=1
        ),
        "audit_agent": AgentConfig(
            agent_id="afc389f0cde549dcaae74bdd4b1d9940",  
            base_url="http://10.224.98.172/openapi/agents/chat/completions/v1",  
            api_key="ae80dcd4bf3c4180bc44d3df2f66143a.oLlO0tI981LDnhTtojAMBPqm3TF2ZZuA",  
            timeout=300,
            max_retries=2
        ),
        "classification_agent": AgentConfig(
            agent_id="cfcddc053c19406283c9f25f69ee9094",  
            base_url="http://10.224.98.172/openapi/agents/chat/completions/v1",  
            api_key="ae80dcd4bf3c4180bc44d3df2f66143a.oLlO0tI981LDnhTtojAMBPqm3TF2ZZuA",  
            timeout=60,
            max_retries=2
        ),
        #统一提取溯源 Agent（合并提取和溯源为一次调用）
        "unified_extraction_agent": AgentConfig(
            agent_id="b26b3b0577844471a54c110abb4c8982",  
            base_url="http://10.224.98.172/openapi/agents/chat/completions/v1",
            api_key="ae80dcd4bf3c4180bc44d3df2f66143a.oLlO0tI981LDnhTtojAMBPqm3TF2ZZuA",
            timeout=300,
            max_retries=2
        )
        # 测试外部模型
        # "unified_extraction_agent": AgentConfig(
        #     agent_id="7cc161ef1ff04d58b3cec0f74daf45eb",  
        #     base_url="https://uat.agentspro.cn/openapi/agents/chat/completions/v1",
        #     api_key="7cc161ef1ff04d58b3cec0f74daf45eb.j1rl5InIprt32kRgIzbo8j8TgBYczZCF",
        #     timeout=300,
        #     max_retries=2
        # )
    }
    
    # 并发配置
    CONCURRENCY_CONFIG = ConcurrencyConfig(
        extraction_workers=5,  # 字段提取并发数
        tracing_workers=5,     # 字段溯源并发数
        audit_workers=10,       # 字段审核并发数
        classification_workers=10,  # 文件分类并发数
        unified_extraction_workers=30  # 统一提取溯源并发数
    )
    
    # 当前环境（dev/prod）- 从全局环境配置获取
    CURRENT_ENV = get_current_env()
    
    @classmethod
    def get_extraction_agent_config(cls) -> AgentConfig:
        """获取字段提取Agent配置"""
        config = cls.DEV_CONFIG if cls.CURRENT_ENV == "dev" else cls.PROD_CONFIG
        return config["extraction_agent"]
    
    @classmethod
    def get_tracing_agent_config(cls) -> AgentConfig:
        """获取字段溯源Agent配置"""
        config = cls.DEV_CONFIG if cls.CURRENT_ENV == "dev" else cls.PROD_CONFIG
        return config["tracing_agent"]
    
    @classmethod
    def get_audit_agent_config(cls) -> AgentConfig:
        """获取字段审核Agent配置"""
        config = cls.DEV_CONFIG if cls.CURRENT_ENV == "dev" else cls.PROD_CONFIG
        return config["audit_agent"]
    
    @classmethod
    def get_classification_agent_config(cls) -> AgentConfig:
        """获取文件分类Agent配置"""
        config = cls.DEV_CONFIG if cls.CURRENT_ENV == "dev" else cls.PROD_CONFIG
        return config["classification_agent"]
    
    @classmethod
    def get_unified_extraction_agent_config(cls) -> AgentConfig:
        """获取统一提取溯源Agent配置"""
        config = cls.DEV_CONFIG if cls.CURRENT_ENV == "dev" else cls.PROD_CONFIG
        return config["unified_extraction_agent"]
    
    @classmethod
    def get_concurrency_config(cls) -> ConcurrencyConfig:
        """获取并发配置"""
        return cls.CONCURRENCY_CONFIG
    
    @classmethod
    def set_environment(cls, env: str):
        """
        设置当前环境
        
        Args:
            env: 环境名称 ('dev' 或 'prod')
        """
        if env not in ["dev", "prod"]:
            raise ValueError(f"无效的环境配置: {env}，必须是 'dev' 或 'prod'")
        cls.CURRENT_ENV = env


# 导出配置实例
llm_config = LLMConfig()

