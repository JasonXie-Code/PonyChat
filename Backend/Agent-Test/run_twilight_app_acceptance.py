"""Send the authorized Twilight regression prompts through the actual emulator UI."""
import base64
import argparse
import json
import re
import subprocess
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'Backend/Agent-Test/reports/emulator-unified-agent-20260906'
ADB=['P:/Tools/android-sdk/platform-tools/adb.exe','-s','emulator-5554']
CASES=[
 ('fresh',1,'紫悦，我们刚认识。你知道我喜欢喝什么茶吗？不知道就直接说不知道，正好回复一段，不要emoji。'),
 ('remember',2,'请记住，我喜欢无糖桂花茶。我们约好明天下午四点在图书馆门口见。请正好回复两段，不用emoji。'),
 ('cancel',3,'明天下午四点的见面取消了，还没有见面，请记下来。请正好回复三段，每段短一点，不用emoji。'),
 ('action',4,'（我从窗边站起来走到门口）我现在在哪里？请你把桌上的书递给我，动作和说话要区分。正好回复四段，每段简短，不用emoji。'),
 ('five',5,'给我五句适合今天的小鼓励，请正好分五段，每段不超过十五个字，不要列表、编号或emoji。'),
 ('expression',1,'我把空白纸也一本正经地归档了，哈哈！请用一个合适的emoji接我的玩笑，并发一张你的表情包，文字正好一段。'),
 ('serious',1,'今天被朋友误会了，我有点难过，不想听建议，只想你认真陪我一会儿。请正好回复一段，不要emoji或表情包。'),
 ('preference_update',1,'请记住，我现在更喜欢无糖乌龙茶了，以后的首选改成乌龙茶，但我没说讨厌桂花茶。请正好回复一段。'),
 ('recall',2,'我现在首选喝什么茶？我是不是讨厌桂花茶，明天下午四点还要赴约吗？请正好回复两段，不用emoji。'),
 ('review',1,'请在聊天后整理一下我们今天的记忆，尤其区分首选饮料、取消的约定和已经发生的动作。现在正好回复一段。'),
]

def dump():
    subprocess.run(ADB+['shell','uiautomator','dump','/sdcard/ponychat-ui.xml'],check=True,stdout=subprocess.DEVNULL)
    return ET.fromstring(subprocess.check_output(ADB+['shell','cat','/sdcard/ponychat-ui.xml']))

def tap(node):
    a,b,c,d=map(int,re.findall(r'\d+',node.get('bounds')))
    subprocess.run(ADB+['shell','input','tap',str((a+c)//2),str((b+d)//2)],check=True)

def messages(after):
    query=urllib.parse.urlencode(dict(username='System',character_id='twilight_sparkle',mode='normal',after_seq=after))
    for attempt in range(4):
        try:
            with urllib.request.urlopen('https://www.ponychat.org/api/conversation/messages_since?'+query,timeout=20) as response:
                return json.load(response)['new_messages']
        except (OSError,urllib.error.URLError):
            if attempt==3:raise
            time.sleep(2)


def await_display(text_rows,image_rows):
    """Database persistence precedes paced App delivery; do not send the next turn early."""
    required={r['content'] for r in text_rows[-1:]}
    required.update(a.get('name') or '表情' for r in image_rows for a in r.get('attachments',[]))
    deadline=time.monotonic()+90
    while time.monotonic()<deadline:
        tree=dump()
        visible={n.get('text') or n.get('content-desc') for n in tree.iter('node')}
        if required<=visible:return True
        viewport=next((n for n in tree.iter('node') if n.get('scrollable')=='true'),None)
        if viewport is not None:
            a,b,c,d=map(int,re.findall(r'\d+',viewport.get('bounds')))
            subprocess.run(ADB+['shell','input','swipe',str((a+c)//2),str(d-70),str((a+c)//2),str(b+70),'350'],check=True)
        time.sleep(3)
    return False

def run():
    OUT.mkdir(parents=True,exist_ok=True)
    target=OUT/'results.json'
    results=json.loads(target.read_text(encoding='utf8'))['cases'] if target.exists() else []
    for name,count,text in CASES[len(results):]:
        baseline=messages(-1); seq=max((r.get('sequence_number',0) for r in baseline),default=-1)
        latest=next((r for r in reversed(baseline) if r['role']=='user'),None)
        if latest and latest['content']==text:
            seq=latest['sequence_number']-1  # Resume observation after a read/network interruption; never resend.
        else:
            tree=dump()
            assert any(n.get('text')=='紫悦' for n in tree.iter('node'))
            tap(next(n for n in tree.iter('node') if n.get('class')=='android.widget.EditText'))
            subprocess.run(ADB+['shell','am','broadcast','-a','ADB_INPUT_B64','--es','msg',base64.b64encode(text.encode()).decode()],check=True,stdout=subprocess.DEVNULL)
            tree=dump()
            assert next(n for n in tree.iter('node') if n.get('class')=='android.widget.EditText').get('text')==text
            tap(next(n for n in tree.iter('node') if n.get('content-desc')=='发送'))
        print('Sent',name,flush=True)
        started=time.monotonic(); stable=None; last=None
        while time.monotonic()-started<210:
            rows=messages(seq)
            users=[r for r in rows if r['role']=='user' and r['content']==text]
            replies=[r for r in rows if r['role']=='assistant' and users and r.get('sequence_number',0)>users[-1].get('sequence_number',0)]
            signature=json.dumps(replies,sort_keys=True,ensure_ascii=False)
            if replies and signature==last:
                if stable is None:stable=time.monotonic()
                if time.monotonic()-stable>6:break
            else:stable=None
            last=signature
            time.sleep(3)
        else:raise RuntimeError('Reply timed out: '+name)
        text_rows=[r for r in replies if not r.get('attachments') and str(r.get('content') or '').strip()]
        image_rows=[r for r in replies if r.get('attachments') or r.get('imageUrl') or r.get('image_url')]
        displayed=await_display(text_rows,image_rows)
        result={'case':name,'input':text,'expected_text_bubbles':count,'text_bubbles':len(text_rows),
                'count_passed':len(text_rows)==count,'seconds':round(time.monotonic()-started,1),
                'user_messages':users,'replies':replies,'image_messages':len(image_rows),'final_items_visible_in_app':displayed}
        results.append(result)
        target.write_text(json.dumps({'scope':'System/twilight_sparkle; emulator-5554 actual App UI','apk':'5.6.19/359 debug','cases':results},ensure_ascii=False,indent=2),encoding='utf8')
        (OUT/(name+'.png')).write_bytes(subprocess.check_output(ADB+['exec-out','screencap','-p']))
        print('Completed',name,'bubbles',len(text_rows),'expected',count,flush=True)
        if not result['count_passed']:raise RuntimeError('Unexpected bubble count; inspect report')
        if not displayed:raise RuntimeError('Final items did not reach App UI; inspect delivery')

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--display-verification',action='store_true')
    args=parser.parse_args()
    if args.display_verification:
        OUT=ROOT/'Backend/Agent-Test/reports/emulator-unified-display-20260906'
        CASES=[(f'count_{n}',n,f'请给我正好{n}段简短的话，每段不超过十个字，不用编号，不用emoji。') for n in range(1,6)]+[
            ('expression_final',1,'哈哈，我连空白纸都整理得整整齐齐！请发一个emoji，再发一张适合的紫悦表情包，文字正好一段。'),
            ('scene_final',2,'（我已经从门口走到窗边）现在我在哪里？没有说过的事情不要加成回忆。请正好回复两段，其中一段写你递书给我的动作。'),
            ('review_final',1,'请在聊天后整理今天的记忆并生成今天的日摘，特别注意取消的见面没有发生。现在正好回复一段，后台没完成就直接说已安排。')]
    run()
