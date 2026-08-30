"""HuggingFace 模型加载工具（离线优先 + 镜像回落）。

集中处理所有 HF 模型加载的共同逻辑：
  1. 先尝试离线加载（已缓存 → 零联网，防 DNS 污染挂死）
  2. 离线失败 → 经 hf-mirror 下载
  3. huggingface_hub 的 constants 在 import 时固化，运行时设 env 无效，
     必须直接 patch constants 才能真正切换离线/在线模式

使用方：
  - cache/semantic_cache.py（bge embedding）
  - rag/knowledge_base.py（bge embedding）
  - rag/retriever.py（bge-reranker CrossEncoder）
"""
import os


# hf-mirror 地址（国内加速）
HF_MIRROR = "https://hf-mirror.com"


def _patch_hf_offline(offline: bool) -> None:
    """patch huggingface_hub.constants 的离线开关和 endpoint。

    huggingface_hub 在 import 时把 HF_HUB_OFFLINE/HF_ENDPOINT 固化到
    constants 模块，运行时改 os.environ 不生效，必须直接改 constants 引用。
    """
    try:
        import huggingface_hub.constants as _hf_const  # noqa: F401
        _hf_const.HF_HUB_OFFLINE = offline
        if not offline:
            _hf_const.ENDPOINT = HF_MIRROR
    except Exception:
        pass


def _set_offline_env() -> None:
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"


def _clear_offline_env() -> None:
    os.environ.pop("HF_HUB_OFFLINE", None)
    os.environ.pop("TRANSFORMERS_OFFLINE", None)


def load_st_embedding(model_name: str):
    """加载 Chroma 的 SentenceTransformerEmbeddingFunction。

    策略：离线优先 → 失败经 hf-mirror 下载。

    Args:
        model_name: 模型名，如 "BAAI/bge-small-zh-v1.5"

    Returns:
        SentenceTransformerEmbeddingFunction 实例

    Raises:
        RuntimeError: 离线和镜像都加载失败
    """
    _set_offline_env()
    _patch_hf_offline(True)
    from chromadb.utils.embedding_functions import (
        SentenceTransformerEmbeddingFunction,
    )
    try:
        return SentenceTransformerEmbeddingFunction(model_name=model_name)
    except Exception as offline_err:
        # 未缓存：放开离线，经镜像下载
        _clear_offline_env()
        _patch_hf_offline(False)
        try:
            return SentenceTransformerEmbeddingFunction(model_name=model_name)
        except Exception as e:
            raise RuntimeError(
                f"embedding 加载失败（离线: {offline_err}; 镜像: {e}）\n"
                f"首次下载：HF_ENDPOINT={HF_MIRROR} python -c "
                f"\"from sentence_transformers import SentenceTransformer as S; "
                f"S('{model_name}')\""
            )


def load_cross_encoder(model_name: str, proxy: str | None = None):
    """加载 CrossEncoder（reranker 用）。

    策略：离线优先 → 失败经代理/镜像下载。

    Args:
        model_name: 模型名，如 "BAAI/bge-reranker-base"
        proxy: 可选代理地址，如 "http://127.0.0.1:3450"。
               传 None 则走 hf-mirror，不设代理。

    Returns:
        CrossEncoder 实例

    Raises:
        RuntimeError: 离线和在线都加载失败
    """
    from sentence_transformers import CrossEncoder

    _set_offline_env()
    _patch_hf_offline(True)
    try:
        model = CrossEncoder(model_name)
        return model
    except Exception as offline_err:
        # 离线失败：放开
        _clear_offline_env()
        _patch_hf_offline(False)

        old_https = os.environ.get("HTTPS_PROXY")
        old_http = os.environ.get("HTTP_PROXY")
        if proxy:
            os.environ["HTTPS_PROXY"] = proxy
            os.environ["HTTP_PROXY"] = proxy
        try:
            model = CrossEncoder(model_name)
        except Exception as e:
            raise RuntimeError(
                f"CrossEncoder 加载失败（离线: {offline_err}; 在线: {e}）\n"
                f"可能原因：① 模型未缓存且网络不通；② 代理不可用。"
            )
        finally:
            if proxy:
                if old_https is not None:
                    os.environ["HTTPS_PROXY"] = old_https
                else:
                    os.environ.pop("HTTPS_PROXY", None)
                if old_http is not None:
                    os.environ["HTTP_PROXY"] = old_http
                else:
                    os.environ.pop("HTTP_PROXY", None)
        return model
