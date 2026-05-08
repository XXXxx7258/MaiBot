"""
配置管理API路由
"""

from pathlib import Path
from typing import Annotated, Any, Dict, List, Tuple, Union, get_args, get_origin
import copy
import os
import types

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
import tomlkit

from src.common.logger import get_logger
from src.common.prompt_i18n import clear_prompt_cache, list_prompt_templates
from src.config.config import CONFIG_DIR, PROJECT_ROOT, Config, ModelConfig
from src.config.config_base import AttributeData, ConfigBase
from src.config.model_configs import (
    APIProvider,
    ModelInfo,
    ModelTaskConfig,
)
from src.config.official_configs import (
    AMemorixConfig,
    BotConfig,
    ChatConfig,
    ChineseTypoConfig,
    DebugConfig,
    EmojiConfig,
    ExpressionConfig,
    KeywordReactionConfig,
    MaimMessageConfig,
    MessageReceiveConfig,
    PersonalityConfig,
    ResponsePostProcessConfig,
    ResponseSplitterConfig,
    TelemetryConfig,
    VoiceConfig,
)
from src.webui.config_schema import ConfigSchemaGenerator
from src.webui.dependencies import require_auth
from src.webui.utils.toml_utils import _update_toml_doc, save_toml_with_format

logger = get_logger("webui")

# 模块级别的类型别名（解决 B008 ruff 错误）
ConfigBody = Annotated[Dict[str, Any], Body()]
SectionBody = Annotated[Any, Body()]
RawContentBody = Annotated[str, Body(embed=True)]
PathBody = Annotated[Dict[str, str], Body()]
PromptContentBody = Annotated[str, Body(embed=True)]

router = APIRouter(prefix="/config", tags=["config"], dependencies=[Depends(require_auth)])

PROMPTS_DIR = PROJECT_ROOT / "prompts"
CUSTOM_PROMPTS_DIR = PROJECT_ROOT / "data" / "custom_prompts"
MAISAKA_PROMPT_PREVIEW_DIR = (PROJECT_ROOT / "logs" / "maisaka_prompt").resolve()


class PromptFileInfo(BaseModel):
    """Prompt 文件信息。"""

    name: str = Field(..., description="Prompt 文件名")
    size: int = Field(..., description="文件大小")
    modified_at: float = Field(..., description="最后修改时间戳")
    display_name: str = Field(default="", description="Prompt 展示名称")
    advanced: bool = Field(default=False, description="是否为高级 Prompt")
    description: str = Field(default="", description="Prompt 描述")
    customized: bool = Field(default=False, description="是否存在用户自定义覆盖")


class PromptCatalogResponse(BaseModel):
    """Prompt 目录响应。"""

    success: bool = True
    languages: List[str]
    files: Dict[str, List[PromptFileInfo]]


class PromptFileResponse(BaseModel):
    """Prompt 文件内容响应。"""

    success: bool = True
    language: str
    filename: str
    content: str
    customized: bool = False


def _safe_prompt_path(language: str, filename: str) -> Path:
    """校验并解析 prompts 下的文件路径。"""

    normalized_language = language.strip()
    normalized_filename = filename.strip()

    if not normalized_language or any(part in normalized_language for part in ("..", "/", "\\")):
        raise HTTPException(status_code=400, detail="无效的 Prompt 语言目录")
    if not normalized_filename.endswith(".prompt") or any(part in normalized_filename for part in ("..", "/", "\\")):
        raise HTTPException(status_code=400, detail="无效的 Prompt 文件名")

    prompt_path = (PROMPTS_DIR / normalized_language / normalized_filename).resolve()
    prompts_root = PROMPTS_DIR.resolve()
    try:
        prompt_path.relative_to(prompts_root)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Prompt 路径越界") from exc
    return prompt_path


def _safe_custom_prompt_path(language: str, filename: str) -> Path:
    """校验并解析 data/custom_prompts 下的用户覆盖文件路径。"""

    normalized_language = language.strip()
    normalized_filename = filename.strip()

    if not normalized_language or any(part in normalized_language for part in ("..", "/", "\\")):
        raise HTTPException(status_code=400, detail="无效的 Prompt 语言目录")
    if not normalized_filename.endswith(".prompt") or any(part in normalized_filename for part in ("..", "/", "\\")):
        raise HTTPException(status_code=400, detail="无效的 Prompt 文件名")

    prompt_path = (CUSTOM_PROMPTS_DIR / normalized_language / normalized_filename).resolve()
    custom_prompts_root = CUSTOM_PROMPTS_DIR.resolve()
    try:
        prompt_path.relative_to(custom_prompts_root)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Prompt 路径越界") from exc
    return prompt_path


def _safe_maisaka_prompt_preview_path(relative_path: str) -> Path:
    """校验并解析 MaiSaka Prompt HTML 预览路径。"""

    normalized_path = relative_path.strip().replace("\\", "/")
    if not normalized_path or normalized_path.startswith("/") or ".." in Path(normalized_path).parts:
        raise HTTPException(status_code=400, detail="无效的 Prompt 预览路径")

    preview_path = (MAISAKA_PROMPT_PREVIEW_DIR / normalized_path).resolve()
    try:
        preview_path.relative_to(MAISAKA_PROMPT_PREVIEW_DIR)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Prompt 预览路径越界") from exc

    if preview_path.suffix.lower() != ".html":
        raise HTTPException(status_code=400, detail="只允许打开 HTML Prompt 预览")
    return preview_path


def _toml_to_plain_dict(obj: Any) -> Any:
    """递归转换 tomlkit 文档/Table 为纯 Python 字典，避免 from_dict 触发 tomlkit __setitem__"""
    if isinstance(obj, dict):
        return {str(k): _toml_to_plain_dict(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_toml_to_plain_dict(v) for v in obj]
    return obj


def _coerce_numeric_value(value: Any, target_type: Any) -> Any:
    """根据配置字段类型，把旧 WebUI 可能写入的数字字符串还原为数字。"""
    if target_type is str:
        if isinstance(value, (int, float)):
            return str(value)
        return value

    if target_type is int:
        if isinstance(value, str):
            try:
                parsed_value = float(value.strip())
            except ValueError:
                return value
            if parsed_value.is_integer():
                return int(parsed_value)
        return value

    if target_type is float:
        if isinstance(value, str):
            try:
                return float(value.strip())
            except ValueError:
                return value
        return value

    return value


def _coerce_value_by_annotation(value: Any, annotation: Any) -> Any:
    """递归按 ConfigBase 字段注解修正数据类型，避免保存时把数字写成字符串。"""
    value = _coerce_numeric_value(value, annotation)
    origin = get_origin(annotation)
    args = get_args(annotation)

    if origin in {Union, types.UnionType}:
        for candidate_type in args:
            if candidate_type is type(None):
                continue
            coerced_value = _coerce_value_by_annotation(value, candidate_type)
            if coerced_value != value or type(coerced_value) is not type(value):
                return coerced_value
        return value

    if origin in {list, List} and isinstance(value, list) and args:
        item_type = args[0]
        return [_coerce_value_by_annotation(item, item_type) for item in value]

    if origin in {dict, Dict} and isinstance(value, dict) and len(args) >= 2:
        value_type = args[1]
        return {key: _coerce_value_by_annotation(item, value_type) for key, item in value.items()}

    if isinstance(value, dict) and isinstance(annotation, type) and issubclass(annotation, ConfigBase):
        return _coerce_config_numeric_values(value, annotation)

    return value


def _coerce_config_numeric_values(data: Dict[str, Any], config_type: type[ConfigBase]) -> Dict[str, Any]:
    """按配置类 schema 统一修正所有数字字段类型。"""
    for field_name, field_info in config_type.model_fields.items():
        if field_name in data:
            data[field_name] = _coerce_value_by_annotation(data[field_name], field_info.annotation)
    return data


# ===== 架构获取接口 =====


@router.get("/prompts", response_model=PromptCatalogResponse)
async def list_prompt_files():
    """列出 prompts 目录下的语言和 Prompt 文件。"""

    try:
        if not PROMPTS_DIR.exists():
            return PromptCatalogResponse(languages=[], files={})

        languages: List[str] = []
        files: Dict[str, List[PromptFileInfo]] = {}
        for language_dir in sorted(PROMPTS_DIR.iterdir(), key=lambda item: item.name):
            if not language_dir.is_dir():
                continue

            language = language_dir.name
            prompt_template_infos = list_prompt_templates(locale=language, prompts_root=PROMPTS_DIR)
            prompt_files: List[PromptFileInfo] = []
            for prompt_file in sorted(language_dir.glob("*.prompt"), key=lambda item: item.name):
                custom_prompt_file = _safe_custom_prompt_path(language, prompt_file.name)
                effective_prompt_file = custom_prompt_file if custom_prompt_file.exists() else prompt_file
                stat = effective_prompt_file.stat()
                template_info = prompt_template_infos.get(prompt_file.stem)
                metadata = template_info.metadata if template_info and template_info.path == prompt_file else None
                prompt_files.append(
                    PromptFileInfo(
                        name=prompt_file.name,
                        size=stat.st_size,
                        modified_at=stat.st_mtime,
                        display_name=metadata.display_name if metadata else "",
                        advanced=metadata.advanced if metadata else False,
                        description=metadata.description if metadata else "",
                        customized=custom_prompt_file.exists(),
                    )
                )

            languages.append(language)
            files[language] = prompt_files

        return PromptCatalogResponse(languages=languages, files=files)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"列出 Prompt 文件失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"列出 Prompt 文件失败: {str(e)}") from e


@router.get("/prompts/{language}/{filename}", response_model=PromptFileResponse)
async def get_prompt_file(language: str, filename: str):
    """读取指定语言下的 Prompt 文件内容。"""

    prompt_path = _safe_prompt_path(language, filename)
    custom_prompt_path = _safe_custom_prompt_path(language, filename)
    if not prompt_path.exists() or not prompt_path.is_file():
        raise HTTPException(status_code=404, detail="Prompt 文件不存在")

    try:
        effective_prompt_path = custom_prompt_path if custom_prompt_path.exists() else prompt_path
        content = effective_prompt_path.read_text(encoding="utf-8")
        return PromptFileResponse(
            language=language,
            filename=filename,
            content=content,
            customized=custom_prompt_path.exists(),
        )
    except Exception as e:
        logger.error(f"读取 Prompt 文件失败: {prompt_path} {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"读取 Prompt 文件失败: {str(e)}") from e


@router.get("/prompts/{language}/{filename}/default", response_model=PromptFileResponse)
async def get_default_prompt_file(language: str, filename: str):
    """只读获取内置 Prompt 模板内容，不读取或修改用户自定义覆盖。"""

    prompt_path = _safe_prompt_path(language, filename)
    if not prompt_path.exists() or not prompt_path.is_file():
        raise HTTPException(status_code=404, detail="Prompt 文件不存在")

    try:
        content = prompt_path.read_text(encoding="utf-8")
        return PromptFileResponse(language=language, filename=filename, content=content, customized=False)
    except Exception as e:
        logger.error(f"读取默认 Prompt 文件失败: {prompt_path} {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"读取默认 Prompt 文件失败: {str(e)}") from e


@router.put("/prompts/{language}/{filename}", response_model=PromptFileResponse)
async def update_prompt_file(language: str, filename: str, content: PromptContentBody):
    """更新指定语言下的 Prompt 文件内容。"""

    prompt_path = _safe_prompt_path(language, filename)
    custom_prompt_path = _safe_custom_prompt_path(language, filename)
    if not prompt_path.parent.exists() or not prompt_path.parent.is_dir():
        raise HTTPException(status_code=404, detail="Prompt 语言目录不存在")
    if not prompt_path.exists() or not prompt_path.is_file():
        raise HTTPException(status_code=404, detail="Prompt 文件不存在")

    try:
        custom_prompt_path.parent.mkdir(parents=True, exist_ok=True)
        custom_prompt_path.write_text(content, encoding="utf-8", newline="\n")
        clear_prompt_cache()
        return PromptFileResponse(language=language, filename=filename, content=content, customized=True)
    except Exception as e:
        logger.error(f"保存 Prompt 文件失败: {prompt_path} {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"保存 Prompt 文件失败: {str(e)}") from e


@router.delete("/prompts/{language}/{filename}", response_model=PromptFileResponse)
async def reset_prompt_file(language: str, filename: str):
    """删除用户自定义覆盖，恢复使用内置 Prompt 模板。"""

    prompt_path = _safe_prompt_path(language, filename)
    custom_prompt_path = _safe_custom_prompt_path(language, filename)
    if not prompt_path.exists() or not prompt_path.is_file():
        raise HTTPException(status_code=404, detail="Prompt 文件不存在")

    try:
        if custom_prompt_path.exists():
            custom_prompt_path.unlink()
            clear_prompt_cache()
        content = prompt_path.read_text(encoding="utf-8")
        return PromptFileResponse(language=language, filename=filename, content=content, customized=False)
    except Exception as e:
        logger.error(f"恢复 Prompt 默认模板失败: {prompt_path} {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"恢复 Prompt 默认模板失败: {str(e)}") from e


@router.get("/maisaka-prompt-preview", response_class=FileResponse)
async def get_maisaka_prompt_preview(path: str = Query(..., description="logs/maisaka_prompt 下的相对 HTML 路径")):
    """打开 MaiSaka 监控中生成的 Prompt HTML 预览。"""

    preview_path = _safe_maisaka_prompt_preview_path(path)
    if not preview_path.exists() or not preview_path.is_file():
        raise HTTPException(status_code=404, detail="Prompt 预览文件不存在")
    return FileResponse(preview_path, media_type="text/html")


@router.get("/schema/bot")
async def get_bot_config_schema():
    """获取麦麦主程序配置架构"""
    try:
        # Config 类包含所有子配置
        schema = ConfigSchemaGenerator.generate_config_schema(Config)
        return {"success": True, "schema": schema}
    except Exception as e:
        logger.error(f"获取配置架构失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取配置架构失败: {str(e)}") from e


@router.get("/schema/model")
async def get_model_config_schema():
    """获取模型配置架构（包含提供商和模型任务配置）"""
    try:
        schema = ConfigSchemaGenerator.generate_config_schema(ModelConfig)
        return {"success": True, "schema": schema}
    except Exception as e:
        logger.error(f"获取模型配置架构失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取模型配置架构失败: {str(e)}") from e


# ===== 子配置架构获取接口 =====


@router.get("/schema/section/{section_name}")
async def get_config_section_schema(section_name: str):
    """
    获取指定配置节的架构

    支持的section_name:
    - bot: BotConfig
    - personality: PersonalityConfig
    - chat: ChatConfig
    - message_receive: MessageReceiveConfig
    - emoji: EmojiConfig
    - expression: ExpressionConfig
    - keyword_reaction: KeywordReactionConfig
    - chinese_typo: ChineseTypoConfig
    - response_post_process: ResponsePostProcessConfig
    - response_splitter: ResponseSplitterConfig
    - telemetry: TelemetryConfig
    - maim_message: MaimMessageConfig
    - debug: DebugConfig
    - voice: VoiceConfig
    - jargon: JargonConfig
    - model_task_config: ModelTaskConfig
    - api_provider: APIProvider
    - model_info: ModelInfo
    """
    section_map = {
        "bot": BotConfig,
        "personality": PersonalityConfig,
        "chat": ChatConfig,
        "message_receive": MessageReceiveConfig,
        "emoji": EmojiConfig,
        "expression": ExpressionConfig,
        "keyword_reaction": KeywordReactionConfig,
        "chinese_typo": ChineseTypoConfig,
        "response_post_process": ResponsePostProcessConfig,
        "response_splitter": ResponseSplitterConfig,
        "telemetry": TelemetryConfig,
        "maim_message": MaimMessageConfig,
        "a_memorix": AMemorixConfig,
        "debug": DebugConfig,
        "voice": VoiceConfig,
        "model_task_config": ModelTaskConfig,
        "api_provider": APIProvider,
        "model_info": ModelInfo,
    }

    if section_name not in section_map:
        raise HTTPException(status_code=404, detail=f"配置节 '{section_name}' 不存在")

    try:
        config_class = section_map[section_name]
        schema = ConfigSchemaGenerator.generate_schema(config_class, include_nested=False)
        return {"success": True, "schema": schema}
    except Exception as e:
        logger.error(f"获取配置节架构失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取配置节架构失败: {str(e)}") from e


# ===== 配置读取接口 =====


@router.get("/bot")
async def get_bot_config():
    """获取麦麦主程序配置"""
    try:
        config_path = os.path.join(CONFIG_DIR, "bot_config.toml")
        if not os.path.exists(config_path):
            raise HTTPException(status_code=404, detail="配置文件不存在")

        with open(config_path, "r", encoding="utf-8") as f:
            config_data = tomlkit.load(f)

        return {"success": True, "config": config_data}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"读取配置文件失败: {e}")
        raise HTTPException(status_code=500, detail=f"读取配置文件失败: {str(e)}") from e


@router.get("/model")
async def get_model_config():
    """获取模型配置（包含提供商和模型任务配置）"""
    try:
        config_path = os.path.join(CONFIG_DIR, "model_config.toml")
        if not os.path.exists(config_path):
            raise HTTPException(status_code=404, detail="配置文件不存在")

        with open(config_path, "r", encoding="utf-8") as f:
            config_data = tomlkit.load(f)

        return {"success": True, "config": config_data}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"读取配置文件失败: {e}")
        raise HTTPException(status_code=500, detail=f"读取配置文件失败: {str(e)}") from e


# ===== 配置更新接口 =====


@router.post("/bot")
async def update_bot_config(config_data: ConfigBody):
    """更新麦麦主程序配置"""
    try:
        config_data = _coerce_config_numeric_values(config_data, Config)

        # 验证配置数据
        try:
            Config.from_dict(AttributeData(), copy.deepcopy(config_data))
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"配置数据验证失败: {str(e)}") from e

        # 保存配置文件（自动保留注释和格式）
        config_path = os.path.join(CONFIG_DIR, "bot_config.toml")
        save_toml_with_format(config_data, config_path)

        logger.info("麦麦主程序配置已更新")
        return {"success": True, "message": "配置已保存"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"保存配置文件失败: {e}")
        raise HTTPException(status_code=500, detail=f"保存配置文件失败: {str(e)}") from e


@router.post("/model")
async def update_model_config(config_data: ConfigBody):
    """更新模型配置"""
    try:
        config_data = _coerce_config_numeric_values(config_data, ModelConfig)

        # 验证配置数据
        try:
            ModelConfig.from_dict(AttributeData(), copy.deepcopy(config_data))
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"配置数据验证失败: {str(e)}") from e

        # 保存配置文件（自动保留注释和格式）
        config_path = os.path.join(CONFIG_DIR, "model_config.toml")
        save_toml_with_format(config_data, config_path)

        logger.info("模型配置已更新")
        return {"success": True, "message": "配置已保存"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"保存配置文件失败: {e}")
        raise HTTPException(status_code=500, detail=f"保存配置文件失败: {str(e)}") from e


# ===== 配置节更新接口 =====


@router.post("/bot/section/{section_name}")
async def update_bot_config_section(section_name: str, section_data: SectionBody):
    """更新麦麦主程序配置的指定节（保留注释和格式）"""
    try:
        # 读取现有配置
        config_path = os.path.join(CONFIG_DIR, "bot_config.toml")
        if not os.path.exists(config_path):
            raise HTTPException(status_code=404, detail="配置文件不存在")

        with open(config_path, "r", encoding="utf-8") as f:
            config_data = tomlkit.load(f)

        # 更新指定节
        if section_name not in config_data:
            raise HTTPException(status_code=404, detail=f"配置节 '{section_name}' 不存在")

        # 使用递归合并保留注释（对于字典类型）
        # 对于数组类型（如 platforms, aliases），直接替换
        if isinstance(section_data, list):
            # 列表直接替换
            config_data[section_name] = section_data
        elif isinstance(section_data, dict) and isinstance(config_data[section_name], dict):
            # 字典递归合并
            _update_toml_doc(config_data[section_name], section_data)
        else:
            # 其他类型直接替换
            config_data[section_name] = section_data

        # 验证完整配置
        try:
            plain_config_data = _coerce_config_numeric_values(_toml_to_plain_dict(config_data), Config)
            Config.from_dict(AttributeData(), copy.deepcopy(plain_config_data))
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"配置数据验证失败: {str(e)}") from e

        config_data = plain_config_data

        # 保存配置（格式化数组为多行，保留注释）
        save_toml_with_format(config_data, config_path)

        logger.info(f"配置节 '{section_name}' 已更新（保留注释）")
        return {"success": True, "message": f"配置节 '{section_name}' 已保存"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新配置节失败: {e}")
        raise HTTPException(status_code=500, detail=f"更新配置节失败: {str(e)}") from e


# ===== 原始 TOML 文件操作接口 =====


@router.get("/bot/raw")
async def get_bot_config_raw():
    """获取麦麦主程序配置的原始 TOML 内容"""
    try:
        config_path = os.path.join(CONFIG_DIR, "bot_config.toml")
        if not os.path.exists(config_path):
            raise HTTPException(status_code=404, detail="配置文件不存在")

        with open(config_path, "r", encoding="utf-8") as f:
            raw_content = f.read()

        return {"success": True, "content": raw_content}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"读取配置文件失败: {e}")
        raise HTTPException(status_code=500, detail=f"读取配置文件失败: {str(e)}") from e


@router.post("/bot/raw")
async def update_bot_config_raw(raw_content: RawContentBody):
    """更新麦麦主程序配置（直接保存原始 TOML 内容，会先验证格式）"""
    try:
        # 验证 TOML 格式
        try:
            config_data = tomlkit.loads(raw_content)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"TOML 格式错误: {str(e)}") from e

        # 验证配置数据结构
        try:
            Config.from_dict(AttributeData(), _toml_to_plain_dict(config_data))
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"配置数据验证失败: {str(e)}") from e

        # 保存配置文件
        config_path = os.path.join(CONFIG_DIR, "bot_config.toml")
        with open(config_path, "w", encoding="utf-8") as f:
            f.write(raw_content)

        logger.info("麦麦主程序配置已更新（原始模式）")
        return {"success": True, "message": "配置已保存"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"保存配置文件失败: {e}")
        raise HTTPException(status_code=500, detail=f"保存配置文件失败: {str(e)}") from e


@router.post("/model/section/{section_name}")
async def update_model_config_section(section_name: str, section_data: SectionBody):
    """更新模型配置的指定节（保留注释和格式）"""
    try:
        # 读取现有配置
        config_path = os.path.join(CONFIG_DIR, "model_config.toml")
        if not os.path.exists(config_path):
            raise HTTPException(status_code=404, detail="配置文件不存在")

        with open(config_path, "r", encoding="utf-8") as f:
            config_data = tomlkit.load(f)

        # 更新指定节
        if section_name not in config_data:
            raise HTTPException(status_code=404, detail=f"配置节 '{section_name}' 不存在")

        # 使用递归合并保留注释（对于字典类型）
        # 对于数组表（如 [[models]], [[api_providers]]），直接替换
        if isinstance(section_data, list):
            # 列表直接替换
            config_data[section_name] = section_data
        elif isinstance(section_data, dict) and isinstance(config_data[section_name], dict):
            # 字典递归合并
            _update_toml_doc(config_data[section_name], section_data)
        else:
            # 其他类型直接替换
            config_data[section_name] = section_data

        # 验证完整配置
        try:
            plain_config_data = _coerce_config_numeric_values(_toml_to_plain_dict(config_data), ModelConfig)
            ModelConfig.from_dict(AttributeData(), copy.deepcopy(plain_config_data))
        except Exception as e:
            logger.error(f"配置数据验证失败，详细错误: {str(e)}")
            # 特殊处理：如果是更新 api_providers，检查是否有模型引用了已删除的provider
            if section_name == "api_providers" and "api_provider" in str(e):
                provider_names = {p.get("name") for p in section_data if isinstance(p, dict)}
                models = plain_config_data.get("models", [])
                orphaned_models: List[str] = [
                    str(model_name)
                    for m in models
                    if isinstance(m, dict)
                    and m.get("api_provider") not in provider_names
                    and (model_name := m.get("name")) is not None
                ]
                if orphaned_models:
                    error_msg = f"以下模型引用了已删除的提供商: {', '.join(orphaned_models)}。请先在模型管理页面删除这些模型，或重新分配它们的提供商。"
                    raise HTTPException(status_code=400, detail=error_msg) from e
            raise HTTPException(status_code=400, detail=f"配置数据验证失败: {str(e)}") from e

        config_data = plain_config_data

        # 保存配置（格式化数组为多行，保留注释）
        save_toml_with_format(config_data, config_path)

        logger.info(f"配置节 '{section_name}' 已更新（保留注释）")
        return {"success": True, "message": f"配置节 '{section_name}' 已保存"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新配置节失败: {e}")
        raise HTTPException(status_code=500, detail=f"更新配置节失败: {str(e)}") from e


# ===== 适配器配置管理接口 =====


def _normalize_adapter_path(path: str) -> str:
    """将路径转换为绝对路径（如果是相对路径，则相对于项目根目录）"""
    if not path:
        return path

    # 如果已经是绝对路径，直接返回
    if os.path.isabs(path):
        return path

    # 相对路径，转换为相对于项目根目录的绝对路径
    return os.path.normpath(os.path.join(PROJECT_ROOT, path))


def _get_allowed_adapter_config_roots() -> Tuple[Path, ...]:
    project_root = Path(PROJECT_ROOT).resolve()
    return (
        project_root,
        (project_root.parent / "MaiBot-Napcat-Adapter").resolve(),
        Path("/MaiMBot/adapters-config").resolve(),
    )


def _resolve_safe_adapter_config_path(path: str) -> Path:
    normalized_path = _normalize_adapter_path(path)
    candidate_path = Path(normalized_path).expanduser().resolve()

    if candidate_path.suffix.lower() != ".toml":
        raise HTTPException(status_code=400, detail="只支持 .toml 格式的配置文件")

    for allowed_root in _get_allowed_adapter_config_roots():
        try:
            candidate_path.relative_to(allowed_root)
            return candidate_path
        except ValueError:
            continue

    raise HTTPException(status_code=400, detail="适配器配置路径超出允许范围")


def _to_relative_path(path: str) -> str:
    """尝试将绝对路径转换为相对于项目根目录的相对路径，如果无法转换则返回原路径"""
    if not path or not os.path.isabs(path):
        return path

    try:
        # 尝试获取相对路径
        rel_path = os.path.relpath(path, PROJECT_ROOT)
        # 如果相对路径不是以 .. 开头（说明文件在项目目录内），则返回相对路径
        if not rel_path.startswith(".."):
            return rel_path
    except (ValueError, TypeError):
        # 在 Windows 上，如果路径在不同驱动器，relpath 会抛出 ValueError
        pass

    # 无法转换为相对路径，返回绝对路径
    return path


@router.get("/adapter-config/path")
async def get_adapter_config_path():
    """获取保存的适配器配置文件路径"""
    try:
        # 从 data/webui.json 读取路径偏好
        webui_data_path = os.path.join("data", "webui.json")
        if not os.path.exists(webui_data_path):
            return {"success": True, "path": None}

        import json

        with open(webui_data_path, "r", encoding="utf-8") as f:
            webui_data = json.load(f)

        adapter_config_path = webui_data.get("adapter_config_path")
        if not adapter_config_path:
            return {"success": True, "path": None}

        try:
            abs_path = str(_resolve_safe_adapter_config_path(adapter_config_path))
        except HTTPException:
            logger.warning(f"已忽略不安全的适配器配置路径: {adapter_config_path}")
            return {"success": True, "path": None}

        # 检查文件是否存在并返回最后修改时间
        if os.path.exists(abs_path):
            import datetime

            mtime = os.path.getmtime(abs_path)
            last_modified = datetime.datetime.fromtimestamp(mtime).isoformat()
            # 返回相对路径（如果可能）
            display_path = _to_relative_path(abs_path)
            return {"success": True, "path": display_path, "lastModified": last_modified}
        else:
            # 文件不存在，返回原路径
            return {"success": True, "path": adapter_config_path, "lastModified": None}

    except Exception as e:
        logger.error(f"获取适配器配置路径失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取配置路径失败: {str(e)}") from e


@router.post("/adapter-config/path")
async def save_adapter_config_path(data: PathBody):
    """保存适配器配置文件路径偏好"""
    try:
        path = data.get("path")
        if not path:
            raise HTTPException(status_code=400, detail="路径不能为空")

        # 保存到 data/webui.json
        webui_data_path = os.path.join("data", "webui.json")
        import json

        # 读取现有数据
        if os.path.exists(webui_data_path):
            with open(webui_data_path, "r", encoding="utf-8") as f:
                webui_data = json.load(f)
        else:
            webui_data = {}

        abs_path = str(_resolve_safe_adapter_config_path(path))

        # 尝试转换为相对路径保存（如果文件在项目目录内）
        save_path = _to_relative_path(abs_path)

        # 更新路径
        webui_data["adapter_config_path"] = save_path

        # 保存
        os.makedirs("data", exist_ok=True)
        with open(webui_data_path, "w", encoding="utf-8") as f:
            json.dump(webui_data, f, ensure_ascii=False, indent=2)

        logger.info(f"适配器配置路径已保存: {save_path}（绝对路径: {abs_path}）")
        return {"success": True, "message": "路径已保存"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"保存适配器配置路径失败: {e}")
        raise HTTPException(status_code=500, detail=f"保存路径失败: {str(e)}") from e


@router.get("/adapter-config")
async def get_adapter_config(path: str):
    """从指定路径读取适配器配置文件"""
    try:
        if not path:
            raise HTTPException(status_code=400, detail="路径参数不能为空")

        abs_path = str(_resolve_safe_adapter_config_path(path))

        # 检查文件是否存在
        if not os.path.exists(abs_path):
            raise HTTPException(status_code=404, detail=f"配置文件不存在: {path}")

        # 读取文件内容
        with open(abs_path, "r", encoding="utf-8") as f:
            content = f.read()

        logger.info(f"已读取适配器配置: {path} (绝对路径: {abs_path})")
        return {"success": True, "content": content}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"读取适配器配置失败: {e}")
        raise HTTPException(status_code=500, detail=f"读取配置失败: {str(e)}") from e


@router.post("/adapter-config")
async def save_adapter_config(data: PathBody):
    """保存适配器配置到指定路径"""
    try:
        path = data.get("path")
        content = data.get("content")

        if not path:
            raise HTTPException(status_code=400, detail="路径不能为空")
        if content is None:
            raise HTTPException(status_code=400, detail="配置内容不能为空")

        abs_path = str(_resolve_safe_adapter_config_path(path))

        # 验证 TOML 格式
        try:
            tomlkit.loads(content)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"TOML 格式错误: {str(e)}") from e

        # 确保目录存在
        dir_path = os.path.dirname(abs_path)
        if dir_path:
            os.makedirs(dir_path, exist_ok=True)

        # 保存文件
        with open(abs_path, "w", encoding="utf-8") as f:
            f.write(content)

        logger.info(f"适配器配置已保存: {path} (绝对路径: {abs_path})")
        return {"success": True, "message": "配置已保存"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"保存适配器配置失败: {e}")
        raise HTTPException(status_code=500, detail=f"保存配置失败: {str(e)}") from e
