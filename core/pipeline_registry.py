"""全局Pipeline注册表，解决跨模块实例问题"""

_pipeline = None

def register(pipeline) -> None:
    global _pipeline
    _pipeline = pipeline

def get():
    return _pipeline