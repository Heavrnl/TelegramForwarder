from typing import Optional, List, Dict
from openai import AsyncOpenAI
from .base import BaseAIProvider
import os
import logging
from .openai_base_provider import OpenAIBaseProvider

logger = logging.getLogger(__name__)

class OpenAIProvider(OpenAIBaseProvider):
    def __init__(self):
        super().__init__(
            env_prefix='OPENAI',
            default_model='gpt-4o-mini',
            default_api_base='https://api.openai.com/v1'
        )

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
                
                messages.append({"role": "user", "content": content})
            else:
                # 没有图片，只添加文本
                messages.append({"role": "user", "content": message})
            
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=messages
            )
            
            return response.choices[0].message.content
            
        except Exception as e:
            logger.error(f"OpenAI处理消息时出错: {str(e)}", exc_info=True)
            return f"AI处理失败: {str(e)}"