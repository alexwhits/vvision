// heatmap.js — tiny client
(function(){
  const ME = document.currentScript;
  const API = ME?.dataset?.api || "https://vvision.onrender.com/api/attention/heatmap";

  const grid = document.getElementById('vv-grid');
  const asof = document.getElementById('vv-asof');
  const msg  = document.getElementById('vv-msg');
  if (!grid) { console.warn('vv-heatmap: grid not found'); return; }
  console.log('vv-heatmap boot');

  const clamp = (n,a=0,b=1)=>Math.max(a,Math.min(b,n));
  const hhmm  = t => new Date(t*1000).toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'});

  function colorFor(item){
    const delta = (typeof item.d1==='number') ? item.d1
               : (typeof item.delta==='number' ? item.delta : 0.1);
    const root  = getComputedStyle(document.documentElement);
    const rgb   = (delta < 0) ? root.getPropertyValue('--red') : root.getPropertyValue('--green');
    const alpha = clamp(0.2 + 0.8 * (item.score ?? 0.5));
    return `rgba(${rgb.trim()}, ${alpha.toFixed(2)})`;
  }
 function bucketSize(score){
  // score is 0..1 — map to 1, 2, 3 with a bias toward small
  if (score >= 0.80) return 3;
  if (score >= 0.45) return 2;
  return 1;
  }

 function cell(item){
  const d = document.createElement('div');
  d.className = 'cell';
  d.style.background = colorFor(item);
  d.classList.add(`size-${bucketSize(item.score ?? 0)}`);
  d.title = item.title || item.name || '';
  return d;

  }

  async function load(){
    try{
      let items = [];
      const r = await fetch(API, {cache:'no-store', mode:'cors'});
      if (r.ok){
        const j = await r.json();
        if (Array.isArray(j.items)) items = j.items;
        if (j.last_updated && asof) asof.textContent = 'as of ' + hhmm(j.last_updated);
      }
      if (!items.length){
        items = Array.from({length:64}, (_,i)=>({score:Math.random(), d1:(Math.random()-.5)}));
        if (msg) msg.textContent = 'showing placeholders (no live data yet).';
      } else if (msg) {
        msg.textContent = '';
      }
      const cols = parseInt(getComputedStyle(document.documentElement).getPropertyValue('--cols')) || 8;
      grid.replaceChildren(...items.slice(0, cols*cols).map(cell));
    } catch(e){
      if (msg) msg.textContent = 'unable to load heatmap (' + (e.message || e) + ')';
    }
  }

  load();
  setInterval(load, 60000);
})();

