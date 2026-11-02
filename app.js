const $=id=>document.getElementById(id);const synth=window.speechSynthesis;let db,books=[],active=null,parts=[],idx=0,playing=false,token=0;const clean=s=>(s||'').replace(/\s+/g,' ').trim();const updateStatus=s=>$('status').textContent=s;
const request=indexedDB.open('my-narrator-v1',1);request.onupgradeneeded=e=>{e.target.result.createObjectStore('books',{keyPath:'id'})};request.onsuccess=async e=>{db=e.target.result;await refresh();let last=localStorage.getItem('lastBook');if(last)openBook(last)};request.onerror=()=>updateStatus('Browser storage is unavailable.');
function store(mode='readonly'){return db.transaction('books',mode).objectStore('books')};function getAll(){return new Promise((resolve,reject)=>{let r=store().getAll();r.onsuccess=()=>resolve(r.result);r.onerror=()=>reject(r.error)})};function save(b){return new Promise((resolve,reject)=>{let r=store('readwrite').put(b);r.onsuccess=resolve;r.onerror=()=>reject(r.error)})};function remove(id){return new Promise((resolve,reject)=>{let r=store('readwrite').delete(id);r.onsuccess=resolve;r.onerror=()=>reject(r.error)})};async function refresh(){books=await getAll();$('library').replaceChildren();for(let b of books){let row=document.createElement('div');row.className='book';let name=document.createElement('span');name.textContent=b.name+' · '+Math.round((b.position||0)/Math.max(1,(b.parts||[]).length)*100)+'%';let actions=document.createElement('div');let open=document.createElement('button');open.textContent='Open';open.onclick=()=>openBook(b.id);let del=document.createElement('button');del.textContent='×';del.className='secondary';del.setAttribute('aria-label','Delete '+b.name);del.onclick=async()=>{if(confirm('Delete this book from this device?')){if(active?.id===b.id){stop();active=null;$('reading').textContent='';$('title').textContent='Choose a book'}await remove(b.id);refresh()}};actions.append(open,del);row.append(name,actions);$('library').append(row)}}
function splitText(text){let sentences=text.match(/[^.!?\n]+(?:[.!?]+|\n|$)/g)||[text];let chunks=[],buf='';for(let sentence of sentences){sentence=clean(sentence);if(!sentence)continue;if(sentence.length>450){if(buf){chunks.push(buf);buf=''}for(let i=0;i<sentence.length;i+=400)chunks.push(sentence.slice(i,i+400));continue}if((buf+' '+sentence).length>400){chunks.push(buf);buf=''}buf+=(buf?' ':'')+sentence}if(buf)chunks.push(buf);return chunks}
async function parsePDF(file){
  if(!window.pdfjsLib)throw Error('PDF library unavailable. Connect to the internet and retry.');
  pdfjsLib.GlobalWorkerOptions.workerSrc='https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js';
  const pdf=await pdfjsLib.getDocument({data:await file.arrayBuffer()}).promise;
  const pages=[];
  for(let n=1;n<=pdf.numPages;n++){
    const page=await pdf.getPage(n),content=await page.getTextContent();
    pages.push(content.items.map(x=>x.str).join(' '));
    updateStatus('Extracting PDF page '+n+' of '+pdf.numPages);
  }
  const outline=await pdf.getOutline();
  const bookmarks=[];
  async function walk(items,depth=1){
    for(const item of items||[]){
      if(item.dest){
        try{
          const dest=typeof item.dest==='string'?await pdf.getDestination(item.dest):item.dest;
          const index=await pdf.getPageIndex(dest[0]);
          bookmarks.push({title:item.title,depth,start:index});
        }catch(e){}
      }
      await walk(item.items,depth+1);
    }
  }
  await walk(outline);
  const sections=[];
  if(bookmarks.length>=2){
    const deepest=Math.max(...bookmarks.map(b=>b.depth));
    const sorted=bookmarks.filter(b=>b.depth===deepest).sort((a,b)=>a.start-b.start);
    const starts=sorted.filter((b,i)=>i===0||b.start!==sorted[i-1].start);
    if(starts.length>=2){
      if(starts[0].start>0)sections.push({title:'Front Matter',text:pages.slice(0,starts[0].start).join('\n\n')});
      for(let i=0;i<starts.length;i++){
        const end=i+1<starts.length?starts[i+1].start:pages.length;
        const text=pages.slice(starts[i].start,end).join('\n\n');
        if(clean(text))sections.push({title:starts[i].title||'Section '+(i+1),text});
      }
    }
  }
  if(!sections.length){
    for(let i=0;i<pages.length;i+=10){
      const text=pages.slice(i,i+10).join('\n\n');
      if(clean(text))sections.push({title:'Pages '+(i+1)+'–'+Math.min(i+10,pages.length),text});
    }
  }
  return sections;
}
async function parseEPUB(file){
  if(!window.JSZip)throw Error('EPUB library unavailable. Connect to the internet and retry.');
  const zip=await JSZip.loadAsync(file),container=zip.file('META-INF/container.xml');
  if(!container)throw Error('Invalid EPUB: container missing');
  const xml=new DOMParser().parseFromString(await container.async('text'),'application/xml');
  const root=xml.getElementsByTagName('rootfile')[0]?.getAttribute('full-path');
  if(!root)throw Error('EPUB package missing');
  const opf=new DOMParser().parseFromString(await zip.file(root).async('text'),'application/xml');
  const items={};
  for(const el of opf.getElementsByTagName('item'))items[el.getAttribute('id')]=el.getAttribute('href');
  const base=root.includes('/')?root.slice(0,root.lastIndexOf('/')+1):'';
  const result=[];
  for(const ref of opf.getElementsByTagName('itemref')){
    const href=items[ref.getAttribute('idref')];if(!href)continue;
    const path=resolvePath(base,decodeURIComponent(href.split('#')[0]));
    const entry=zip.file(path);if(!entry)continue;
    const doc=new DOMParser().parseFromString(await entry.async('text'),'text/html');
    doc.querySelectorAll('script,style,nav').forEach(el=>el.remove());
    const chapters=Array.from(doc.querySelectorAll('div.chapter'));
    if(chapters.length){
      for(const chapter of chapters){
        const heading=chapter.querySelector('p.cn,h1,h2,h3');
        const title=clean(heading?.textContent)||'Chapter '+(result.length+1);
        const text=chapter.textContent||'';
        if(clean(text))result.push({title,text});
      }
    }else{
      const text=doc.body?.textContent||'';
      const title=clean(doc.querySelector('h1,h2,title')?.textContent)||'Section '+(result.length+1);
      if(clean(text))result.push({title,text});
    }
  }
  return result;
}
function bibleBookFromHeading(label){
  const normalized=clean(label).replace(/[–—:]/g,' ').replace(/^(?:the\\s+)?book\\s+of\\s+/i,'').trim();
  const aliases={'Psalm':'Psalms','Song of Solomon':'Song of Songs','Canticles':'Song of Songs'};
  for(const [alias,book] of Object.entries(aliases)){
    if(new RegExp('^'+alias+'(?:\\s|$)','i').test(normalized))return book;
  }
  const names=bibleBooks.slice().sort((a,b)=>b.length-a.length);
  return names.find(name=>normalized.toLowerCase()===name.toLowerCase()||normalized.toLowerCase().startsWith(name.toLowerCase()+' '))||null;
}
function annotateBibleSections(sections){
  // Use only explicit book headings, or numbered chapters following an
  // explicit book heading. Never infer a book merely from its sequence.
  let current=null,chapterNumber=0;
  for(const section of sections){
    const label=clean(section.title),text=clean(section.text||'');
    const firstLine=(section.text||'').split(/\\n/).map(clean).find(Boolean)||'';
    const source=bibleBookFromHeading(label);
    const direct=label.match(/^(?:Psalm\\s+\\d+|(?:[1-3]\\s+)?[A-Za-z]+(?:\\s+of\\s+[A-Za-z]+)?\\s+\\d+)\\b/i);
    if(source){
      current=source;
      const number=label.match(/\\b(?:chapter\\s+)?(\\d+)\\b/i);
      if(number){chapterNumber=Number(number[1]);section.bible={book:source,chapter:chapterNumber};}
      else {chapterNumber=0;section.bible={book:source,chapter:null};}
      continue;
    }
    const explicit=label.match(/^(?:chapter|chap\\.?|psalm)\\s*(\\d+)\\b/i);
    if(explicit&&current){
      chapterNumber=Number(explicit[1]);
      section.bible={book:current,chapter:chapterNumber};
      continue;
    }
    // Chapter number only is meaningful when the EPUB has established context.
    if(/^\\d{1,3}$/.test(label)&&current){
      chapterNumber=Number(label);section.bible={book:current,chapter:chapterNumber};continue;
    }
    // Editorial material does not inherit the preceding Bible book.
    if(!direct && /^(?:introduction|preface|foreword|copyright|contents|leadership|article|notes|study|index|appendix|about|acknowledg)/i.test(label)){
      current=null;
    }
  }
  return sections;
}
function resolvePath(base,path){let segments=(base+path).split('/'),out=[];for(let p of segments){if(p==='..')out.pop();else if(p&&p!=='.')out.push(p)}return out.join('/')}
$('file').onchange=async e=>{let file=e.target.files[0];if(!file||!db)return;try{updateStatus('Importing '+file.name+'…');let sections=file.name.toLowerCase().endsWith('.pdf')?await parsePDF(file):await parseEPUB(file),chunks=sections.flatMap(x=>splitText(x.text));if(!chunks.length)throw Error('No readable text found. Scanned PDFs need OCR.');let b={id:crypto.randomUUID(),name:file.name,parts:chunks,sections:annotateBibleSections(sections).map(x=>({title:x.title,parts:splitText(x.text),bible:x.bible||null})),position:0};await save(b);await refresh();openBook(b.id);updateStatus('Imported '+chunks.length+' narration segments.')}catch(err){updateStatus('Import failed: '+err.message)}e.target.value=''};
const bibleBooks="Genesis|Exodus|Leviticus|Numbers|Deuteronomy|Joshua|Judges|Ruth|1 Samuel|2 Samuel|1 Kings|2 Kings|1 Chronicles|2 Chronicles|Ezra|Nehemiah|Esther|Job|Psalms|Proverbs|Ecclesiastes|Song of Songs|Isaiah|Jeremiah|Lamentations|Ezekiel|Daniel|Hosea|Joel|Amos|Obadiah|Jonah|Micah|Nahum|Habakkuk|Zephaniah|Haggai|Zechariah|Malachi|Matthew|Mark|Luke|John|Acts|Romans|1 Corinthians|2 Corinthians|Galatians|Ephesians|Philippians|Colossians|1 Thessalonians|2 Thessalonians|1 Timothy|2 Timothy|Titus|Philemon|Hebrews|James|1 Peter|2 Peter|1 John|2 John|3 John|Jude|Revelation".split('|');
function bibleLocation(title,metadata){
  if(metadata?.book&&bibleBooks.includes(metadata.book))return {testament:bibleBooks.indexOf(metadata.book)<39?'Old Testament':'New Testament',book:metadata.book,chapter:metadata.chapter||null};
  const label=(title||'').trim();
  const ps=label.match(/^Psalm\\s+(\\d+)\\b/i);
  if(ps)return {testament:'Old Testament',book:'Psalms',chapter:ps[1]};
  for(let i=0;i<bibleBooks.length;i++){
    const book=bibleBooks[i];
    const escaped=book.replace(/[.*+?^$\u007b\u007d()|[\]\\]/g,'\\$&');
    const match=label.match(new RegExp('^'+escaped+'\\s+(\\d+)\\b','i'));
    if(match)return {testament:i<39?'Old Testament':'New Testament',book,chapter:match[1]};
  }
  return {testament:'Additional Material',book:'Other Sections',chapter:null};
}
function chapterGroup(title,metadata){const p=bibleLocation(title,metadata);return p.testament+' / '+p.book;}
function populateSections(){
  const sections=active?.sections||[];
  for(const [testamentId,groupId,sectionId] of [
    ['testament','bookGroup','section'],
    ['exportTestament','exportGroup','exportSection']
  ]){
    const testament=$(testamentId),group=$(groupId),select=$(sectionId);
    const locations=sections.map(x=>bibleLocation(x.title,x.bible));
    testament.replaceChildren();
    for(const value of ['all','Old Testament','New Testament','Additional Material']){
      if(value!=='all'&&!locations.some(x=>x.testament===value))continue;
      const opt=document.createElement('option');opt.value=value;
      opt.textContent=value==='all'?'All sections':value;testament.append(opt);
    }
    const updateChapters=()=>{
      const selected=group.value;select.replaceChildren();
      const all=document.createElement('option');all.value='all';
      all.textContent=selected==='all'?'All chapters':'All chapters in selected book';select.append(all);
      for(let i=0;i<sections.length;i++){
        const p=locations[i];
        if(testament.value!=='all'&&p.testament!==testament.value)continue;
        if(selected!=='all'&&chapterGroup(sections[i].title,sections[i].bible)!==selected)continue;
        const o=document.createElement('option');o.value=String(i);
        o.textContent=p.chapter?'Chapter '+p.chapter:sections[i].title;
        select.append(o);
      }
      if(sectionId==='section')chooseReadingSection();
    };
    const updateBooks=()=>{
      group.replaceChildren();
      const all=document.createElement('option');all.value='all';all.textContent='All books';group.append(all);
      const names=[...new Set(locations.filter(x=>testament.value==='all'||x.testament===testament.value).map(x=>x.testament+' / '+x.book))];
      for(const name of names){const o=document.createElement('option');o.value=name;o.textContent=name.split(' / ').slice(1).join(' / ');group.append(o);}
      updateChapters();
    };
    testament.onchange=updateBooks;group.onchange=updateChapters;updateBooks();
  }
}
function selectedSections(testamentId,groupId,sectionId){
  if(!active)return [];
  const selected=$(sectionId).value,group=$(groupId).value,testament=$(testamentId).value;
  if(selected!=='all')return [active.sections[Number(selected)]];
  return active.sections.filter(x=>(testament==='all'||bibleLocation(x.title,x.bible).testament===testament)&&(group==='all'||chapterGroup(x.title,x.bible)===group));
}
function chooseReadingSection(){
  if(!active)return;
  stop();
  const n=$('section').value,group=$('bookGroup').value;
  if(n!=='all')parts=active.sections[Number(n)].parts;
  else parts=selectedSections('testament','bookGroup','section').flatMap(x=>x.parts);
  idx=0;show();
}
function openBook(id){let b=books.find(x=>x.id===id);if(!b)return;stop();active=b;parts=b.parts;populateSections();idx=Math.min(b.position||0,parts.length-1);localStorage.setItem('lastBook',id);$('title').textContent=b.name;show()};$('section').onchange=chooseReadingSection;
function show(){if(!active)return;$('reading').textContent=parts.slice(Math.max(0,idx-1),Math.min(parts.length,idx+4)).join('\n\n');updateStatus('Segment '+(idx+1)+' of '+parts.length)};async function persist(){if(!active)return;active.position=idx;await save(active)};function stop(){token++;playing=false;synth?.cancel()};function narrationText(text){
  if(!$('skipVerseNumbers')?.checked)return text;
  // Only strip verse labels 1–176 followed by a word, at the start of
  // a segment or after sentence punctuation. Preserve dates and quantities.
  return text.replace(/(^|[.!?]\\s+)(?:1[0-6]\\d|17[0-6]|[1-9]\\d?)\\s+(?=[A-Za-z“"‘'])/g,'$1');
}
function speak(){if(!active||!synth)return;stop();playing=true;const current=token;function next(){if(!playing||current!==token)return;if(idx>=parts.length){playing=false;updateStatus('Finished!');return}show();persist();let u=new SpeechSynthesisUtterance(narrationText(parts[idx]));u.rate=Number($('speed').value);let v=synth.getVoices().find(v=>v.voiceURI===$('voice').value);if(v)u.voice=v;u.onend=()=>{if(current!==token||!playing)return;idx++;next()};u.onerror=e=>{if(current!==token)return;playing=false;updateStatus('Speech stopped: '+e.error)};synth.speak(u)}next()};$('play').onclick=()=>{if(!active)return;if(synth?.paused&&playing){synth.resume();return}speak()};$('pause').onclick=()=>{if(synth?.speaking&&!synth.paused){synth.pause();updateStatus('Paused')}else if(synth?.paused){synth.resume();show()}};$('prev').onclick=()=>{if(!active)return;idx=Math.max(0,idx-1);persist();speak()};$('next').onclick=()=>{if(!active)return;idx=Math.min(parts.length-1,idx+1);persist();speak()};$('speed').oninput=()=>{$('speedLabel').textContent=Number($('speed').value).toFixed(1)+'×'};function voices(){let old=$('voice').value;$('voice').replaceChildren();for(let v of synth?.getVoices()||[]){let opt=document.createElement('option');opt.value=v.voiceURI;opt.textContent=v.name+' ('+v.lang+')';$('voice').append(opt)}if(old)$('voice').value=old};if(synth){voices();synth.onvoiceschanged=voices}document.addEventListener('visibilitychange',()=>{if(document.hidden&&active)persist()});if('serviceWorker'in navigator)navigator.serviceWorker.register('sw.js').catch(()=>{});


// Local audiobook export: no network transfer of book content.
$('exportBook').onclick=()=>{
  if(!active){updateStatus('Open a book before exporting.');return;}
  const safe=active.name.replace(/\.[^.]+$/,'').replace(/[^a-z0-9_-]+/gi,'-').slice(0,90)||'book';
  const voice=$('exportVoice').value;
  const choice=$('exportSection').value;const selected=selectedSections('exportTestament','exportGroup','exportSection').flatMap(x=>x.parts);
  const body='MY_NARRATOR_EXPORT\n'+JSON.stringify({title:active.name,voice,section:choice})+'\n'+selected.join('\n\n');
  const url=URL.createObjectURL(new Blob([body],{type:'text/plain;charset=utf-8'}));
  const link=document.createElement('a');link.href=url;link.download=safe+'.txt';document.body.append(link);link.click();link.remove();
  setTimeout(()=>URL.revokeObjectURL(url),1000);
  updateStatus('Book text downloaded. Run convert_book.py on your Mac with --voice '+voice+'.');
};
