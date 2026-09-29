"""Evidence-bounded Chinese reports; no new facts or model calls are introduced."""

from __future__ import annotations

from marketpulse.investigation.domain.enums import ClaimType, ReportType, ValidationStatus
from marketpulse.investigation.localization import chinese_text, label
from marketpulse.investigation.reporting.writer import (
    FULL_SECTIONS,
    STATUS_SECTIONS,
    ContentClass,
    DraftSection,
    NarrativeUnit,
    ProjectionClaim,
    ReportDraft,
    SectionStatus,
    WriterProjection,
)

VERSION = "report-writer-zh-v2"

TYPE_BOUNDARIES = {
    ClaimType.STATEMENT: (
        "验证对象是来源是否作出该陈述；不能据此将来源的说法直接视为已独立证实的客观事实。"
    ),
    ClaimType.EVENT_FACT: "此项结论限于已验证的事件要素，不自动说明事件原因或责任。",
    ClaimType.QUANTITATIVE: (
        "阅读数字时应同时检查统计时间、地域、样本与单位；不同口径的数据不能直接比较或合并。"
    ),
    ClaimType.CAUSAL: (
        "应区分直接观测、调查机构的因果判断和推测；时间先后或相关性本身不构成因果证明。"
    ),
    ClaimType.IMPACT: (
        "影响结论限于记录中的群体、地域和观察期；短期监测不能直接推断长期个人健康或其他远期结果。"
    ),
    ClaimType.ATTRIBUTION: (
        "责任归属仅限于证据支持的行为与判断，不能扩大为未经证实的动机或法律责任。"
    ),
    ClaimType.INSTITUTIONAL_ACTION: (
        "本项记录机构采取或宣布的行动；行动实施不等于其效果已经得到验证。"
    ),
    ClaimType.ANALYTIC_INFERENCE: (
        "这是基于现有材料的分析推断，需保留前提与不确定性，并接受后续证据修正。"
    ),
}

GAP_ACTIONS = {
    "MISSING_PRIMARY_SOURCE": ("寻找原始公告、调查报告或原始数据，并核对发布机构和版本。"),
    "INSUFFICIENT_INDEPENDENCE": ("追溯报道的共同出处，补充不依赖同一公告或通讯稿的独立材料。"),
    "INSUFFICIENT_ENTAILMENT": (
        "重新读取声明对应的上下文，补充直接支持该声明的原文，必要时缩小声明范围。"
    ),
    "MISSING_CAUSAL_SUPPORT": "补充可区分相关性与因果关系的调查证据，并检验替代解释。",
    "MISSING_MECHANISM": "查找事件机制、过程测量或技术调查记录，避免仅凭结果倒推原因。",
    "UNREADABLE_SOURCE": ("重新获取可读取的原始文档；无法读取的来源不能作为已核验事实的依据。"),
    "SOURCE_CONFLICT": ("逐项核对冲突材料的发布日期、适用范围和原始出处，再判断是否确实互相矛盾。"),
    "UNRESOLVED_QUANTITATIVE_CONFLICT": ("统一单位、时间、地域和统计对象，保留无法协调的差异。"),
    "ATTRIBUTION_UNDER_SUPPORTED": ("补充参与方行为与结果之间的证据链，明确责任判断的适用边界。"),
}


def chinese_draft(p: WriterProjection) -> ReportDraft:
    status_report = p.report_type is ReportType.INVESTIGATION_STATUS
    keys = STATUS_SECTIONS if status_report else FULL_SECTIONS
    content: dict[str, list[NarrativeUnit]] = {key: [] for key in keys}

    def add(
        section: str,
        text: str,
        kind: ContentClass = ContentClass.GOVERNANCE_DISCLOSURE,
        refs: tuple[str, ...] = (),
    ) -> None:
        content[section].append(
            NarrativeUnit(
                unit_key=f"{section.lower()}-{len(content[section]) + 1}",
                section_key=section,
                text=text,
                content_class=kind,
                claim_refs=refs,
            )
        )

    def finding(section: str, claim: ProjectionClaim, *, explain: bool = True) -> None:
        statement = chinese_text(claim.statement)
        prefix = {
            ValidationStatus.VERIFIED: "已验证",
            ValidationStatus.PROBABLE: "可能成立，但证据仍不充分",
            ValidationStatus.DISPUTED: "存在争议，尚无一致结论",
        }.get(claim.validation_status, "尚未证实，当前证据不足")
        kind = (
            ContentClass.FACTUAL_ASSERTION
            if claim.validation_status in (ValidationStatus.VERIFIED, ValidationStatus.PROBABLE)
            else ContentClass.GOVERNANCE_DISCLOSURE
        )
        add(section, f"{prefix}：{statement}", kind, (claim.stable_key,))
        if explain:
            add(
                section,
                f"验证说明：本项属于“{label(claim.claim_type)}”，"
                f"已记录 {claim.supporting_relations} 条支持方向的证据关联、"
                f"{claim.contradicting_relations} 条反证方向的关联。"
                "具体支持范围以引用原文及验证记录为准。",
            )

    verified = [c for c in p.claims if c.validation_status is ValidationStatus.VERIFIED]
    probable = [c for c in p.claims if c.validation_status is ValidationStatus.PROBABLE]
    disputed = [c for c in p.claims if c.validation_status is ValidationStatus.DISPUTED]
    unresolved = [
        c
        for c in p.claims
        if c.validation_status
        not in (ValidationStatus.VERIFIED, ValidationStatus.PROBABLE, ValidationStatus.DISPUTED)
    ]
    open_gaps = [g for g in p.gaps if g.status in ("OPEN", "IN_PROGRESS")]
    summary = "EXECUTIVE_STATUS" if status_report else "EXECUTIVE_SUMMARY"
    sources = "SEARCH_AND_SOURCE_SUMMARY" if status_report else "SOURCE_COVERAGE"
    limits = "BLOCKING_GAPS_AND_LIMITATIONS" if status_report else "LIMITATIONS_AND_RESEARCH_GAPS"
    next_steps = "NEXT_STEPS" if status_report else "CONCLUSIONS_AND_NEXT_STEPS"

    add(
        summary,
        f"本报告围绕“{chinese_text(p.investigation_title)}”整理现有调查结果。"
        f"当前运行状态为“{label(p.terminal_run_status)}”；共记录 {len(p.claims)} 条声明，"
        f"其中 {len(verified)} 条已验证、{len(probable)} 条可能成立、"
        f"{len(disputed)} 条存在争议、{len(unresolved)} 条尚未形成可确认结论。",
    )
    highlights = sorted(verified, key=lambda c: not c.is_critical)[:3]
    if highlights:
        add(summary, "本次调查可优先关注以下已验证发现；每项发现的证据可通过文后引用回查。")
        for claim in highlights:
            finding(summary, claim, explain=False)
    else:
        add(
            summary,
            "本轮尚无通过验证的关键发现。以下内容用于说明调"
            "查进展与证据缺口，不能作为事件已经查明的结论。",
        )
    add(
        summary,
        f"仍有 {len(open_gaps)} 项未完成研究缺口、"
        f"{sum(c.status != 'RESOLVED' for c in p.conflicts)} 项未解决冲突记录。"
        "调查结束、报告生成和获准发布是不同状态；应结合审核结果使用本报告。",
    )

    add("SCOPE_AND_MANDATE", chinese_text(p.investigation_goal), ContentClass.PRESENTATIONAL)
    add(
        "SCOPE_AND_MANDATE",
        "本报告仅覆盖本轮已归档和验证的材料。未获取、无法解析或未进入"
        "分析的内容不属于已核查范围；来源中的陈述与客观事实分别处理。",
    )
    for index, question in enumerate(p.questions, 1):
        add(
            "INVESTIGATION_QUESTIONS",
            f"{index}. {chinese_text(question)}",
            ContentClass.PRESENTATIONAL,
        )
    if not p.questions:
        add("INVESTIGATION_QUESTIONS", "本轮未记录明确的调查问题，不能据此宣称问题覆盖完整。")

    method = (
        "本次为内置离线案例回放，使用归档来源及人工整理的声明—摘录映射，"
        "用于复现验证、引用和发布门禁，不代表模型对陌生事件的联网调查效果。"
        if p.execution_provenance == "CURATED_OFFLINE"
        else "本次由研究、分析与验证环节协作完成。候选声明经过原文定位、语义关系、"
        "来源谱系、独立性与冲突检查；模型判断本身并不构成事实保证。"
    )
    add(sources if status_report else "METHODOLOGY", method)
    if not status_report:
        add(
            "METHODOLOGY",
            "阅读方法：先确认声明的验证状态，再核对引用的原文、时间和统计口"
            "径。“已验证”按声明类型解释；规则评分不能理解为事实成立的概率。",
        )
    add(
        sources,
        f"本轮记录 {p.source_statistics.total_sources} 个来源、"
        f"{p.source_statistics.independent_families} 个已分组的来源家族、"
        f"{p.source_statistics.evidence_count} 条证据摘录。"
        "来源家族是谱系分组，不等于每条声明都获得了同样数量的独立交叉验证。",
    )
    add(
        sources,
        "支持或反证关联的数量不代表独立来源数量；只有通过语义与完整性检查的关系才能形成正式引用。",
    )

    if status_report:
        for claim in verified + probable:
            finding("AVAILABLE_FINDINGS", claim)
    else:
        for index, event in enumerate(p.timeline, 1):
            # Do not promote a stored candidate timestamp into a verified factual claim.
            add(
                "TIMELINE",
                f"时间记录 {index}：{event.event_time or '未记录具体时间'}"
                f"（{label(event.time_precision)}；该时间字段需与原文共同核对）。",
            )
            if event.claim_refs:
                add(
                    "TIMELINE",
                    chinese_text(event.description),
                    ContentClass.FACTUAL_ASSERTION,
                    event.claim_refs,
                )
            else:
                add("TIMELINE", f"尚未证实的时间线候选：{chinese_text(event.description)}")
        for section, claims in (
            ("VERIFIED_FINDINGS", verified),
            ("PROBABLE_FINDINGS", probable),
            ("DISPUTED_FINDINGS", disputed),
        ):
            for claim_type in dict.fromkeys(c.claim_type for c in claims):
                add(section, f"“{label(claim_type)}”的阅读边界：" + TYPE_BOUNDARIES[claim_type])
            for claim in claims:
                finding(section, claim)
        section_types = {
            "QUANTITATIVE_FINDINGS": ClaimType.QUANTITATIVE,
            "IMPACT_SCOPE_AND_ANALYSIS": ClaimType.IMPACT,
            "CAUSAL_AND_MECHANISM_ANALYSIS": ClaimType.CAUSAL,
            "ACTOR_AND_ATTRIBUTION_ASSESSMENT": ClaimType.ATTRIBUTION,
            "REMEDIATION_AND_FOLLOW_UP": ClaimType.INSTITUTIONAL_ACTION,
        }
        for section, claim_type in section_types.items():
            relevant = [
                c for c in p.claims if c.claim_type is claim_type or c.report_section == section
            ]
            if relevant:
                add(section, TYPE_BOUNDARIES[claim_type])
                for claim in relevant:
                    finding(section, claim, explain=False)
        for conflict in p.conflicts:
            add(
                "CONFLICT_ANALYSIS",
                f"冲突类型：{label(conflict.conflict_type)}；"
                f"严重程度：{label(conflict.severity)}；处理状态：{label(conflict.status)}。"
                + chinese_text(conflict.resolution_summary or "No resolution established."),
            )
            for claim in p.claims:
                if claim.stable_key in conflict.claim_refs:
                    finding("CONFLICT_ANALYSIS", claim, explain=False)
            for explanation in conflict.possible_explanations:
                add("CONFLICT_ANALYSIS", "待核对的可能解释：" + chinese_text(explanation))
            add(
                "CONFLICT_ANALYSIS",
                "处理原则：先区分观察时点、采样位置、统计对象及阈值。不同范围"
                "的结果可以同时成立；无法协调的分歧应保留，不能选择性忽略反证。",
            )

    for limitation in p.limitations:
        add(limits, chinese_text(limitation))
    for claim in verified + probable:
        if claim.report_section == "LIMITATIONS_AND_RESEARCH_GAPS":
            finding(limits, claim, explain=False)
    add(
        limits,
        "归档和哈希可以核对引用是否忠于所保存的原文，但不能单独证明来源内容真实"
        "。未发现冲突不等于已排除所有反证；没有证据也不等于证明某种影响不存在。",
    )
    for claim in unresolved + (disputed if status_report else []):
        finding(limits, claim, explain=False)
    for gap in open_gaps:
        add(limits, f"待补充事项（{label(gap.severity)}）：{chinese_text(gap.reason)}")
        add(
            next_steps,
            f"针对“{chinese_text(gap.reason)}”："
            + GAP_ACTIONS.get(
                gap.gap_type, "补充直接相关的一手材料与独立证据，重新核对声明及其适用范围。"
            ),
        )
    if not open_gaps:
        add(
            next_steps,
            "当前未记录开放研究缺口。建议审核者抽查关键引用的原文、时点"
            "及口径，确认没有将来源陈述扩大为事实判断，再决定是否发布。",
        )
    add(
        next_steps,
        f"本轮结论边界：可供核查的已验证声明为 {len(verified)} 条。"
        "尚未证实或存在争议的内容继续保留其限定；新增材料应形成新的调查或报告版本，保留本版证据链以便比较。",
    )

    return ReportDraft(
        report_type=p.report_type,
        schema_version=VERSION,
        sections=tuple(
            DraftSection(
                section_key=key,
                status=SectionStatus.CONTENT
                if content[key]
                else SectionStatus.INSUFFICIENT_SUPPORTED_MATERIAL,
                units=tuple(content[key]),
            )
            for key in keys
        ),
    )
