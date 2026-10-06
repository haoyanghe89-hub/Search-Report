"""Evidence-bounded Chinese report composition.

This module changes presentation only. It never changes claim status, creates
evidence, or promotes diagnostics into factual findings.
"""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict

from marketpulse.investigation.domain.enums import ReportType, ValidationStatus
from marketpulse.investigation.localization import chinese_text, label
from marketpulse.investigation.reporting.writer import (
    COMPACT_FULL_SECTIONS,
    COMPACT_STATUS_SECTIONS,
    ContentClass,
    DraftSection,
    NarrativeUnit,
    ProjectionClaim,
    ProjectionGap,
    ReportDraft,
    SectionStatus,
    WriterProjection,
)

VERSION = "report-writer-zh-v4"


def append_chinese_quant_block(draft, material):
    """Append trusted frozen numbers; never ask a writer/model to produce them."""
    from marketpulse.quant.reporting import append_quant_draft

    return append_quant_draft(draft, material)


GAP_ACTIONS = {
    "EVIDENCE_GAP": "补充直接相关的一手材料与独立证据，重新核对声明及其适用范围。",
    "MISSING_PRIMARY_SOURCE": "寻找原始公告、调查报告或原始数据，并核对发布机构和版本。",
    "INSUFFICIENT_INDEPENDENCE": "补充不依赖同一厂商、公告或通讯稿的第三方独立材料并复测。",
    "INSUFFICIENT_ENTAILMENT": "补充直接支持声明的原文与上下文，必要时缩小声明范围。",
    "MISSING_CAUSAL_SUPPORT": "补充可区分相关性与因果关系的调查证据，并检验替代解释。",
    "MISSING_MECHANISM": "查找事件机制、过程测量或技术调查记录，避免仅凭结果倒推原因。",
    "UNREADABLE_SOURCE": "重新获取可读取的原始文档；无法读取的来源不用于形成确认结论。",
    "SOURCE_CONFLICT": "核对冲突材料的日期、范围与原始出处，保留无法协调的差异。",
    "UNRESOLVED_QUANTITATIVE_CONFLICT": "统一单位、时间、地域和统计对象，保留无法协调的差异。",
    "ATTRIBUTION_UNDER_SUPPORTED": "补充参与方行为与结果之间的证据链，明确责任判断边界。",
    "ANALYSIS_ERROR": "修复分析链路后，基于已归档材料重新执行分析与验证。",
    "OTHER": "补充直接相关的一手材料与独立证据，重新核对声明及其适用范围。",
}

_TECHNICAL_PATTERNS = (
    re.compile(r"\b[A-Za-z][\w.]*?(?:Error|Exception)\b"),
    re.compile(r"\b(?:PDF_IMAGE_CONTENT_NOT_EXTRACTED|REPORT_FINALIZATION_PENDING)\b"),
    re.compile(r"\b(?:[A-Z][A-Z0-9]+_)+[A-Z0-9]+\b"),
    re.compile(r"\bProfile requirement is not met\b", re.IGNORECASE),
    re.compile(r"\bexact ENTAILS judgment\b", re.IGNORECASE),
    re.compile(r"\b(?:traceback|stack trace|diagnostic payload)\b", re.IGNORECASE),
    re.compile(r"^[A-Z][A-Z0-9_]{3,}[：:]"),
)


def _normalized(text: str) -> str:
    value = unicodedata.normalize("NFKC", text).strip().casefold()
    value = re.sub(r"^待补充事项（[^）]+）：", "", value)
    value = re.sub(r"^针对[“\"](.+?)[”\"]：", r"\1", value)
    return re.sub(r"[\W_]+", "", value)


def _unique_texts(values: list[str] | tuple[str, ...]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        clean = chinese_text(value).strip()
        key = _normalized(clean)
        if clean and key and key not in seen:
            seen.add(key)
            result.append(clean)
    return result


def _is_technical(text: str) -> bool:
    return any(pattern.search(text) for pattern in _TECHNICAL_PATTERNS)


def _public_reason(text: str) -> str | None:
    match = re.match(r"^[A-Z][A-Z0-9_]{3,}[：:]\s*(.+)$", text)
    if match and any("\u4e00" <= char <= "\u9fff" for char in match[1]):
        return match[1]
    return None


def _diagnostic_key(text: str) -> str:
    for pattern in _TECHNICAL_PATTERNS:
        match = pattern.search(text)
        if match:
            return _normalized(match.group(0))
    return _normalized(text)


def _status_phrase(claim: ProjectionClaim) -> str:
    return {
        ValidationStatus.VERIFIED: "已验证",
        ValidationStatus.PROBABLE: "很可能成立（不等同于已验证）",
        ValidationStatus.DISPUTED: "存在争议，尚无一致结论",
    }.get(claim.validation_status, "尚未证实，当前证据不足")


def _severity(values: list[str]) -> str:
    rank = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1}
    return max(values, key=lambda value: rank.get(value, 0), default="MEDIUM")


def _group_gaps(gaps: list[ProjectionGap]) -> list[tuple[str, list[ProjectionGap]]]:
    grouped: dict[str, list[ProjectionGap]] = defaultdict(list)
    order: list[str] = []
    for gap in gaps:
        key = gap.gap_type or "OTHER"
        if key not in grouped:
            order.append(key)
        grouped[key].append(gap)
    return [(key, grouped[key]) for key in order]


def chinese_draft(p: WriterProjection) -> ReportDraft:
    status_report = p.report_type is ReportType.INVESTIGATION_STATUS
    ordered_keys = COMPACT_STATUS_SECTIONS if status_report else COMPACT_FULL_SECTIONS
    content: dict[str, list[NarrativeUnit]] = {key: [] for key in ordered_keys}
    seen_units: set[str] = set()

    def add(
        section: str,
        text: str,
        kind: ContentClass = ContentClass.GOVERNANCE_DISCLOSURE,
        refs: tuple[str, ...] = (),
        *,
        semantic_key: str | None = None,
    ) -> None:
        clean = " ".join(text.split()).strip()
        key = semantic_key or _normalized(clean)
        if not clean or not key or key in seen_units:
            return
        seen_units.add(key)
        content[section].append(
            NarrativeUnit(
                unit_key=f"{section.lower()}-{len(content[section]) + 1}",
                section_key=section,
                text=clean,
                content_class=kind,
                claim_refs=tuple(dict.fromkeys(refs)),
            )
        )

    claims_by_key = {claim.stable_key: claim for claim in p.claims}
    verified = [c for c in p.claims if c.validation_status is ValidationStatus.VERIFIED]
    probable = [c for c in p.claims if c.validation_status is ValidationStatus.PROBABLE]
    disputed = [c for c in p.claims if c.validation_status is ValidationStatus.DISPUTED]
    unresolved = [
        c
        for c in p.claims
        if c.validation_status
        not in (ValidationStatus.VERIFIED, ValidationStatus.PROBABLE, ValidationStatus.DISPUTED)
    ]
    supported = sorted((*verified, *probable), key=lambda c: (not c.is_critical, c.stable_key))
    open_gaps = [gap for gap in p.gaps if gap.status in {"OPEN", "IN_PROGRESS"}]

    summary = "EXECUTIVE_STATUS" if status_report else "EXECUTIVE_SUMMARY"
    limits = "BLOCKING_GAPS_AND_LIMITATIONS" if status_report else "LIMITATIONS_AND_RESEARCH_GAPS"

    if p.completion_level:
        add(
            summary,
            f"完整度为“{p.completion_level}”；该标识描述材料覆盖与确认程度，不代表发布许可。",
            semantic_key="summary-completion",
        )

    summary_claims = supported[:3]
    if summary_claims:
        answer = "；".join(
            f"{_status_phrase(claim)}：{chinese_text(claim.statement)}" for claim in summary_claims
        )
        add(
            summary,
            "目前可确认或有较强证据支持的结论是：" + answer + "。",
            ContentClass.FACTUAL_ASSERTION,
            tuple(claim.stable_key for claim in summary_claims),
            semantic_key="summary-supported-answer",
        )
    else:
        add(
            summary,
            "目前尚无通过验证或达到“很可能成立”门槛的关键发现，不能据此确认相关结论。",
            semantic_key="summary-no-supported-answer",
        )

    if disputed or unresolved:
        pending = disputed + unresolved
        topics = _unique_texts(tuple(label(str(claim.claim_type)) for claim in pending))
        topic_summary = "、".join(topics[:4]) or "尚待核查的声明"
        add(
            summary,
            f"尚不能确认的内容共有 {len(pending)} 条，其中 {len(disputed)} 条存在争议、"
            f"{len(unresolved)} 条尚未证实；主要涉及{topic_summary}，具体局限与补证路径见下文。",
            refs=tuple(claim.stable_key for claim in pending),
            semantic_key="summary-unresolved-answer",
        )
    else:
        add(
            summary,
            "当前已评估声明中没有处于争议或未证实状态的项目；结论仍以引用原文的适用范围为边界。",
            semantic_key="summary-no-unresolved",
        )

    add(
        summary,
        f"本报告围绕“{chinese_text(p.investigation_title)}”整理现有材料，共评估 "
        f"{len(p.claims)} 条声明：{len(verified)} 条已验证、{len(probable)} 条很可能成立、"
        f"{len(disputed)} 条存在争议、{len(unresolved)} 条尚未证实。",
        semantic_key="summary-status-counts",
    )
    add(
        summary,
        f"本轮仍有 {len(open_gaps)} 项开放研究缺口和 "
        f"{sum(conflict.status != 'RESOLVED' for conflict in p.conflicts)} 项未解决冲突；"
        "下文只呈现现有证据能够支持的范围。",
        semantic_key="summary-boundary-counts",
    )

    summarized = {claim.stable_key for claim in summary_claims}
    remaining = [claim for claim in supported if claim.stable_key not in summarized]
    themed: dict[str, list[ProjectionClaim]] = defaultdict(list)
    for claim in (*remaining, *disputed):
        themed[str(claim.claim_type)].append(claim)
    for claim_type, claims in themed.items():
        sentences = "；".join(
            f"{_status_phrase(claim)}：{chinese_text(claim.statement)}" for claim in claims
        )
        factual = all(
            claim.validation_status in (ValidationStatus.VERIFIED, ValidationStatus.PROBABLE)
            for claim in claims
        )
        add(
            "CORE_FINDINGS",
            f"在“{label(claim_type)}”主题下，现有材料显示：{sentences}。",
            ContentClass.FACTUAL_ASSERTION if factual else ContentClass.GOVERNANCE_DISCLOSURE,
            tuple(claim.stable_key for claim in claims),
            semantic_key=f"finding-theme:{claim_type}",
        )

    for conflict in p.conflicts:
        if conflict.status == "RESOLVED":
            continue
        add(
            "CORE_FINDINGS",
            f"现有材料还存在一项“{label(conflict.conflict_type)}”冲突，"
            f"严重程度为“{label(conflict.severity)}”，目前“{label(conflict.status)}”；"
            "不同口径或范围的结果可能同时成立，无法协调的分歧继续保留。",
            refs=conflict.claim_refs,
            semantic_key=f"conflict:{conflict.stable_key}",
        )

    evidence_summary = (
        f"本轮记录 {p.source_statistics.total_sources} 个来源、"
        f"{p.source_statistics.independent_families} 个已分组来源家族和 "
        f"{p.source_statistics.evidence_count} 条证据摘录。"
        if p.source_statistics.total_sources
        else "未能获取到可用资料，当前没有可用于形成确认结论的证据基础；"
        "可能原因包括网络或代理不可达、模型服务余额不足，或来源无法访问。"
    )
    add(
        "EVIDENCE_BASE",
        evidence_summary,
        ContentClass.PRESENTATIONAL,
        semantic_key="evidence-statistics",
    )
    add(
        "EVIDENCE_BASE",
        "来源家族用于识别共同出处；来源或证据条数不自动等于独立交叉验证数量，"
        "结论可信度仍取决于原文是否直接支持声明及其限定条件。",
        semantic_key="evidence-credibility-boundary",
    )

    technical: list[str] = []
    gap_reason_keys = {_normalized(chinese_text(gap.reason)) for gap in open_gaps if gap.reason}
    targeted_claims: set[str] = set()
    for gap_type, gaps in _group_gaps(open_gaps):
        raw_reasons = _unique_texts(tuple(gap.reason for gap in gaps))
        technical_reasons = [reason for reason in raw_reasons if _is_technical(reason)]
        technical.extend(technical_reasons)
        reasons = [reason for reason in raw_reasons if not _is_technical(reason)]
        if not reasons:
            reasons = [
                {
                    "UNREADABLE_SOURCE": "相关来源当前缺少可读取的文本内容",
                    "ANALYSIS_ERROR": "分析环节未能形成可供核查的结果",
                }.get(gap_type, f"{label(gap_type)}仍待补充")
            ]
        claim_refs = tuple(
            dict.fromkeys(gap.target_claim_ref for gap in gaps if gap.target_claim_ref)
        )
        targeted_claims.update(claim_refs)
        affected = [claims_by_key[key] for key in claim_refs if key in claims_by_key]
        affected_text = "；".join(chinese_text(claim.statement) for claim in affected)
        impact = (
            f"影响 {len(affected)} 条声明（{affected_text}）"
            if affected
            else f"共记录 {len(gaps)} 项同类缺口"
        )
        reason_text = "；".join(reasons)
        raw_actions = _unique_texts(
            tuple(action for gap in gaps for action in gap.suggested_actions)
        )
        if technical_reasons:
            technical.extend(raw_actions)
            actions: list[str] = []
        else:
            actions = [action for action in raw_actions if not _is_technical(action)]
            technical.extend(action for action in raw_actions if _is_technical(action))
        action = "；".join(actions) or GAP_ACTIONS.get(gap_type, GAP_ACTIONS["OTHER"])
        add(
            limits,
            f"局限（{label(_severity([gap.severity for gap in gaps]))}）："
            f"{label(gap_type)}{impact}。当前缺口：{reason_text}。后续建议：{action}",
            refs=claim_refs,
            semantic_key=f"gap-group:{gap_type}",
        )

    for limitation in p.limitations:
        translated = chinese_text(limitation)
        if _is_technical(limitation):
            technical.append(limitation)
        elif _normalized(translated) not in gap_reason_keys:
            add(
                limits,
                f"局限：{translated} 后续建议：补充对应材料或限定条件后重新核查。",
                semantic_key=f"limitation:{_normalized(translated)}",
            )
    if p.stop_reason:
        if _is_technical(p.stop_reason):
            technical.append(p.stop_reason)
            public_reason = _public_reason(p.stop_reason)
            if public_reason:
                add(
                    limits,
                    f"局限：本轮因“{public_reason}”收尾。"
                    "后续建议：如需扩大覆盖，可选择更长档位继续核查。",
                    semantic_key="public-stop-reason",
                )
        else:
            translated = chinese_text(p.stop_reason)
            add(
                limits,
                f"局限：本轮因“{translated}”收尾。后续建议：排除该限制后基于已归档材料继续调查。",
                semantic_key=f"stop-reason:{_normalized(translated)}",
            )
    if p.unassessed_claims:
        add(
            limits,
            f"局限：另有 {p.unassessed_claims} 条候选声明尚未完成验证。"
            "后续建议：补充对应原文与限定条件后重新核查。",
            semantic_key="unassessed-claims",
        )

    untargeted = [claim for claim in unresolved if claim.stable_key not in targeted_claims]
    if untargeted:
        add(
            limits,
            f"局限：另有 {len(untargeted)} 条声明尚未证实："
            + "；".join(chinese_text(claim.statement) for claim in untargeted)
            + "。后续建议：补充直接支持材料与独立来源后重新验证。",
            refs=tuple(claim.stable_key for claim in untargeted),
            semantic_key="untargeted-unverified-claims",
        )
    if not content[limits] and not p.claims:
        add(
            limits,
            "局限：本轮没有形成可评估声明。后续建议：先补充可读取的一手资料，再重新开展调查。",
            semantic_key="no-assessed-material",
        )

    add(
        "RESEARCH_APPENDIX",
        "调查目标：" + chinese_text(p.investigation_goal),
        ContentClass.PRESENTATIONAL,
        semantic_key="appendix-goal",
    )
    if p.questions:
        add(
            "RESEARCH_APPENDIX",
            "调查问题："
            + "；".join(
                f"{index}. {chinese_text(question)}"
                for index, question in enumerate(p.questions, 1)
            ),
            ContentClass.PRESENTATIONAL,
            semantic_key="appendix-questions",
        )
    method = (
        "方法：本次为内置离线案例回放，使用归档来源及人工整理的声明—摘录映射。"
        if p.execution_provenance == "CURATED_OFFLINE"
        else "方法：研究、分析与验证环节协作处理候选声明，并检查原文定位、"
        "语义关系、来源谱系、独立性与冲突；模型判断本身不构成事实保证。"
    )
    add(
        "RESEARCH_APPENDIX",
        method,
        ContentClass.PRESENTATIONAL,
        semantic_key="appendix-method",
    )

    for diagnostic in _unique_texts(tuple(technical)):
        add(
            "TECHNICAL_APPENDIX",
            diagnostic,
            ContentClass.PRESENTATIONAL,
            semantic_key=f"diagnostic:{_diagnostic_key(diagnostic)}",
        )

    return ReportDraft(
        report_type=p.report_type,
        schema_version=VERSION,
        sections=tuple(
            DraftSection(
                section_key=key,
                status=SectionStatus.CONTENT,
                units=tuple(content[key]),
            )
            for key in ordered_keys
            if content[key]
        ),
    )
