import logging
from typing import Optional

from langchain import requests

from config.config import SEARCH_TOOL_CONFIG


def _search_tavily(query: str) -> Optional[str]:
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

res = _search_tavily("今天西安天气怎么样")
print(res)