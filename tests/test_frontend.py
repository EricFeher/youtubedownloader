"""A valódi HTML/CSS/JS felület tesztjei, helyi pywebview API-helyettessel."""

import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from playwright.sync_api import expect, sync_playwright


WEB = Path(__file__).resolve().parents[1] / "ytletolto" / "web"
API = r"""
window.recorded = { enqueued: [], saved: [], probes: [] };
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
  init:async()=>({settings:{output_dir:'/downloads',mode:'video',quality:'best',container:'mp4',audio_format:'mp3',compatible:false},
    ffmpeg:true,js_runtime:true,queue:{version:0,items:[]}}),
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


def set_range(page, side, seconds):
    page.locator(f"#range-{side}").evaluate("(input,value)=>{input.value=value;input.dispatchEvent(new Event('input',{bubbles:true}));}", seconds)


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


def test_close_range_handles_can_both_be_dragged(page):
    page.locator("#url").fill("https://youtu.be/one")
    expect(page.locator("#range-section")).to_be_visible()
    set_range(page, "start", 60)
    set_range(page, "end", 61)
    bounds = page.locator("#range-slider").bounding_box()
    width, y = bounds["width"] - 24, bounds["y"] + 24
    # Az összecsúszott fogantyúk bal felét megfogva a kezdet mozdul.
    x = bounds["x"] + 12 + width * 60 / 120 - 4
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(bounds["x"] + 12 + width / 4, y, steps=8)
    page.mouse.up()
    expect(page.locator("#range-start")).to_have_value("30")
    expect(page.locator("#range-end")).to_have_value("61")


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
