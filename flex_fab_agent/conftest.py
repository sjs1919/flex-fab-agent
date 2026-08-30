"""pytest 全局配置：把 agent-training 根加入 sys.path，让 `demo` 包可解析。

eval/ 内部用相对导入（from ..core.llm_client），必须让 `demo` 作为父包导入，
因此这里加的是 agent-training 根（demo 的父目录），不是 demo 根。
"""
import sys
from pathlib import Path

AGENT_TRAINING_ROOT = Path(__file__).resolve().parent.parent  # demo/../ = agent-training/
if str(AGENT_TRAINING_ROOT) not in sys.path:
    sys.path.insert(0, str(AGENT_TRAINING_ROOT))
