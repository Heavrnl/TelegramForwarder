from typing import Optional, List, Dict
from openai import AsyncOpenAI
from .base import BaseAIProvider
import os
import logging

logger = logging.getLogger(__name__)

class OpenAIBaseProvider(BaseAIProvider):
    def __init__(self, env_prefix: str = 'OPENAI', default_model: str = 'gpt-4o-mini', 
                 default_api_base: str = 'https://api.openai.com/v1'):
        """
        初始化基础OpenAI格式提供者
        
        Args:
            env_prefix: 环境变量前缀，如 'OPENAI', 'GROK', 'DEEPSEEK', 'QWEN'
            default_model: 默认模型名称
            default_api_base: 默认API基础URL
        """
        super().__init__()
        self.env_prefix = env_prefix
        self.default_model = default_model
        self.default_api_base = default_api_base
        self.client = None
        self.model = None

    async def initialize(self, **kwargs) -> None:
        """初始化OpenAI客户端"""
        try:
            api_key = os.getenv(f'{self.env_prefix}_API_KEY')
            if not api_key:
                raise ValueError(f"未设置 {self.env_prefix}_API_KEY 环境变量")
            
            api_base = os.getenv(f'{self.env_prefix}_API_BASE', self.default_api_base)

            self.client = AsyncOpenAI(
                api_key=api_key,
                base_url=api_base
            )

            self.model = kwargs.get('model', self.default_model)
            logger.info(f"初始化OpenAI模型: {self.model}")

        except Exception as e:
            error_msg = f"初始化 {self.env_prefix} 客户端时出错: {str(e)}"
            logger.error(error_msg, exc_info=True)
            raise

    async def process_message(self, 
                            message: str, 
                            prompt: Optional[str] = None,
                            images: Optional[List[Dict[str, str]]] = None,
                            **kwargs) -> str:
        """处理消息"""
        try:
            if not self.client:
                await self.initialize(**kwargs)
                
            messages = []
            if prompt:
                messages.append({"role": "system", "content": prompt})
            
            # 如果有图片，需要添加到消息中
            if images and len(images) > 0:
                # 创建包含文本和图片的内容数组
                content = []
                
                # 添加文本
                content.append({
                    "type": "text",
                    "text": message
                })
                
                # 添加每张图片
                for img in images:
                    content.append({
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{img['mime_type']};base64,{img['data']}"
                        }
                    })
                    logger.info(f"已添加一张类型为 {img['mime_type']} 的图片，大小约 {len(img['data']) // 1000} KB")
                
                messages.append({"role": "user", "content": content})
            else:
                # 没有图片，只添加文本
                messages.append({"role": "user", "content": message})

            logger.info(f"实际使用的OpenAI模型: {self.model}")
            
            # 所有模型统一使用流式调用
            completion = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                stream=True
            )
            
            # 收集所有内容
            collected_content = ""
            collected_reasoning = ""
            
            for chunk in completion:
                if not chunk.choices:
                    continue
                    
                delta = chunk.choices[0].delta
                
                # 处理思考内容（如果存在）
                if hasattr(delta, 'reasoning_content') and delta.reasoning_content is not None:
                    collected_reasoning += delta.reasoning_content
                
                # 处理回答内容
                if hasattr(delta, 'content') and delta.content is not None:
                    collected_content += delta.content
            
            # 如果没有内容但有思考过程，可能是思考模型只返回了思考过程
            if not collected_content and collected_reasoning:
                logger.warning("模型只返回了思考过程，没有最终回答")
                return "模型未能生成有效回答"
            
            return collected_content
            
        except Exception as e:
            logger.error(f"{self.env_prefix} API 调用失败: {str(e)}")
            return f"AI处理失败: {str(e)}"