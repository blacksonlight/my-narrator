'use strict';
const $ = id => document.getElementById(id);
const audio = $('player');
let db, library=[], active=null, objectUrl=null, lastSaved=0;
const fmt = n => {if(!Number.isFinite(n))return '0:00';n=Math.floor(n);return Math.floor(n/3600)?Math.floor(n/3600)+':'+String(Math.floor(n%3600/60)).padStart(2,'0')+':'+String(n%60).padStart(2,'0'):Math.floor(n/60)+':'+String(n%60).padStart(2,'0')};
const notice = s => $('notice').textContent=s;
const request=indexedDB.open('my-narrator-audio-v1',1);
request.onupgradeneeded=e=>e.target.result.createObjectStore('audio',{keyPath:'id'});
request.onerror=()=>notice('Device storage unavailable. Try Safari outside Private Browsing.');
request.onsuccess=async e=>{db=e.target.result;await refresh();const last=localStorage.getItem('my-narrator-last-audio');if(last&&library.some(x=>x.id===last))await openTrack(last,false)};
function operation(mode, fn){return new Promise((resolve,reject)=>{const tx=db.transaction('audio',mode);const req=fn(tx.objectStore('audio'));req.onsuccess=()=>resolve(req.result);req.onerror=()=>reject(req.error);tx.onerror=()=>reject(tx.error)})}
const all=()=>operation('readonly',s=>s.getAll());
const put=b=>operation('readwrite',s=>s.put(b));
const del=id=>operation('readwrite',s=>s.delete(id));
async function refresh(){
  library=await all();library.sort((a,b)=>b.added-a.added);$('library').replaceChildren();
  if(!library.length){const p=document.createElement('p');p.className='muted';p.textContent='No audiobooks yet. Import one above.';$('library').append(p)}
  for(const item of library){
    const row=document.createElement('div');row.className='track';
    const name=document.createElement('div');name.className='track-name';name.textContent=item.name;
    const actions=document.createElement('div');actions.className='row';
    const open=document.createElement('button');open.className='secondary';open.textContent='Listen';open.onclick=()=>openTrack(item.id,true);
    const remove=document.createElement('button');remove.className='secondary';remove.textContent='×';remove.setAttribute('aria-label','Delete '+item.name);
    remove.onclick=async()=>{if(!confirm('Delete this audiobook from this device?'))return;if(active?.id===item.id){audio.pause();audio.removeAttribute('src');audio.load();if(objectUrl)URL.revokeObjectURL(objectUrl);objectUrl=null;active=null;$('now').textContent='Choose an audiobook'}await del(item.id);await refresh()};
    actions.append(open,remove);row.append(name,actions);$('library').append(row);
  }
  if(navigator.storage?.estimate){const e=await navigator.storage.estimate();$('storage').textContent='Device app storage: '+(e.usage/1048576).toFixed(0)+' MB used (estimate).'}
}
$('audioFiles').onchange=async e=>{
  if(!db)return;
  const files=[...e.target.files];if(!files.length)return;
  let count=0;
  for(const file of files){
    if(!/\.(mp3|m4b)$/i.test(file.name)){notice('Skipped unsupported file: '+file.name);continue}
    try{
      notice('Saving '+file.name+' locally…');
      await put({id:crypto.randomUUID(),name:file.name,blob:file,position:0,added:Date.now()+count});
      count++;
    }catch(err){notice('Import failed (possibly storage full): '+err.message);break}
  }
  e.target.value='';await refresh();if(count)notice('Saved '+count+' audiobook file(s) for offline listening.');
};
async function openTrack(id,autoplay){
  const item=library.find(x=>x.id===id);if(!item)return;
  saveProgress();audio.pause();
  if(objectUrl)URL.revokeObjectURL(objectUrl);
  active=item;objectUrl=URL.createObjectURL(item.blob);
  audio.src=objectUrl;audio.load();$('now').textContent=item.name;
  localStorage.setItem('my-narrator-last-audio',id);
  notice('Ready to listen. Playback position is saved automatically.');
  audio.onloadedmetadata=()=>{
    if(Number.isFinite(audio.duration)&&item.position>0)audio.currentTime=Math.min(item.position,Math.max(0,audio.duration-1));
    updateTime();
    if(autoplay)audio.play().catch(()=>notice('Tap Play to begin listening.'));
  };
}
function saveProgress(){if(!active||!db)return;active.position=audio.currentTime||0;put(active).catch(()=>{})}
function updateTime(){
  $('elapsed').textContent=fmt(audio.currentTime);$('duration').textContent=fmt(audio.duration);
  $('seek').value=Number.isFinite(audio.duration)&&audio.duration>0?Math.round(audio.currentTime/audio.duration*1000):0;
}
audio.ontimeupdate=()=>{updateTime();if(Date.now()-lastSaved>5000){lastSaved=Date.now();saveProgress()}};
audio.onpause=()=>{saveProgress();$('toggle').textContent='▶ Play'};
audio.onplay=()=>{$('toggle').textContent='Ⅱ Pause';updateMediaSession()};
audio.onended=()=>{if(active){active.position=0;put(active).catch(()=>{})}notice('Finished listening.')};
audio.onerror=()=>notice('This audio format may not be supported by this browser.');
$('toggle').onclick=()=>{if(!active)return notice('Import and choose an audiobook first.');if(audio.paused)audio.play().catch(()=>notice('Unable to play this file.'));else audio.pause()};
$('back').onclick=()=>{if(active)audio.currentTime=Math.max(0,audio.currentTime-15)};
$('forward').onclick=()=>{if(active&&Number.isFinite(audio.duration))audio.currentTime=Math.min(audio.duration,audio.currentTime+30)};
$('seek').oninput=e=>{if(active&&Number.isFinite(audio.duration))audio.currentTime=Number(e.target.value)/1000*audio.duration};
$('speed').onchange=e=>audio.playbackRate=Number(e.target.value);
document.addEventListener('visibilitychange',()=>{if(document.hidden)saveProgress()});
window.addEventListener('pagehide',saveProgress);
function updateMediaSession(){
  if(!('mediaSession' in navigator)||!active)return;
  navigator.mediaSession.metadata=new MediaMetadata({title:active.name,artist:'My Narrator',album:'My Audiobooks'});
  try{
    navigator.mediaSession.setActionHandler('play',()=>audio.play());
    navigator.mediaSession.setActionHandler('pause',()=>audio.pause());
    navigator.mediaSession.setActionHandler('seekbackward',()=>{audio.currentTime=Math.max(0,audio.currentTime-15)});
    navigator.mediaSession.setActionHandler('seekforward',()=>{audio.currentTime=Math.min(audio.duration||Infinity,audio.currentTime+30)});
    navigator.mediaSession.setActionHandler('seekto',details=>{if(Number.isFinite(details.seekTime))audio.currentTime=details.seekTime});
  }catch(e){}
}
if('serviceWorker'in navigator)navigator.serviceWorker.register('sw.js').catch(()=>{});
