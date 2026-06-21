/* PREAMBLE_PLACEHOLDER */

var scene,camera,renderer,controls,raycaster,mouse,interactive=[],hovered=null,isLocked=false,modalOpen=false;
var move={forward:false,backward:false,left:false,right:false};
var velocity=new THREE.Vector3(),direction=new THREE.Vector3(),clock=new THREE.Clock();

(function(){
var _euler=new THREE.Euler(0,0,0,'YXZ');var _PI_2=Math.PI/2;var _change={type:'change'};var _lock={type:'lock'};var _unlock={type:'unlock'};
THREE.PointerLockControls=function(camera,domElement){
var scope=this;var euler=new THREE.Euler(0,0,0,'YXZ');
this.domElement=domElement||document.body;this.isLocked=false;this.pointerSpeed=1.0;
function onMouseMove(event){if(!scope.isLocked)return;var mx=event.movementX||event.mozMovementX||event.webkitMovementX||0;var my=event.movementY||event.mozMovementY||event.webkitMovementY||0;euler.setFromQuaternion(camera.quaternion);euler.y-=mx*0.002*scope.pointerSpeed;euler.x-=my*0.002*scope.pointerSpeed;euler.x=Math.max(-_PI_2,Math.min(_PI_2,euler.x));camera.quaternion.setFromEuler(euler);scope.dispatchEvent(_change);}
function onPointerlockChange(){if(document.pointerLockElement===scope.domElement){scope.isLocked=true;scope.dispatchEvent(_lock);}else{scope.isLocked=false;scope.dispatchEvent(_unlock);}}
this.connect=function(){document.addEventListener('mousemove',onMouseMove);document.addEventListener('pointerlockchange',onPointerlockChange);};
this.disconnect=function(){document.removeEventListener('mousemove',onMouseMove);document.removeEventListener('pointerlockchange',onPointerlockChange);};
this.lock=function(){this.domElement.requestPointerLock();};
this.unlock=function(){document.exitPointerLock();};
this.moveForward=function(distance){var v=new THREE.Vector3();v.setFromMatrixColumn(camera.matrix,0);v.crossVectors(camera.up,v);camera.position.addScaledVector(v,distance);};
this.moveRight=function(distance){var v=new THREE.Vector3();v.setFromMatrixColumn(camera.matrix,0);camera.position.addScaledVector(v,distance);};
this.getDirection=function(v){return v.copy(camera.getWorldDirection(new THREE.Vector3()));};
this.connect();};
THREE.PointerLockControls.prototype=Object.create(THREE.EventDispatcher.prototype);
THREE.PointerLockControls.prototype.constructor=THREE.PointerLockControls;
})();

/* ── 高分辨率文字纹理 ── */
function mkTex(text,sub,w,h){
var c=document.createElement('canvas'),x=c.getContext('2d');
var scale=3;  // 3倍渲染，大幅提高清晰度
c.width=w*scale;c.height=h*scale;
x.scale(scale,scale);
var cw=w,ch=h;
x.fillStyle='rgba(255,248,232,.96)';x.fillRect(0,0,cw,ch);
x.strokeStyle='#b78a2f';x.lineWidth=4;x.strokeRect(10,10,cw-20,ch-20);
x.fillStyle='#8c1d18';x.textAlign='center';
// 根据canvas宽度动态计算字体大小
var fontSize=Math.min(28,Math.max(16,Math.floor(cw/30)));
x.font='bold '+fontSize+'px "Microsoft YaHei","SimHei",sans-serif';
var lineH=fontSize+8;
var maxW=cw-40;
var lines=(text||'').split('\n');
var startY=30+fontSize/2;
for(var li=0;li<lines.length;li++){
  var l=lines[li],lx='',ly=startY;
  for(var ci=0;ci<l.length;ci++){
    var test=lx+l[ci];
    if(x.measureText(test).width>maxW&&lx){x.fillText(lx,cw/2,ly);lx=l[ci];ly+=lineH;}
    else lx=test;
  }
  x.fillText(lx,cw/2,ly);startY=ly+lineH;
}
// 副标题
var subSize=Math.max(12,fontSize-8);
x.fillStyle='#9a6b1f';x.font=subSize+'px "Microsoft YaHei","SimHei",sans-serif';
var sx='',sy=startY+6;
var subMaxW=maxW-20;
for(var si=0;si<(sub||'').length;si++){
  var st=sx+sub[si];
  if(x.measureText(st).width>subMaxW&&sx){x.fillText(sx,cw/2,sy);sx=sub[si];sy+=subSize+4;}
  else sx=st;
}
x.fillText(sx,cw/2,sy);
var tex=new THREE.CanvasTexture(c);tex.minFilter=THREE.LinearFilter;tex.magFilter=THREE.LinearFilter;return tex;
}

function mkTexDark(text,sub,w,h){
var c=document.createElement('canvas'),x=c.getContext('2d');
var scale=3;
c.width=w*scale;c.height=h*scale;
x.scale(scale,scale);
var cw=w,ch=h;
x.fillStyle='rgba(45,30,20,.95)';x.fillRect(0,0,cw,ch);
x.strokeStyle='#b78a2f';x.lineWidth=3;x.strokeRect(8,8,cw-16,ch-16);
x.fillStyle='#f5e6c8';x.textAlign='center';
var fontSize=Math.min(26,Math.max(14,Math.floor(cw/32)));
x.font='bold '+fontSize+'px "Microsoft YaHei","SimHei",sans-serif';
var lineH=fontSize+6;
var maxW=cw-36;
var lines=(text||'').split('\n');
var startY=26+fontSize/2;
for(var li=0;li<lines.length;li++){
  var l=lines[li],lx='',ly=startY;
  for(var ci=0;ci<l.length;ci++){
    var test=lx+l[ci];
    if(x.measureText(test).width>maxW&&lx){x.fillText(lx,cw/2,ly);lx=l[ci];ly+=lineH;}
    else lx=test;
  }
  x.fillText(lx,cw/2,ly);startY=ly+lineH;
}
var subSize=Math.max(12,fontSize-6);
x.fillStyle='#d4b896';x.font=subSize+'px "Microsoft YaHei","SimHei",sans-serif';
var sx='',sy=startY+4;
var subMaxW=maxW-16;
for(var si=0;si<(sub||'').length;si++){
  var st=sx+sub[si];
  if(x.measureText(st).width>subMaxW&&sx){x.fillText(sx,cw/2,sy);sx=sub[si];sy+=subSize+4;}
  else sx=st;
}
x.fillText(sx,cw/2,sy);
var tex=new THREE.CanvasTexture(c);tex.minFilter=THREE.LinearFilter;tex.magFilter=THREE.LinearFilter;return tex;
}

function imgTex(src,title){if(!src)return mkTexDark('[档案影像]',title,256,192);var resolved=src;if(src.indexOf('://')<0&&src.indexOf('/')!==0){resolved='./'+src;}var placeholder=mkTexDark('档案影像','加载中…',256,192);var tex=new THREE.Texture(placeholder.image);tex.minFilter=THREE.LinearFilter;tex.magFilter=THREE.LinearFilter;var img=new Image();img.onload=function(){tex.image=img;tex.colorSpace=THREE.SRGBColorSpace;tex.needsUpdate=true;};img.onerror=function(){var fail=mkTexDark('[图片加载失败]',title||'',256,192);tex.image=fail.image;tex.needsUpdate=true;};img.src=resolved;return tex}

function init(){
var container=document.getElementById('cv');scene=new THREE.Scene();scene.background=new THREE.Color(0xe8dfd2);scene.fog=new THREE.FogExp2(0xe8dfd2,.02);
camera=new THREE.PerspectiveCamera(60,innerWidth/innerHeight,.1,200);camera.position.set(0,1.7,8);camera.lookAt(0,1.5,-6);
renderer=new THREE.WebGLRenderer({antialias:true});renderer.setSize(innerWidth,innerHeight);renderer.setPixelRatio(Math.min(devicePixelRatio,2));renderer.shadowMap.enabled=true;renderer.shadowMap.type=THREE.PCFSoftShadowMap;renderer.toneMapping=THREE.ACESFilmicToneMapping;renderer.toneMappingExposure=1.3;container.appendChild(renderer.domElement);
controls=new THREE.PointerLockControls(camera,document.body);
controls.addEventListener('lock',function(){isLocked=true;document.getElementById('crosshair').style.opacity='1';document.getElementById('hint').classList.add('hidden');document.getElementById('header').style.opacity='0';document.getElementById('ctls').style.opacity='0.6';});
controls.addEventListener('unlock',function(){isLocked=false;document.getElementById('crosshair').style.opacity='0';if(!modalOpen){document.getElementById('hint').classList.remove('hidden');document.getElementById('header').style.opacity='1';document.getElementById('ctls').style.opacity='1';}});
document.getElementById('hint').addEventListener('click',function(){if(!modalOpen)controls.lock();});
document.querySelector('.btn').addEventListener('click',function(e){e.stopPropagation();if(!modalOpen)controls.lock();});
document.addEventListener('keydown',onKeyDown);document.addEventListener('keyup',onKeyUp);
raycaster=new THREE.Raycaster();mouse=new THREE.Vector2(0,0);
buildLights();buildHall();placeExhibits();
window.addEventListener('resize',onResize);
window.addEventListener('mousemove',onHover);
window.addEventListener('click',function(ev){var m=document.getElementById('modal');if(ev.target.closest&&ev.target.closest('#modal'))return;if(m.classList.contains('show'))return;if(hovered)showModal(hovered.userData);});
setTimeout(function(){document.getElementById('loading').classList.add('hidden');},2000);
animate();}

function buildLights(){
scene.add(new THREE.AmbientLight(0xfff2d8,1.4));
scene.add(new THREE.HemisphereLight(0xfff8e8,0xd8b46a,.65));
var sun=new THREE.DirectionalLight(0xfff8e8,2.2);sun.position.set(8,10,10);sun.castShadow=true;sun.shadow.mapSize.set(2048,2048);scene.add(sun);
var fill=new THREE.DirectionalLight(0xffe4b0,.7);fill.position.set(-10,6,8);scene.add(fill);
var spot=new THREE.SpotLight(0xfff4d6,5);spot.position.set(0,7,4);spot.target.position.set(0,0,0);spot.angle=Math.PI/3;spot.penumbra=.55;spot.distance=40;spot.castShadow=true;scene.add(spot);scene.add(spot.target);
}

function buildHall(){
var W=36,D=24,wallH=8;
var group=new THREE.Group();
var floor=new THREE.Mesh(new THREE.PlaneGeometry(W,D),new THREE.MeshStandardMaterial({color:0xd6c8b0,roughness:.32,metalness:.04}));floor.rotation.x=-Math.PI/2;floor.receiveShadow=true;group.add(floor);
var carpet=new THREE.Mesh(new THREE.PlaneGeometry(6,D-4),new THREE.MeshStandardMaterial({color:0x8c1d18,roughness:.55,metalness:0}));carpet.rotation.x=-Math.PI/2;carpet.position.y=.025;group.add(carpet);
for(var rz=-D/3;rz<=D/3;rz+=D/3){var stripe=new THREE.Mesh(new THREE.PlaneGeometry(W-2,.06),new THREE.MeshBasicMaterial({color:0xb78a2f,transparent:true,opacity:.55,side:THREE.DoubleSide}));stripe.rotation.x=-Math.PI/2;stripe.position.set(0,.04,rz);group.add(stripe);}
var wallMat=new THREE.MeshStandardMaterial({color:0x5c3a21,roughness:.48,metalness:0,side:THREE.DoubleSide});
var backWall=new THREE.Mesh(new THREE.PlaneGeometry(W,wallH),wallMat);backWall.position.set(0,wallH/2,-D/2);group.add(backWall);
var leftWall=new THREE.Mesh(new THREE.PlaneGeometry(D,wallH),wallMat);leftWall.rotation.y=Math.PI/2;leftWall.position.set(-W/2,wallH/2,0);group.add(leftWall);
var rightWall=leftWall.clone();rightWall.position.set(W/2,wallH/2,0);group.add(rightWall);
var frontWall=new THREE.Mesh(new THREE.PlaneGeometry(W,wallH),wallMat);frontWall.position.set(0,wallH/2,D/2);frontWall.rotation.y=Math.PI;group.add(frontWall);
/* TITLE_BAND_PLACEHOLDER */
/* GOLD_BAND_PLACEHOLDER */
/* TITLE_MESH_PLACEHOLDER */
/* SUB_MESH_PLACEHOLDER */
var ceiling=new THREE.Mesh(new THREE.PlaneGeometry(W,D),new THREE.MeshStandardMaterial({color:0xf0e6d0,roughness:.45,metalness:0,side:THREE.DoubleSide}));ceiling.rotation.x=Math.PI/2;ceiling.position.y=wallH;group.add(ceiling);
scene.add(group);
}

/* ── 墙板：动态字体大小，3倍分辨率 ── */
function buildWallPanel(text,sub,w,h,x,y,z,ry){
var tex=mkTex(text,sub,w,h);
var mat=new THREE.MeshBasicMaterial({map:tex,transparent:true,side:THREE.DoubleSide});
var mesh=new THREE.Mesh(new THREE.PlaneGeometry(w/200,h/200),mat);
mesh.position.set(x,y,z);
if(ry)mesh.rotation.y=ry;
return mesh;
}

function buildWallPanelDark(text,sub,w,h,x,y,z,ry){
var tex=mkTexDark(text,sub,w,h);
var mat=new THREE.MeshBasicMaterial({map:tex,transparent:true,side:THREE.DoubleSide});
var mesh=new THREE.Mesh(new THREE.PlaneGeometry(w/200,h/200),mat);
mesh.position.set(x,y,z);
if(ry)mesh.rotation.y=ry;
return mesh;
}

/* ── 时间线面板：图文分列，避免重叠 ── */
function buildTimelinePanel(e,idx,total){
var g=new THREE.Group();g.userData=e;
var pw=3.6,ph=1.6;
var bg=new THREE.Mesh(new THREE.PlaneGeometry(pw,ph),new THREE.MeshBasicMaterial({color:0x2d1e12,transparent:true,opacity:.93,side:THREE.DoubleSide}));
g.add(bg);
var border=new THREE.Mesh(new THREE.PlaneGeometry(pw+.06,ph+.06),new THREE.MeshBasicMaterial({color:0xb78a2f,transparent:true,opacity:.75,side:THREE.DoubleSide}));
border.position.z=-.01;g.add(border);
// 左侧图片区域（固定宽度1.1）
if(e.image){
  var imgMesh=new THREE.Mesh(new THREE.PlaneGeometry(1.0,.75),new THREE.MeshBasicMaterial({map:imgTex(e.image,e.title),side:THREE.DoubleSide}));
  imgMesh.position.set(-pw/2+.65,0,.02);g.add(imgMesh);
}
// 右侧文字区域
var textX=pw/2-.95;
// 日期
var dateTex=mkTexDark(e.date||'','',360,64);
var dateMesh=new THREE.Mesh(new THREE.PlaneGeometry(1.7,.2),new THREE.MeshBasicMaterial({map:dateTex,transparent:true,side:THREE.DoubleSide}));
dateMesh.position.set(textX,ph/2-.2,.02);g.add(dateMesh);
// 标题
var titleTex=mkTexDark(e.title||e.event||'','',360,64);
var titleMesh=new THREE.Mesh(new THREE.PlaneGeometry(1.7,.2),new THREE.MeshBasicMaterial({map:titleTex,transparent:true,side:THREE.DoubleSide}));
titleMesh.position.set(textX,ph/2-.48,.02);g.add(titleMesh);
// 描述（限制35字）
var descText=(e.description||'').substring(0,35);
var descTex=mkTexDark(descText,'',360,128);
var descMesh=new THREE.Mesh(new THREE.PlaneGeometry(1.7,.5),new THREE.MeshBasicMaterial({map:descTex,transparent:true,side:THREE.DoubleSide}));
descMesh.position.set(textX,-ph/2+.4,.02);g.add(descMesh);
return g;
}

/* ── 照片框（带边框的墙面照片，标签内置避免重叠） ── */
function buildPhotoFrame(e,x,y,z,ry){
var g=new THREE.Group();g.userData=e;
var pw=1.6,ph=1.4;
// 边框
var frame=new THREE.Mesh(new THREE.PlaneGeometry(pw+.08,ph+.08),new THREE.MeshBasicMaterial({color:0xb78a2f,side:THREE.DoubleSide}));
g.add(frame);
// 深色底板（让标签文字清晰）
var bgPlate=new THREE.Mesh(new THREE.PlaneGeometry(pw,ph),new THREE.MeshBasicMaterial({color:0x2d1e12,side:THREE.DoubleSide}));
bgPlate.position.z=.005;g.add(bgPlate);
// 照片（不使用 transparent，避免未加载时透出边框）
  var photo=new THREE.Mesh(new THREE.PlaneGeometry(pw-.1,ph-.45),new THREE.MeshBasicMaterial({map:imgTex(e.image,e.title),side:THREE.DoubleSide}));
photo.position.set(0,.2,.01);g.add(photo);
// 标签（内置在框底部）
if(e.title||e.date){
  var labelTex=mkTexDark(e.title||'',e.date||'',320,64);
  var label=new THREE.Mesh(new THREE.PlaneGeometry(pw-.1,.2),new THREE.MeshBasicMaterial({map:labelTex,transparent:true,side:THREE.DoubleSide}));
  label.position.set(0,-ph/2+.18,.02);g.add(label);
}
g.position.set(x,y,z);if(ry)g.rotation.y=ry;
return g;
}

function placeExhibits(){
var groups={overview:[],timeline:[],figures:[],spirit:[],images:[],other:[]};
for(var i=0;i<exhibitsData.length;i++){var e=exhibitsData[i];if(e.id==='overview')groups.overview.push(e);else if(e.id&&e.id.indexOf('tl-')===0)groups.timeline.push(e);else if(e.id&&e.id.indexOf('fig-')===0)groups.figures.push(e);else if(e.id==='spirit')groups.spirit.push(e);else if(e.id&&e.id.indexOf('img-')===0)groups.images.push(e);else groups.other.push(e);}

/* === 前墙：档案主题大标题 + 序言 === */
var W=36,D=24;
if(groups.overview.length>0){
  var ov=groups.overview[0];
  var ovPanel=buildWallPanel(ov.title,ov.description,800,600,0,1.5,-D/2+.2,0);
  scene.add(ovPanel);
  var ovLight=new THREE.PointLight(0xfff0d0,1.5,8);ovLight.position.set(0,2.5,-D/2+1);scene.add(ovLight);
}

/* === 左墙：时间线标题 + 事件 === */
if(groups.timeline.length>0){
  var tlTitle=buildWallPanelDark('时间历程','按时间顺序展示档案事件',640,128,-W/2+.2,2.2,0,Math.PI/2);
  scene.add(tlTitle);
  var tls=groups.timeline;
  var maxTL=Math.min(tls.length,5);
  var tlSpan=D-4;
  var tlStep=tlSpan/Math.max(1,maxTL);
  for(var i=0;i<maxTL;i++){
    var z=-tlSpan/2+i*tlStep+tlStep/2;
    var panel=buildTimelinePanel(tls[i],i,maxTL);
    panel.position.set(-W/2+.2,1.6,z);
    panel.rotation.y=Math.PI/2;
    scene.add(panel);
    interactive.push(panel);
    var tlSpot=new THREE.SpotLight(0xfff4d6,2);tlSpot.position.set(-W/2+2,3,z);tlSpot.target=panel;tlSpot.angle=Math.PI/6;tlSpot.penumbra=.5;tlSpot.distance=6;scene.add(tlSpot);
  }
}

/* === 右墙：人物档案标题 + 人物照片 === */
if(groups.figures.length>0){
  var figTitle=buildWallPanelDark('人物档案','关键人物与事迹',640,128,W/2-.2,2.2,0,-Math.PI/2);
  scene.add(figTitle);
  var maxFig=Math.min(groups.figures.length,5);
  var figSpan=D-4;
  var figStep=figSpan/Math.max(1,maxFig);
  for(var i=0;i<maxFig;i++){
    var fig=groups.figures[i];
    var z=-figSpan/2+i*figStep+figStep/2;
    if(fig.image){
      var frame=buildPhotoFrame(fig,W/2-.2,1.6,z,-Math.PI/2);
      scene.add(frame);interactive.push(frame);
    }else{
      var figText=buildWallPanelDark(fig.title||fig.name||'',fig.description||fig.bio||'',480,320,W/2-.2,1.6,z,-Math.PI/2);
      scene.add(figText);interactive.push(figText);
    }
  }
}

/* === 后墙：精神总结 === */
if(groups.spirit.length>0){
  var sp=groups.spirit[0];
  var spPanel=buildWallPanel(sp.title,sp.description,800,600,0,1.5,D/2-.2,Math.PI);
  scene.add(spPanel);
  var spLight=new THREE.PointLight(0xfff0d0,1.5,8);spLight.position.set(0,2.5,D/2-1);scene.add(spLight);
}

/* === 四面墙下方：照片墙（减少数量，增大间距） === */
var allImgs=groups.images.concat(groups.other);
var maxImg=Math.min(allImgs.length,8);
// 前墙下方两侧
var frontImgCount=Math.min(2,Math.floor(maxImg/4));
for(var i=0;i<frontImgCount;i++){
  var side=i%2===0?-1:1;
  var x=side*(W/4);
  var z=-D/2+.2;
  if(allImgs[i]&&allImgs[i].image){
    var frame=buildPhotoFrame(allImgs[i],x,1.4,z,0);
    scene.add(frame);interactive.push(frame);
  }
}
// 后墙下方两侧
var backStart=frontImgCount;
var backImgCount=Math.min(2,Math.floor((maxImg-backStart)/3));
for(var i=0;i<backImgCount;i++){
  var side=i%2===0?-1:1;
  var x=side*(W/4);
  var z=D/2-.2;
  var idx2=backStart+i;
  if(allImgs[idx2]&&allImgs[idx2].image){
    var frame=buildPhotoFrame(allImgs[idx2],x,1.4,z,Math.PI);
    scene.add(frame);interactive.push(frame);
  }
}
// 左墙下方
var leftStart=backStart+backImgCount;
var leftImgCount=Math.min(2,maxImg-leftStart);
for(var i=0;i<leftImgCount;i++){
  var z=-D/4+i*D/2;
  var idx3=leftStart+i;
  if(allImgs[idx3]&&allImgs[idx3].image){
    var frame=buildPhotoFrame(allImgs[idx3],-W/2+.2,1.4,z,Math.PI/2);
    scene.add(frame);interactive.push(frame);
  }
}
// 右墙下方
var rightStart=leftStart+leftImgCount;
var rightImgCount=Math.min(2,maxImg-rightStart);
for(var i=0;i<rightImgCount;i++){
  var z=-D/4+i*D/2;
  var idx4=rightStart+i;
  if(allImgs[idx4]&&allImgs[idx4].image){
    var frame=buildPhotoFrame(allImgs[idx4],W/2-.2,1.4,z,-Math.PI/2);
    scene.add(frame);interactive.push(frame);
  }
}

/* === 展柜：大厅中央 === */
var caseStart=rightStart+rightImgCount;
var caseImgCount=maxImg-caseStart;
var caseSpacing=5;
for(var i=0;i<caseImgCount;i++){
  var idx5=caseStart+i;
  if(allImgs[idx5]&&allImgs[idx5].image){
    var zCase=i*caseSpacing-(caseImgCount-1)*caseSpacing/2;
    var exhibit=createExhibit(allImgs[idx5]);
    exhibit.position.set(0,0,zCase);
    scene.add(exhibit);interactive.push(exhibit);
  }
}
}

/* ── 展柜（陈列墙上放不下的照片） ── */
function createExhibit(e){
var g=new THREE.Group();g.userData=e;
var base=new THREE.Mesh(new THREE.BoxGeometry(2.2,.35,1.2),new THREE.MeshStandardMaterial({color:0x8c1d18,roughness:.5,metalness:.08}));base.position.y=.18;base.castShadow=true;g.add(base);
var glass=new THREE.Mesh(new THREE.BoxGeometry(2.2,2.2,1.2),new THREE.MeshPhysicalMaterial({color:0xfff8e8,metalness:0,roughness:.12,transmission:.75,transparent:true,opacity:.22,side:THREE.DoubleSide}));glass.position.y=1.3;g.add(glass);
if(e.image){
  var imgPanel=new THREE.Mesh(new THREE.PlaneGeometry(1.8,1.4),new THREE.MeshBasicMaterial({map:imgTex(e.image,e.title),side:THREE.DoubleSide}));
  imgPanel.position.set(0,1.5,.3);g.add(imgPanel);
  var labelBg=new THREE.Mesh(new THREE.PlaneGeometry(1.8,.45),new THREE.MeshBasicMaterial({color:0x8c1d18,transparent:true,opacity:.85,side:THREE.DoubleSide}));
  labelBg.position.set(0,.6,.3);g.add(labelBg);
  var label=new THREE.Mesh(new THREE.PlaneGeometry(1.7,.35),new THREE.MeshBasicMaterial({map:mkTex(e.title||'',e.date||'',640,128),transparent:true}));
  label.position.set(0,.6,.32);g.add(label);
  // 简介标签（截断至40字）
  if(e.description){
    var descShort=(e.description||'').substring(0,40);
    var descTex=mkTexDark(descShort,'',640,96);
    var descMesh=new THREE.Mesh(new THREE.PlaneGeometry(1.7,.25),new THREE.MeshBasicMaterial({map:descTex,transparent:true,side:THREE.DoubleSide}));
    descMesh.position.set(0,.25,.32);g.add(descMesh);
  }
}else{
  var panel=new THREE.Mesh(new THREE.PlaneGeometry(1.8,1.4),new THREE.MeshStandardMaterial({map:mkTex(e.title||'',e.date||'',512,384),roughness:.55,side:THREE.DoubleSide}));
  panel.position.set(0,1.5,.3);g.add(panel);
  var label=new THREE.Mesh(new THREE.PlaneGeometry(2,.4),new THREE.MeshBasicMaterial({map:mkTex(e.title||'',e.date||'',640,128),transparent:true}));
  label.position.set(0,.7,.65);g.add(label);
}
var glow=new THREE.Mesh(new THREE.RingGeometry(.95,1.35,40),new THREE.MeshBasicMaterial({color:0xb78a2f,transparent:true,opacity:.16,side:THREE.DoubleSide}));glow.rotation.x=-Math.PI/2;glow.position.y=.03;g.add(glow);g.userData.glow=glow;
return g;
}

function onKeyDown(event){
  var m=document.getElementById('modal');
  if(event.code==='Escape'&&m.classList.contains('show')){closeModal();event.preventDefault();return;}
  switch(event.code){
    case'ArrowUp':case'KeyW':move.forward=true;break;
    case'ArrowLeft':case'KeyA':move.left=true;break;
    case'ArrowDown':case'KeyS':move.backward=true;break;
    case'ArrowRight':case'KeyD':move.right=true;break;
  }
}
function onKeyUp(event){
  switch(event.code){
    case'ArrowUp':case'KeyW':move.forward=false;break;
    case'ArrowLeft':case'KeyA':move.left=false;break;
    case'ArrowDown':case'KeyS':move.backward=false;break;
    case'ArrowRight':case'KeyD':move.right=false;break;
  }
}
function onResize(){camera.aspect=innerWidth/innerHeight;camera.updateProjectionMatrix();renderer.setSize(innerWidth,innerHeight);}
function onHover(ev){
raycaster.setFromCamera(new THREE.Vector2(0,0),camera);
var hits=raycaster.intersectObjects(interactive,true),found=null;
for(var i=0;i<hits.length;i++){
  var o=hits[i].object;
  while(o.parent&&(!o.userData.title&&!o.userData.event))o=o.parent;
  if(o.userData.title||o.userData.event){found=o;break;}
}
if(found!==hovered){
  if(hovered&&hovered.userData.glow)hovered.userData.glow.material.opacity=.12;
  hovered=found;
  if(hovered&&hovered.userData.glow)hovered.userData.glow.material.opacity=.35;
}
var tp=document.getElementById('tooltip');
if(hovered){
  tp.style.display='block';
  tp.style.left=(ev.clientX+18)+'px';
  tp.style.top=(ev.clientY+18)+'px';
  tp.innerHTML='<strong>'+(hovered.userData.title||hovered.userData.event||'')+'</strong><div class=meta>'+(hovered.userData.date||'')+'</div>点击查看档案详情';
}else tp.style.display='none';
}
function showModal(e){modalOpen=true;document.getElementById('hint').classList.add('hidden');document.getElementById('header').style.opacity='0';var m=document.getElementById('modal');if(controls&&controls.isLocked)controls.unlock();document.getElementById('modal-title').textContent=e.title||e.event||'';document.getElementById('modal-date').textContent=e.date||'';document.getElementById('modal-desc').textContent=e.description||'';var img=document.getElementById('modal-img');if(e.image){var resolved=e.image;if(e.image.indexOf('://')<0&&e.image.indexOf('/')!==0)resolved='./'+e.image;img.src=resolved;img.style.display='block';}else img.style.display='none';m.classList.add('show');}
window.closeModal=function(event){if(event&&event.stopPropagation)event.stopPropagation();modalOpen=false;document.getElementById('modal').classList.remove('show');document.getElementById('hint').classList.add('hidden');document.getElementById('header').style.opacity='0';if(controls&&!controls.isLocked)controls.lock();}
function animate(){requestAnimationFrame(animate);var delta=Math.min(clock.getDelta(),.05);
velocity.x-=velocity.x*10*delta;velocity.z-=velocity.z*10*delta;
direction.z=Number(move.forward)-Number(move.backward);direction.x=Number(move.right)-Number(move.left);direction.normalize();
if(controls.isLocked){
  if(move.forward||move.backward)velocity.z-=direction.z*42*delta;
  if(move.left||move.right)velocity.x-=direction.x*42*delta;
  var nx=camera.position.x-velocity.x*delta,nz=camera.position.z-velocity.z*delta;
  if(nx>-16&&nx<16&&nz>-10&&nz<10){
    controls.moveForward(-velocity.z*delta);
    controls.moveRight(-velocity.x*delta);
  }
}
for(var i=0;i<interactive.length;i++){
  var obj=interactive[i];
  if(obj.userData.glow){
    obj.rotation.y+=delta*.12;
    var p=obj.children[2];
    if(p)p.position.y=1.4+Math.sin(performance.now()*.0015+obj.position.x)*.035;
  }
}
renderer.render(scene,camera);}
init();
