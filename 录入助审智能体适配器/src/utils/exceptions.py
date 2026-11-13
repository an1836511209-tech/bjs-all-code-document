"""
自定义异常类模块
"""


class FileProcessingError(Exception):
    """文件处理异常"""
    pass


class QualityCheckError(Exception):
    """质量检测异常"""
    pass


class PDFConversionError(Exception):
    """PDF转换异常"""
    pass


class ExcelProcessingError(Exception):
    """Excel处理异常"""
    pass


class CSVProcessingError(Exception):
    """CSV处理异常"""
    pass


class WordProcessingError(Exception):
    """Word文档处理异常"""
    pass