import json
import os
import sys
from pathlib import Path

ROOT = Path(r'D:\deepsearch')
OUT = ROOT / 'frontend/test-results/live-motion'
BASE = os.environ.get('LIVE_MOTION_BASE_URL', 'http://127.0.0.1:5183')
sys.path.insert(0, str(ROOT / 'frontend/.playwright-runtime'))
from playwright.sync_api import sync_playwright

checks = []
errors = []
def check(name, passed, details=None):
    checks.append({'name': name, 'passed': bool(passed), 'details': details})

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, executable_path=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe')
    context = browser.new_context(viewport={'width': 1440, 'height': 900})
    page = context.new_page()
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.on('console', lambda message: errors.append(message.text) if message.type == 'error' else None)
    page.add_init_script("Object.defineProperty(navigator, 'hardwareConcurrency', {get: () => 8})")
    page.goto(f'{BASE}/test-results/live-motion/harness.html', wait_until='networkidle')
    page.evaluate('liveHarness.addFirst()')
    page.wait_for_timeout(550)
    page.evaluate('liveHarness.addSecond()')
    page.wait_for_timeout(80)
    page.emulate_media(reduced_motion='reduce')
    page.wait_for_timeout(50)
    dynamic = page.evaluate("""() => ({
      value:document.querySelector('[data-budget-key="search"]').textContent,
      transforms:[...document.querySelectorAll('.progress-step,.worker-record,.phase-value,.badge,[data-budget-key]')].map(n=>getComputedStyle(n).transform),
      hidden:[...document.querySelectorAll('.progress-step,.worker-record,.phase-value,.badge,[data-budget-key]')].filter(n=>getComputedStyle(n).opacity!=='1').length,
      opacityDetails:[...document.querySelectorAll('.progress-step,.worker-record,.phase-value,.badge,[data-budget-key]')].map(n=>({classes:n.className,opacity:getComputedStyle(n).opacity,inline:n.style.opacity,transition:getComputedStyle(n).transition})),
      loops:motionProbe.globalTimeline.getChildren(true,true,false).filter(t=>t.repeat()===-1).length
    })""")
    check('changing reduced-motion mid-counter immediately reaches persisted value', dynamic['value'] == '4', dynamic)
    check('dynamic reduced-motion resets all displacement and visibility', dynamic['hidden'] == 0 and all(t == 'none' for t in dynamic['transforms']), dynamic)
    check('dynamic reduced-motion kills looping tweens', dynamic['loops'] == 0, dynamic)

    page.emulate_media(reduced_motion='no-preference')
    page.evaluate('liveHarness.burst(100)')
    page.wait_for_timeout(650)
    bulk = page.evaluate("""() => {
      const list=document.querySelector('.progress-steps'),rect=list.getBoundingClientRect();
      const nodes=[...list.querySelectorAll('.progress-step')];
      const visible=nodes.filter(n=>{const r=n.getBoundingClientRect();return r.bottom>rect.top&&r.top<Math.min(rect.bottom,innerHeight)});
      return {count:nodes.length,visible:visible.length,scans:nodes.filter(n=>motionProbe.getTweensOf(n.querySelector('.step-scan')).length).length,
        hidden:nodes.filter(n=>getComputedStyle(n).opacity==='0').length,overflow:document.documentElement.scrollWidth>document.documentElement.clientWidth};
    }""")
    check('100-step snapshot renders complete content', bulk['count'] == 100 and bulk['hidden'] == 0, bulk)
    check('scan tween count bounded by visible cards', bulk['scans'] <= bulk['visible'] and bulk['scans'] > 0, bulk)
    check('100-step snapshot has no horizontal overflow', not bulk['overflow'], bulk)
    page.evaluate('document.querySelector(".progress-steps").scrollTop=10000')
    page.wait_for_timeout(650)
    tail = page.evaluate("""() => {
      const node=document.querySelector('[data-step-id="BURST-99"]');
      return {opacity:getComputedStyle(node).opacity,transform:getComputedStyle(node).transform,
        firstScan:motionProbe.getTweensOf(document.querySelector('[data-step-id="BURST-0"] .step-scan')).length};
    }""")
    check('new offscreen steps reveal when scrolled into view', tail['opacity'] == '1' and tail['transform'] == 'none', tail)
    check('scans are killed when cards leave viewport', tail['firstScan'] == 0, tail)
    page.evaluate('window.savedMotionNodes=[...document.querySelector(".run-progress").querySelectorAll("*")];liveHarness.unmount()')
    page.wait_for_timeout(50)
    cleanup = page.evaluate("({dom:document.querySelectorAll('.run-progress').length,tweens:motionProbe.getTweensOf(window.savedMotionNodes).length,loops:motionProbe.globalTimeline.getChildren(true,true,false).filter(t=>t.repeat()===-1).length})")
    check('unmount kills DOM tweens and loops', cleanup['dom'] == 0 and cleanup['tweens'] == 0 and cleanup['loops'] == 0, cleanup)
    context.close()

    context = browser.new_context(viewport={'width':1440,'height':900})
    page=context.new_page()
    page.add_init_script("Object.defineProperty(navigator, 'hardwareConcurrency', {get: () => 2})")
    page.goto(f'{BASE}/test-results/live-motion/harness.html', wait_until='networkidle')
    page.evaluate('liveHarness.addFirst()')
    page.wait_for_timeout(600)
    low = page.evaluate("({loops:motionProbe.globalTimeline.getChildren(true,true,false).filter(t=>t.repeat()===-1).length,opacity:getComputedStyle(document.querySelector('.progress-step')).opacity})")
    check('low-power devices disable loops but retain content', low['loops'] == 0 and low['opacity'] == '1', low)
    context.close()
    browser.close()

check('edge cases have no browser errors', not errors, errors)
result={'passed':all(c['passed'] for c in checks),'checks':checks,'errors':errors}
(OUT/'edge-acceptance.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(result,ensure_ascii=False,indent=2))
raise SystemExit(0 if result['passed'] else 1)
