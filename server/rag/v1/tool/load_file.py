import logging
import os
import re

import PyPDF2
import markdown
import tiktoken
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)
enc = tiktoken.get_encoding("cl100k_base")


class ReadFiles:
    """
    读取文件的类，用于从指定路径读取支持的文件类型（如 .txt、.md、.pdf）并进行内容分割。
    支持返回每个文档片段的来源文件名。
    """

    def __init__(self, path: str) -> None:
        self._path = path
        self.file_list = self.get_files()

    def get_files(self):
        """遍历指定文件夹，获取支持的文件类型列表。"""
        file_list = []
        for filepath, dirnames, filenames in os.walk(self._path):
            for filename in filenames:
                if filename.endswith((".md", ".txt", ".pdf")):
                    file_list.append(os.path.join(filepath, filename))
        return file_list

    def get_content(self, max_token_len: int = 600, cover_content: int = 150):
        """
        读取文件内容并进行分割，返回切分后的文档片段列表。
        """
        docs = []
        for file in self.file_list:
            try:
                content = self.read_file_content(file)
                if not content or not content.strip():
                    logger.warning(f"文件内容为空，跳过: {file}")
                    continue
                chunk_content = self.get_chunk(
                    content, max_token_len=max_token_len, cover_content=cover_content
                )
                docs.extend(chunk_content)
            except Exception as e:
                logger.error(f"读取文件失败 {file}: {e}")
                continue
        return docs

    def get_content_with_source(self, max_token_len: int = 600, cover_content: int = 150):
        """
        读取文件内容并进行分割，返回 (文档片段列表, 来源文件名列表) 元组。
        每个片段都记录来源于哪个文件。
        """
        docs = []
        sources = []
        for file in self.file_list:
            try:
                content = self.read_file_content(file)
                if not content or not content.strip():
                    logger.warning(f"文件内容为空，跳过: {file}")
                    continue
                chunk_content = self.get_chunk(
                    content, max_token_len=max_token_len, cover_content=cover_content
                )
                source_name = os.path.basename(file)
                # 去掉 doc_id 前缀（如 "a1b2c3d4_原始文件名.pdf"）
                parts = source_name.split("_", 1)
                if len(parts) > 1 and len(parts[0]) == 8:
                    source_name = parts[1]

                docs.extend(chunk_content)
                sources.extend([source_name] * len(chunk_content))
            except Exception as e:
                logger.error(f"读取文件失败 {file}: {e}")
                continue
        return docs, sources

    @classmethod
    def get_chunk(cls, text: str, max_token_len: int = 600, cover_content: int = 150):
        """将文档内容按最大 Token 长度进行切分。"""
        chunk_text = []
        curr_len = 0
        curr_chunk = ''
        token_len = max_token_len - cover_content
        lines = text.splitlines()

        for line in lines:
            line = line.replace(' ', '')
            line_len = len(enc.encode(line))
            if line_len > max_token_len:
                num_chunks = (line_len + token_len - 1) // token_len
                for i in range(num_chunks):
                    start = i * token_len
                    end = start + token_len
                    while not line[start:end].rstrip().isspace():
                        start += 1
                        end += 1
                        if start >= line_len:
                            break
                    curr_chunk = curr_chunk[-cover_content:] + line[start:end]
                    chunk_text.append(curr_chunk)
                start = (num_chunks - 1) * token_len
                curr_chunk = curr_chunk[-cover_content:] + line[start:end]
                chunk_text.append(curr_chunk)
            elif curr_len + line_len <= token_len:
                curr_chunk += line + '\n'
                curr_len += line_len + 1
            else:
                chunk_text.append(curr_chunk)
                curr_chunk = curr_chunk[-cover_content:] + line
                curr_len = line_len + cover_content

        if curr_chunk:
            chunk_text.append(curr_chunk)

        return chunk_text

    @classmethod
    def read_file_content(cls, file_path: str):
        """读取文件内容，根据文件类型选择不同的读取方式。"""
        if file_path.endswith('.pdf'):
            return cls.read_pdf(file_path)
        elif file_path.endswith('.md'):
            return cls.read_markdown(file_path)
        elif file_path.endswith('.txt'):
            return cls.read_text(file_path)
        else:
            raise ValueError(f"不支持的文件类型: {file_path}")

    @classmethod
    def read_pdf(cls, file_path: str):
        """读取 PDF 文件内容，包含错误处理。"""
        try:
            with open(file_path, 'rb') as file:
                reader = PyPDF2.PdfReader(file)
                text = ""
                for page_num in range(len(reader.pages)):
                    try:
                        page_text = reader.pages[page_num].extract_text()
                        if page_text:
                            text += page_text
                    except Exception as e:
                        logger.warning(f"PDF 第 {page_num+1} 页提取失败: {e}")
                        continue
                return text
        except Exception as e:
            logger.error(f"PDF 文件读取失败 {file_path}: {e}")
            return ""

    @classmethod
    def read_markdown(cls, file_path: str):
        """读取 Markdown 文件内容，并将其转换为纯文本。"""
        try:
            with open(file_path, 'r', encoding='utf-8', errors='replace') as file:
                md_text = file.read()
                html_text = markdown.markdown(md_text)
                soup = BeautifulSoup(html_text, 'html.parser')
                plain_text = soup.get_text()
                text = re.sub(r'http\S+', '', plain_text)
                return text
        except Exception as e:
            logger.error(f"Markdown 文件读取失败 {file_path}: {e}")
            return ""

    @classmethod
    def read_text(cls, file_path: str):
        """读取普通文本文件内容，包含编码容错。"""
        for encoding in ['utf-8', 'gbk', 'gb2312', 'latin-1']:
            try:
                with open(file_path, 'r', encoding=encoding) as file:
                    return file.read()
            except UnicodeDecodeError:
                continue
            except Exception as e:
                logger.error(f"文本文件读取失败 {file_path}: {e}")
                return ""
        logger.error(f"无法解码文件 {file_path}，已尝试所有编码")
        return ""
