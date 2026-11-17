"""Launch the desktop UI and record a read-only startup check."""
import json
import multiprocessing
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def launch():
    import webview
    from ytletolto.app import main

    start = webview.start

    def check_ui():
        window = webview.windows[0]
        window.events.loaded.wait(15)
        window.evaluate_js("""new Promise(resolve => {
          const deadline = Date.now() + 15000;
          const check = () => {
            if (document.querySelector('#language').disabled && Date.now() < deadline) {
              setTimeout(check, 100); return;
            }
            resolve({ready: !!window.app && !document.querySelector('#language').disabled,
              language: document.documentElement.lang,
              paste: document.querySelector('#paste-btn').textContent.trim(),
              translatedError: window.i18n?.t({message:'UNEXPECTED_ERROR',params:{error:'check'}}),
              flagsLoaded: [...document.querySelectorAll('.language-picker img')].every(i=>i.complete && i.naturalWidth>0)
            });
          }; check();
        })""", callback=lambda result: (ROOT / 'output' / 'desktop-startup-check.json').write_text(
            json.dumps(result, ensure_ascii=False), encoding='utf-8'))

    webview.start = lambda **kwargs: start(check_ui, **kwargs)
    main()


if __name__ == '__main__':
    multiprocessing.freeze_support()
    launch()
