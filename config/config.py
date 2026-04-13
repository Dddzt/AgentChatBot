import os
from dotenv import load_dotenv

load_dotenv()

#########################################  离线/本地的大模型信息  #########################################

QWEN_DATA = {
    'use': True,
    'model': 'qwen-plus',  
    'key': os.getenv('QWEN_API_KEY', ''),
    'url': 'https://dashscope.aliyuncs.com/compatible-mode/v1',
    'temperature': 0.7,
    'embedding_model': 'text-embedding-v3',
    'vision_model': 'qwen-vl-plus',
    'timeout': 120,
    'stream_flush_chars': 24,
    'stream_flush_interval': 0.12,
}

# OLLAMA_DATA = {
#     'use': True,  
#     # 'model': 'qwen:1.8b',  # ollama运行的模型名称
#     # 'code_model': 'qwen:1.8b',
#     # 'model': 'qwen3:14b',  # ollama运行的模型名称
#     # 'code_model': 'qwen3:14b',

#     'model': 'qwen2.5-32b-awq',
#     'code_model': 'qwen2.5-32b-awq',
#     'embedding_model': 'bge-m3',
#     'key': 'EMPTY',
#     # 'url': 'http://localhost:11434/api/chat',  # 本地 Ollama 服务地址
#     # 'api_url': "http://localhost:11434/v1/",
#     'url': 'http://u950935-bdd8-eeea0541.bjb2.seetacloud.com:6006/v1/',
#     'api_url': "http://u950935-bdd8-eeea0541.bjb2.seetacloud.com:6006/v1/",
#     'stream_flush_chars': 24,
#     'stream_flush_interval': 0.12,
# }

OLLAMA_DATA = {
    'use': True,
    'model': 'qwen2.5-32b-awq',
    'code_model': 'qwen2.5-32b-awq',
    'embedding_model': 'bge-m3',
    'key': 'EMPTY',
    # 地址已经正确，保持不变
    'url': 'https://u950935-afee-4765a824.bjb1.seetacloud.com:8443/v1/',
    'api_url': 'https://u950935-afee-4765a824.bjb1.seetacloud.com:8443/v1/',
    'stream_flush_chars': 24,
    'stream_flush_interval': 0.12,
}

MOONSHOT_DATA = {
    'use': True,
    'key': os.getenv('MOONSHOT_API_KEY', ''),
    'url': "https://api.moonshot.cn/v1",
    'model': "kimi-k2.5",
    "prompt": ""
}

BAICHUAN_DATA = {
    'use': False,
    'key': "",
    'url': "https://api.baichuan-ai.com/v1/",
    'model': "Baichuan2-Turbo"
    # 百川模型不支持自定义提示词内容#
}

#########################################  文件存储配置  #########################################

# 统一的文件存储路径配置（飞书、Web端等共用）
DOWNLOAD_ADDRESS = {
    'image': 'downloads/image',    # 图片下载存储路径
    'audio': 'downloads/audio',    # 音频下载存储路径
    'vidio': 'downloads/vidio',    # 视频下载存储路径（注意：保持vidio拼写以兼容现有代码）
    'file': 'downloads/file',      # 其他文件下载存储路径
}

# Web端上传文件存储路径
UPLOAD_FOLDER = 'uploads'

# 文件上传限制
FILE_CONFIG = {
    'max_size': 50 * 1024 * 1024,  # 最大文件大小 50MB
    'allowed_extensions': {
        'image': {'png', 'jpg', 'jpeg', 'gif', 'bmp'},
        'document': {'txt', 'md', 'pdf', 'doc', 'docx'},
        'audio': {'mp3', 'wav', 'ogg', 'flac', 'm4a'},
        'video': {'mp4', 'avi', 'mov', 'mkv', 'wmv'}
    }
}

#########################################  本地数据库信息  #########################################

# 本地mysql数据库信息
DB_DATA = {
    'host': 'localhost',  # 数据库地址
    'user': 'root',  # 数据库用户
    'password': '1234',  # 数据库密码
    'database': 'agent'  # 数据库名称
}

# redis信息
REDIS_DATA = {
    'host': 'localhost',
    'port': 6379,
    'db': 0
}



#########################################  feishu信息  #########################################

FEISHU_DATA = {
    "app_id": os.getenv("FEISHU_APP_ID", ""),
    "app_secret": os.getenv("FEISHU_APP_SECRET", ""),
    "encrypt_key": os.getenv("FEISHU_ENCRYPT_KEY", ""),
    "verification_token": os.getenv("FEISHU_VERIFICATION_TOKEN", ""),
}

#########################################  搜索工具配置  #########################################

SEARCH_TOOL_CONFIG = {
    # 搜索引擎优先级：tavily  > duckduckgo
    'priority': ['tavily', 'duckduckgo'],
    
    # Tavily API 配置（推荐，专业的搜索API）
    # 注册地址：https://tavily.com/
    'tavily': {
        'use': True,
        'api_key': os.getenv('TAVILY_API_KEY', ''),
        'max_results': 3,
        'search_depth': 'basic',  # basic 或 advanced
    },
    
    # DuckDuckGo 配置（免费，无需API Key，但可能不稳定）
    'duckduckgo': {
        'use': True,  # 作为兜底方案
        'region': 'wt-wt',  # 地区设置
        'max_results': 3,
        'time': 'd',  # d=day, w=week, m=month
    }
}

#########################################  RAG 知识库配置  #########################################

RAG_CONFIG = {
    'knowledge_base_path': 'data/knowledge_bases',
    'max_token_len': 600,
    'cover_content': 150,
    'default_k': 3,
    'allowed_extensions': {'pdf', 'md', 'txt'},
}
