"""
文件处理工具 - 用于处理上传的图片和文件
支持：图片OCR识别、文本提取、文档分析
"""
import os
import logging
import base64
from typing import Dict, Any, Optional
from PIL import Image
import PyPDF2
import docx
from pathlib import Path
import requests
import json

logging.basicConfig(level=logging.INFO)

# 尝试导入OCR库
try:
    import pytesseract
    HAS_OCR = True
except ImportError:
    HAS_OCR = False
    logging.warning("pytesseract未安装，OCR功能不可用。安装: pip install pytesseract")


class FileProcessor:
    """文件处理器：处理图片、文档、音频、视频等多种类型"""
    
    def __init__(self):
        self.supported_image_formats = ['.png', '.jpg', '.jpeg', '.gif', '.bmp']
        self.supported_doc_formats = ['.txt', '.md', '.pdf', '.doc', '.docx']
        self.supported_audio_formats = ['.mp3', '.wav', '.ogg', '.flac', '.m4a']
        self.supported_video_formats = ['.mp4', '.avi', '.mov', '.mkv', '.wmv']
        
        # 加载配置
        try:
            from config.config import QWEN_DATA
            self.api_key = QWEN_DATA.get('key')
            self.api_url = QWEN_DATA.get('url')
            self.model = QWEN_DATA.get('model', 'qwen-plus')
            # 视觉模型配置（从配置文件读取，默认qwen-vl-plus）
            self.vision_model = QWEN_DATA.get('vision_model', 'qwen-vl-plus')
        except:
            self.api_key = None
            self.api_url = None
            self.model = None
            self.vision_model = None
    
    def process_file(self, file_path: str, file_type: str = None) -> Dict[str, Any]:
        """
        统一文件处理入口
        
        Args:
            file_path: 文件路径
            file_type: 文件类型 (image/file)
        
        Returns:
            处理结果字典
        """
        if not os.path.exists(file_path):
            return {'success': False, 'error': f'文件不存在: {file_path}'}
        
        ext = os.path.splitext(file_path)[1].lower()
        
        try:
            # 处理图片
            if ext in self.supported_image_formats:
                return self.process_image(file_path)
            
            # 处理文档
            elif ext in self.supported_doc_formats:
                return self.process_document(file_path)
            
            # 处理音频
            elif ext in self.supported_audio_formats:
                return self.process_audio(file_path)
            
            # 处理视频
            elif ext in self.supported_video_formats:
                return self.process_video(file_path)
            
            else:
                return {
                    'success': False,
                    'error': f'不支持的文件格式: {ext}'
                }
        
        except Exception as e:
            logging.error(f"处理文件失败: {e}")
            return {'success': False, 'error': str(e)}
    
    def process_image(self, image_path: str) -> Dict[str, Any]:
        """
        处理图片文件 - 使用视觉大模型分析图片内容
        
        Args:
            image_path: 图片路径
        
        Returns:
            图片信息和识别内容
        """
        try:
            with Image.open(image_path) as img:
                # 获取图片基本信息
                width, height = img.size
                format_name = img.format
                mode = img.mode
                
                # 直接使用视觉模型识别图片内容（视觉模型能识别文字，无需OCR）
                vision_description = self._analyze_image_with_vision_model(image_path)
                
                # 如果视觉模型失败，才生成基础描述作为fallback
                basic_description = ""
                if not vision_description:
                    basic_description = self._generate_image_description(img, image_path)
                
                result = {
                    'success': True,
                    'type': 'image',
                    'file_path': image_path,
                    'filename': os.path.basename(image_path),
                    'width': width,
                    'height': height,
                    'format': format_name,
                    'mode': mode,
                    'ocr_text': '',  # 不再使用OCR
                    'vision_description': vision_description,  # 视觉模型识别结果（包含文字识别）
                    'basic_description': basic_description,  # 基础描述（作为fallback）
                }
                
                logging.info(f"图片处理成功: {os.path.basename(image_path)}")
                return result
                
        except Exception as e:
            logging.error(f"处理图片失败: {e}")
            return {'success': False, 'error': f'图片处理失败: {str(e)}'}
    
    def _extract_text_from_image(self, img: Image.Image) -> str:
        """
        使用OCR提取图片中的文字
        
        Args:
            img: PIL Image对象
        
        Returns:
            识别到的文字内容
        """
        if not HAS_OCR:
            return ""
        
        try:
            # 使用Tesseract OCR识别文字（支持中英文）
            text = pytesseract.image_to_string(img, lang='chi_sim+eng')
            text = text.strip()
            if text:
                logging.info(f"OCR识别到文字: {len(text)} 字符")
            return text
        except Exception as e:
            logging.warning(f"OCR识别失败: {e}")
            return ""
    
    def _analyze_image_with_vision_model(self, image_path: str) -> str:
        """
        使用视觉大模型分析图片内容
        
        Args:
            image_path: 图片路径
        
        Returns:
            图片内容描述
        """
        if not self.api_key or not self.api_url:
            logging.warning("视觉模型未配置API密钥或URL")
            return ""
        
        try:
            logging.info(f"开始调用视觉模型分析图片: {image_path}")
            logging.info(f"使用视觉模型: {self.vision_model}")
            
            # 将图片转换为base64
            with open(image_path, 'rb') as f:
                image_data = base64.b64encode(f.read()).decode('utf-8')
            
            # 确定图片MIME类型
            ext = os.path.splitext(image_path)[1].lower()
            mime_types = {
                '.png': 'image/png',
                '.jpg': 'image/jpeg',
                '.jpeg': 'image/jpeg',
                '.gif': 'image/gif',
                '.bmp': 'image/bmp'
            }
            mime_type = mime_types.get(ext, 'image/jpeg')
            
            # 调用视觉模型API
            headers = {
                'Authorization': f'Bearer {self.api_key}',
                'Content-Type': 'application/json'
            }
            
            payload = {
                'model': self.vision_model,
                'messages': [
                    {
                        'role': 'user',
                        'content': [
                            {
                                'type': 'image_url',
                                'image_url': {
                                    'url': f'data:{mime_type};base64,{image_data}'
                                }
                            },
                            {
                                'type': 'text',
                                'text': '请详细描述这张图片的内容，包括：1.图片中的主要元素和对象；2.图片中的文字内容（如果有）；3.图片的整体场景和主题。'
                            }
                        ]
                    }
                ],
                'max_tokens': 1000
            }
            
            response = requests.post(
                f"{self.api_url}/chat/completions",
                headers=headers,
                json=payload,
                timeout=60  # 增加超时时间
            )
            
            if response.status_code == 200:
                result = response.json()
                description = result.get('choices', [{}])[0].get('message', {}).get('content', '')
                if description:
                    logging.info(f"视觉模型识别成功，描述长度: {len(description)}")
                else:
                    logging.warning("视觉模型返回空内容")
                return description
            else:
                logging.error(f"视觉模型调用失败: HTTP {response.status_code}")
                logging.error(f"响应内容: {response.text[:500]}")
                return ""
                
        except Exception as e:
            logging.error(f"视觉模型分析异常: {e}")
            return ""
    
    def _generate_image_description(self, img: Image.Image, image_path: str) -> str:
        """
        生成图片描述（简化版，不依赖AI模型）
        
        Args:
            img: PIL Image对象
            image_path: 图片路径
        
        Returns:
            图片描述文本
        """
        width, height = img.size
        aspect_ratio = width / height
        
        # 判断方向
        if aspect_ratio > 1.5:
            orientation = "横向"
        elif aspect_ratio < 0.67:
            orientation = "竖向"
        else:
            orientation = "方形"
        
        # 判断尺寸
        if width > 2000 or height > 2000:
            size_desc = "高分辨率"
        elif width < 500 and height < 500:
            size_desc = "小尺寸"
        else:
            size_desc = "中等尺寸"
        
        # 获取主要颜色（简化版）
        try:
            # 缩小图片加快处理
            img_small = img.resize((50, 50))
            img_small = img_small.convert('RGB')
            
            # 获取主色调
            pixels = list(img_small.getdata())
            r_avg = sum([p[0] for p in pixels]) // len(pixels)
            g_avg = sum([p[1] for p in pixels]) // len(pixels)
            b_avg = sum([p[2] for p in pixels]) // len(pixels)
            
            # 判断主色调
            if r_avg > 180 and g_avg > 180 and b_avg > 180:
                color_desc = "以浅色为主"
            elif r_avg < 75 and g_avg < 75 and b_avg < 75:
                color_desc = "以深色为主"
            elif r_avg > g_avg and r_avg > b_avg:
                color_desc = "偏红色调"
            elif g_avg > r_avg and g_avg > b_avg:
                color_desc = "偏绿色调"
            elif b_avg > r_avg and b_avg > g_avg:
                color_desc = "偏蓝色调"
            else:
                color_desc = "色彩均衡"
        except:
            color_desc = "色彩丰富"
        
        description = f"这是一张{orientation}、{size_desc}的图片，{color_desc}。"
        
        return description
    
    def process_document(self, doc_path: str) -> Dict[str, Any]:
        """
        处理文档文件
        
        Args:
            doc_path: 文档路径
        
        Returns:
            文档内容和摘要
        """
        ext = os.path.splitext(doc_path)[1].lower()
        
        try:
            # 提取文本
            if ext == '.txt' or ext == '.md':
                content = self._read_text_file(doc_path)
            elif ext == '.pdf':
                content = self._read_pdf_file(doc_path)
            elif ext in ['.doc', '.docx']:
                content = self._read_word_file(doc_path)
            else:
                return {'success': False, 'error': f'不支持的文档格式: {ext}'}
            
            if not content:
                return {'success': False, 'error': '文档内容为空'}
            
            # 生成摘要
            summary = self._generate_document_summary(content)
            
            result = {
                'success': True,
                'type': 'document',
                'file_path': doc_path,
                'format': ext,
                'content': content,
                'content_length': len(content),
                'word_count': len(content.split()),
                'summary': summary
            }
            
            logging.info(f"文档处理成功: {os.path.basename(doc_path)}, 字数: {result['word_count']}")
            return result
            
        except Exception as e:
            logging.error(f"处理文档失败: {e}")
            return {'success': False, 'error': f'文档处理失败: {str(e)}'}
    
    def _read_text_file(self, file_path: str) -> str:
        """读取文本文件"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return f.read()
        except UnicodeDecodeError:
            # 尝试其他编码
            with open(file_path, 'r', encoding='gbk') as f:
                return f.read()
    
    def _read_pdf_file(self, file_path: str) -> str:
        """读取PDF文件"""
        text = ""
        with open(file_path, 'rb') as f:
            pdf_reader = PyPDF2.PdfReader(f)
            for page_num in range(len(pdf_reader.pages)):
                page = pdf_reader.pages[page_num]
                text += page.extract_text() + "\n"
        return text.strip()
    
    def _read_word_file(self, file_path: str) -> str:
        """读取Word文件"""
        try:
            doc = docx.Document(file_path)
            text = "\n".join([paragraph.text for paragraph in doc.paragraphs])
            return text.strip()
        except Exception as e:
            logging.error(f"读取Word文件失 败: {e}")
            return ""
    
    def _generate_document_summary(self, content: str, max_length: int = 500) -> str:
        """
        生成文档摘要
        
        Args:
            content: 文档内容
            max_length: 摘要最大长度
        
        Returns:
            文档摘要
        """
        # 清理内容
        content = content.strip()
        
        # 如果内容很短，直接返回
        if len(content) <= max_length:
            return f"文档全文: {content}"
        
        # 获取前几行作为摘要
        lines = content.split('\n')
        summary_lines = []
        current_length = 0
        
        for line in lines[:10]:  # 最多取前10行
            line = line.strip()
            if line and current_length + len(line) <= max_length:
                summary_lines.append(line)
                current_length += len(line)
            if current_length >= max_length * 0.8:
                break
        
        summary = "\n".join(summary_lines)
        
        if len(summary) < len(content):
            summary += f"\n\n[文档总计 {len(content)} 字符，以上为开头部分]"
        
        return summary
    
    def process_audio(self, audio_path: str) -> Dict[str, Any]:
        """
        处理音频文件
        
        Args:
            audio_path: 音频文件路径
        
        Returns:
            音频文件信息
        """
        try:
            ext = os.path.splitext(audio_path)[1].lower()
            file_size = os.path.getsize(audio_path)
            filename = os.path.basename(audio_path)
            
            # 根据文件大小估算时长（粗略估算）
            # MP3: 约128kbps = 16KB/s, WAV: 约1411kbps = 176KB/s
            if ext == '.mp3':
                estimated_duration = file_size / (16 * 1024)  # 秒
            elif ext == '.wav':
                estimated_duration = file_size / (176 * 1024)
            else:
                estimated_duration = file_size / (32 * 1024)  # 默认估算
            
            # 格式化时长
            minutes = int(estimated_duration // 60)
            seconds = int(estimated_duration % 60)
            duration_str = f"{minutes}分{seconds}秒" if minutes > 0 else f"{seconds}秒"
            
            # 根据格式确定音频类型描述
            format_desc = {
                '.mp3': 'MP3压缩音频',
                '.wav': 'WAV无损音频',
                '.ogg': 'OGG音频',
                '.flac': 'FLAC无损音频',
                '.m4a': 'M4A音频'
            }.get(ext, '音频文件')
            
            result = {
                'success': True,
                'type': 'audio',
                'file_path': audio_path,
                'filename': filename,
                'format': ext,
                'format_desc': format_desc,
                'file_size': file_size,
                'estimated_duration': estimated_duration,
                'duration_str': duration_str,
                'text_content': f"这是一个{format_desc}文件，文件名为「{filename}」，文件大小{self._format_file_size(file_size)}，估计时长约{duration_str}。",
                'summary': f"[音频] {filename} - {format_desc}，时长约{duration_str}"
            }
            
            logging.info(f"音频处理成功: {filename}")
            return result
            
        except Exception as e:
            logging.error(f"处理音频失败: {e}")
            return {'success': False, 'error': f'音频处理失败: {str(e)}'}
    
    def process_video(self, video_path: str) -> Dict[str, Any]:
        """
        处理视频文件
        
        Args:
            video_path: 视频文件路径
        
        Returns:
            视频文件信息
        """
        try:
            ext = os.path.splitext(video_path)[1].lower()
            file_size = os.path.getsize(video_path)
            filename = os.path.basename(video_path)
            
            # 根据文件大小估算时长（粗略估算，假设1080p约8Mbps）
            estimated_duration = file_size / (1024 * 1024)  # 约1MB/s
            
            # 格式化时长
            minutes = int(estimated_duration // 60)
            seconds = int(estimated_duration % 60)
            if minutes >= 60:
                hours = minutes // 60
                minutes = minutes % 60
                duration_str = f"{hours}小时{minutes}分{seconds}秒"
            elif minutes > 0:
                duration_str = f"{minutes}分{seconds}秒"
            else:
                duration_str = f"{seconds}秒"
            
            # 根据格式确定视频类型描述
            format_desc = {
                '.mp4': 'MP4视频',
                '.avi': 'AVI视频',
                '.mov': 'MOV视频',
                '.mkv': 'MKV视频',
                '.wmv': 'WMV视频'
            }.get(ext, '视频文件')
            
            result = {
                'success': True,
                'type': 'video',
                'file_path': video_path,
                'filename': filename,
                'format': ext,
                'format_desc': format_desc,
                'file_size': file_size,
                'estimated_duration': estimated_duration,
                'duration_str': duration_str,
                'text_content': f"这是一个{format_desc}文件，文件名为「{filename}」，文件大小{self._format_file_size(file_size)}，估计时长约{duration_str}。",
                'summary': f"[视频] {filename} - {format_desc}，时长约{duration_str}"
            }
            
            logging.info(f"视频处理成功: {filename}")
            return result
            
        except Exception as e:
            logging.error(f"处理视频失败: {e}")
            return {'success': False, 'error': f'视频处理失败: {str(e)}'}
    
    def _format_file_size(self, size_bytes: int) -> str:
        """格式化文件大小"""
        if size_bytes < 1024:
            return f"{size_bytes} B"
        elif size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.1f} KB"
        elif size_bytes < 1024 * 1024 * 1024:
            return f"{size_bytes / (1024 * 1024):.1f} MB"
        else:
            return f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"
    
    def convert_to_text(self, file_path: str) -> str:
        """
        将文件转换为纯文本格式，用于输入大模型
        
        Args:
            file_path: 文件路径
        
        Returns:
            文本内容
        """
        result = self.process_file(file_path)
        
        if not result.get('success'):
            return f"[文件处理失败: {result.get('error', '未知错误')}]"
        
        file_type = result.get('type')
        filename = os.path.basename(file_path)
        
        if file_type == 'image':
            # 图片：输出视觉模型识别结果
            parts = [f"[图片文件: {filename}]"]
            parts.append(f"图片尺寸: {result['width']} x {result['height']} 像素")
            parts.append(f"图片格式: {result['format']}")
            
            # 输出视觉模型识别结果（视觉模型已包含文字识别能力）
            vision_desc = result.get('vision_description', '')
            if vision_desc:
                parts.append("")
                parts.append("图片内容分析:")
                parts.append(vision_desc)
            
            # 如果没有视觉结果，输出基础描述
            if not vision_desc:
                basic_desc = result.get('basic_description', '')
                if basic_desc:
                    parts.append("")
                    parts.append("图片基础信息:")
                    parts.append(basic_desc)
            
            return "\n".join(parts)
        
        elif file_type == 'document':
            # 文档：输出完整内容（不截断）
            content = result.get('content', '')
            
            parts = [f"[文档文件: {filename}]"]
            parts.append(f"文档格式: {result['format']}")
            parts.append(f"文档字数: {result['word_count']} 个单词")
            parts.append("")
            parts.append("文档完整内容:")
            parts.append(content)
            
            return "\n".join(parts)
        
        elif file_type == 'audio':
            return result.get('text_content', f'[音频文件: {filename}]')
        
        elif file_type == 'video':
            return result.get('text_content', f'[视频文件: {filename}]')
        
        else:
            return f"[未知文件类型: {filename}]"


class MultiFileProcessor:
    """多文件批量处理器"""
    
    def __init__(self):
        self.processor = FileProcessor()
    
    def process_files(self, file_list: list) -> Dict[str, Any]:
        """
        批量处理文件
        
        Args:
            file_list: 文件信息列表，每个元素包含 file_path 和 file_type
        
        Returns:
            批量处理结果
        """
        results = []
        success_count = 0
        fail_count = 0
        
        for file_info in file_list:
            file_path = file_info.get('file_path')
            file_type = file_info.get('file_type', 'file')
            
            result = self.processor.process_file(file_path, file_type)
            
            if result.get('success'):
                success_count += 1
            else:
                fail_count += 1
            
            results.append({
                'file_name': os.path.basename(file_path),
                'result': result
            })
        
        return {
            'success': True,
            'total': len(file_list),
            'success_count': success_count,
            'fail_count': fail_count,
            'results': results
        }
    
    def generate_combined_summary(self, file_list: list) -> str:
        """
        生成多文件的综合摘要
        
        Args:
            file_list: 文件信息列表
        
        Returns:
            综合摘要文本
        """
        batch_result = self.process_files(file_list)
        
        summary_parts = []
        summary_parts.append(f"## 文件处理报告")
        summary_parts.append(f"- 总文件数: {batch_result['total']}")
        summary_parts.append(f"- 成功处理: {batch_result['success_count']}")
        summary_parts.append(f"- 处理失败: {batch_result['fail_count']}")
        summary_parts.append("")
        
        for item in batch_result['results']:
            file_name = item['file_name']
            result = item['result']
            
            if result.get('success'):
                summary_parts.append(f"### 📄 {file_name}")
                
                if result['type'] == 'image':
                    summary_parts.append(f"- 类型: 图片")
                    summary_parts.append(f"- 尺寸: {result['width']}x{result['height']}")
                    summary_parts.append(f"- 描述: {result['description']}")
                
                elif result['type'] == 'document':
                    summary_parts.append(f"- 类型: 文档")
                    summary_parts.append(f"- 字数: {result['word_count']}")
                    summary_parts.append(f"- 摘要: {result['summary'][:200]}...")
                
                summary_parts.append("")
            else:
                summary_parts.append(f"### ❌ {file_name}")
                summary_parts.append(f"- 错误: {result.get('error', '未知错误')}")
                summary_parts.append("")
        
        return "\n".join(summary_parts)


# 单例实例
file_processor = FileProcessor()
multi_file_processor = MultiFileProcessor()
