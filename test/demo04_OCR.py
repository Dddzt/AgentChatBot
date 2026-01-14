from PIL import Image
import pytesseract

# 关键：若未配置系统环境变量，取消下面注释并填写你的Tesseract安装路径
pytesseract.pytesseract.tesseract_cmd = r'D:\software\ItApp\Tesseract-OCR\tesseract.exe'

# 1. 读取图片
img_path = "D:\\data\\image\\07f764947e4faae8c02bf69ca655ec6e_20251230_170918.jpg"  # 图片路径（桌面图片可写完整路径：r'C:\Users\你的用户名\Desktop\test.png'）
try:
    img = Image.open(img_path)
except Exception as e:
    print(f"读取图片失败：{e}")
    exit()

# 2. 调用Tesseract进行OCR识别（支持中英双语）
text = pytesseract.image_to_string(img, lang='chi_sim+eng')

# 3. 输出识别结果
print("【图片识别结果】：")
print(text.strip())