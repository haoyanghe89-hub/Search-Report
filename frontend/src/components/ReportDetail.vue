<script setup>
import { ref, computed } from 'vue'

const props = defineProps({
  reportData: {
    type: Object,
    default: () => ({})
  }
})

// 判断是否是后端真实报告数据（有 report + sections 结构）
const isBackendReport = computed(() => {
  return props.reportData?.report && Array.isArray(props.reportData.sections)
})

// 后端报告章节中文映射
const sectionTypeLabels = {
  EXECUTIVE_SUMMARY: { title: '执行摘要', num: '1' },
  SCOPE_AND_MANDATE: { title: '范围与任务', num: '2' },
  INVESTIGATION_QUESTIONS: { title: '调查问题', num: '3' },
  METHODOLOGY: { title: '方法学', num: '4' },
  SOURCE_COVERAGE: { title: '来源覆盖', num: '5' },
  TIMELINE: { title: '事件时间线', num: '6' },
  VERIFIED_FINDINGS: { title: '已验证发现', num: '7' },
  PROBABLE_FINDINGS: { title: '高概率发现', num: '8' },
  DISPUTED_FINDINGS: { title: '争议发现', num: '9' },
  QUANTITATIVE_FINDINGS: { title: '定量发现', num: '10' },
  IMPACT_SCOPE_AND_ANALYSIS: { title: '影响范围与分析', num: '11' },
  CAUSAL_AND_MECHANISM_ANALYSIS: { title: '因果机制分析', num: '12' },
  ACTOR_AND_ATTRIBUTION_ASSESSMENT: { title: '主体归因评估', num: '13' },
  CONFLICT_ANALYSIS: { title: '冲突分析', num: '14' },
  REMEDIATION_AND_FOLLOW_UP: { title: '补救与跟进', num: '15' },
  LIMITATIONS_AND_RESEARCH_GAPS: { title: '局限与研究缺口', num: '16' },
  CONCLUSIONS_AND_NEXT_STEPS: { title: '结论与下一步', num: '17' }
}

// 后端报告章节（按 order_index 排序）
const backendSections = computed(() => {
  if (!isBackendReport.value) return []
  return [...props.reportData.sections].sort((a, b) => a.order_index - b.order_index)
})

// 后端报告元数据
const backendReportMeta = computed(() => {
  if (!isBackendReport.value) return null
  return props.reportData.report
})

// 目录展开状态
const expandedSections = ref({})

// 17 章节完整内容
const reportSections = [
  {
    id: 'executive-summary',
    num: '1',
    title: '执行摘要',
    titleEn: 'Executive Summary',
    type: 'summary',
    content: {
      paragraphs: [
        '本报告对 2023 年 2 月 3 日发生在俄亥俄州东巴勒斯坦的 Norfolk Southern 32N 次货运列车脱轨事故进行了系统性调查与证据验证。调查覆盖事故原因、应急响应、环境影响、健康风险及责任归属等多个维度。',
        '调查共收集 10 个有效信息来源，其中 7 个为官方一手来源，提取证据片段 13 条，形成事实声明 8 项，全部经验证达到"已验证"或"高概率"等级。平均置信度为 96%。',
        '核心结论：脱轨事故由过热的车轮轴承发展为轴故障所致；应急处置总体及时得当，受控焚烧决策在当时情境下为合理选择；短期环境影响已得到有效控制，但长期健康影响仍需持续监测。'
      ],
      keyFindings: [
        '事故直接原因：过热车轮轴承导致轴故障',
        '脱轨规模：38 节车厢，含 11 节危险化学品罐车',
        '应急响应：多部门协同，疏散及时',
        '环境监测：空气质量已恢复正常水平',
        '信息冲突：1 处数值差异，已通过权威来源确认解决'
      ]
    }
  },
  {
    id: 'incident-overview',
    num: '2',
    title: '事件概述',
    titleEn: 'Incident Overview',
    type: 'narrative',
    content: {
      paragraphs: [
        '2023 年 2 月 3 日晚约 8 时 54 分，Norfolk Southern 铁路公司运营的 32N 次货运列车在俄亥俄州东巴勒斯坦附近脱轨。列车从伊利诺伊州麦迪逊出发，目的地为宾夕法尼亚州康韦。',
        '列车共计 149 节车厢，其中 38 节在事故中脱轨。脱轨车厢中包括 11 节装载危险化学品的罐车，主要涉及氯乙烯（vinyl chloride）、丙烯酸丁酯（butyl acrylate）、丙烯酸乙基己酯（ethylhexyl acrylate）等物质。',
        '事故发生后，俄亥俄州州长于 2 月 4 日宣布进入紧急状态，并对事故周边 1 英里范围内的居民发布强制疏散令。2 月 6 日，为防止罐车发生灾难性爆炸，应急人员对 5 节氯乙烯罐车实施了受控释放与定向焚烧处置。',
        '2 月 8 日，在空气质量检测达标后，疏散令正式解除，居民获准返回家园。'
      ]
    }
  },
  {
    id: 'timeline',
    num: '3',
    title: '事件时间线',
    titleEn: 'Timeline of Events',
    type: 'timeline',
    content: {
      events: [
        { time: '2023-02-03 20:54', event: '32N 次列车在东巴勒斯坦脱轨', citations: [1, 2] },
        { time: '2023-02-04', event: '俄亥俄州州长宣布紧急状态，发布疏散令', citations: [5, 7] },
        { time: '2023-02-05', event: 'NTSB 启动正式调查', citations: [1] },
        { time: '2023-02-06 15:30', event: '实施氯乙烯受控释放与焚烧', citations: [5, 6] },
        { time: '2023-02-08', event: '疏散令解除，居民获准返家', citations: [3, 4] },
        { time: '2023-02-10', event: 'NTSB 发布初步报告', citations: [1] },
        { time: '2023-03 起', event: '多项独立研究发布，评估环境与健康影响', citations: [8, 9] }
      ]
    }
  },
  {
    id: 'verified-facts',
    num: '4',
    title: '已验证关键事实',
    titleEn: 'Verified Key Findings',
    type: 'findings',
    content: {
      findings: [
        { text: '过热的车轮轴承发展为轴故障，最终导致 32N 次列车脱轨事故发生。这一结论得到了 NTSB 官方报告与 EPA 事故记录的双重印证。', citations: [1, 3] },
        { text: 'Norfolk Southern 32N 次货运列车共计 38 节车厢脱轨，其中 11 节装载危险化学品。', citations: [1, 2, 7] },
        { text: '联邦和州一级应急人员在泄漏事件发生后迅速开展了多介质环境监测工作，涵盖空气质量、水质与土壤污染三个维度。', citations: [3, 4, 5] },
        { text: '为防止罐车发生灾难性爆炸，应急人员对 5 节氯乙烯罐车实施了受控释放与定向焚烧处置。', citations: [1, 6] },
        { text: 'NTSB 负责对此次铁路事故进行正式调查并发布安全建议。', citations: [1, 2] },
        { text: '俄亥俄州州长宣布紧急状态，1 英里范围内居民被强制疏散。', citations: [5, 7] }
      ]
    }
  },
  {
    id: 'cause-analysis',
    num: '5',
    title: '事故原因分析',
    titleEn: 'Cause Analysis',
    type: 'analysis',
    content: {
      paragraphs: [
        '根据 NTSB 初步调查结果，事故的直接原因是过热的车轮轴承发展为灾难性的轴故障。热轴检测系统在脱轨前已检测到轴承温度异常升高，但列车未能在脱轨前安全停下。',
        '关于轴承过热的根本原因，NTSB 仍在进一步调查中。可能的因素包括轴承维护质量、润滑状况、承载负荷及运行速度等。最终结论有待 NTSB 完成完整调查报告。',
        '需要指出的是，本调查的结论基于目前公开的初步报告。随着调查的深入，事故原因可能会有进一步的细化或修正。'
      ],
      subsections: [
        {
          title: '直接原因',
          items: ['车轮轴承过热发展为轴故障', '热轴检测系统报警后列车未能及时停车']
        },
        {
          title: '待确认因素',
          items: ['轴承维护记录与质量', '润滑系统状态', '列车运行速度与载重', '轨道状况']
        }
      ]
    }
  },
  {
    id: 'emergency-response',
    num: '6',
    title: '应急响应评估',
    titleEn: 'Emergency Response Assessment',
    type: 'assessment',
    content: {
      paragraphs: [
        '本次事故的应急响应涉及联邦、州、地方多个层级的应急机构。NTSB 负责事故调查，EPA 负责环境监测与清理，俄亥俄州应急管理局协调州内资源，地方消防部门承担初期响应职责。',
        '从响应时效来看，疏散令在事故发生后约 12 小时内发布，受控焚烧决策在约 67 小时后实施，整体响应符合危险化学品事故处置的时间要求。',
        '信息透明度方面，EPA 定期发布空气与水质监测数据，州长办公室多次举行新闻发布会。但在事故初期，公众对信息的及时性和完整性仍有一定质疑。'
      ]
    }
  },
  {
    id: 'environmental-impact',
    num: '7',
    title: '环境影响评估',
    titleEn: 'Environmental Impact Assessment',
    type: 'assessment',
    content: {
      paragraphs: [
        '事故对环境的影响主要体现在空气、水和土壤三个介质上。EPA 在事故后开展了持续的多介质环境监测工作。',
        '空气质量方面，事故后初期检测到 elevated levels 的氯乙烯及燃烧副产物。随着焚烧结束和扩散，约两周内空气质量恢复到基线水平。',
        '水体方面，部分地表水体检测到化学品污染，主要集中在事故附近的溪流中。EPA 采取了拦截和处理措施，防止污染物进一步扩散。',
        '土壤方面，事故现场周边土壤存在一定程度的污染，主要为 VOCs 和半挥发性化合物。清理工作包括受污染土壤的移除与处置。'
      ]
    }
  },
  {
    id: 'health-impact',
    num: '8',
    title: '健康影响评估',
    titleEn: 'Health Impact Assessment',
    type: 'assessment',
    content: {
      paragraphs: [
        '事故对公众健康的潜在影响是社会关注的焦点。短期来看，高浓度的氯乙烯和燃烧产物可能引起眼睛和呼吸道刺激、头痛、恶心等急性症状。',
        '长期健康影响方面，氯乙烯被列为已知人类致癌物，长期暴露可能增加肝癌等癌症风险。然而，目前的暴露水平数据显示，在疏散解除后，居民暴露水平已降至安全标准以下。',
        '需要强调的是，对于长期健康影响，目前尚缺乏足够的流行病学数据。建议开展长期健康监测研究，以全面评估事故对居民健康的长期影响。这也是本调查识别出的重要研究缺口之一。'
      ]
    }
  },
  {
    id: 'responsibility',
    num: '9',
    title: '责任归属分析',
    titleEn: 'Attribution of Responsibility',
    type: 'analysis',
    content: {
      paragraphs: [
        '根据目前掌握的证据，Norfolk Southern 铁路公司作为列车运营方，对事故负有主要责任。列车的维护状况、运行安全管理体系是事故原因调查的核心。',
        '同时，监管层面也存在需要审视的问题。包括热轴检测系统的有效性、危险化学品运输的安全标准、应急响应预案的完备性等。',
        '需要指出的是，最终的责任认定有待 NTSB 完成完整调查并发布最终报告。本调查的责任分析仅基于目前公开信息的初步判断。'
      ]
    }
  },
  {
    id: 'quantitative-findings',
    num: '10',
    title: '定量发现',
    titleEn: 'Quantitative Findings',
    type: 'findings',
    content: {
      items: [
        { label: '脱轨车厢数', value: '38 节', note: '来源：NTSB 初步报告' },
        { label: '危险化学品罐车', value: '11 节', note: '含氯乙烯、丙烯酸丁酯等' },
        { label: '疏散范围', value: '1 英里', note: '约 500 户居民受影响' },
        { label: '受控焚烧罐车', value: '5 节', note: '氯乙烯罐车' },
        { label: '参与响应机构', value: '6+', note: '联邦、州、地方多部门' },
        { label: '空气恢复时间', value: '约 2 周', note: '基于学术研究估算' }
      ]
    }
  },
  {
    id: 'source-conflicts',
    num: '11',
    title: '来源冲突与差异',
    titleEn: 'Source Conflicts and Discrepancies',
    type: 'conflict',
    content: {
      paragraphs: [
        '本次调查共识别 1 处信息冲突，已通过来源优先级评估解决。',
        '冲突点：不同来源对脱轨车厢数量的报道存在差异。部分早期新闻报道称 36 节，NTSB 初步报告称 38 节。',
        '解决方式：以 NTSB 官方调查报告为权威来源，采纳 38 节的数据。可能原因包括统计口径差异（是否包含守车等）和信息更新时间不同。'
      ]
    }
  },
  {
    id: 'limitations',
    num: '12',
    title: '研究局限与证据缺口',
    titleEn: 'Limitations and Evidence Gaps',
    type: 'limitations',
    content: {
      paragraphs: [
        '本调查存在以下局限和证据缺口，在解读报告结论时应予以考虑：'
      ],
      gaps: [
        { title: '长期健康影响数据不足', severity: '高', description: '现有研究主要关注短期空气质量和急性健康影响，对长期癌症风险、慢性健康效应的数据和研究仍然有限。' },
        { title: '地下水污染范围不明确', severity: '中', description: '土壤污染数据较为充分，但地下水污染的迁移路径、影响范围和持续时间仍需进一步监测和研究。' },
        { title: '事故根本原因待确认', severity: '中', description: '目前仅有 NTSB 初步报告，事故根本原因的完整调查结论尚未发布。' },
        { title: '二手来源类型单一', severity: '低', description: '二手来源均为学术论文类，缺乏新闻媒体、行业报告等其他类型来源的交叉验证。' }
      ]
    }
  },
  {
    id: 'recommendations',
    num: '13',
    title: '政策与监管建议',
    titleEn: 'Policy and Regulatory Recommendations',
    type: 'recommendations',
    content: {
      recommendations: [
        { title: '加强危险化学品运输安全监管', detail: '建议对高风险危险化学品的铁路运输实施更严格的安全标准，包括车辆维护、路线选择、速度限制等方面。' },
        { title: '改进热轴检测系统', detail: '建议评估现有热轴检测系统的有效性，探索更先进的监测技术，提高故障预警的及时性和准确性。' },
        { title: '完善环境应急响应预案', detail: '建议针对铁路危险化学品泄漏事故，制定更完善的环境应急响应预案，明确各部门职责和协调机制。' },
        { title: '建立长期健康监测机制', detail: '建议在重大危险化学品泄漏事故后，建立居民长期健康监测和登记制度，跟踪评估长期健康影响。' },
        { title: '提升应急信息透明度', detail: '建议建立标准化的应急信息发布机制，确保公众及时、准确地获取事故信息和防护指导。' }
      ]
    }
  },
  {
    id: 'conclusion',
    num: '14',
    title: '结论',
    titleEn: 'Conclusion',
    type: 'summary',
    content: {
      paragraphs: [
        '本调查基于 10 个有效来源、13 条证据片段，对 2023 年东巴勒斯坦列车脱轨事故进行了系统性的事实核查与验证。8 项核心事实声明全部达到"已验证"或"高概率"等级，平均置信度 96%。',
        '事故直接原因明确：过热车轮轴承发展为轴故障。应急响应总体得当：疏散及时、处置决策合理、环境监测全面。短期环境影响已得到有效控制。',
        '同时，本调查也识别出重要的证据缺口，包括长期健康影响数据不足、地下水污染范围不明确、事故根本原因有待最终调查结论等。这些缺口需要在后续研究和调查中逐步填补。',
        '建议从安全监管、技术改进、应急管理、健康监测、信息透明等多个层面吸取教训，完善危险化学品运输安全体系。'
      ]
    }
  },
  {
    id: 'methodology',
    num: '15',
    title: '方法学说明',
    titleEn: 'Methodology',
    type: 'methodology',
    content: {
      paragraphs: [
        '本调查采用多智能体协作的系统化调查方法，包括规划、信息收集、分析研判、证据验证、报告编纂五个阶段。',
        '证据验证采用多源交叉验证策略，对每项声明至少寻找两个独立来源进行印证。验证标准包括来源权威性、证据蕴含度、来源独立性等多个维度。',
        '来源分级：官方一手来源（政府报告、官方声明、监管机构文件）优先级最高；学术研究为二手来源，提供补充视角和深度分析。'
      ]
    }
  },
  {
    id: 'glossary',
    num: '16',
    title: '术语表',
    titleEn: 'Glossary',
    type: 'glossary',
    content: {
      terms: [
        { term: '氯乙烯（Vinyl Chloride）', definition: '一种用于制造塑料的工业化学品，易燃，被列为已知人类致癌物。' },
        { term: 'NTSB', definition: '国家运输安全委员会（National Transportation Safety Board），美国负责运输事故调查的联邦机构。' },
        { term: 'EPA', definition: '环境保护署（Environmental Protection Agency），美国负责环境保护的联邦机构。' },
        { term: '受控焚烧（Controlled Burn）', definition: '在受控条件下有意点燃危险物质，以减少爆炸风险或加速污染物降解的应急处置措施。' },
        { term: '热轴检测（Hot Box Detection）', definition: '通过红外传感器等技术监测列车轴承温度，及时发现过热轴承的安全监测系统。' },
        { term: 'VOCs', definition: '挥发性有机化合物（Volatile Organic Compounds），一类易挥发的有机化学物质的总称。' }
      ]
    }
  },
  {
    id: 'references',
    num: '17',
    title: '参考文献',
    titleEn: 'References',
    type: 'references'
  }
]

// 切换章节展开
function toggleSection(id) {
  expandedSections.value[id] = !expandedSections.value[id]
}

// 跳转到章节
function scrollToSection(id) {
  const el = document.getElementById(`section-${id}`)
  if (el) {
    el.scrollIntoView({ behavior: 'smooth', block: 'start' })
    expandedSections.value[id] = true
  }
}
</script>

<template>
  <div class="report-detail">
    <!-- 后端真实报告 -->
    <template v-if="isBackendReport">
      <!-- 封面 -->
      <div class="report-cover">
        <div class="cover-badge">
          <span class="badge-text">调查报告</span>
          <span class="badge-version">v{{ backendReportMeta.version }}</span>
        </div>
        <h1 class="cover-title">
          {{ backendReportMeta.report_type === 'FULL_INVESTIGATION' ? '完整调查报告' : '调查状态报告' }}
        </h1>
        <div class="cover-subtitle">
          Report ID: {{ backendReportMeta.report_id }}
        </div>
        <div class="cover-meta">
          <div class="meta-item">
            <span class="meta-label">调查编号</span>
            <span class="meta-value">{{ backendReportMeta.investigation_id }}</span>
          </div>
          <div class="meta-item">
            <span class="meta-label">运行编号</span>
            <span class="meta-value">{{ backendReportMeta.run_id }}</span>
          </div>
          <div class="meta-item">
            <span class="meta-label">发布状态</span>
            <span class="meta-value" :class="backendReportMeta.release_status?.toLowerCase()">{{ backendReportMeta.release_status }}</span>
          </div>
        </div>
      </div>

      <div class="report-body">
        <!-- 目录 -->
        <div class="toc-section">
          <h2 class="toc-title">
            <span class="toc-num">目</span>
            录
          </h2>
          <ol class="toc-list">
            <li
              v-for="section in backendSections"
              :key="section.section_id"
              class="toc-item"
            >
              <button class="toc-link" @click="scrollToSection(section.section_id)">
                <span class="toc-section-num">{{ sectionTypeLabels[section.section_type]?.num || section.order_index + 1 }}</span>
                <span class="toc-section-title">{{ sectionTypeLabels[section.section_type]?.title || section.section_type }}</span>
                <span class="toc-dots"></span>
              </button>
            </li>
          </ol>
        </div>

        <!-- 各章节 -->
        <div class="sections">
          <section
            v-for="section in backendSections"
            :key="section.section_id"
            :id="`section-${section.section_id}`"
            class="report-section backend"
          >
            <div class="section-header" @click="toggleSection(section.section_id)">
              <div class="section-num-label">
                <span class="num">{{ sectionTypeLabels[section.section_type]?.num || section.order_index + 1 }}</span>
              </div>
              <div class="section-titles">
                <h2 class="section-title">{{ sectionTypeLabels[section.section_type]?.title || section.section_type }}</h2>
                <p class="section-title-en">{{ section.section_type }}</p>
              </div>
              <span class="toggle-icon">{{ expandedSections[section.section_id] ? '−' : '+' }}</span>
            </div>

            <div
              v-show="expandedSections[section.section_id] !== false"
              class="section-content"
            >
              <!-- 章节状态 -->
              <div v-if="section.content?.status" class="section-status">
                状态：{{ section.content.status }}
              </div>

              <!-- 内容单元 -->
              <div
                v-for="(unit, i) in (section.content?.units || [])"
                :key="i"
                class="content-unit"
                :class="unit.content_class?.toLowerCase().replace(/_/g, '-')"
              >
                <p class="unit-text">{{ unit.text }}</p>
                <div v-if="unit.claim_refs?.length" class="unit-refs">
                  <span class="ref-label">关联声明：</span>
                  <span v-for="ref in unit.claim_refs" :key="ref" class="ref-tag">{{ ref }}</span>
                </div>
              </div>

              <!-- 无内容提示 -->
              <div v-if="!section.content?.units?.length" class="empty-section">
                本章节暂无内容
              </div>
            </div>
          </section>
        </div>
      </div>
    </template>

    <!-- Mock 报告（后端无数据时显示） -->
    <template v-else>
    <!-- 报告封面 -->
    <div class="report-cover">
      <div class="cover-badge">
        <span class="badge-text">调查报告</span>
        <span class="badge-version">第 1 版</span>
      </div>
      <h1 class="cover-title">
        2023 年俄亥俄州东巴勒斯坦<br>
        <em>列车脱轨事故</em>调查
      </h1>
      <div class="cover-subtitle">
        East Palestine Train Derailment Investigation Report
      </div>
      <div class="cover-meta">
        <div class="meta-item">
          <span class="meta-label">报告编号</span>
          <span class="meta-value">REP-EP-2023-001</span>
        </div>
        <div class="meta-item">
          <span class="meta-label">发布日期</span>
          <span class="meta-value">2026 年 9 月 22 日</span>
        </div>
        <div class="meta-item">
          <span class="meta-label">验证状态</span>
          <span class="meta-value verified">已验证 · 已发布</span>
        </div>
      </div>
    </div>

    <div class="report-body">
      <!-- 目录 -->
      <div class="toc-section">
        <h2 class="toc-title">
          <span class="toc-num">目</span>
          录
        </h2>
        <ol class="toc-list">
          <li
            v-for="section in reportSections"
            :key="section.id"
            class="toc-item"
          >
            <button class="toc-link" @click="scrollToSection(section.id)">
              <span class="toc-section-num">{{ section.num }}</span>
              <span class="toc-section-title">{{ section.title }}</span>
              <span class="toc-dots"></span>
            </button>
          </li>
        </ol>
      </div>

      <!-- 各章节 -->
      <div class="sections">
        <section
          v-for="section in reportSections"
          :key="section.id"
          :id="`section-${section.id}`"
          class="report-section"
          :class="section.type"
        >
          <div class="section-header" @click="toggleSection(section.id)">
            <div class="section-num-label">
              <span class="num">{{ section.num }}</span>
            </div>
            <div class="section-titles">
              <h2 class="section-title">{{ section.title }}</h2>
              <p class="section-title-en">{{ section.titleEn }}</p>
            </div>
            <span class="toggle-icon">{{ expandedSections[section.id] ? '−' : '+' }}</span>
          </div>

          <div
            v-show="expandedSections[section.id] !== false"
            class="section-content"
          >
            <!-- 执行摘要 -->
            <template v-if="section.type === 'summary'">
              <div v-for="(p, i) in section.content.paragraphs" :key="i" class="section-paragraph">
                {{ p }}
              </div>
              <div class="key-findings-box">
                <h4>核心发现</h4>
                <ul>
                  <li v-for="(f, i) in section.content.keyFindings" :key="i">{{ f }}</li>
                </ul>
              </div>
            </template>

            <!-- 叙述类 -->
            <template v-else-if="section.type === 'narrative' || section.type === 'analysis' || section.type === 'assessment'">
              <div v-for="(p, i) in section.content.paragraphs" :key="i" class="section-paragraph">
                {{ p }}
              </div>
              <div v-if="section.content.subsections" class="subsections">
                <div v-for="(sub, i) in section.content.subsections" :key="i" class="subsection">
                  <h4 class="subsection-title">{{ sub.title }}</h4>
                  <ul class="subsection-list">
                    <li v-for="(item, j) in sub.items" :key="j">{{ item }}</li>
                  </ul>
                </div>
              </div>
            </template>

            <!-- 时间线 -->
            <template v-else-if="section.type === 'timeline'">
              <div class="report-timeline">
                <div
                  v-for="(event, i) in section.content.events"
                  :key="i"
                  class="timeline-item"
                >
                  <div class="tl-time">{{ event.time }}</div>
                  <div class="tl-event-text">
                    {{ event.event }}
                    <span
                      v-for="cite in event.citations"
                      :key="cite"
                      class="cite"
                    >[{{ cite }}]</span>
                  </div>
                </div>
              </div>
            </template>

            <!-- 发现类 -->
            <template v-else-if="section.type === 'findings'">
              <div
                v-for="(finding, i) in section.content.findings"
                :key="i"
                class="finding-block"
              >
                <p>
                  {{ finding.text }}
                  <span
                    v-for="cite in finding.citations"
                    :key="cite"
                    class="cite"
                  >[{{ cite }}]</span>
                </p>
              </div>
            </template>

            <!-- 定量发现 -->
            <template v-else-if="section.id === 'quantitative-findings'">
              <div class="quant-grid">
                <div
                  v-for="(item, i) in section.content.items"
                  :key="i"
                  class="quant-item"
                >
                  <div class="quant-value">{{ item.value }}</div>
                  <div class="quant-label">{{ item.label }}</div>
                  <div class="quant-note">{{ item.note }}</div>
                </div>
              </div>
            </template>

            <!-- 冲突类 -->
            <template v-else-if="section.type === 'conflict'">
              <div v-for="(p, i) in section.content.paragraphs" :key="i" class="section-paragraph">
                {{ p }}
              </div>
            </template>

            <!-- 局限类 -->
            <template v-else-if="section.type === 'limitations'">
              <div v-for="(p, i) in section.content.paragraphs" :key="i" class="section-paragraph">
                {{ p }}
              </div>
              <div class="gaps-grid">
                <div
                  v-for="(gap, i) in section.content.gaps"
                  :key="i"
                  class="gap-card"
                >
                  <div class="gap-head">
                    <span class="gap-title">{{ gap.title }}</span>
                    <span class="gap-severity">{{ gap.severity }}</span>
                  </div>
                  <p class="gap-desc">{{ gap.description }}</p>
                </div>
              </div>
            </template>

            <!-- 建议类 -->
            <template v-else-if="section.type === 'recommendations'">
              <div class="rec-list">
                <div
                  v-for="(rec, i) in section.content.recommendations"
                  :key="i"
                  class="rec-item"
                >
                  <div class="rec-num">{{ i + 1 }}</div>
                  <div class="rec-content">
                    <h4 class="rec-title">{{ rec.title }}</h4>
                    <p class="rec-detail">{{ rec.detail }}</p>
                  </div>
                </div>
              </div>
            </template>

            <!-- 方法学 -->
            <template v-else-if="section.type === 'methodology'">
              <div v-for="(p, i) in section.content.paragraphs" :key="i" class="section-paragraph">
                {{ p }}
              </div>
            </template>

            <!-- 术语表 -->
            <template v-else-if="section.type === 'glossary'">
              <div class="glossary-list">
                <div
                  v-for="(item, i) in section.content.terms"
                  :key="i"
                  class="glossary-item"
                >
                  <dt class="glossary-term">{{ item.term }}</dt>
                  <dd class="glossary-def">{{ item.definition }}</dd>
                </div>
              </div>
            </template>

            <!-- 参考文献 -->
            <template v-else-if="section.type === 'references'">
              <div class="refs-placeholder">
                <p>参考文献完整列表见「来源」章节。</p>
              </div>
            </template>
          </div>
        </section>
      </div>
    </div>
    </template>
  </div>
</template>

<style scoped>
.report-detail {
  max-width: 780px;
  margin: 0 auto;
}

/* 封面 */
.report-cover {
  text-align: center;
  padding: 60px 40px 48px;
  margin-bottom: 48px;
  background: white;
  box-shadow:
    0 1px 2px var(--paper-shadow),
    0 16px 48px rgba(60, 45, 20, 0.1);
  position: relative;
}

.report-cover::before {
  content: '';
  position: absolute;
  top: 24px;
  bottom: 24px;
  left: 28px;
  width: 1px;
  background: linear-gradient(180deg, transparent, var(--paper-edge) 10%, var(--paper-edge) 90%, transparent);
}

.report-cover::after {
  content: '';
  position: absolute;
  top: 24px;
  bottom: 24px;
  right: 28px;
  width: 1px;
  background: linear-gradient(180deg, transparent, var(--paper-edge) 10%, var(--paper-edge) 90%, transparent);
}

.cover-badge {
  display: inline-flex;
  align-items: center;
  gap: 12px;
  padding: 8px 20px;
  border: 1px solid var(--accent-line);
  margin-bottom: 32px;
}

.badge-text {
  font-family: var(--font-mono);
  font-size: 11px;
  letter-spacing: 0.15em;
  color: var(--accent);
  text-transform: uppercase;
}

.badge-version {
  font-family: var(--font-serif);
  font-style: italic;
  font-size: 12px;
  color: var(--ink-muted);
  padding-left: 12px;
  border-left: 1px solid var(--paper-edge);
}

.cover-title {
  font-family: var(--font-display);
  font-size: 36px;
  font-weight: 600;
  line-height: 1.25;
  color: var(--ink-black);
  margin-bottom: 16px;
  letter-spacing: -0.01em;
}

.cover-title em {
  font-style: italic;
  font-weight: 400;
  color: var(--ink-soft);
}

.cover-subtitle {
  font-family: var(--font-serif);
  font-style: italic;
  font-size: 16px;
  color: var(--ink-muted);
  margin-bottom: 40px;
  padding-bottom: 24px;
  border-bottom: 1px solid var(--paper-edge);
  position: relative;
}

.cover-subtitle::after {
  content: '';
  position: absolute;
  bottom: -5px;
  left: 50%;
  transform: translateX(-50%);
  width: 40px;
  height: 1px;
  background: var(--accent);
}

.cover-meta {
  display: flex;
  justify-content: center;
  gap: 48px;
}

.meta-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
  text-align: center;
}

.cover-meta .meta-label {
  font-family: var(--font-mono);
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.12em;
  color: var(--ink-faint);
}

.cover-meta .meta-value {
  font-family: var(--font-serif);
  font-size: 14px;
  font-weight: 600;
  color: var(--ink-deep);
}

.cover-meta .meta-value.verified {
  color: var(--status-verified);
}

/* 报告主体 */
.report-body {
  background: white;
  padding: 48px 56px;
  box-shadow:
    0 1px 2px var(--paper-shadow),
    0 12px 40px rgba(60, 45, 20, 0.08);
}

/* 目录 */
.toc-section {
  margin-bottom: 48px;
  padding-bottom: 32px;
  border-bottom: 1px solid var(--paper-edge);
}

.toc-title {
  font-family: var(--font-display);
  font-size: 22px;
  font-weight: 600;
  color: var(--ink-black);
  margin-bottom: 24px;
  text-align: center;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
}

.toc-num {
  font-family: var(--font-serif);
  font-style: italic;
  font-weight: 400;
  color: var(--accent);
}

.toc-list {
  list-style: none;
  padding: 0;
  columns: 2;
  column-gap: 32px;
}

.toc-item {
  break-inside: avoid;
  margin-bottom: 8px;
}

.toc-link {
  display: flex;
  align-items: baseline;
  gap: 8px;
  width: 100%;
  padding: 6px 0;
  background: none;
  border: none;
  cursor: pointer;
  text-align: left;
  transition: all 0.3s var(--ease-out);
  position: relative;
}

.toc-link:hover {
  color: var(--accent);
  padding-left: 8px;
}

.toc-section-num {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--accent);
  min-width: 20px;
  flex-shrink: 0;
}

.toc-section-title {
  font-family: var(--font-serif);
  font-size: 14px;
  color: var(--ink-deep);
  transition: color 0.3s var(--ease-out);
}

.toc-link:hover .toc-section-title {
  color: var(--accent);
}

.toc-dots {
  flex: 1;
  border-bottom: 1px dotted var(--paper-edge);
  margin-bottom: 3px;
  margin-left: 4px;
}

/* 章节 */
.report-section {
  margin-bottom: 32px;
  border-bottom: 1px solid var(--paper-edge);
  padding-bottom: 32px;
}

.report-section:last-child {
  border-bottom: none;
  margin-bottom: 0;
  padding-bottom: 0;
}

.section-header {
  display: flex;
  align-items: flex-start;
  gap: 20px;
  cursor: pointer;
  padding: 8px 0;
  transition: background 0.3s var(--ease-out);
}

.section-header:hover {
  background: var(--accent-pale);
  margin: 0 -16px;
  padding: 8px 16px;
}

.section-num-label {
  width: 44px;
  height: 44px;
  border-radius: 50%;
  background: var(--paper-warm);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  transition: all 0.3s var(--ease-out);
}

.section-header:hover .section-num-label {
  background: var(--accent-pale);
}

.section-num-label .num {
  font-family: var(--font-display);
  font-style: italic;
  font-weight: 600;
  font-size: 18px;
  color: var(--accent);
}

.section-titles {
  flex: 1;
  min-width: 0;
}

.section-title {
  font-family: var(--font-display);
  font-size: 22px;
  font-weight: 600;
  color: var(--ink-black);
  margin-bottom: 4px;
}

.section-title-en {
  font-family: var(--font-serif);
  font-style: italic;
  font-size: 13px;
  color: var(--ink-faint);
  margin: 0;
}

.toggle-icon {
  font-size: 20px;
  color: var(--ink-faint);
  font-weight: 300;
  transition: all 0.3s var(--ease-out);
  flex-shrink: 0;
  width: 24px;
  text-align: center;
}

.section-header:hover .toggle-icon {
  color: var(--accent);
}

.section-content {
  padding: 16px 0 0 64px;
  animation: fadeSlide 0.4s var(--ease-out);
}

@keyframes fadeSlide {
  from {
    opacity: 0;
    transform: translateY(-8px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.section-paragraph {
  font-family: var(--font-serif);
  font-size: 15px;
  line-height: 1.9;
  color: var(--ink-deep);
  margin-bottom: 16px;
  text-align: justify;
}

.section-paragraph:last-child {
  margin-bottom: 0;
}

.cite {
  display: inline-block;
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--accent);
  cursor: pointer;
  vertical-align: super;
  line-height: 0;
  padding: 0 2px;
  margin: 0 1px;
  transition: all 0.25s var(--ease-out);
  position: relative;
}

.cite::after {
  content: '';
  position: absolute;
  bottom: -2px;
  left: 0;
  width: 100%;
  height: 1px;
  background: var(--accent);
  transform: scaleX(0);
  transform-origin: left;
  transition: transform 0.35s var(--ease-out);
}

.cite:hover::after {
  transform: scaleX(1);
}

/* 核心发现框 */
.key-findings-box {
  margin: 24px 0;
  padding: 24px 28px;
  background: var(--paper-warm);
  border-left: 3px solid var(--accent);
}

.key-findings-box h4 {
  font-family: var(--font-display);
  font-size: 16px;
  font-weight: 600;
  color: var(--ink-deep);
  margin-bottom: 12px;
}

.key-findings-box ul {
  list-style: none;
  padding: 0;
  margin: 0;
}

.key-findings-box li {
  padding: 6px 0 6px 20px;
  position: relative;
  font-family: var(--font-serif);
  font-size: 14px;
  color: var(--ink-soft);
  line-height: 1.6;
}

.key-findings-box li::before {
  content: '✓';
  position: absolute;
  left: 0;
  color: var(--status-verified);
  font-size: 12px;
}

/* 子章节 */
.subsections {
  margin-top: 20px;
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 20px;
}

.subsection {
  padding: 16px 20px;
  background: var(--paper-warm);
}

.subsection-title {
  font-family: var(--font-serif);
  font-size: 14px;
  font-weight: 600;
  color: var(--ink-deep);
  margin-bottom: 8px;
}

.subsection-list {
  list-style: none;
  padding: 0;
  margin: 0;
}

.subsection-list li {
  padding: 4px 0 4px 16px;
  position: relative;
  font-family: var(--font-serif);
  font-size: 13px;
  color: var(--ink-soft);
  line-height: 1.6;
}

.subsection-list li::before {
  content: '—';
  position: absolute;
  left: 0;
  color: var(--accent);
  font-size: 11px;
}

/* 报告内时间线 */
.report-timeline {
  position: relative;
  padding-left: 24px;
}

.report-timeline::before {
  content: '';
  position: absolute;
  left: 6px;
  top: 4px;
  bottom: 4px;
  width: 1px;
  background: var(--paper-edge);
}

.timeline-item {
  position: relative;
  padding-bottom: 20px;
  display: flex;
  gap: 20px;
}

.timeline-item:last-child {
  padding-bottom: 0;
}

.timeline-item::before {
  content: '';
  position: absolute;
  left: -21px;
  top: 6px;
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: var(--paper-base);
  border: 1.5px solid var(--accent);
}

.tl-time {
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--accent);
  white-space: nowrap;
  min-width: 140px;
}

.tl-event-text {
  font-family: var(--font-serif);
  font-size: 14px;
  color: var(--ink-deep);
  line-height: 1.7;
}

/* 发现块 */
.finding-block {
  margin-bottom: 16px;
  padding: 16px 20px;
  background: var(--paper-base);
  border-left: 2px solid var(--status-verified);
  transition: all 0.35s var(--ease-out);
}

.finding-block:hover {
  background: var(--accent-pale);
  border-left-color: var(--accent);
}

.finding-block p {
  font-family: var(--font-serif);
  font-size: 14px;
  line-height: 1.85;
  color: var(--ink-deep);
  margin: 0;
}

/* 定量发现 */
.quant-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
}

.quant-item {
  padding: 24px 20px;
  text-align: center;
  background: var(--paper-warm);
  border: 1px solid var(--paper-edge);
  transition: all 0.4s var(--ease-out);
}

.quant-item:hover {
  transform: translateY(-2px);
  border-color: var(--accent-line);
  box-shadow: 0 8px 24px var(--paper-shadow);
}

.quant-value {
  font-family: var(--font-display);
  font-size: 28px;
  font-weight: 600;
  color: var(--ink-black);
  margin-bottom: 8px;
  font-variant-numeric: oldstyle-nums;
}

.quant-label {
  font-family: var(--font-serif);
  font-size: 13px;
  font-weight: 600;
  color: var(--ink-deep);
  margin-bottom: 4px;
}

.quant-note {
  font-family: var(--font-serif);
  font-style: italic;
  font-size: 11px;
  color: var(--ink-faint);
}

/* 缺口网格 */
.gaps-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  margin-top: 20px;
}

.gap-card {
  padding: 20px;
  background: var(--paper-warm);
  border: 1px solid var(--paper-edge);
  transition: all 0.4s var(--ease-out);
}

.gap-card:hover {
  border-color: var(--accent-line);
  transform: translateY(-2px);
  box-shadow: 0 8px 20px var(--paper-shadow);
}

.gap-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 10px;
}

.gap-title {
  font-family: var(--font-serif);
  font-size: 15px;
  font-weight: 600;
  color: var(--ink-deep);
}

.gap-severity {
  font-family: var(--font-mono);
  font-size: 10px;
  padding: 2px 8px;
  border: 1px solid var(--status-disputed);
  color: var(--status-disputed);
  border-radius: 2px;
}

.gap-desc {
  font-family: var(--font-serif);
  font-size: 13px;
  line-height: 1.7;
  color: var(--ink-soft);
  margin: 0;
}

/* 建议列表 */
.rec-list {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.rec-item {
  display: flex;
  gap: 20px;
  padding: 20px;
  background: var(--paper-warm);
  border-left: 3px solid var(--accent);
  transition: all 0.4s var(--ease-out);
}

.rec-item:hover {
  transform: translateX(4px);
  background: var(--accent-pale);
}

.rec-num {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  background: var(--paper-base);
  display: flex;
  align-items: center;
  justify-content: center;
  font-family: var(--font-display);
  font-style: italic;
  font-weight: 600;
  font-size: 18px;
  color: var(--accent);
  flex-shrink: 0;
}

.rec-content {
  flex: 1;
}

.rec-title {
  font-family: var(--font-serif);
  font-size: 16px;
  font-weight: 600;
  color: var(--ink-deep);
  margin-bottom: 8px;
}

.rec-detail {
  font-family: var(--font-serif);
  font-size: 14px;
  line-height: 1.7;
  color: var(--ink-soft);
  margin: 0;
}

/* 术语表 */
.glossary-list {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.glossary-item {
  display: flex;
  gap: 20px;
  padding-bottom: 16px;
  border-bottom: 1px solid var(--paper-edge);
}

.glossary-item:last-child {
  border-bottom: none;
  padding-bottom: 0;
}

.glossary-term {
  font-family: var(--font-serif);
  font-weight: 600;
  font-size: 14px;
  color: var(--ink-deep);
  min-width: 180px;
  flex-shrink: 0;
}

.glossary-def {
  font-family: var(--font-serif);
  font-size: 14px;
  line-height: 1.7;
  color: var(--ink-soft);
  margin: 0;
}

.refs-placeholder {
  text-align: center;
  padding: 40px;
  font-style: italic;
  color: var(--ink-faint);
}

/* 后端报告内容单元 */
.section-status {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--ink-muted);
  margin-bottom: 16px;
  padding: 4px 10px;
  background: var(--paper-warm);
  display: inline-block;
}

.content-unit {
  margin-bottom: 16px;
  padding: 12px 16px;
  background: var(--paper-base);
  border-left: 2px solid var(--paper-edge);
  transition: all 0.3s var(--ease-out);
}

.content-unit:hover {
  background: var(--accent-pale);
  border-left-color: var(--accent);
}

.content-unit.factual-assertion {
  border-left-color: var(--status-verified);
}

.content-unit.analytical-synthesis {
  border-left-color: #7c3aed;
}

.content-unit.governance-disclosure {
  border-left-color: #f59e0b;
}

.unit-text {
  font-family: var(--font-serif);
  font-size: 14px;
  line-height: 1.85;
  color: var(--ink-deep);
  margin: 0;
}

.unit-refs {
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px solid var(--paper-edge);
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
}

.ref-label {
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--ink-muted);
}

.ref-tag {
  font-family: var(--font-mono);
  font-size: 10px;
  padding: 2px 6px;
  background: white;
  border: 1px solid var(--paper-edge);
  color: var(--accent);
}

.empty-section {
  font-family: var(--font-serif);
  font-style: italic;
  font-size: 13px;
  color: var(--ink-faint);
  text-align: center;
  padding: 20px;
}

@media (max-width: 900px) {
  .report-body {
    padding: 32px 24px;
  }

  .toc-list {
    columns: 1;
  }

  .subsections {
    grid-template-columns: 1fr;
  }

  .quant-grid {
    grid-template-columns: repeat(2, 1fr);
  }

  .gaps-grid {
    grid-template-columns: 1fr;
  }

  .section-content {
    padding-left: 0;
    padding-top: 12px;
  }

  .cover-meta {
    flex-direction: column;
    gap: 16px;
  }
}
</style>
