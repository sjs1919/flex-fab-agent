"""pytest 全局配置：把项目根加入 sys.path，让 `flex_fab_agent` 包可解析。

eval/ 内部用相对导入（from ..core.llm_client），必须让 `flex_fab_agent` 作为父包导入，
因此这里加的是项目根（flex_fab_agent 的父目录），不是 flex_fab_agent 根。
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent  # flex_fab_agent/../ = 项目根/
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
