import asyncio
import numpy as np

from pyppeteer.launcher import launch
from collections import Counter, namedtuple
from io import BytesIO
from PIL import Image

Rect = namedtuple('Rect', ['x', 'y', 'width', 'height'])

State = namedtuple('State', ['image', 'elements'])

Action = namedtuple('Action', ['x', 'y', 'type'])

Element = namedtuple('Element', ['tag', 'selector', 'bounding_box'])

class CoverageReporter:

    def __init__(self, coverage_data):
        self.coverage_data = coverage_data

    def summary(self):
        cov = [self._file_summary(v['s']) 
                for v in self.coverage_data.values()]
        not_covered = sum(n for n, _ in cov)
        stmts = sum(s for _, s in cov)
        return 1.0 - (not_covered / stmts)

    def _file_summary(self, statement_coverage):
        cnt = Counter(list(statement_coverage.values()))
        not_covered = cnt[0]
        stmts = sum(cnt.values())
        return (not_covered, stmts)

class WebEnv:
    
    CELL_SIZE = 20

    def __init__(self, app_url, headless=False, content_selector=None):
        self.app_url = app_url
        self.content_selector = 'html' if not content_selector else content_selector
        self.headless = headless

    def reset(self):
        self.browser = launch(headless=self.headless)
        self.page = self._run_cmd(self.browser.newPage())
        self._run_cmd(self.page.goto(self.app_url))
        self.viewport = self._viewport()
        self.coverage = self._coverage()
        return self._state(), self._actions()

    def step(self, action):
        mouse = self.page.mouse
        v = self.viewport
        self._run_cmd(mouse.click(x=v.x + action.x, y=v.y + action.y))
        old_coverage = self.coverage
        new_coverage = self._coverage()
        reward = new_coverage - old_coverage
        self.coverage = new_coverage
        return self._state(), self._actions(), reward

    def _state(self):
        return State(
                image=self._screenshot(),
                elements=self._elements()
        )
    
    def _actions(self):
        w, h = self.viewport.width, self.viewport.height
        cw = int(w / self.CELL_SIZE)
        ch = int(h / self.CELL_SIZE)
        return [Action(
                    int(cx * self.CELL_SIZE - (self.CELL_SIZE / 2)), 
                    int(cy * self.CELL_SIZE - (self.CELL_SIZE / 2)), 
                    type='click'
                ) 
                for cy in range(1, ch + 1) 
                for cx in range(1, cw + 1)]

    def _run_cmd(self, cmd):
        return asyncio.get_event_loop().run_until_complete(cmd)

    def _coverage(self):
        coverage = self._run_cmd(self.page.evaluate('() => {return window.__coverage__}'))
        reporter = CoverageReporter(coverage)
        return reporter.summary()

    def _screenshot(self):
        buf = self._run_cmd(self.page.screenshot())
        img = np.array(Image.open(BytesIO(buf)))
        v = self.viewport
        return img[
                v.y: v.y + v.height, 
                v.x: v.x + v.width
        ]

    def _viewport(self):
        v = self._run_cmd(self.page.evaluate('''
            () => {
                var e = document.querySelector("''' + self.content_selector + '''")
                var b = e.getBoundingClientRect()
                return {
                    x: b.x,
                    y: b.y,
                    width: b.width,
                    height: b.height
                }
            }
        '''))
        return Rect(**v)

    def _elements(self):

        elements = self._run_cmd(self.page.evaluate('''
            () => {
                function fullPath(el){
                    var names = [];
                    while (el.parentNode){
                        if (el.id){
                            names.unshift('#'+el.id);
                            break;
                        }else{
                            if (el==el.ownerDocument.documentElement) 
                                names.unshift(el.tagName.toLowerCase());
                            else{
                                for (var c=1,e=el;e.previousElementSibling;e=e.previousElementSibling,c++);
                                names.unshift(el.tagName.toLowerCase()+":nth-child("+c+")");
                            }
                            el=el.parentNode;
                        }
                    }
                    return names.join(" > ");
                }

                var root = document.querySelector("''' + self.content_selector + '''")
                var nodes = root.querySelectorAll("*")
                var elements = []
                nodes.forEach(function(v, _, _) {elements.push(v)})
                return elements.map((e) => {
                    var b = e.getBoundingClientRect()
                    return {
                        tag: e.localName,
                        selector: fullPath(e),
                        box: {
                            x: b.x,
                            y: b.y,
                            width: b.width,
                            height: b.height
                        }
                    }
                })
            }
        '''))
        return list(map(
            lambda e: Element(e['tag'], e['selector'], Rect(**e['box'])),
            elements
        ))
