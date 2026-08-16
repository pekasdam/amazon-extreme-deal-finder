import csv, json, os, re, subprocess, sys, textwrap
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT=Path(__file__).resolve().parent
MANIFEST=Path(sys.argv[1] if len(sys.argv)>1 else os.environ.get('VIDEO_MANIFEST','em_property_group_factory/current_video.json'))
OUT=Path(os.environ.get('VIDEO_OUT','build/em_property_group'))
OUT.mkdir(parents=True, exist_ok=True)
W,H=1920,1080
NAVY=(6,31,55); NAVY2=(10,52,86); NAVY3=(14,66,105); WHITE=(246,248,251); MUTED=(184,199,214); GOLD=(246,184,53); GREEN=(63,201,128); RED=(239,86,91); BLUE=(90,177,235); GRID=(14,55,87)
FONT_B='/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'; FONT_R='/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
def F(n,b=True): return ImageFont.truetype(FONT_B if b else FONT_R,n)
def run(cmd): subprocess.run(cmd,check=True)
def ffprobe(path): return float(subprocess.check_output(['ffprobe','-v','error','-show_entries','format=duration','-of','default=nw=1:nk=1',str(path)],text=True).strip())
def color(name): return {'gold':GOLD,'green':GREEN,'red':RED,'blue':BLUE,'white':WHITE}.get(str(name).lower(),GOLD)

def base_slide():
    im=Image.new('RGB',(W,H),NAVY); d=ImageDraw.Draw(im)
    for x in range(0,W,96): d.line((x,0,x,H),fill=GRID,width=1)
    for y in range(0,H,96): d.line((0,y,W,y),fill=GRID,width=1)
    d.text((48,32),'EM PROPERTY GROUP',font=F(34),fill=WHITE)
    d.text((48,72),'REAL ESTATE INVESTING MADE SIMPLE',font=F(15),fill=GOLD)
    d.rounded_rectangle((1515,28,1874,77),radius=16,outline=GOLD,width=2)
    d.text((1552,43),'HYPOTHETICAL EXAMPLE',font=F(18),fill=GOLD)
    return im

def center(d,text,y,fo,fill=WHITE,maxw=1660,spacing=8):
    words=str(text).split(); lines=[]; cur=''
    for word in words:
        test=(cur+' '+word).strip()
        if d.textbbox((0,0),test,font=fo)[2] <= maxw: cur=test
        else:
            if cur: lines.append(cur)
            cur=word
    if cur: lines.append(cur)
    lh=fo.size+spacing
    for i,line in enumerate(lines):
        box=d.textbbox((0,0),line,font=fo); tw=box[2]-box[0]
        d.text(((W-tw)//2,y+i*lh),line,font=fo,fill=fill)
    return y+len(lines)*lh

def banner(d,value,accent=GOLD,sub=None):
    y=385; d.rounded_rectangle((245,y,1675,y+260),radius=44,fill=NAVY2,outline=accent,width=4)
    fo=F(90)
    while d.textbbox((0,0),value,font=fo)[2]>1330 and fo.size>44: fo=F(fo.size-4)
    box=d.textbbox((0,0),value,font=fo); tw=box[2]-box[0]
    d.text(((W-tw)//2,y+70),value,font=fo,fill=accent)
    if sub: center(d,sub,y+305,F(28,False),MUTED,1500)

def three(d,values,subs=None,accents=None):
    xs=[95,665,1235]; accents=accents or ['red','gold','green']
    for i,x in enumerate(xs):
        a=color(accents[i]); d.rounded_rectangle((x,355,x+490,760),radius=32,fill=NAVY2,outline=a,width=3)
        d.text((x+165,387),f'DEAL {chr(65+i)}',font=F(25),fill=MUTED)
        fo=F(60)
        while d.textbbox((0,0),values[i],font=fo)[2]>430 and fo.size>35: fo=F(fo.size-3)
        box=d.textbbox((0,0),values[i],font=fo); tw=box[2]-box[0]
        d.text((x+(490-tw)//2,470),values[i],font=fo,fill=a)
        if subs:
            box=d.textbbox((0,0),subs[i],font=F(21,False)); tw=box[2]-box[0]
            d.text((x+(490-tw)//2,690),subs[i],font=F(21,False),fill=MUTED)

def render_scene(scene,index):
    im=base_slide(); d=ImageDraw.Draw(im); center(d,scene['title'],155,F(54),WHITE)
    layout=scene.get('layout','banner')
    if layout=='three': three(d,scene['values'],scene.get('subs'),scene.get('accents'))
    elif layout in ('list','score'):
        y=330
        for n,item in enumerate(scene['items'],1):
            a=color(scene.get('accent','gold')) if layout=='list' else [BLUE,GOLD,GREEN,WHITE][(n-1)%4]
            d.rounded_rectangle((350,y,1570,y+100),radius=24,fill=NAVY2,outline=a,width=2)
            if layout=='list': d.text((395,y+28),f'{n}.',font=F(28),fill=a); x=465
            else: x=430
            d.text((x,y+29),item,font=F(31),fill=WHITE if layout=='list' else a)
            y+=122
    else: banner(d,scene['value'],color(scene.get('accent','gold')),scene.get('sub'))
    d.text((55,1023),'Hypothetical educational example • verify real-world numbers',font=F(18,False),fill=MUTED)
    p=OUT/f'scene_{index:02d}.png'; im.save(p); return p

def make_thumbnail(m):
    t=m['thumbnail']; im=Image.new('RGB',(1280,720),NAVY); d=ImageDraw.Draw(im)
    for x in range(0,1280,80): d.line((x,0,x,720),fill=GRID,width=1)
    for y in range(0,720,80): d.line((0,y,1280,y),fill=GRID,width=1)
    center2=lambda txt,y,fo,c: d.text(((1280-(d.textbbox((0,0),txt,font=fo)[2]))//2,y),txt,font=fo,fill=c)
    center2(t['headline'],55,F(60),WHITE)
    if 'values' in t:
        xs=[120,485,850]; cs=[RED,GOLD,GREEN]
        for x,val,c in zip(xs,t['values'],cs): d.text((x,180),val,font=F(86),fill=c)
    center2(t['hook'],345,F(60),GOLD)
    d.text((62,655),'EM PROPERTY GROUP',font=F(25),fill=WHITE)
    p=OUT/'thumbnail.jpg'; im.save(p,quality=94); return p

def srt_time(sec):
    ms=int(round(sec*1000)); h,ms=divmod(ms,3600000); m,ms=divmod(ms,60000); s,ms=divmod(ms,1000); return f'{h:02d}:{m:02d}:{s:02d},{ms:03d}'

def create_srt(texts,durs):
    out=OUT/'captions.srt'; n=1; t=0.0
    with out.open('w',encoding='utf-8') as f:
        for text,dur in zip(texts,durs):
            chunks=[s.strip() for s in re.split(r'(?<=[.!?])\s+',text) if s.strip()] or [text]
            weights=[max(1,len(c.split())) for c in chunks]; total=sum(weights); local=t
            for i,(c,w) in enumerate(zip(chunks,weights)):
                end=t+dur if i==len(chunks)-1 else local+dur*w/total
                f.write(f'{n}\n{srt_time(local)} --> {srt_time(end)}\n'+ '\n'.join(textwrap.wrap(c,52))+'\n\n'); n+=1; local=end
            t+=dur
    return out

def youtube_upload(video,thumb,captions,m):
    required=['YOUTUBE_CLIENT_ID','YOUTUBE_CLIENT_SECRET','YOUTUBE_REFRESH_TOKEN']
    if not all(os.environ.get(k) for k in required):
        print('YouTube OAuth secrets not configured; build completed without upload.'); return None
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    scopes=['https://www.googleapis.com/auth/youtube.upload','https://www.googleapis.com/auth/youtube.force-ssl']
    creds=Credentials(None,refresh_token=os.environ['YOUTUBE_REFRESH_TOKEN'],token_uri='https://oauth2.googleapis.com/token',client_id=os.environ['YOUTUBE_CLIENT_ID'],client_secret=os.environ['YOUTUBE_CLIENT_SECRET'],scopes=scopes); creds.refresh(Request())
    yt=build('youtube','v3',credentials=creds)
    body={'snippet':{'title':m['youtube']['title'],'description':m['youtube']['description'],'categoryId':'27','defaultLanguage':'en'},'status':{'privacyStatus':'private','selfDeclaredMadeForKids':False,'containsSyntheticMedia':True}}
    req=yt.videos().insert(part='snippet,status',body=body,media_body=MediaFileUpload(str(video),chunksize=-1,resumable=True)); resp=None
    while resp is None:
        _,resp=req.next_chunk()
    vid=resp['id']; print('Uploaded private YouTube video:',vid)
    yt.thumbnails().set(videoId=vid,media_body=MediaFileUpload(str(thumb))).execute()
    yt.captions().insert(part='snippet',body={'snippet':{'videoId':vid,'language':'en','name':'English'}},media_body=MediaFileUpload(str(captions))).execute()
    (OUT/'youtube_video_id.txt').write_text(vid)
    return vid

def main():
    m=json.loads(MANIFEST.read_text(encoding='utf-8')); scenes=m['scenes']; texts=[s['narration'] for s in scenes]
    scene_pngs=[render_scene(s,i) for i,s in enumerate(scenes,1)]
    audio=[]; durs=[]
    for i,text in enumerate(texts,1):
        txt=OUT/f'scene_{i:02d}.txt'; wav=OUT/f'scene_{i:02d}.wav'; txt.write_text(text+'\n')
        run([sys.executable,'-m','piper','-m','en_US-joe-medium','--data-dir','voices','--sentence-silence','0.12','--input-file',str(txt),'-f',str(wav)])
        audio.append(wav); durs.append(ffprobe(wav))
    acon=OUT/'audio_concat.txt'; acon.write_text('\n'.join(f"file '{p.resolve().as_posix()}'" for p in audio))
    master=OUT/'narration.wav'; run(['ffmpeg','-y','-loglevel','error','-f','concat','-safe','0','-i',str(acon),'-af','highpass=f=70,lowpass=f=12000,acompressor=threshold=-20dB:ratio=2.2:attack=8:release=90,loudnorm=I=-16:TP=-1.5:LRA=9','-ar','24000','-ac','1',str(master)])
    vcon=OUT/'visuals.txt'
    with vcon.open('w') as f:
        for p,d in zip(scene_pngs,durs): f.write(f"file '{p.resolve().as_posix()}'\nduration {d:.6f}\n")
        f.write(f"file '{scene_pngs[-1].resolve().as_posix()}'\n")
    final=OUT/'video_upload_ready.mp4'; run(['ffmpeg','-y','-loglevel','error','-f','concat','-safe','0','-i',str(vcon),'-i',str(master),'-vf','fps=30,scale=1920:1080:flags=lanczos,format=yuv420p','-c:v','libx264','-preset','veryfast','-crf','19','-c:a','aac','-b:a','160k','-ar','48000','-movflags','+faststart','-shortest',str(final)])
    thumb=make_thumbnail(m); captions=create_srt(texts,durs); youtube_upload(final,thumb,captions,m)
    print('Factory completed:',final)
if __name__=='__main__': main()
