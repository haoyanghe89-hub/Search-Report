"""A1/A2 acceptance through the real app and unchanged 2s LIVE polling."""
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(r'D:\deepsearch')
OUT = ROOT / 'frontend/test-results/live-motion'
sys.path.insert(0, str(ROOT / 'frontend/.playwright-runtime'))
from playwright.sync_api import sync_playwright

BASE = os.environ.get('LIVE_MOTION_BASE_URL', 'http://127.0.0.1:5183')
EDGE = r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'
results = {'checks': [], 'console_errors': [], 'page_errors': [], 'http_errors': [], 'screenshots': [], 'frames': [], 'title_metrics': []}
sys.stdout.reconfigure(encoding='utf-8')


def check(name, passed, details=None):
    results['checks'].append({'name': name, 'passed': bool(passed), 'details': details})


def shot(page, name):
    path = OUT / name
    page.screenshot(path=str(path), full_page=True)
    results['screenshots'].append(str(path.relative_to(ROOT)))


def style(page, selector):
    return page.locator(selector).evaluate('node => ({opacity:getComputedStyle(node).opacity, transform:getComputedStyle(node).transform})')


def mock_api(page, state):
    def handle(route):
        path = urlparse(route.request.url).path.rstrip('/')
        stage = state['stage']
        run = {'run_id': 'RUN-LIVE-MOTION', 'investigation_id': 'INV-LIVE-MOTION', 'mode': 'LIVE',
               'status': 'READY_FOR_REPORT' if stage == 3 else 'RUNNING', 'state_version': stage,
               'current_phase': 'VERIFYING' if stage >= 2 else 'SEARCHING' if stage else 'WAITING_FOR_EXECUTION',
               'created_at': '2026-10-01T12:00:00Z', 'updated_at': '2026-10-01T12:00:08Z'}
        if path == '/api/investigations':
            payload = [{'investigation_id': 'INV-LIVE-MOTION', 'title': state['title'], 'run_count': 1}]
        elif path == '/api/investigations/INV-LIVE-MOTION':
            payload = {'investigation_id': 'INV-LIVE-MOTION', 'title': state['title'], 'investigation_goal': '追溯事件经过，核对来源与证据。'}
        elif path == '/api/investigations/INV-LIVE-MOTION/runs':
            payload = [run]
        elif path == '/api/runs/RUN-LIVE-MOTION':
            state['polls'].append(stage)
            payload = {'run': run, 'workers': {} if stage == 0 else {'official': 'RUNNING' if stage == 1 else 'SUCCEEDED', 'technical': 'VERIFYING' if stage == 2 else 'SUCCEEDED' if stage == 3 else 'PENDING'},
                       'budget': {'search_calls_used': 0 if stage == 0 else 1 if stage == 1 else 4, 'max_search_calls': 12,
                                  'fetch_calls_used': 2 if stage >= 2 else 0, 'max_fetch_calls': 8, 'model_calls_used': 1 if stage >= 2 else 0, 'max_model_calls': 5}}
        elif path == '/api/runs/RUN-LIVE-MOTION/steps':
            payload = [] if stage == 0 else [{'step_id': 'STEP-LIVE-01', 'agent_role': 'official', 'step_type': 'SEARCH', 'status': 'RUNNING' if stage == 1 else 'COMPLETED'}]
            if stage >= 2:
                payload.append({'step_id': 'STEP-LIVE-02', 'agent_role': 'technical', 'step_type': 'VERIFY', 'status': 'VERIFYING' if stage == 2 else 'SUCCEEDED'})
        elif path.startswith('/api/runs/RUN-LIVE-MOTION/'):
            payload = []
        elif path == '/api/operations/status':
            payload = {'healthy': True, 'alerts': []}
        else:
            raise RuntimeError(f'Unexpected mock endpoint: {path}')
        route.fulfill(status=200, content_type='application/json', body=json.dumps(payload, ensure_ascii=False))
    # Exact host prefix: do not intercept Vite /src/api/*.js modules.
    page.route(f'{BASE}/api/**', handle)


def open_mock(page, state, label):
    page.on('console', lambda message: results['console_errors'].append({'page': label, 'text': message.text}) if message.type == 'error' else None)
    page.on('pageerror', lambda error: results['page_errors'].append({'page': label, 'text': str(error)}))
    page.on('response', lambda response: results['http_errors'].append({'page': label, 'status': response.status, 'url': response.url}) if response.status >= 400 else None)
    page.add_init_script("Object.defineProperty(navigator, 'hardwareConcurrency', {get: () => 8})")
    page.add_init_script(f"localStorage.setItem('search-report-theme', {json.dumps(state['theme'])})")
    mock_api(page, state)
    page.goto(BASE, wait_until='networkidle')
    if page.locator('.mobile-menu-trigger').is_visible():
        page.locator('.mobile-menu-trigger').click()
    page.locator('.case-card').first.click()
    page.wait_for_selector('.hero-title')


MONITOR = """() => {
  const m = window.liveMonitor = {frames:0,longFrames:0,maxFrame:0,entry:false,stamp:false,workerStamp:false,
    phase:false,budget:false,leave:false,resultDuringLeave:false,resultAfter:false,resultOpen:false,reducedDisplacement:false};
  let before = performance.now();
  function tick(now) {
    const delta=now-before; before=now; m.frames++; m.maxFrame=Math.max(m.maxFrame,delta); if(delta>50)m.longFrames++;
    const run=document.querySelector('.run-progress'), result=document.querySelector('.results-panel');
    const step=document.querySelector('[data-step-id="STEP-LIVE-02"]');
    const stamp=document.querySelector('[data-step-id="STEP-LIVE-01"] .verified');
    const workerStamp=document.querySelector('[data-worker-name="official"] .verified');
    const phase=document.querySelector('.phase-value'); const budget=document.querySelector('[data-budget-key="search"]');
    if(step && (getComputedStyle(step).opacity!=='1' || getComputedStyle(step).transform!=='none'))m.entry=true;
    if(stamp && getComputedStyle(stamp).transform!=='none')m.stamp=true;
    if(workerStamp && getComputedStyle(workerStamp).transform!=='none')m.workerStamp=true;
    if(phase && getComputedStyle(phase).opacity!=='1')m.phase=true;
    if(budget && ['2','3'].includes(budget.textContent))m.budget=true;
    if(run && Number(getComputedStyle(run).opacity)<0.98) {m.leave=true;if(result)m.resultDuringLeave=true;}
    if(!run && result) {m.resultAfter=true;if(Number(getComputedStyle(result).opacity)<1)m.resultOpen=true;}
    if(matchMedia('(prefers-reduced-motion: reduce)').matches) {
      for(const node of document.querySelectorAll('.progress-step,.worker-record,.phase-value,.worker-status,.step-status,[data-budget-key]')) {
        if(getComputedStyle(node).opacity!=='1' || getComputedStyle(node).transform!=='none')m.reducedDisplacement=true;
      }
    }
    window.liveFrame = requestAnimationFrame(tick);
  }
  window.liveFrame = requestAnimationFrame(tick);
}"""


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True, executable_path=EDGE)
    for width, height in ((1440, 900), (390, 844)):
        for theme in ('dark', 'light'):
            for reduced in (False, True):
                label = f'{width}x{height}-{theme}-' + ('reduced' if reduced else 'motion')
                context = browser.new_context(viewport={'width': width, 'height': height}, reduced_motion='reduce' if reduced else 'no-preference', has_touch=width < 768, is_mobile=width < 768)
                page = context.new_page()
                state = {'stage': 0, 'title': '实时证据归档验收', 'theme': theme, 'polls': []}
                open_mock(page, state, label)
                page.wait_for_selector('.waiting-docket')
                check(f'{label}: CASE INTAKE waiting visible', 'CASE INTAKE' in page.locator('.waiting-docket').inner_text())
                check(f'{label}: pending process auto expands', page.locator('.process-panel').get_attribute('open') is not None)
                page.locator('.run-progress').scroll_into_view_if_needed()
                page.evaluate(MONITOR)
                state['stage'] = 1
                page.wait_for_selector('[data-step-id="STEP-LIVE-01"]')
                page.locator('[data-step-id="STEP-LIVE-01"]').scroll_into_view_if_needed()
                page.wait_for_timeout(550)
                check(f'{label}: AGENT/EXHIBIT indexed content', page.locator('[data-step-id="STEP-LIVE-01"]').inner_text().startswith('EXHIBIT 01') and page.locator('[data-worker-name="official"]').inner_text().startswith('AGENT 01'))
                state['stage'] = 2
                page.wait_for_selector('[data-step-id="STEP-LIVE-02"]')
                page.locator('[data-step-id="STEP-LIVE-02"]').scroll_into_view_if_needed()
                page.wait_for_timeout(600)
                check(f'{label}: completion stamp text', page.locator('[data-step-id="STEP-LIVE-01"] .step-status').inner_text() == '已归档')
                check(f'{label}: completed scan stops', page.locator('[data-step-id="STEP-LIVE-01"] .step-scan').evaluate("node => getComputedStyle(node).opacity") == '0')
                check(f'{label}: persisted budget reached', page.locator('[data-budget-key="search"]').inner_text() == '4')
                check(f'{label}: existing step stays settled', style(page, '[data-step-id="STEP-LIVE-01"]')['transform'] == 'none')
                if width < 768:
                    a = style(page, '[data-step-id="STEP-LIVE-02"] .step-scan')
                    page.wait_for_timeout(80)
                    b = style(page, '[data-step-id="STEP-LIVE-02"] .step-scan')
                    check(f'{label}: touch scan static', a == b)
                check(f'{label}: no horizontal overflow during run', page.evaluate('document.documentElement.scrollWidth <= document.documentElement.clientWidth'))
                # Capture settled cards before terminal snapshot; recording excludes screenshot overhead.
                page.evaluate('cancelAnimationFrame(window.liveFrame)')
                during = page.evaluate('window.liveMonitor')
                if reduced:
                    check(f'{label}: reduced data updates static', not during['reducedDisplacement'] and not during['entry'] and not during['stamp'], during)
                else:
                    check(f'{label}: new step entry captured', during['entry'], during)
                    check(f'{label}: step and worker stamp captured', during['stamp'] and during['workerStamp'], during)
                    check(f'{label}: budget and phase animation captured', during['budget'] and during['phase'], during)
                shot(page, f'flow-{label}.png')
                page.evaluate(MONITOR)
                state['stage'] = 3
                page.wait_for_selector('.run-progress', state='detached', timeout=10000)
                page.wait_for_selector('.section-nav', timeout=10000)
                page.wait_for_timeout(550)
                terminal = page.evaluate('cancelAnimationFrame(window.liveFrame); window.liveMonitor')
                check(f'{label}: terminal results visible', terminal['resultAfter'])
                check(f'{label}: results follow close', not terminal['resultDuringLeave'], terminal)
                if reduced:
                    check(f'{label}: reduced flow static', not terminal['reducedDisplacement'] and not terminal['leave'] and not terminal['resultOpen'], terminal)
                else:
                    check(f'{label}: dossier closes then opens', terminal['leave'] and terminal['resultOpen'], terminal)
                check(f'{label}: nine tabs preserved', page.locator('[data-tab-key]').count() == 9)
                check(f'{label}: tab indicator initialized', page.locator('.tab-indicator').evaluate('node => node.getBoundingClientRect().width > 0'))
                check(f'{label}: no overflow after terminal', page.evaluate('document.documentElement.scrollWidth <= document.documentElement.clientWidth'))
                check(f'{label}: actual LIVE polling progressed', all(stage in state['polls'] for stage in (0, 1, 2, 3)), state['polls'])
                results['frames'].append({'case': label, 'during': during, 'terminal': terminal})
                shot(page, f'results-{label}.png')
                print(f'Completed {label}', flush=True)
                context.close()

    titles = {
        'lg': '东巴勒斯坦列车脱轨事故',
        'md': '东巴勒斯坦列车脱轨事故后污染物扩散与公开监测信息核验',
        'sm': '关于东巴勒斯坦列车脱轨事故后空气与水体污染物扩散监测数据公开信息及长期居民健康风险评估结论的证据核验调查报告'
    }
    for width, height in ((1440, 900), (390, 844)):
        for theme in ('dark', 'light'):
            for size, title in titles.items():
                label = f'title-{size}-{width}x{height}-{theme}'
                context = browser.new_context(viewport={'width': width, 'height': height}, reduced_motion='reduce')
                page = context.new_page()
                state = {'stage': 3, 'title': title, 'theme': theme, 'polls': []}
                open_mock(page, state, label)
                page.wait_for_selector('.section-nav')
                page.evaluate('window.scrollTo(0, 0)')
                metrics = page.locator('.hero-title').evaluate("""node => {
                  const style=getComputedStyle(node), rect=node.getBoundingClientRect();
                  const status=document.querySelector('.hero-status').getBoundingClientRect();
                  const cta=document.querySelector('.hero-primary-action').getBoundingClientRect();
                  return {text:node.textContent.trim(),class:node.className,fontSize:parseFloat(style.fontSize),lineHeight:parseFloat(style.lineHeight),
                    titleHeight:rect.height,titleBottom:rect.bottom,statusBottom:status.bottom,ctaBottom:cta.bottom,
                    scrollWidth:document.documentElement.scrollWidth,clientWidth:document.documentElement.clientWidth,
                    nodeOverflow:node.scrollWidth>node.clientWidth+1};
                }""")
                check(f'{label}: correct tier', f'hero-title--{size}' in metrics['class'], metrics)
                check(f'{label}: complete title retained', metrics['text'] == title, metrics)
                check(f'{label}: no truncation or overflow', not metrics['nodeOverflow'] and metrics['scrollWidth'] <= metrics['clientWidth'], metrics)
                check(f'{label}: stamp and CTA fit first screen', metrics['statusBottom'] <= height and metrics['ctaBottom'] <= height, metrics)
                expected = (40, 60) if size == 'lg' else (30, 42) if size == 'md' else (24, 32)
                check(f'{label}: token size range', expected[0] <= metrics['fontSize'] <= expected[1], metrics)
                results['title_metrics'].append({'case': label, **metrics})
                shot(page, f'{label}.png')
                context.close()
    browser.close()

check('no unexpected console errors', not results['console_errors'], results['console_errors'])
check('no page exceptions', not results['page_errors'], results['page_errors'])
check('mock API and app resources healthy', not results['http_errors'], results['http_errors'])
results['passed'] = all(item['passed'] for item in results['checks'])
(OUT / 'final-acceptance.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({'passed': results['passed'], 'checks': len(results['checks']), 'failed': [item for item in results['checks'] if not item['passed']]}, ensure_ascii=False, indent=2))
raise SystemExit(0 if results['passed'] else 1)
