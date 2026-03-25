

# 测试qwen大模型
from server.client.qwen_client import QwenClient
client = QwenClient()
message = "你是谁"
messages = [
    {"role": "user", "content": message}
]
response = client.invoke(messages)
print(response)