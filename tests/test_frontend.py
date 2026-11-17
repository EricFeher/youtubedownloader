"""A valódi HTML/CSS/JS felület tesztjei, helyi pywebview API-helyettessel."""

import json
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from playwright.sync_api import expect, sync_playwright


WEB = Path(__file__).resolve().parents[1] / "ytletolto" / "web"
API = r"""
window.recorded = { enqueued: [], saved: [], probes: [] };
window.updateData = {current_version:'1.1.0',status:'current',available:false,supported:true,version:'1.1.0',notes:'## Javítások\n- Stabilabb letöltések.',published_at:'2026-11-15T10:00:00Z',error:'',progress:null};
window.updateCalls = [];
const quality = (tier) => ({tier, fps: 30, size: 1000000});
window.videoData = {
  one: {kind:'video', title:'Első videó', thumbnail:'video-one.jpg', uploader:'Media Minds', duration:120, max_height:1080,
    qualities:{mp4:[quality(1080),quality(720)],mkv:[quality(1080)],webm:[quality(720)]}},
  two: {kind:'video', title:'Második videó', thumbnail:'video-two.jpg', uploader:'Media Minds', duration:240, max_height:2160,
    qualities:{mp4:[quality(2160),quality(1080),quality(720)],mkv:[quality(2160)],webm:[quality(2160)]}},
  three: {kind:'video', title:'Harmadik videó', uploader:'Media Minds', duration:60, max_height:720,
    qualities:{mp4:[quality(720),quality(480)],mkv:[quality(720)],webm:[quality(720)]}}
};
window.pywebview = {api: {
  init:async()=>({settings:{language:window.testLanguage ?? 'hu',output_dir:'/downloads',mode:'video',quality:'best',container:'mp4',audio_format:'mp3',compatible:false},
    ffmpeg:true,js_runtime:true,queue:{version:0,items:[]},update:window.updateData}),
  check_update:async()=>{window.updateCalls.push('check');return window.updateData;},
  download_update:async()=>{window.updateCalls.push('download');return {...window.updateData,status:'ready',progress:100};},
  install_update:async()=>{window.updateCalls.push('install');return {ok:false,error:'Teszt: az újraindítás most nem érhető el.'};},
  save_settings:async(changes)=>window.recorded.saved.push(changes),
  probe:async(url,playlist)=>{
    window.recorded.probes.push(url);
    if(url.includes('/playlist') || playlist) return {ok:true,info:{kind:'playlist',title:'Tesztlista',thumbnail:'playlist.jpg',uploader:'Media Minds',count:3,
      entries:Object.entries(window.videoData).map(([id,v],i)=>({id,index:i+1,title:v.title,duration:v.duration,thumbnail:`entry-${id}.jpg`}))}};
    const id=new URL(url).searchParams.get('v') || url.split('/').pop();
    if(window.deferId===id) return await new Promise(resolve=>{window.resolveProbe=resolve;});
    return {ok:true,info:window.videoData[id] || window.videoData.one};
  },
  enqueue:async(options)=>{window.recorded.enqueued.push(options);return {ok:true,added:1,skipped:0};}
}};
"""


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def web_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(QuietHandler, directory=str(WEB)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}/index.html"
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        yield browser
        browser.close()


@pytest.fixture
def page(browser, web_server):
    page = browser.new_page(viewport={"width": 820, "height": 1000})
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.add_init_script(API)
    page.goto(web_server)
    page.evaluate("window.dispatchEvent(new Event('pywebviewready'))")
    expect(page.locator("#folder")).to_have_text("\u200e/downloads\u200e")
    yield page
    page.close()
    assert errors == []


def set_language(page, language):
    page.locator("#language").click()
    page.locator(f'[data-language="{language}"]').click()


@pytest.mark.parametrize("bridge", ["undefined", "{api: {}}", "{api: {init: true}}"])
def test_initialization_waits_for_callable_bridge(browser, web_server, bridge):
    page = browser.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.add_init_script(API + """
      window.readyApi = window.pywebview.api;
      window.initCalls = 0;
      const originalInit = window.readyApi.init;
      window.readyApi.init = () => { window.initCalls++; return originalInit(); };
      window.pywebview = """ + bridge + ";")
    try:
        page.goto(web_server)
        page.wait_for_function("window.app !== undefined")
        page.evaluate("window.dispatchEvent(new Event('pywebviewready'))")
        expect(page.locator("#language")).to_be_disabled()
        assert page.evaluate("window.initCalls") == 0
        page.evaluate("""window.pywebview = {api: window.readyApi};
          window.dispatchEvent(new Event('pywebviewready'));""")
        expect(page.locator("#folder")).to_have_text("\u200e/downloads\u200e")
        page.evaluate("window.dispatchEvent(new Event('pywebviewready'))")
        assert page.evaluate("window.initCalls") == 1
        assert page.evaluate("window.updateCalls") == ["check"]
        assert errors == []
    finally:
        page.close()


@pytest.mark.parametrize("failure", ["throw new Error('Bridge unavailable');", "return Promise.reject(new Error('Bridge unavailable'));"])
def test_initialization_failure_allows_retry_without_overlapping_calls(browser, web_server, failure):
    page = browser.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.add_init_script(API + """
      window.initCalls = 0;
      const originalInit = window.pywebview.api.init;
      window.pywebview.api.init = () => {
        window.initCalls++;
        if (window.initCalls === 1) { """ + failure + """ }
        return new Promise(resolve => { window.resolveInit = () => resolve(originalInit()); });
      };
    """)
    try:
        page.goto(web_server)
        page.wait_for_function("window.initCalls === 1")
        expect(page.locator("#language")).to_be_disabled()
        page.evaluate("""window.dispatchEvent(new Event('pywebviewready'));
          window.dispatchEvent(new Event('pywebviewready'));""")
        assert page.evaluate("window.initCalls") == 2
        expect(page.locator("#language")).to_be_disabled()
        page.evaluate("window.resolveInit()")
        expect(page.locator("#folder")).to_have_text("\u200e/downloads\u200e")
        expect(page.locator("#language")).to_be_enabled()
        page.evaluate("window.dispatchEvent(new Event('pywebviewready'))")
        assert page.evaluate("window.initCalls") == 2
        assert page.evaluate("window.updateCalls") == ["check"]
        assert errors == []
    finally:
        page.close()


def test_missing_translation_falls_back_to_english_catalog(page):
    hungarian = json.loads((WEB / "locales" / "hu.json").read_text(encoding="utf-8"))
    del hungarian["PASTE"]
    page.route("**/locales/hu.json", lambda route: route.fulfill(json=hungarian))
    page.reload()
    expect(page.locator("html")).to_have_attribute("lang", "hu")
    expect(page.locator("#paste-btn")).to_have_text("Paste")
    expect(page.locator("#download-label")).to_have_text("MP4 letöltése")
    assert page.evaluate("Object.isFrozen(window.i18n.TEXT)")
    assert page.evaluate("window.i18n.t('External error: file {title}.mp4')") == "External error: file {title}.mp4"


def test_language_menu_shows_flags_full_names_and_current_selection(page):
    trigger = page.locator("#language")
    menu = page.locator("#language-menu")
    expect(menu).to_be_hidden()
    expect(page.locator("#language-code")).to_have_text("HU")
    trigger.click()
    expect(trigger).to_have_attribute("aria-expanded", "true")
    expect(menu.get_by_role("menuitemradio")).to_have_count(2)
    expect(menu.get_by_role("menuitemradio", name="Magyar")).to_have_attribute("aria-checked", "true")
    expect(menu.get_by_role("menuitemradio", name="English")).to_be_visible()
    assert menu.locator("img").evaluate_all("images => images.every(img => img.complete && img.naturalWidth > 0)")
    menu.get_by_role("menuitemradio", name="English").click()
    expect(menu).to_be_hidden()
    expect(trigger).to_be_focused()
    expect(page.locator("#language-code")).to_have_text("EN")
    expect(page.locator("#language-flag")).to_have_attribute("src", "flags/en.svg")
    assert page.evaluate("window.recorded.saved") == [{"language": "en"}]
    trigger.click()
    expect(menu.get_by_role("menuitemradio", name="English")).to_have_attribute("aria-checked", "true")
    page.locator("#url").click()
    expect(menu).to_be_hidden()
    expect(trigger).to_have_attribute("aria-expanded", "false")


def test_language_menu_keyboard_navigation_and_dismissal(page):
    trigger = page.locator("#language")
    menu = page.locator("#language-menu")
    trigger.focus()
    page.keyboard.press("ArrowDown")
    expect(menu.get_by_role("menuitemradio", name="Magyar")).to_be_focused()
    page.keyboard.press("End")
    expect(menu.get_by_role("menuitemradio", name="English")).to_be_focused()
    page.keyboard.press("Escape")
    expect(menu).to_be_hidden()
    expect(trigger).to_be_focused()
    assert page.evaluate("window.recorded.saved") == []
    page.keyboard.press("Enter")
    page.keyboard.press("ArrowUp")
    page.keyboard.press("Enter")
    expect(page.locator("#language-code")).to_have_text("EN")
    expect(menu).to_be_hidden()
    trigger.click()
    page.keyboard.press("Tab")
    expect(menu).to_be_hidden()


def set_range(page, side, seconds):
    page.locator(f"#range-{side}").evaluate("(input,value)=>{input.value=value;input.dispatchEvent(new Event('input',{bubbles:true}));}", seconds)


def test_language_switch_translates_controls_and_preserves_video_settings(page):
    page.locator("#url").fill("https://youtu.be/one")
    expect(page.locator("#range-section")).to_be_visible()
    set_range(page, "start", 20)
    set_range(page, "end", 90)
    page.locator('#quality label:has(input[value="720"])').click()
    set_language(page, "en")
    expect(page.locator("html")).to_have_attribute("lang", "en")
    expect(page.locator("#paste-btn")).to_have_text("Paste")
    expect(page.locator("#url")).to_have_attribute("placeholder", "Paste one or more YouTube links…")
    expect(page.locator("#range-start")).to_have_attribute("aria-label", "Section start")
    expect(page.locator("#range-summary")).to_have_text("Selected duration: 1:10")
    expect(page.locator("#container-hint")).to_contain_text("Plays anywhere")
    expect(page.locator("#quality")).to_contain_text("Best")
    expect(page.locator("#download-label")).to_have_text("Download MP4")
    expect(page.locator("#range-start")).to_have_value("20")
    expect(page.locator('#quality input[value="720"]')).to_be_checked()
    expect(page.locator("#title")).to_have_text("Első videó")
    assert page.evaluate("window.recorded.saved.at(-1)") == {"language": "en"}
    set_language(page, "hu")
    expect(page.locator("#range-summary")).to_have_text("Kijelölt hossz: 1:10")
    expect(page.locator("#paste-btn")).to_have_text("Beillesztés")


def test_saved_english_language_is_used_on_startup(page):
    page.add_init_script("window.testLanguage='en'")
    page.reload()
    page.evaluate("window.dispatchEvent(new Event('pywebviewready'))")
    expect(page.locator("#language")).to_have_attribute("value", "en")
    expect(page.locator("#download-label")).to_have_text("Download MP4")
    page.locator("#updates-open").click()
    expect(page.locator("#updates-title")).to_have_text("Updates and what's new")
    expect(page.locator("#update-status")).to_have_text("You are using the latest version.")
    expect(page.locator("#release-date")).to_contain_text("November")
    expect(page.locator("#release-notes")).to_contain_text("Stabilabb letöltések")


def test_language_switch_keeps_playlist_selection_editor_and_ranges(page):
    page.locator("#url").fill("https://www.youtube.com/playlist?list=PL1")
    expect(page.locator("#playlist-items .playlist-item")).to_have_count(3)
    page.locator('.playlist-item[data-index="2"] .playlist-open').click()
    expect(page.locator("#editor-title")).to_have_text("Második videó")
    set_range(page, "start", 30)
    page.locator('.playlist-item[data-index="3"] .playlist-select').uncheck()
    page.locator('#mode-grid label:has(input[value="audio"])').click()
    set_language(page, "en")
    expect(page.locator("#playlist-summary")).to_have_text("2 / 3 items selected · 1 video, 1 audio")
    expect(page.locator('.playlist-item[data-index="3"] .playlist-select')).not_to_be_checked()
    expect(page.locator('.playlist-item[data-index="2"] button[data-mode="audio"]')).to_have_attribute("aria-pressed", "true")
    expect(page.locator('.playlist-item[data-index="2"] .playlist-open')).to_have_attribute("aria-current", "true")
    expect(page.locator("#range-start")).to_have_value("30")
    expect(page.locator("#editor-title")).to_have_text("Második videó")
    expect(page.locator("#preview-kind")).to_have_text("Playlist · 3 videos")


def test_running_queue_progress_errors_and_backend_templates_change_language(page):
    page.evaluate("""window.app.onEvent({type:'queue',version:1,items:[
      {id:1,state:'running',title:'Kész',mode:'video',container:'mp4',files:[]},
      {id:2,state:'failed',title:'Video {error}',mode:'audio',audio_format:'mp3',files:[],message:{message:'UNEXPECTED_ERROR',params:{error:'Disk {name} full'}}}
    ]});
    window.app.onEvent({type:'progress',id:1,percent:42,speed:1024,eta:30});""")
    set_language(page, "en")
    expect(page.locator('.q-item[data-id="1"] .q-status')).to_contain_text("Downloading video track")
    expect(page.locator('.q-item[data-id="1"] .q-status')).to_contain_text("0:30 remaining")
    expect(page.locator('.q-item[data-id="1"] .q-pct')).to_have_text("42%")
    expect(page.locator('.q-item[data-id="1"] .q-title')).to_have_text("Kész")
    expect(page.locator('.q-item[data-id="2"] .q-status')).to_have_text("Unexpected error: Disk {name} full")
    expect(page.locator('.q-item[data-id="2"] .q-actions')).to_contain_text("Retry")
    expect(page.locator("#log")).to_contain_text("Video {error}: Unexpected error: Disk {name} full")
    assert page.locator("#log > div").count() == 2
    page.evaluate("window.app.onEvent({type:'status',id:1,text:{message:'PREPARING_AUDIO_ITEMS',params:{count:2}}})")
    expect(page.locator('.q-item[data-id="1"] .q-status')).to_have_text("Preparing 2 items as audio…")
    set_language(page, "hu")
    expect(page.locator('.q-item[data-id="1"] .q-status')).to_have_text("2 elem előkészítése hangként…")
    assert page.locator("#log > div").count() == 2


def test_language_switch_preserves_pending_cancel_and_update_failure(page):
    page.evaluate("""window.pywebview.api.cancel=async()=>true;
    window.app.onEvent({type:'queue',version:1,items:[{id:1,state:'running',title:'Video',mode:'video',container:'mp4',files:[]}]});""")
    page.locator('.q-item .q-actions button').click()
    set_language(page, "en")
    expect(page.locator('.q-item .q-actions button')).to_be_disabled()
    expect(page.locator('.q-item .q-actions button')).to_have_text("Cancelling…")
    page.evaluate("""window.app.onEvent({type:'queue',version:2,items:[]});
    window.pywebview.api.install_update=async()=>({ok:false,error:{message:'APP_WINDOW_UNAVAILABLE',params:{}}});
    window.app.onUpdate({...window.updateData,status:'ready',available:true,version:'1.2.0'});""")
    page.locator("#updates-open").click()
    page.locator("#update-install").click()
    expect(page.locator("#update-error")).to_have_text("The application window is unavailable.")
    page.locator("#updates-close").click()
    set_language(page, "hu")
    page.locator("#updates-open").click()
    expect(page.locator("#update-error")).to_be_visible()
    expect(page.locator("#update-error")).to_have_text("Az alkalmazás ablaka nem érhető el.")


def test_english_plural_forms_and_safe_parameter_substitution(page):
    set_language(page, "en")
    assert page.evaluate("""[window.i18n.t(window.i18n.TEXT.DOWNLOAD_ITEMS,{count:1}),
      window.i18n.t(window.i18n.TEXT.DOWNLOAD_ITEMS,{count:2}),
      window.i18n.t(window.i18n.TEXT.SELECT_VIDEO,{title:'<b>{title}</b>'})]""") == [
        "Download 1 item", "Download 2 items", "Select <b>{title}</b> for download",
    ]


STORYBOARD_SVG = '''<svg xmlns="http://www.w3.org/2000/svg" width="320" height="180">
<path fill="red" d="M0 0h160v90H0z"/><path fill="lime" d="M160 0h160v90H160z"/>
<path fill="blue" d="M0 90h160v90H0z"/><path fill="yellow" d="M160 90h160v90H160z"/></svg>'''


def add_storyboard(page):
    page.evaluate("""() => {
      window.videoData.one.storyboard = {width:160,height:90,columns:2,rows:2,fps:1/12,
        sheets:[{url:'/storyboards/0.svg',start:0,duration:48,frame_count:4},
                {url:'/storyboards/1.svg',start:48,duration:48,frame_count:4},
                {url:'/storyboards/2.svg',start:96,duration:24,frame_count:2}]};
    }""")


def frame_pixel(page):
    return page.locator("#range-preview-frame").evaluate(
        "canvas => [...canvas.getContext('2d').getImageData(160,60,1,1).data]")


@pytest.mark.parametrize("preview_state", ["available", "loading", "unavailable"])
def test_timeline_preview_translations_preserve_range_and_cached_frames(page, preview_state):
    pending = []
    if preview_state != "unavailable":
        page.route("**/storyboards/*", lambda route: pending.append(route))
        add_storyboard(page)
    page.locator("#url").fill("https://youtu.be/one")
    expect(page.locator("#range-section")).to_be_visible()
    set_range(page, "start", 12)
    if preview_state == "available":
        expect(page.locator("#range-preview-status")).to_have_text("El\u0151n\u00e9zet bet\u00f6lt\u00e9se\u2026")
        for route in pending:
            route.fulfill(content_type="image/svg+xml", body=STORYBOARD_SVG)
        expect(page.locator("#range-preview-frame")).to_have_attribute("aria-label", "El\u0151n\u00e9zet 0:12 k\u00f6r\u00fcl")
    # Invoke the menu action without moving the pointer away from the preview.
    page.locator('[data-language="en"]').evaluate("button => button.click()")
    expect(page.locator("#range-start")).to_have_value("12")
    if preview_state == "available":
        expect(page.locator("#range-preview-frame")).to_have_attribute("aria-label", "Preview near 0:12")
        assert frame_pixel(page) == [0, 255, 0, 255]
    elif preview_state == "loading":
        expect(page.locator("#range-preview-status")).to_have_text("Loading preview\u2026")
        for route in pending:
            route.fulfill(content_type="image/svg+xml", body=STORYBOARD_SVG)
        expect(page.locator("#range-preview-frame")).to_have_attribute("aria-label", "Preview near 0:12")
        assert frame_pixel(page) == [0, 255, 0, 255]
    else:
        expect(page.locator("#range-preview-status")).to_have_text("Preview unavailable")
    page.locator('[data-language="hu"]').evaluate("button => button.click()")
    if preview_state == "unavailable":
        expect(page.locator("#range-preview-status")).to_have_text("Az el\u0151n\u00e9zet nem \u00e9rhet\u0151 el")
    else:
        expect(page.locator("#range-preview-frame")).to_have_attribute("aria-label", "El\u0151n\u00e9zet 0:12 k\u00f6r\u00fcl")


def test_timeline_thumbnails_follow_handles_keyboard_and_final_partial_sheet(page):
    set_language(page, "en")
    requested = []

    def image(route):
        requested.append(route.request.url)
        route.fulfill(content_type="image/svg+xml", body=STORYBOARD_SVG)

    page.route("**/storyboards/*", image)
    add_storyboard(page)
    page.locator("#url").fill("https://youtu.be/one")
    expect(page.locator("#range-section")).to_be_visible()
    expect(page.locator("#range-preview")).to_be_hidden()
    page.locator("#range-end").focus()
    expect(page.locator("#range-preview-frame")).to_be_visible()
    expect(page.locator("#range-preview-time")).to_have_text("2:00")
    expect(page.locator("#range-preview-frame")).to_have_attribute("aria-label", "Preview near 1:48")
    assert frame_pixel(page) == [0, 255, 0, 255]  # Last valid cell, not a blank one.
    set_range(page, "start", 12)
    expect(page.locator("#range-preview-frame")).to_have_attribute("aria-label", "Preview near 0:12")
    assert frame_pixel(page) == [0, 255, 0, 255]
    page.locator("#range-start").press("Shift+ArrowRight")
    page.locator("#range-start").press("ArrowRight")
    page.locator("#range-start").press("ArrowRight")
    expect(page.locator("#range-preview-time")).to_have_text("0:24")
    expect(page.locator("#range-preview-frame")).to_have_attribute("aria-label", "Preview near 0:24")
    assert frame_pixel(page) == [0, 0, 255, 255]
    bounds = page.locator("#range-slider").bounding_box()
    x, y, width = bounds["x"] + 12, bounds["y"] + 24, bounds["width"] - 24
    page.mouse.move(x + width, y)
    page.mouse.down()
    page.mouse.move(x + width * 0.4, y, steps=5)
    expect(page.locator("#range-preview-time")).to_have_text("0:48")
    expect(page.locator("#range-preview-frame")).to_have_attribute("aria-label", "Preview near 0:48")
    assert frame_pixel(page) == [255, 0, 0, 255]
    page.mouse.up()
    expect(page.locator("#range-preview")).to_be_hidden()
    page.locator("#range-reset").click()
    expect(page.locator("#range-preview")).to_be_hidden()
    expect(page.locator("#range-start")).to_have_value("0")
    expect(page.locator("#range-end")).to_have_value("120")
    assert len(requested) == 3


@pytest.mark.parametrize("playlist", [False, True])
def test_hover_preview_follows_timeline_without_moving_handles_or_layout(page, playlist):
    set_language(page, "en")
    page.set_viewport_size({"width": 360, "height": 700})
    page.route("**/storyboards/*", lambda route: route.fulfill(content_type="image/svg+xml", body=STORYBOARD_SVG))
    add_storyboard(page)
    page.locator("#url").fill("https://youtube.com/playlist?list=PL" if playlist else "https://youtu.be/one")
    expect(page.locator("#range-section")).to_be_visible()
    if playlist:
        expect(page.locator("#editor-loading")).to_be_hidden()
    page.evaluate("document.fonts.ready")
    page.locator("#range-slider").scroll_into_view_if_needed()
    bounds = page.locator("#range-slider").bounding_box()
    quality = page.locator("#quality").bounding_box()
    for fraction in [0, 0.5, 1]:
        x = bounds["x"] + 12 + (bounds["width"] - 24) * fraction
        page.mouse.move(x, bounds["y"] + 24)
        expect(page.locator("#range-preview-frame")).to_be_visible()
        expect(page.locator("#range-preview-time")).to_have_text({0: "0:00", 0.5: "1:00", 1: "2:00"}[fraction])
        bubble = page.locator("#range-preview").bounding_box()
        assert bubble["y"] + bubble["height"] < bounds["y"] + 24
        assert bubble["x"] >= bounds["x"] - 1
        assert bubble["x"] + bubble["width"] <= bounds["x"] + bounds["width"] + 1
        anchor = page.locator("#range-preview").evaluate("el => parseFloat(el.style.getPropertyValue('--preview-anchor'))")
        assert abs(bubble["x"] + anchor - x) < 1
        assert page.locator("#range-slider").bounding_box() == bounds
        assert page.locator("#quality").bounding_box() == quality
    expect(page.locator("#range-start")).to_have_value("0")
    expect(page.locator("#range-end")).to_have_value("120")
    page.mouse.move(0, 0)
    expect(page.locator("#range-preview")).to_be_hidden()
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")


def test_late_thumbnail_cannot_replace_new_position_or_playlist_item(page):
    set_language(page, "en")
    pending = []
    page.route("**/storyboards/*", lambda route: pending.append(route))
    add_storyboard(page)
    page.locator("#url").fill("https://youtube.com/playlist?list=PL")
    expect(page.locator("#editor-loading")).to_be_hidden()
    expect(page.locator("#range-section")).to_be_visible()
    with page.expect_request("**/storyboards/*"):
        set_range(page, "start", 24)
    expect(page.locator("#range-preview-status")).to_have_text("Loading preview…")
    for route in list(pending):
        route.fulfill(content_type="image/svg+xml", body=STORYBOARD_SVG)
    expect(page.locator("#range-preview-frame")).to_have_attribute("aria-label", "Preview near 0:24")
    assert frame_pixel(page) == [0, 0, 255, 255]
    pending.clear()
    set_range(page, "start", 48)
    expect(page.locator("#range-preview-status")).to_have_text("Loading preview…")
    page.locator('.playlist-item[data-index="2"] .playlist-open').click()
    expect(page.locator("#range-preview")).to_be_hidden()
    for route in pending:
        route.fulfill(content_type="image/svg+xml", body=STORYBOARD_SVG)
    expect(page.locator("#range-preview")).to_be_hidden()
    expect(page.locator("#range-end")).to_have_value("240")


@pytest.mark.parametrize("failure", ["network", "timeout"])
@pytest.mark.parametrize("retry_seconds", [12, 24])
def test_failed_thumbnail_can_retry_same_sheet(page, failure, retry_seconds):
    set_language(page, "en")
    requested = []
    pending = []

    def image(route):
        requested.append(route.request.url)
        if len(requested) == 1:
            if failure == "network":
                route.abort("internetdisconnected")
            else:
                pending.append(route)
        else:
            route.fulfill(content_type="image/svg+xml", body=STORYBOARD_SVG)

    page.route("**/storyboards/*", image)
    add_storyboard(page)
    page.locator("#url").fill("https://youtu.be/one")
    expect(page.locator("#range-section")).to_be_visible()
    if failure == "timeout":
        page.clock.install()
    set_range(page, "start", 12)
    if failure == "timeout":
        expect(page.locator("#range-preview-status")).to_have_text("Loading preview…")
        page.clock.fast_forward(10001)
    expect(page.locator("#range-preview-status")).to_have_text("Preview unavailable")
    expect(page.locator("#range-preview-frame")).to_be_hidden()
    for route in pending:
        route.abort("timedout")

    set_range(page, "start", retry_seconds)
    expect(page.locator("#range-preview-frame")).to_be_visible()
    expect(page.locator("#range-preview-status")).to_be_hidden()
    expect(page.locator("#range-preview-frame")).to_have_attribute(
        "aria-label", f"Preview near 0:{retry_seconds}")
    assert frame_pixel(page) == ([0, 255, 0, 255] if retry_seconds == 12 else [0, 0, 255, 255])
    assert len(requested) == 2
    set_range(page, "start", 36)
    expect(page.locator("#range-preview-frame")).to_have_attribute("aria-label", "Preview near 0:36")
    assert frame_pixel(page) == [255, 255, 0, 255]
    assert len(requested) == 2


def test_failed_thumbnail_does_not_block_clip_download(page):
    set_language(page, "en")
    page.route("**/storyboards/*", lambda route: route.fulfill(status=404, body="Missing"))
    add_storyboard(page)
    page.locator("#url").fill("https://youtu.be/one")
    expect(page.locator("#range-section")).to_be_visible()
    set_range(page, "start", 12)
    expect(page.locator("#range-preview-status")).to_have_text("Preview unavailable")
    expect(page.locator("#range-preview-frame")).to_be_hidden()
    set_range(page, "end", 36)
    page.locator("#download-btn").click()
    payload = page.evaluate("window.recorded.enqueued[0]")
    assert (payload["start_time"], payload["end_time"]) == (12, 36)


def test_updates_auto_check_notes_dialog_keyboard_and_safe_text(page):
    assert page.evaluate("window.updateCalls") == ["check"]
    expect(page.locator("#update-banner")).to_be_hidden()
    page.locator("#updates-open").click()
    expect(page.locator("#updates-dialog")).to_be_visible()
    expect(page.locator("#update-status")).to_contain_text("legfrissebb")
    expect(page.locator("#release-notes")).to_contain_text("Stabilabb")
    page.evaluate("window.updateData={...window.updateData,available:true,status:'available',version:'1.2.0',notes:'<img src=x onerror=alert(1)> Újdonságok'}")
    page.locator("#update-check").click()
    expect(page.locator("#release-notes")).to_have_text("<img src=x onerror=alert(1)> Újdonságok")
    assert page.locator("#release-notes img").count() == 0
    page.locator("#updates-close").click()
    expect(page.locator("#update-banner")).to_be_visible()
    page.locator("#update-banner-open").click()
    page.keyboard.press("Escape")
    expect(page.locator("#updates-dialog")).not_to_be_visible()
    expect(page.locator("#update-banner-open")).to_be_focused()


def test_update_download_progress_restart_gating_and_failure(page):
    page.evaluate("window.updateData={...window.updateData,available:true,status:'available',version:'1.2.0'};window.app.onUpdate(window.updateData)")
    page.locator("#update-banner-open").click()
    page.locator("#update-download").click()
    expect(page.locator("#update-install")).to_be_enabled()
    page.evaluate("window.app.onEvent({type:'queue',version:5,items:[{id:1,state:'queued',title:'Teszt',mode:'video',container:'mp4',files:[]}]})")
    expect(page.locator("#update-install")).to_be_disabled()
    expect(page.locator("#update-status")).to_contain_text("letöltési sor végét")
    page.evaluate("window.app.onEvent({type:'queue',version:6,items:[]})")
    page.locator("#update-install").click()
    expect(page.locator("#update-error")).to_contain_text("újraindítás")
    expect(page.locator("#update-install")).to_be_enabled()
    assert page.evaluate("window.updateCalls") == ["check", "download", "install"]
    page.evaluate("window.app.onUpdate({...window.updateData,status:'downloading',progress:42})")
    expect(page.locator("#update-progress")).to_have_attribute("value", "42")
    expect(page.locator("#update-download")).to_be_disabled()
    expect(page.locator("#update-check")).to_be_disabled()


def test_update_network_retry_unsupported_build_and_small_window(page):
    page.set_viewport_size({"width": 600, "height": 700})
    page.locator("#updates-open").click()
    page.evaluate("window.app.onUpdate({...window.updateData,status:'error',error:'Nincs internetkapcsolat.'})")
    expect(page.locator("#update-error")).to_have_text("Nincs internetkapcsolat.")
    page.locator("#update-check").click()
    expect(page.locator("#update-error")).to_be_hidden()
    page.evaluate("window.app.onUpdate({...window.updateData,available:true,supported:false,status:'available',version:'1.2.0',notes:'Hosszú sor '.repeat(200)})")
    expect(page.locator("#update-download")).to_be_hidden()
    expect(page.locator("#update-status")).to_contain_text("Windows")
    assert page.locator("#updates-dialog").evaluate("el=>el.scrollWidth<=el.clientWidth")
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")


def test_playlist_editor_keeps_individual_settings_and_sends_them(page):
    # A link beírását hagyjuk előnézetté válni, az Enter már letöltést indítana.
    page.locator("#url").fill("https://youtube.com/playlist?list=PL")
    expect(page.locator("#editor-title")).to_have_text("Első videó")
    set_range(page, "start", 10)
    set_range(page, "end", 30)
    page.locator('input[name="container"][value="mkv"]').locator("..").click()
    page.locator('.playlist-item[data-index="2"] .playlist-open').click()
    expect(page.locator("#editor-title")).to_have_text("Második videó")
    expect(page.locator("#range-end")).to_have_value("240")
    page.locator('input[name="mode"][value="audio"]').locator("..").click()
    page.locator('input[name="audio_format"][value="opus"]').locator("..").click()
    set_range(page, "start", 45)
    set_range(page, "end", 90)
    page.locator('.playlist-item[data-index="1"] .playlist-open').click()
    expect(page.locator("#range-start")).to_have_value("10")
    expect(page.locator("#range-end")).to_have_value("30")
    expect(page.locator('input[name="container"][value="mkv"]')).to_be_checked()
    expect(page.locator('input[name="mode"][value="video"]')).to_be_checked()
    page.locator('.playlist-item[data-index="3"] .playlist-select').uncheck()
    page.locator("#download-btn").click()
    payload = page.evaluate("window.recorded.enqueued[0]")
    one, two = payload["items"][0]["selection"]
    assert one["options"] | {"quality": "best"} == {"mode": "video", "quality": "best", "container": "mkv", "audio_format": "mp3", "compatible": False, "start_time": 10, "end_time": 30}
    assert two["options"]["mode"] == "audio"
    assert two["options"]["audio_format"] == "opus"
    assert one["thumbnail"] == "video-one.jpg"
    assert two["thumbnail"] == "video-two.jpg"
    assert (one["title"], two["title"]) == ("Első videó", "Második videó")
    assert payload["items"][0]["playlist_title"] == "Tesztlista"
    assert (two["options"]["start_time"], two["options"]["end_time"]) == (45, 90)
    assert page.evaluate("window.recorded.saved") == []


def test_single_video_slider_drag_keyboard_reset_and_download(page):
    page.locator("#url").fill("https://youtu.be/one")
    expect(page.locator("#range-section")).to_be_visible()
    bounds = page.locator("#range-slider").bounding_box()
    x, y, width = bounds["x"] + 12, bounds["y"] + 24, bounds["width"] - 24
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x + width / 4, y, steps=8)
    page.mouse.up()
    expect(page.locator("#range-start")).to_have_value("30")
    page.locator("#range-start").press("ArrowRight")
    expect(page.locator("#range-start")).to_have_value("31")
    set_range(page, "end", 10)
    expect(page.locator("#range-end")).to_have_value("32")
    page.locator("#range-reset").click()
    expect(page.locator("#range-start")).to_have_value("0")
    expect(page.locator("#range-end")).to_have_value("120")
    set_range(page, "start", 15)
    set_range(page, "end", 50)
    page.locator("#download-btn").click()
    payload = page.evaluate("window.recorded.enqueued[0]")
    assert (payload["start_time"], payload["end_time"]) == (15, 50)
    assert payload["items"][0]["selection"] is None
    expect(page.locator("#range-section")).to_be_hidden()


@pytest.mark.parametrize("playlist", [False, True])
@pytest.mark.parametrize("side", ["start", "end"])
def test_dragging_range_keeps_layout_and_quality_controls_stable(page, playlist, side):
    page.set_viewport_size({"width": 600, "height": 700})
    page.locator("#url").fill("https://youtube.com/playlist?list=PL" if playlist else "https://youtu.be/one")
    expect(page.locator("#range-section")).to_be_visible()
    if playlist:
        expect(page.locator("#editor-title")).to_have_text("Első videó")
    page.evaluate("document.fonts.ready")
    page.locator('#quality input[value="720"]').check(force=True)
    page.locator("#range-slider").scroll_into_view_if_needed()
    # A minőségválasztó a húzás alatt is ugyanazokat az elemeket tartsa meg.
    page.evaluate("window.qualityBeforeDrag = [...document.querySelector('#quality').children]")
    measure = """() => ({
      scroll: scrollY,
      boxes: ['#range-slider', '#quality', 'form.card'].map(selector => {
        const rect = document.querySelector(selector).getBoundingClientRect();
        return [rect.x, rect.y, rect.width, rect.height];
      })
    })"""
    before = page.evaluate(measure)
    bounds = page.locator("#range-slider").bounding_box()
    x, y, width = bounds["x"] + 12, bounds["y"] + 24, bounds["width"] - 24
    page.mouse.move(x + (width if side == "end" else 0), y)
    page.mouse.down()
    for fraction in ([0.9, 0.6, 0.3, 1] if side == "end" else [0.1, 0.3, 0.6, 0]):
        page.mouse.move(x + width * fraction, y, steps=5)
        assert page.evaluate(measure) == before
        assert page.evaluate("window.qualityBeforeDrag.every((node, i) => node === document.querySelector('#quality').children[i])")
        expect(page.locator('#quality input[value="720"]')).to_be_checked()
        if fraction not in (0, 1):
            expect(page.locator("#quality small").first).to_be_hidden()
    page.mouse.up()
    expect(page.locator(f"#range-{side}")).to_have_value("120" if side == "end" else "0")
    expect(page.locator("#quality small").first).to_be_visible()


def test_late_metadata_cannot_replace_active_video(page):
    page.evaluate("window.deferId='two'")
    page.locator("#url").fill("https://youtube.com/playlist?list=PL")
    expect(page.locator("#editor-title")).to_have_text("Első videó")
    page.locator('.playlist-item[data-index="2"] .playlist-open').click()
    expect(page.locator("#editor-loading")).to_be_visible()
    page.locator('.playlist-item[data-index="3"] .playlist-open').click()
    expect(page.locator("#editor-title")).to_have_text("Harmadik videó")
    page.evaluate("window.resolveProbe({ok:true,info:window.videoData.two})")
    expect(page.locator("#editor-title")).to_have_text("Harmadik videó")
    page.locator('.playlist-item[data-index="2"] .playlist-open').click()
    expect(page.locator("#editor-title")).to_have_text("Második videó")
    expect(page.locator("#range-end")).to_have_value("240")


def test_changing_link_discards_old_ranges_and_small_window_fits(page):
    page.set_viewport_size({"width": 600, "height": 900})
    page.locator("#url").fill("https://youtu.be/one")
    expect(page.locator("#range-section")).to_be_visible()
    set_range(page, "start", 40)
    page.locator("#url").fill("https://youtu.be/three")
    expect(page.locator("#title")).to_have_text("Harmadik videó")
    expect(page.locator("#range-start")).to_have_value("0")
    expect(page.locator("#range-end")).to_have_value("60")
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")


def test_playlist_toggle_restores_single_video_range(page):
    page.locator("#url").fill("https://youtube.com/watch?v=one&list=PL")
    expect(page.locator("#range-section")).to_be_visible()
    set_range(page, "start", 20)
    set_range(page, "end", 40)
    page.locator("#playlist").check()
    expect(page.locator("#editor-title")).to_have_text("Első videó")
    set_range(page, "start", 5)
    set_range(page, "end", 15)
    page.locator("#playlist").uncheck()
    expect(page.locator("#editor-preview")).to_be_hidden()
    expect(page.locator("#range-start")).to_have_value("20")
    expect(page.locator("#range-end")).to_have_value("40")


def test_full_range_sends_no_cut_and_checkbox_does_not_change_editor(page):
    page.locator("#url").fill("https://youtube.com/playlist?list=PL")
    expect(page.locator("#editor-title")).to_have_text("Első videó")
    page.locator('.playlist-item[data-index="2"] .playlist-select').uncheck()
    expect(page.locator("#editor-title")).to_have_text("Első videó")
    page.locator("#download-btn").click()
    payload = page.evaluate("window.recorded.enqueued[0]")
    assert "start_time" not in payload
    assert [item["id"] for item in payload["items"][0]["selection"]] == ["one", "three"]
    assert all(item["options"]["start_time"] == 0 and item["options"]["end_time"] is None for item in payload["items"][0]["selection"])


@pytest.mark.parametrize("side,initial,target,offset_x,offset_y", [
    ("start", 20, 40, -15, 19),
    ("end", 100, 80, 15, -19),
])
def test_range_handles_can_be_grabbed_outside_visible_circle(page, side, initial, target, offset_x, offset_y):
    page.locator("#url").fill("https://youtu.be/one")
    expect(page.locator("#range-section")).to_be_visible()
    set_range(page, "start", 20)
    set_range(page, "end", 100)
    bounds = page.locator("#range-slider").bounding_box()
    width = bounds["width"] - 24
    x = bounds["x"] + 12 + width * initial / 120 + offset_x
    y = bounds["y"] + 24 + offset_y
    page.mouse.move(x, y)
    page.mouse.down()
    # A láthatatlan fogási terület szélén megfogva se ugorjon el az időpont.
    expect(page.locator(f"#range-{side}")).to_have_value(str(initial))
    page.mouse.move(x + width * (target - initial) / 120, y, steps=8)
    page.mouse.up()
    expect(page.locator(f"#range-{side}")).to_have_value(str(target))
    expect(page.locator("#range-end" if side == "start" else "#range-start")).to_have_value("100" if side == "start" else "20")


@pytest.mark.parametrize("side", ["start", "end"])
@pytest.mark.parametrize("end", [61, 66])
def test_close_range_handles_can_both_be_dragged(page, side, end):
    page.locator("#url").fill("https://youtu.be/one")
    expect(page.locator("#range-section")).to_be_visible()
    set_range(page, "start", 60)
    set_range(page, "end", end)
    bounds = page.locator("#range-slider").bounding_box()
    width, y = bounds["width"] - 24, bounds["y"] + 24
    # Az összecsúszott fogantyúk két fele a megfelelő végpontot mozgassa.
    offset = (-4 if end == 61 else 12) * (1 if side == "start" else -1)
    x = bounds["x"] + 12 + width * (60 if side == "start" else end) / 120 + offset
    page.mouse.move(x, y)
    page.mouse.down()
    expect(page.locator("#range-start")).to_have_value("60")
    expect(page.locator("#range-end")).to_have_value(str(end))
    page.mouse.move(bounds["x"] + 12 + width * (0.25 if side == "start" else 0.75) + offset, y, steps=8)
    page.mouse.up()
    expect(page.locator("#range-start")).to_have_value("30" if side == "start" else "60")
    expect(page.locator("#range-end")).to_have_value(str(end) if side == "start" else "90")


def test_queue_updates_video_image_even_when_download_state_is_unchanged(page):
    page.evaluate("""() => {
      window.queueItem = {id:1,url:'https://youtube.com/playlist?list=PL',title:'Tesztlista',mode:'video',container:'mp4',
        playlist:true,compatible:false,thumbnail:'video-one.jpg',state:'running',status:'Letöltés…',files:[]};
      window.app.onEvent({type:'queue',version:1,items:[window.queueItem]});
    }""")
    thumb = page.locator(".q-thumb")
    assert "video-one.jpg" in thumb.evaluate("el => el.style.backgroundImage")
    page.evaluate("window.app.onEvent({type:'queue',version:2,items:[{...window.queueItem,thumbnail:'video-two.jpg'}]})")
    assert "video-two.jpg" in thumb.evaluate("el => el.style.backgroundImage")
    assert "playlist.jpg" not in thumb.evaluate("el => el.style.backgroundImage")
    page.evaluate("window.app.onEvent({type:'queue',version:3,items:[{...window.queueItem,thumbnail:null}]})")
    assert thumb.evaluate("el => el.style.backgroundImage") == ""
    expect(thumb).not_to_have_class("q-thumb has-image")


@pytest.mark.parametrize("mode", ["video", "audio"])
def test_queue_shows_current_video_title_and_separate_playlist_label(page, mode):
    page.set_viewport_size({"width": 600, "height": 700})
    page.evaluate("""mode => {
      window.queueItem = {id:1,url:'https://youtube.com/playlist?list=PL',title:'Első videó',playlist_title:'Tesztlista',
        mode,container:'mp4',audio_format:'mp3',playlist:true,state:'queued',files:[]};
      window.app.onEvent({type:'queue',version:1,items:[window.queueItem]});
    }""", mode)
    expect(page.locator(".q-title")).to_have_text("Első videó")
    expect(page.locator(".q-playlist")).to_have_text("Lejátszási lista: Tesztlista")
    page.evaluate("""() => {
      window.app.onEvent({type:'queue',version:2,items:[{...window.queueItem,state:'running'}]});
      window.app.onEvent({type:'queue',version:3,items:[{...window.queueItem,state:'running',title:'Második videó'}]});
    }""")
    expect(page.locator(".q-title")).to_have_text("Második videó")
    expect(page.locator(".q-playlist")).to_have_text("Lejátszási lista: Tesztlista")
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    page.evaluate("window.app.onEvent({type:'queue',version:4,items:[{...window.queueItem,playlist:false,playlist_title:''}]})")
    expect(page.locator(".q-playlist")).to_be_hidden()


def test_playlist_from_video_link_sends_playlist_name_and_selected_video_title(page):
    page.locator("#url").fill("https://youtube.com/watch?v=one&list=PL")
    expect(page.locator("#title")).to_have_text("Első videó")
    page.locator("#playlist").check()
    expect(page.locator("#editor-title")).to_have_text("Első videó")
    page.locator("#download-btn").click()
    payload = page.evaluate("window.recorded.enqueued[0]")
    assert payload["items"][0]["playlist_title"] == "Tesztlista"
    assert payload["items"][0]["selection"][0]["title"] == "Első videó"
