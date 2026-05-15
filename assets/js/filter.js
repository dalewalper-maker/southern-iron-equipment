(function(){
  var q=document.getElementById('q'),cat=document.getElementById('cat'),mk=document.getElementById('mk'),
      cards=[].slice.call(document.querySelectorAll('[data-unit]')),
      cnt=document.getElementById('cnt'),nr=document.getElementById('nr');
  function apply(){
    var t=(q.value||'').toLowerCase(),c=cat.value,m=mk.value,n=0;
    cards.forEach(function(el){
      var ok=(!c||el.dataset.cat===c)&&(!m||el.dataset.make===m)&&(!t||el.dataset.search.indexOf(t)>-1);
      el.style.display=ok?'':'none';if(ok)n++;
    });
    cnt.textContent=n;nr.style.display=n?'none':'block';
  }
  [q,cat,mk].forEach(function(e){e&&e.addEventListener('input',apply)});
})();
