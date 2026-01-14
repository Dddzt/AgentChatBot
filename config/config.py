#########################################  离线/本地的大模型信息  #########################################

CHATGPT_DATA = {
    'use': True,
    'model': 'qwen-plus',  
    'key': 'REDACTED_QWEN_KEY', 
    'url': 'https://dashscope.aliyuncs.com/compatible-mode/v1',
    'temperature': 0.7,  # 生成内容的多样性程度，0-1 范围内
    'vision_model': 'qwen-vl-plus',  # 视觉模型，用于图片内容分析（阿里云qwen-vl-plus）
}

OLLAMA_DATA = {
    'use': True,  
    'model': 'qwen:1.8b',  # ollama运行的模型名称
    'code_model': 'qwen:1.8b',
    'key': 'EMPTY',
    'url': 'http://localhost:11434/api/chat',  # 本地 Ollama 服务地址
    'api_url': "http://localhost:11434/v1/"
}

MOONSHOT_DATA = {
    'use': False,
    'key': "",
    'url': "https://api.moonshot.cn/v1",
    'model': "moonshot-v1-8k",
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
    "app_id":"REDACTED_FEISHU_APP_ID",  #应用凭证中的App ID
    "app_secret":"REDACTED_FEISHU_SECRET", #应用凭证中的App Secret
    "encrypt_key":"REDACTED_FEISHU_ENCRYPT", # 自建应用中的"事件与回调"下的加密策略中的Encrypt Key
    "tenant_access_token":"t-g104crd8IC2EJFGPKBPN2RHOQDSB6PF3MVWA2EYY" #参考"开发文档"下的"服务端API"中的"认证与授权"下的"获取访问凭证"下的"自建应用获取 tenant_access_token"
}

#########################################  搜索工具配置  #########################################

SEARCH_TOOL_CONFIG = {
    # 搜索引擎优先级：tavily  > duckduckgo
    'priority': ['tavily', 'duckduckgo'],
    
    # Tavily API 配置（推荐，专业的搜索API）
    # 注册地址：https://tavily.com/
    'tavily': {
        'use': True,
        'api_key': 'REDACTED_TAVILY_KEY',  # 在此填入你的 Tavily API Key
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
