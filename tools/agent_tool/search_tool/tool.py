import logging
from langchain_core.tools import tool
from langchain_community.tools import DuckDuckGoSearchResults
from langchain_community.utilities import DuckDuckGoSearchAPIWrapper
from pydantic import BaseModel
import requests
import json
from typing import Optional, List, Dict
from config.config import SEARCH_TOOL_CONFIG

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s]: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)


class SearchAPIWrapper(BaseModel):
    
    def _search_tavily(self, query: str) -> Optional[str]:
        """使用 Tavily API 搜索"""
        config = SEARCH_TOOL_CONFIG.get('tavily', {})
        if not config.get('use') or not config.get('api_key'):
            return None
            
        try:
            url = "https://api.tavily.com/search"
            headers = {"Content-Type": "application/json"}
            payload = {
                "api_key": config['api_key'],
                "query": query,
                "max_results": config.get('max_results', 3),
                "search_depth": config.get('search_depth', 'basic'),
                "include_answer": True,
            }
            
            response = requests.post(url, json=payload, headers=headers, timeout=10)
            if response.status_code == 200:
                data = response.json()
                results = []
                
                # 添加AI生成的答案
                if data.get('answer'):
                    results.append(f"AI总结: {data['answer']}")
                
                # 添加搜索结果
                for item in data.get('results', []):
                    title = item.get('title', '')
                    content = item.get('content', '')
                    url = item.get('url', '')
                    results.append(f"标题: {title}\n内容: {content}\n链接: {url}")
                
                logging.info("使用 Tavily API 搜索成功")
                return "\n\n".join(results)
            else:
                logging.warning(f"Tavily API 返回错误: {response.status_code}")
        except Exception as e:
            logging.error(f"Tavily 搜索失败: {e}")
        return None
    
    def _search_duckduckgo(self, query: str) -> Optional[str]:
        """使用 DuckDuckGo 搜索(免费,兜底方案)"""
        config = SEARCH_TOOL_CONFIG.get('duckduckgo', {})
        if not config.get('use'):
            return None
                
        try:
            # 尝试使用 langchain 的 DuckDuckGo
            wrapper = DuckDuckGoSearchAPIWrapper(
                region=config.get('region', 'wt-wt'),
                time=config.get('time', 'd'),
                max_results=config.get('max_results', 3)
            )
            search = DuckDuckGoSearchResults(api_wrapper=wrapper, source="text")
            response = search.invoke(query)
                
            logging.info("使用 DuckDuckGo 搜索成功")
            return response
        except Exception as e:
            logging.warning(f"DuckDuckGo langchain 方式失败: {e}")
                
            # 备用方案:直接使用 HTTP 请求
            try:
                import urllib.parse
                encoded_query = urllib.parse.quote(query)
                url = f"https://api.duckduckgo.com/?q={encoded_query}&format=json"
                response = requests.get(url, timeout=10)
                    
                if response.status_code == 200:
                    data = response.json()
                    results = []
                        
                    # 提取摘要信息
                    if data.get('AbstractText'):
                        results.append(f"摘要: {data['AbstractText']}")
                        
                    # 提取相关主题
                    for topic in data.get('RelatedTopics', [])[:3]:
                        if isinstance(topic, dict) and topic.get('Text'):
                            results.append(f"相关信息: {topic['Text']}")
                        
                    if results:
                        logging.info("使用 DuckDuckGo API 搜索成功")
                        return "\n\n".join(results)
            except Exception as e2:
                logging.error(f"DuckDuckGo HTTP 方式也失败: {e2}")
            
        return None
    
    def run(self, query: str) -> str:
        """按优先级尝试不同的搜索引擎"""
        priority = SEARCH_TOOL_CONFIG.get('priority', ['tavily', 'duckduckgo'])
        
        search_methods = {
            'tavily': self._search_tavily,
            'duckduckgo': self._search_duckduckgo,
        }
        
        # 按优先级依次尝试
        for engine in priority:
            if engine in search_methods:
                logging.info(f"尝试使用 {engine} 搜索...")
                result = search_methods[engine](query)
                if result:
                    return result
        
        return "所有搜索引擎均失败，请检查网络连接或API配置"
    
    def generate_result(self, query: str) -> str:
        """生成搜索结果"""
        try:
            result = self.run(query)
            if result:
                return result
        except Exception as e:
            logging.error(f"搜索时出错: {e}")
        return "搜索失败，请稍后重试"


search = SearchAPIWrapper()


@tool
def search_tool(query: str) -> str:
    """联网搜索工具，支持多种搜索引擎（Tavily、SerpAPI、DuckDuckGo），自动选择可用的搜索引擎"""
    return search.generate_result(query)


# 返回工具信息
def register_tool():
    tool_func = search_tool  # 工具函数
    tool_func.__name__ = "search_tool"
    return {
        "name": "search_tool",
        "agent_tool": tool_func,
        "description": "联网搜索工具，支持Tavily、DuckDuckGo搜索引擎"
    }