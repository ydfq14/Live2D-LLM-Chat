"""
SafetyRAG —— 基于向量检索的安全拦截系统（Guardrails）。

设计原则：
- 规则存储在 safety_rag/safety_rules.json（文本可读，可维护）
- 向量库存储在 safety_db/（独立于 plugins_data/）
- 拦截策略：关键词匹配（0ms） + 向量检索（语义匹配，~50ms）
- 话术从规则模板动态渲染，不硬编码
- 使用 VectorStore 适配器（适配器模式），支持未来切换数据库

初始化流程：
1. 读取 safety_rag/safety_rules.json
2. 将每条规则的 description 向量化存入 safety_db/（通过 VectorStore 适配器）
3. 运行时：先关键词匹配，关键词未命中则向量检索
"""
from __future__ import annotations

import json
import os
import sys
from typing import Any, Dict, List, Optional

from log_config import get_logger

logger = get_logger("safety_rag")

# 确保能导入 plugins 目录下的 vector_store_adapter
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from plugins.vector_store_adapter import VectorStore, ChromaAdapter, create_vector_store


class SafetyRAG:
    """安全规则向量检索系统。

    Attributes:
        rules: 内存中的规则列表（关键词快速匹配）
        store: VectorStore 适配器实例（语义检索）
    """

    def __init__(
        self,
        rules_path: str = "./safety_rag/safety_rules.json",
        db_path: str = "./safety_db",
        adapter: Optional[VectorStore] = None,
        adapter_name: str = "chroma",
    ) -> None:
        self.rules_path = rules_path
        self.db_path = db_path
        self._rules: List[Dict[str, Any]] = []
        self.store: Optional[VectorStore] = adapter
        self._adapter_name = adapter_name
        self._init_rules()
        self._init_vector_store()

    # ────────────────────────────────────────────
    # 初始化
    # ────────────────────────────────────────────

    def _init_rules(self) -> None:
        """从 JSON 加载规则到内存。"""
        if not os.path.exists(self.rules_path):
            logger.warning("[SafetyRAG] 规则文件不存在: %s", self.rules_path)
            return

        try:
            with open(self.rules_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._rules = data.get("rules", [])
            logger.info("[SafetyRAG] 加载 %d 条规则", len(self._rules))
        except Exception as e:
            logger.error("[SafetyRAG] 规则加载失败: %s", e)

    def _init_vector_store(self) -> None:
        """初始化 VectorStore 适配器，将规则向量化。"""
        if self.store is None:
            try:
                if self._adapter_name == "chroma":
                    self.store = ChromaAdapter(
                        persist_dir=self.db_path,
                        collection_name="safety_rules",
                    )
                else:
                    self.store = create_vector_store(
                        self._adapter_name,
                        persist_dir=self.db_path,
                        collection_name="safety_rules",
                    )
                logger.info("[SafetyRAG] VectorStore 适配器就绪: %s", self._adapter_name)
            except Exception as e:
                logger.error("[SafetyRAG] 向量库初始化失败: %s", e)
                self.store = None
                return

        if self.store and self.store.is_ready:
            # 检查是否已有数据（简单判断：查询一条看是否返回）
            try:
                existing = self.store.query("自杀", n_results=1)
                if not existing:
                    self._index_rules()
                else:
                    logger.info("[SafetyRAG] 复用已有向量库: %s", self.db_path)
            except Exception:
                self._index_rules()
        else:
            logger.warning("[SafetyRAG] VectorStore 未就绪，关键词匹配仍可用")

    def _index_rules(self) -> None:
        """将规则向量化存入 VectorStore。"""
        if not self.store or not self._rules:
            return

        for rule in self._rules:
            rule_id = rule.get("id", "")
            description = rule.get("description", "")
            keywords = rule.get("indicators", {}).get("keywords", [])
            semantic = rule.get("indicators", {}).get("semantic_hints", [])

            text_to_embed = f"{description}. 相关表达：{', '.join(semantic)}. 关键词：{', '.join(keywords[:10])}"

            try:
                self.store.add(
                    ids=[rule_id],
                    documents=[text_to_embed],
                    metadatas=[{
                        "level": rule.get("level", "low"),
                        "category": rule.get("category", ""),
                        "action": rule.get("response", {}).get("action", "normal"),
                    }]
                )
            except Exception as e:
                logger.warning("[SafetyRAG] 规则索引失败 %s: %s", rule_id, e)

        logger.info("[SafetyRAG] 已索引 %d 条规则到向量库", len(self._rules))

    # ────────────────────────────────────────────
    # 核心检测
    # ────────────────────────────────────────────

    def check_input(self, text: str) -> Dict[str, Any]:
        """检查用户输入是否触发安全规则。

        策略：
        1. 关键词硬匹配（O(1) 快速检测）
        2. 向量语义检索（未命中关键词时，做语义兜底）

        Returns:
            {
                "risk_level": "safe" | "low" | "medium" | "high",
                "risk_type": str,
                "intercept": bool,
                "response": str | None,
                "reason": str,
            }
        """
        if not text or not isinstance(text, str):
            return self._safe_result()

        text_lower = text.lower()

        # ── 第一层：关键词硬匹配 ──
        keyword_result = self._check_keywords(text_lower)
        if keyword_result:
            return keyword_result

        # ── 第二层：向量语义检索 ──
        vector_result = self._check_vector(text)
        if vector_result:
            return vector_result

        return self._safe_result()

    def _check_keywords(self, text: str) -> Optional[Dict[str, Any]]:
        """关键词匹配，返回命中的规则结果。"""
        for rule in self._rules:
            keywords = rule.get("indicators", {}).get("keywords", [])
            for kw in keywords:
                if kw in text:
                    return self._build_result(rule, f"关键词命中: {kw}")
        return None

    def _check_vector(self, text: str) -> Optional[Dict[str, Any]]:
        """向量语义检索，返回最匹配的规则。"""
        if not self.store or not self.store.is_ready:
            return None

        try:
            results = self.store.query(text, n_results=1)

            if not results:
                return None

            best = results[0]
            best_distance = best.get("distance", 1.0)
            if best_distance > 0.4:
                return None

            rule_id = best.get("id", "")
            rule = next((r for r in self._rules if r.get("id") == rule_id), None)
            if not rule:
                return None

            return self._build_result(rule, f"语义检索命中 (距离={best_distance:.3f})")

        except Exception as e:
            logger.debug("[SafetyRAG] 向量检索失败: %s", e)
            return None

    def _build_result(self, rule: Dict[str, Any], reason: str) -> Dict[str, Any]:
        """根据规则构建检测结果。"""
        level = rule.get("level", "low")
        category = rule.get("category", "")
        response_cfg = rule.get("response", {})
        action = response_cfg.get("action", "normal")
        template = response_cfg.get("template", "")
        resources = response_cfg.get("resources", [])

        rendered = self._render_template(template, resources)
        intercept = (level == "high" or action == "intercept")

        return {
            "risk_level": level,
            "risk_type": category,
            "intercept": intercept,
            "response": rendered if intercept else None,
            "reason": reason,
            "rule_id": rule.get("id", ""),
        }

    def _render_template(self, template: str, resources: List[Dict[str, str]]) -> str:
        """渲染模板，替换资源变量。"""
        if not resources:
            return template.replace("{{resources}}", "").strip()

        lines = []
        for r in resources:
            name = r.get("name", "")
            number = r.get("number", "")
            hours = r.get("hours", "")
            if hours:
                lines.append(f"• {name}：{number}（{hours}）")
            else:
                lines.append(f"• {name}：{number}")

        resources_str = "\n".join(lines)
        return template.replace("{{resources}}", resources_str).strip()

    def _safe_result(self) -> Dict[str, Any]:
        """安全返回（无风险）。"""
        return {
            "risk_level": "safe",
            "risk_type": "",
            "intercept": False,
            "response": None,
            "reason": "",
            "rule_id": "",
        }

    def get_stats(self) -> Dict[str, Any]:
        """获取安全系统统计。"""
        return {
            "rules_loaded": len(self._rules),
            "vector_db_ready": self.store is not None and self.store.is_ready,
            "db_path": self.db_path,
            "rules_path": self.rules_path,
            "adapter": self._adapter_name,
        }
