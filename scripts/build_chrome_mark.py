"""Rebuild the vector chrome edition of Wynxq's two arcs and core.

No dependencies, textures, shaders or runtime render loop. The resulting SVG
is rasterized once by Qt at the requested display size.
"""
from pathlib import Path
import math
import gzip

OUTPUT = Path(__file__).resolve().parents[1] / 'wynxq/assets/wynxq-chrome.svgz'

def unit(v):
    length = math.sqrt(sum(x*x for x in v))
    return tuple(x / length for x in v)

def rotate(v):
    x,y,z=v
    a,b=math.radians(31),math.radians(-24)
    y,z=y*math.cos(a)-z*math.sin(a),y*math.sin(a)+z*math.cos(a)
    return (x*math.cos(b)-y*math.sin(b),x*math.sin(b)+y*math.cos(b),z)

def shade(n):
    x,y,z=unit(rotate(n))
    # Reflected studio strips: cool broad fill, narrow white softbox and a
    # very subtle warm lower bounce. Dark bands give polished metal its depth.
    rx,ry,rz=2*x*z,2*y*z,2*z*z-1
    base=.12+.14*(ry+1)/2
    soft=.68*math.exp(-((ry+.40)/.23)**2)
    edge=.65*math.exp(-((rx+.66)/.16)**2)
    rim=.26*(1-abs(z))**3
    tone=min(1,base+soft+edge+rim)
    warm=.10*math.exp(-((ry-.67)/.08)**2)
    return '#%02x%02x%02x' % tuple(int(255*min(1,max(0,c))) for c in
        (tone*.95+warm,tone*.98+warm*.55,tone+warm*.18))

faces=[]
def add(points,normal):
    points=[rotate(p) for p in points]
    faces.append((sum(p[2] for p in points)/len(points),points,shade(normal)))

def ring(radius,tube,start,end,depth):
    count,sections=128,24
    def vertex(u,v):
        return ((radius+tube*math.cos(v))*math.cos(u),
                (radius+tube*math.cos(v))*math.sin(u),tube*math.sin(v)+depth)
    for i in range(count):
        u=start+(end-start)*i/count
        un=start+(end-start)*(i+1)/count
        for j in range(sections):
            v=j*math.tau/sections;vn=(j+1)*math.tau/sections
            mid=(u+un)/2;mv=(v+vn)/2
            add([vertex(u,v),vertex(un,v),vertex(un,vn),vertex(u,vn)],
                (math.cos(mv)*math.cos(mid),math.cos(mv)*math.sin(mid),math.sin(mv)))
    for u,sign in ((start,-1),(end,1)):
        add([vertex(u,j*math.tau/sections) for j in range(sections)],
            (-sign*math.sin(u),sign*math.cos(u),0))

ring(88,13,-math.pi*.62,math.pi*1.24,0)
ring(52,10,math.pi*.35,math.pi*1.72,9)
# The core stays a sphere, preserving the familiar small-size identity.
for i in range(40):
    for j in range(24):
        def sphere(u,v):
            return (19*math.cos(u)*math.sin(v),19*math.sin(u)*math.sin(v),19*math.cos(v)+16)
        u,un=i*math.tau/40,(i+1)*math.tau/40
        v,vn=j*math.pi/24,(j+1)*math.pi/24
        m=sphere((u+un)/2,(v+vn)/2)
        add([sphere(u,v),sphere(un,v),sphere(un,vn),sphere(u,vn)],(m[0],m[1],m[2]-16))

lines=['<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256" viewBox="-128 -128 256 256">',
       '<title>Wynxq — polished metal arcs and core</title>']
for _,points,color in sorted(faces,key=lambda f:f[0]):
    coords=' '.join(f'{x:.2f},{y:.2f}' for x,y,z in points)
    lines.append(f'<polygon points="{coords}" fill="{color}" stroke="{color}" stroke-width="0.25" stroke-linejoin="round"/>')
lines.append('</svg>')
OUTPUT.parent.mkdir(parents=True,exist_ok=True)
OUTPUT.write_bytes(gzip.compress(('\n'.join(lines)+'\n').encode(), mtime=0))
print(OUTPUT)
