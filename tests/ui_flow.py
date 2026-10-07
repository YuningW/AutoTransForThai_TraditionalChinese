"""Drive the page in headless Chrome like a person would (no models or Claude needed):
start a job from a dropped-in file, flag a line with a note, edit a Chinese line, check the
server got it all, then screenshot. Needs a running server with a finished job.

    .venv/bin/python tests/ui_flow.py http://127.0.0.1:8779 <job_id> <video_file> <out_dir>
"""
import asyncio
import json
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

import websockets

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


class Page:
    def __init__(self, ws):
        self.ws, self.n = ws, 0

    async def send(self, method, **params):
        self.n += 1
        my = self.n
        await self.ws.send(json.dumps({"id": my, "method": method, "params": params}))
        while True:
            msg = json.loads(await self.ws.recv())
            if msg.get("id") == my:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error']}")
                return msg.get("result", {})

    async def js(self, expr):
        r = await self.send("Runtime.evaluate", expression=expr, awaitPromise=True, returnByValue=True)
        if r.get("exceptionDetails"):
            raise RuntimeError(r["exceptionDetails"].get("exception", {}).get("description") or r["exceptionDetails"])
        return r["result"].get("value")

    async def wait(self, expr, timeout=20):
        end = time.time() + timeout
        while time.time() < end:
            if await self.js(expr):
                return
            await asyncio.sleep(0.25)
        raise AssertionError("timed out waiting for: " + expr)

    async def click(self, selector):
        box = await self.js(f"""(() => {{ const e = document.querySelector({json.dumps(selector)});
            e.scrollIntoView({{block: 'center'}}); const r = e.getBoundingClientRect();
            return [r.x + r.width / 2, r.y + r.height / 2]; }})()""")
        for t in ("mousePressed", "mouseReleased"):
            await self.send("Input.dispatchMouseEvent", type=t, x=box[0], y=box[1], button="left", clickCount=1)

    async def type(self, text):
        await self.send("Input.insertText", text=text)

    async def shot(self, path):
        import base64
        r = await self.send("Page.captureScreenshot", format="png")
        Path(path).write_bytes(base64.b64decode(r["data"]))


def api(base, path):
    with urllib.request.urlopen(base + path) as r:
        return json.loads(r.read())


async def main(base, jid, video, out):
    prof = tempfile.mkdtemp(prefix="ac-ui-")
    chrome = subprocess.Popen([CHROME, "--headless=new", "--remote-debugging-port=9333", f"--user-data-dir={prof}",
                               "--window-size=1440,1000", "--hide-scrollbars", "about:blank"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(40):
            try:
                tabs = json.loads(urllib.request.urlopen("http://127.0.0.1:9333/json").read())
                break
            except OSError:
                await asyncio.sleep(0.25)
        ws_url = next(t["webSocketDebuggerUrl"] for t in tabs if t["type"] == "page")
        async with websockets.connect(ws_url, max_size=50_000_000) as ws:
            p = Page(ws)
            await p.send("Page.enable")
            await p.send("DOM.enable")
            await p.send("Emulation.setDeviceMetricsOverride", width=1440, height=1000, deviceScaleFactor=1, mobile=False)

            # 1. start page: choose a video file (what dropping does), then Make captions
            await p.send("Page.navigate", url=base + "/")
            await p.wait("document.querySelector('#jobList') && document.readyState === 'complete'")
            assert await p.js("document.querySelector('#go').disabled"), "Make captions should wait for a video"
            doc = await p.send("DOM.getDocument")
            node = await p.send("DOM.querySelector", nodeId=doc["root"]["nodeId"], selector="#videoFile")
            await p.send("DOM.setFileInputFiles", nodeId=node["nodeId"], files=[str(video)])
            await p.wait("!document.querySelector('#go').disabled")
            assert Path(video).name in await p.js("document.querySelector('#dropText').textContent")
            await p.click("#helpBox summary")
            await p.click("#about")
            await p.type("UI test upload")
            await p.shot(Path(out) / "ui_start.png")
            await p.click("#go")
            await p.wait("location.hash.startsWith('#/job/')", 60)
            new_id = (await p.js("location.hash")).split("/")[-1]
            job = api(base, f"/api/jobs/{new_id}")
            assert job["about"] == "UI test upload", job["about"]
            print("upload ok:", new_id, job["state"])

            # 2. open the finished job, flag line 5 as a translation problem with a note
            await p.send("Page.navigate", url=f"{base}/#/job/{jid}")
            await p.wait("document.querySelectorAll('#lines .line').length > 5")
            await p.click('.line[data-id="5"] .flag')
            await p.wait("!document.querySelector('.line[data-id=\"5\"] .flagbox').hidden")
            await p.click('.line[data-id="5"] [data-flag="translation"]')
            await p.wait("document.querySelector('.line[data-id=\"5\"]').classList.contains('flagged')")
            await p.click('.line[data-id="5"] .note')
            await p.type("too rude, she is teasing a friend")
            await p.click("#topTitle")                       # blur saves the note
            await asyncio.sleep(1)
            l5 = next(l for l in api(base, f"/api/jobs/{jid}/lines") if l["id"] == 5)
            assert l5["flag"] == "translation" and l5["note"] == "too rude, she is teasing a friend", l5
            assert not await p.js("document.querySelector('#fixbar').hidden"), "the Fix bar should show"
            print("flag ok:", l5["flag"], "|", l5["note"])

            # 3. type a new Chinese line
            await p.click('.line[data-id="6"] .zh')
            await p.send("Input.dispatchKeyEvent", type="keyDown", key="End", code="End", windowsVirtualKeyCode=35)
            await p.type("！")
            await p.send("Input.dispatchKeyEvent", type="keyDown", key="Enter", code="Enter", windowsVirtualKeyCode=13)
            await asyncio.sleep(1)
            l6 = next(l for l in api(base, f"/api/jobs/{jid}/lines") if l["id"] == 6)
            assert l6["status"] == "edited" and l6["zh"].endswith("！"), l6
            print("edit ok:", l6["zh"])

            # 4. click a time: the video jumps there and the overlay shows that line
            await p.click('.line[data-id="9"] .time')
            await asyncio.sleep(1.5)
            await p.js("document.querySelector('#video').pause()")
            ov = await p.js("document.querySelector('#ovBox').textContent")
            now = await p.js("document.querySelector('.line.now')?.dataset.id")
            print("seek ok: line", now, "|", ov)
            await p.shot(Path(out) / "ui_job.png")

            # 5. undo the test flag so the job is left as it was
            await p.click('.line[data-id="5"] .unflag')
            await asyncio.sleep(0.8)
            print("memory dialog:", await p.js("document.querySelector('#openMemory').textContent.trim()"))
            await p.click("#openMemory")
            await p.wait("document.querySelector('#memory').open")
            await asyncio.sleep(0.8)
            await p.shot(Path(out) / "ui_memory.png")
            return new_id
    finally:
        chrome.terminate()


if __name__ == "__main__":
    print(asyncio.run(main(*sys.argv[1:5])))
