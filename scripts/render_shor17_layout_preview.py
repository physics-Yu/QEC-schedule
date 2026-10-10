"""Render the static layout coordinates to an inspectable PNG, no simulation."""
from pathlib import Path
import json
from PIL import Image, ImageDraw, ImageFont

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'artifacts/demos/shor17-four-factory-layout-20261009'
L=json.loads((OUT/'layout.json').read_bytes())
im=Image.new('RGB',(1920,1410),'#fbfcfd');d=ImageDraw.Draw(im)
fontpath='C:/Windows/Fonts/msyh.ttc'
def font(size):return ImageFont.truetype(fontpath,size)
def text(x,y,s,size=20,fill='#405868',anchor=None):d.text((x,y),s,font=font(size),fill=fill,anchor=anchor)
scale=1.22;ox=76;oy=210
def point(x,y):return (ox+(x+60)*scale,oy+(y-385)*scale)
def rect(b,fill,outline=None,width=1):
    p=point(*b[:2])+point(*b[2:]);d.rounded_rectangle(p,radius=6,fill=fill,outline=outline,width=width)
def wt(x,y,s,size=18,fill='#405868',anchor=None):text(*point(x,y),s,size,fill,anchor)

text(56,30,'SHOR-17   /   INITIAL LAYOUT',17,'#8395a1')
text(56,60,'17 个 data 码块 + 右侧 4 座 magic factory',35,'#243d4d')
text(56,116,'沿用原 HRS 17 比特交互布局 · 全部工厂位于同一侧 · 只验收初始布局',21,'#687e8c')
for x,value,label in [(56,'289','data 原子'),(430,'480','magic 原子'),(812,'769','原子总数'),(1205,'2','AOD 系统')]:
    text(x,164,value,30,'#2f4959');text(x+92,173,label,18,'#6c818e')

rect(L['regions']['compute'],'#e7eef4','#cbd8e2')
rect(L['regions']['magic'],'#edf2ef','#d0ddd5')
rect(L['regions']['transfer_corridor'],'#f3f0e7')
wt(-6,405,'COMPUTE ZONE',22,'#38536a')
wt(600,405,'MAGIC FACTORY ZONE · 同一侧',22,'#486b59')
wt(1050,410,'每厂 120 原子 · 200 ms / magic',15,'#708977')
wt(512,685,'预留',15,'#958c6f');wt(512,706,'通道',15,'#958c6f')
for f in L['factories']:
    rect(f['bounds_um'],'#f8faf8','#cbd8ce')
    wt(f['bounds_um'][0]+3,f['origin_um'][1]+35,f['id'],15,'#597060')
for p in L['patches']:
    x,y=p['anchor_um'];rect([x,y,x+80,y+80],None,'#7ba18f' if p.get('output_carrier') else '#ccd7df',2 if p.get('output_carrier') else 1)
    wt(x+40,y+82,p['label'],16,'#526b7c','mt')
colors={'data':'#40586b','X':'#68a49b','Z':'#8c9cbd','probe':'#b29060'}
for a in L['atoms']:
    x,y=point(*a['xy_um']);r=4.1 if a['role']!='probe' else 5
    d.ellipse((x-r,y-r,x+r,y+r),fill=colors[a['role']])
wt(-6,969,'AOD_data · 289 原子',18,'#54728a')
wt(600,969,'AOD_magic · 四厂共用 · 480 原子',18,'#5a7968')
rect(L['regions']['measurement']['preview_bounds_um'],'#e9f1f4','#ccdfe6')
wt(0,1047,'MEASUREMENT ZONE',24,'#4e7184')
wt(0,1085,'横跨整个 x 轴；初始为空',19,'#708895')
wt(0,1118,'y = 1020–1220 μm',17,'#8095a0')
wt(-23,1185,'←',28,'#6b8799');wt(1350,1185,'→',28,'#6b8799')
px,py=point(1130,1180);qx,qy=point(1230,1180);d.line((px,py,qx,qy),fill='#7b909b',width=3);wt(1180,1190,'100 μm',15,'#7b909b','mt')
for x,role,name in [(70,'data','数据原子'),(350,'X','X ancilla'),(640,'Z','Z ancilla'),(930,'probe','factory probe')]:
    d.ellipse((x,1320,x+11,1331),fill=colors[role]);text(x+24,1310,name,18,'#677e8c')
text(70,1354,'所有原子初始驻留 SLM。200 ms 为指定单厂周期；未运行电路、蒸馏或异步调度。',18,'#748993')
im.save(OUT/'layout-overview.png')
print(OUT/'layout-overview.png')
