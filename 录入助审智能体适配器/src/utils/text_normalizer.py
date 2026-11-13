"""
文本规范化工具

提供文本规范化功能，用于字段值对比时的兼容处理：
- 中英文符号转换
- 数值格式规范化
- 空白字符处理
"""

from typing import Optional
from loguru import logger


# 中文符号到英文符号的映射表
CHINESE_TO_ENGLISH_PUNCTUATION = {
    # 括号
    '（': '(',
    '）': ')',
    '【': '[',
    '】': ']',
    '「': '[',
    '」': ']',
    '『': '[',
    '』': ']',
    '〔': '[',
    '〕': ']',
    '〈': '<',
    '〉': '>',
    '《': '<',
    '》': '>',
    
    # 引号
    '"': '"',
    '"': '"',
    ''': "'",
    ''': "'",
    '「': '"',
    '」': '"',
    
    # 标点符号
    '，': ',',
    '。': '.',
    '：': ':',
    '；': ';',
    '？': '?',
    '！': '!',
    '、': ',',
    '～': '~',
    '—': '-',
    '－': '-',
    '–': '-',
    
    # 数学符号
    '×': 'x',
    '÷': '/',
    '＋': '+',
    '－': '-',
    '＝': '=',
    '％': '%',
    
    # 全角数字
    '０': '0',
    '１': '1',
    '２': '2',
    '３': '3',
    '４': '4',
    '５': '5',
    '６': '6',
    '７': '7',
    '８': '8',
    '９': '9',
    
    # 全角字母（小写）
    'ａ': 'a', 'ｂ': 'b', 'ｃ': 'c', 'ｄ': 'd', 'ｅ': 'e',
    'ｆ': 'f', 'ｇ': 'g', 'ｈ': 'h', 'ｉ': 'i', 'ｊ': 'j',
    'ｋ': 'k', 'ｌ': 'l', 'ｍ': 'm', 'ｎ': 'n', 'ｏ': 'o',
    'ｐ': 'p', 'ｑ': 'q', 'ｒ': 'r', 'ｓ': 's', 'ｔ': 't',
    'ｕ': 'u', 'ｖ': 'v', 'ｗ': 'w', 'ｘ': 'x', 'ｙ': 'y',
    'ｚ': 'z',
    
    # 全角字母（大写）
    'Ａ': 'A', 'Ｂ': 'B', 'Ｃ': 'C', 'Ｄ': 'D', 'Ｅ': 'E',
    'Ｆ': 'F', 'Ｇ': 'G', 'Ｈ': 'H', 'Ｉ': 'I', 'Ｊ': 'J',
    'Ｋ': 'K', 'Ｌ': 'L', 'Ｍ': 'M', 'Ｎ': 'N', 'Ｏ': 'O',
    'Ｐ': 'P', 'Ｑ': 'Q', 'Ｒ': 'R', 'Ｓ': 'S', 'Ｔ': 'T',
    'Ｕ': 'U', 'Ｖ': 'V', 'Ｗ': 'W', 'Ｘ': 'X', 'Ｙ': 'Y',
    'Ｚ': 'Z',
    
    # 全角空格
    '\u3000': ' ',  # 全角空格
}


def normalize_punctuation(text: str) -> str:
    """
    将中文标点符号转换为英文标点符号
    
    Args:
        text: 原始文本
        
    Returns:
        str: 转换后的文本
        
    Examples:
        >>> normalize_punctuation("中粮米业（仙桃）有限公司")
        '中粮米业(仙桃)有限公司'
        
        >>> normalize_punctuation("价格：100元")
        '价格:100元'
    """
    if not text:
        return text
    
    result = []
    for char in text:
        if char in CHINESE_TO_ENGLISH_PUNCTUATION:
            result.append(CHINESE_TO_ENGLISH_PUNCTUATION[char])
        else:
            result.append(char)
    
    return ''.join(result)


def normalize_number(value: str) -> str:
    """
    规范化数值格式
    
    - 去掉尾部多余的0（如 "98.60" -> "98.6"）
    - 整数去掉小数点（如 "100.00" -> "100"）
    
    Args:
        value: 原始值字符串
        
    Returns:
        str: 规范化后的值
        
    Examples:
        >>> normalize_number("98.60")
        '98.6'
        
        >>> normalize_number("100.00")
        '100'
        
        >>> normalize_number("abc")
        'abc'
    """
    value = str(value).strip()
    if not value:
        return value
    
    try:
        num = float(value)
        # 如果是整数，返回整数格式
        if num == int(num):
            return str(int(num))
        # 否则返回去掉尾部0的浮点数格式
        return f"{num:g}"
    except (ValueError, TypeError):
        # 不是数字，返回原值
        return value


def normalize_whitespace(text: str, remove_all: bool = False) -> str:
    """
    规范化空白字符
    
    - 去除首尾空白
    - 将多个连续空白字符合并为一个空格（remove_all=False）
    - 或完全移除所有空白字符（remove_all=True）
    - 将各种空白字符（制表符、换行符等）转换为普通空格或移除
    
    Args:
        text: 原始文本
        remove_all: 是否完全移除所有空白字符（默认False）
        
    Returns:
        str: 规范化后的文本
        
    Examples:
        >>> normalize_whitespace("  hello   world  ")
        'hello world'
        
        >>> normalize_whitespace("  hello   world  ", remove_all=True)
        'helloworld'
        
        >>> normalize_whitespace("你 好", remove_all=True)
        '你好'
    """
    if not text:
        return text
    
    import re
    if remove_all:
        # 完全移除所有空白字符
        text = re.sub(r'\s+', '', text)
    else:
        # 将所有空白字符替换为单个空格
        text = re.sub(r'\s+', ' ', text)
        # 去除首尾空白
        text = text.strip()
    
    return text


def normalize_for_comparison(text: Optional[str]) -> str:
    """
    综合规范化函数，用于字段值对比
    
    依次执行以下规范化操作：
    1. 中英文符号转换
    2. 完全移除所有空白字符（对比时忽略空格差异）
    3. 转小写
    4. 数值格式规范化
    
    Args:
        text: 原始文本
        
    Returns:
        str: 规范化后的文本
        
    Examples:
        >>> normalize_for_comparison("中粮米业（仙桃）有限公司")
        '中粮米业(仙桃)有限公司'
        
        >>> normalize_for_comparison("  HELLO  WORLD  ")
        'helloworld'
        
        >>> normalize_for_comparison("你 好")
        '你好'
        
        >>> normalize_for_comparison("98.60")
        '98.6'
    """
    if text is None:
        return ""
    
    text = str(text)
    
    # 1. 中英文符号转换
    text = normalize_punctuation(text)
    
    # 2. 完全移除所有空白字符（对比时忽略所有空格差异）
    text = normalize_whitespace(text, remove_all=True)
    
    # 3. 转小写
    text = text.lower()
    
    # 4. 尝试数值格式规范化（仅当整个字符串是数字时）
    text = normalize_number(text)
    
    return text


def are_values_equivalent(value1: Optional[str], value2: Optional[str]) -> bool:
    """
    判断两个值是否等价（考虑符号兼容性和空格差异）
    
    Args:
        value1: 第一个值
        value2: 第二个值
        
    Returns:
        bool: 是否等价
        
    Examples:
        >>> are_values_equivalent("中粮米业（仙桃）有限公司", "中粮米业(仙桃)有限公司")
        True
        
        >>> are_values_equivalent("98.60", "98.6")
        True
        
        >>> are_values_equivalent("Hello World", "hello  world")
        True
        
        >>> are_values_equivalent("你好", "你 好")
        True
    """
    normalized1 = normalize_for_comparison(value1)
    normalized2 = normalize_for_comparison(value2)
    
    return normalized1 == normalized2

