"""Question classifier — maps detected question text into one of 13 human judgment categories.

Source of truth: rules/human_judgment_categories.yaml (13 categories).
Implementation strategy: keyword/regex matching (Tier 0 v1 — to be replaced with LLM later).

The classifier returns:
- a category id from the 13 enum values when the question text contains a marker keyword
- ``None`` when no category matches → caller should treat as Policy Gate R1 BLOCK
  (the question is likely AI 即決領域 and should not be asked).
"""

from __future__ import annotations

import re
from typing import Optional

# Keywords per category. Order matters only for tie-breaking — multi-match is OK.
# Keep keywords scoped to wording from human_judgment_categories.yaml.
CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "parent_goal_change": [
        "親ゴール",
        "Done 条件",
        "Done条件",
        "親ゴール確定",
        "親ゴール変更",
        "親ゴール差し替え",
    ],
    "business_priority": [
        "事業優先",
        "優先順位",
        "稼働配分",
        "リソース配分",
        "先に直す",
        "どのツールを先",
    ],
    "external_communication": [
        "取引先",
        "顧客対応",
        "対応方針",
        "取引条件",
        "交渉",
        "家族",
        "対外的",
    ],
    "cost_commitment": [
        "新規 SaaS",
        "新規SaaS",
        "新規 API 契約",
        "API 契約",
        "外注",
        "業務委託",
        "GPT 追加",
        "GPT追加",
        "API の上限変更",
        "API上限変更",
    ],
    "ux_brand": [
        "ブランドトーン",
        "ブランド トーン",
        "ファーストビュー",
        "訴求文言",
        "料金",
        "ブランド",
        "トーン変更",
    ],
    "privacy_security": [
        "個人情報",
        "機密",
        "外部公開",
        "データ保持",
        "保持期間",
    ],
    "permission_blocked": [
        "GitHub Org",
        "GitHubOrg",
        "GCP コンソール",
        "GCPコンソール",
        "本番デプロイ",
        "権限上不可能",
        "実行不能",
    ],
    "data_destructive": [
        "DB migration",
        "DBmigration",
        "破壊的",
        "batch update",
        "不可逆",
        "本番データ",
    ],
    "security_iam": [
        "API key",
        "APIキー",
        "rotation",
        "OAuth",
        "IAM",
        "GitHub 権限",
        "GitHub権限",
    ],
    "legal_compliance": [
        "法務",
        "規約",
        "コンプライアンス",
        "著作権",
        "利用規約",
    ],
    "public_communication": [
        "LP",
        "顧客向け",
        "営業資料",
        "SNS",
        "公開物",
        "対外発信",
    ],
    "budget_quota": [
        "予算",
        "課金上限",
        "月額予算",
        "上限変更",
    ],
    "hr_evaluation": [
        "評価",
        "採用",
        "人事",
        "スタッフへの指示",
    ],
}


def classify(question_text: str) -> Optional[str]:
    """Return the matched human judgment category id, or None if not classifiable.

    None means the question is likely AI 即決領域 — caller should BLOCK.
    """
    if not question_text:
        return None

    for category, keywords in CATEGORY_KEYWORDS.items():
        for kw in keywords:
            # Case-insensitive substring match for ASCII keywords; exact substring for CJK.
            if re.search(re.escape(kw), question_text, re.IGNORECASE | re.UNICODE):
                return category

    return None


def classify_all(question_text: str) -> list[str]:
    """Return all matched categories (useful for debugging / multi-category inspection)."""
    matched: list[str] = []
    if not question_text:
        return matched

    for category, keywords in CATEGORY_KEYWORDS.items():
        for kw in keywords:
            if re.search(re.escape(kw), question_text, re.IGNORECASE | re.UNICODE):
                matched.append(category)
                break

    return matched
