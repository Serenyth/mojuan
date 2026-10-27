"""OpenAI 兼容 API 客户端。

配置来自「设置」页：baseURL / apiKey / model（文本）与 visionModel（视觉）。
用 httpx 直连 /chat/completions，不引官方 SDK——各家兼容层在路径、字段、
返回结构上的差异自己控制，出错时堆栈更干净。

所有异常都带中文 message，直接能显示给用户。
"""

import base64
import json
import re

import httpx

from app.settings import get_settings

_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE)


class AiError(Exception):
    """模型调用失败。message 面向用户。"""


class AiConfigError(AiError):
    """没配好接口。"""


class AiRequestError(AiError):
    """网络或 HTTP 层失败。"""


class AiResponseError(AiError):
    """返回结构不对或内容为空。"""


def _first_balanced(text: str, opener: str, closer: str) -> str | None:
    """从 opener 首次出现处找一段配平的括号内容，找不到返回 None。"""
    start = text.find(opener)
    if start < 0:
        return None
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == opener:
            depth += 1
        elif char == closer:
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return None


def extract_json(text: str):
    """从模型回复里抠出 JSON。

    模型很爱在 JSON 外面包一层 ```json 围栏或者几句解释，
    这里先脱围栏，再找第一段配平的 JSON。

    两种括号都试、取起点更靠前的那个：数组里套对象时，先找 "{" 只会
    拿到第一个元素，把整个数组丢掉。
    """
    candidate = text.strip()
    fenced = _FENCE.search(candidate)
    if fenced:
        candidate = fenced.group(1).strip()

    chunks = []
    for opener, closer in (("{", "}"), ("[", "]")):
        chunk = _first_balanced(candidate, opener, closer)
        if chunk:
            chunks.append((candidate.find(opener), chunk))

    last_error: json.JSONDecodeError | None = None
    for _, chunk in sorted(chunks):
        try:
            return json.loads(chunk)
        except json.JSONDecodeError as error:
            last_error = error
            continue

    snippet = " ".join(candidate.split())[:300]
    if last_error is not None:
        reason = f"JSON 语法错误：{last_error.msg}（第 {last_error.lineno} 行第 {last_error.colno} 列）"
    elif not candidate:
        reason = "内容为空"
    else:
        reason = "没找到完整的 {} 或 [] 代码块（可能被截断或括号不配对）"
    raise AiResponseError(f"没找到可解析的 JSON：{reason}。原文开头：{snippet or '（空）'}")


class AiClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        vision_model: str = "",
        timeout: float = 90.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.vision_model = vision_model or model
        self.timeout = timeout

    @classmethod
    def from_conn(cls, conn) -> "AiClient":
        settings = get_settings(conn)
        if not settings.get("ai_base_url") or not settings.get("ai_api_key"):
            raise AiConfigError("尚未配置模型接口，请先到「设置」页填写 Base URL 与 API Key")
        if not settings.get("ai_model"):
            raise AiConfigError("尚未配置文本模型，请先到「设置」页填写模型名")
        return cls(
            base_url=settings["ai_base_url"],
            api_key=settings["ai_api_key"],
            model=settings["ai_model"],
            vision_model=settings.get("ai_vision_model", ""),
        )

    # ---------------------------------------------------------------- 基础调用

    def _post(self, payload: dict) -> dict:
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        try:
            response = httpx.post(url, json=payload, headers=headers, timeout=self.timeout)
        except httpx.TimeoutException as error:
            raise AiRequestError(f"模型接口超时（{self.timeout:.0f}s）") from error
        except httpx.HTTPError as error:
            raise AiRequestError(f"连不上模型接口：{error}") from error

        if response.status_code >= 400:
            detail = ""
            try:
                body = response.json()
                detail = body.get("error", {}).get("message") or body.get("detail") or ""
            except Exception:
                detail = response.text[:200]
            raise AiRequestError(f"模型接口返回 {response.status_code}：{detail or '无说明'}")

        try:
            return response.json()
        except json.JSONDecodeError as error:
            snippet = " ".join(response.text.split())[:300]
            raise AiResponseError(
                f"模型接口返回的不是合法 JSON（{error.msg}，第 {error.lineno} 行第 "
                f"{error.colno} 列，状态 {response.status_code}）。原文开头：{snippet or '（空）'}"
            ) from error

    @staticmethod
    def _message(data: dict) -> tuple[str, str]:
        """取出 (正文, 思考内容)。

        思考内容只有推理模型（reasoning_content，DeepSeek-R1 / QwQ 等）
        才会给；普通模型返回空串。agent 循环把它当思维链展示。
        """
        try:
            message = data["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as error:
            raise AiResponseError(f"模型返回结构异常：{str(data)[:200]}") from error
        content = message.get("content")
        if isinstance(content, list):
            content = "".join(
                part.get("text", "") for part in content if isinstance(part, dict)
            )
        reasoning = message.get("reasoning_content") or ""
        if isinstance(reasoning, list):
            reasoning = "".join(str(part) for part in reasoning)
        return ("" if content is None else str(content)).strip(), str(reasoning).strip()

    @staticmethod
    def _content(data: dict) -> str:
        content, _ = AiClient._message(data)
        if not content:
            raise AiResponseError("模型返回了空内容")
        return content

    # ---------------------------------------------------------------- 对外能力

    def chat(
        self,
        messages: list[dict],
        *,
        model: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 8000,
        return_reasoning: bool = False,
    ):
        """要一段回复。return_reasoning=True 时返回 (正文, 思考内容)。"""
        payload = {
            "model": model or self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        data = self._post(payload)
        if return_reasoning:
            content, reasoning = self._message(data)
            if not content:
                raise AiResponseError("模型返回了空内容")
            return content, reasoning
        return self._content(data)

    def chat_json(
        self,
        messages: list[dict],
        *,
        model: str | None = None,
        temperature: float = 0.1,
        max_tokens: int = 8000,
    ):
        """要一段 JSON。低温 + 宽容解析，拿到 dict 或 list。"""
        text = self.chat(
            messages, model=model, temperature=temperature, max_tokens=max_tokens
        )
        return extract_json(text)

    def chat_vision(
        self,
        prompt: str,
        images: list[tuple[bytes, str]],
        *,
        system: str | None = None,
        temperature: float = 0.1,
        max_tokens: int = 8000,
    ) -> str:
        """图片题用多模态直读，不做 OCR。

        images 是 (字节, mime) 列表，转成 data URL 内联进消息。
        """
        parts: list[dict] = [{"type": "text", "text": prompt}]
        for data, mime in images:
            encoded = base64.b64encode(data).decode("ascii")
            parts.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime};base64,{encoded}"},
                }
            )

        messages: list[dict] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": parts})

        return self.chat(
            messages,
            model=self.vision_model,
            temperature=temperature,
            max_tokens=max_tokens,
        )
