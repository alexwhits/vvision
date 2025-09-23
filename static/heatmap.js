// static/heatmap.js
(function(){
  const ME  = document.currentScript;
  const API = ME?.dataset?.api || "https://vvision.onrender.com/api/attention/heatmap";

  const grid = document.getElementById('vv-grid');
  const asof = document.getElementById('vv-asof');
  const msg  = document.getElementById('vv-msg');
  const tip  = document.getElementById('vv-tooltip');

  if (!grid) { console.warn('vv-heatmap: grid not found'); return; }
  console.log('vv-heatmap boot');

  // ----- helpers
  const clamp = (n,a=0,b=1)=>Math.max(a,Math.min(b,n));
  const hhmm  = t => new Date(t*1000).toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'});

  function colorFor(item){
    const delta = (typeof item.d1==='number') ? item.d1
               : (typeof item.delta==='number' ? item.delta : 0.1);
    const root  = getComputedStyle(document.documentElement);
    const rgb   = (delta < 0) ? root.getPropertyValue('--red') : root.getPropertyValue('--green');
    const alpha = clamp(0.18 + 0.82 * (item.score ?? 0.5));
    return `rgba(${rgb.trim()}, ${alpha.toFixed(2)})`;
  }
  function bucketSize(score){
    if (score >= 0.80) return 3;
    if (score >= 0.45) return 2;
    return 1;
  }

  function cell(item){
    const d = document.createElement(item.url ? 'a' : 'div');
    d.className = 'cell';
    d.style.background = colorFor(item);
    d.classList.add(`size-${bucketSize(item.score ?? 0)}`);
    if (item.url){ d.href = item.url; d.target = '_blank'; d.rel = 'noopener'; }

    // label on big tiles
    const lbl = document.createElement('span');
    lbl.className = 'label';
    lbl.textContent = (item.title || item.name || '').toString();
    d.appendChild(lbl);

    // tooltip payload
    d.dataset.tt = JSON.stringify({
      title: item.title || item.name || '',
      src: item.source || '',
      s: Number(item.score ?? 0).toFixed(2),
      d: typeof item.d1 === 'number' ? item.d1.toFixed(2)
         : (typeof item.delta === 'number' ? item.delta.toFixed(2) : '0.00')
    });

    return d;
  }

  function showTip(e){
    if (!tip) return;
    try{
      const data = JSON.parse(e.currentTarget.dataset.tt || '{}');
      tip.innerHTML = `<div>${data.title}</div>
        <div style="color:#aaa">${data.src} · score ${data.s} · Δ ${data.d}</div>`;
      tip.style.opacity = '1';
      moveTip(e);
    }catch(_){}
  }
  function hideTip(){ if (tip) tip.style.opacity = '0'; }
  function moveTip(e){
    if (!tip) return;
    const pad = 12;
    tip.style.left = (e.clientX + pad) + 'px';
    tip.style.top  = (e.clientY + pad) + 'px';
  }

  async function load(){
    try{
      // cache-bust to force fresh data
      const r = await fetch(`${API}?min=2&t=${Date.now()}`, { cache:'no-store', mode:'cors' });
      let items = [];
      if (r.ok){
        const j = await r.json();
        if (Array.isArray(j.items)) items = j.items;
        if (j.last_updated && asof) asof.textContent = 'as of ' + hhmm(j.last_updated);
      }

      // fill to capacity (dense mosaic)
      const unit = parseInt(getComputedStyle(grid).getPropertyValue('--unit')) || 44;
      const colsGuess = Math.max(6, Math.floor(grid.clientWidth / unit));
      const maxCells  = colsGuess * colsGuess;
      if (items.length < maxCells){
        const extra = Array.from({length:maxCells - items.length}, ()=>({
          score: Math.random(), d1: (Math.random() - .5)
        }));
        items = items.concat(extra);
      }

      grid.replaceChildren(...items.slice(0, maxCells).map(cell));

      // wire tooltips
      grid.querySelectorAll('.cell').forEach(el => {
        el.addEventListener('mouseenter', showTip);
        el.addEventListener('mouseleave', hideTip);
        el.addEventListener('mousemove', moveTip);
      });

      if (msg) msg.textContent = '';
    }catch(e){
      if (msg) msg.textContent = 'unable to load heatmap (' + (e.message || e) + ')';
    }
  }

  load();
  setInterval(load, 60000); // refresh every 60s
})();
