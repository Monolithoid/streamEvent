'use strict';
const $ = id => document.getElementById(id);
const csrf = document.querySelector('meta[name="csrf-token"]').content;
let model, previewUrl, timer, controller, generation = 0, dirty = false;
async function api(path, body, signal) {
  const response = await fetch(path, {method: body === undefined ? 'GET' : 'POST', signal,
    headers: {'Content-Type': 'application/json', 'X-CSRF-Token': csrf}, body: body === undefined ? undefined : JSON.stringify(body)});
  if (response.status === 401) {location.assign('/login'); throw new Error('Connexion expirée.');}
  if (!response.ok) {const error = await response.json().catch(() => ({})); throw new Error(error.error || 'La requête a échoué.');}
  return response;
}
function message(text) {$('message').textContent = text;}
function changed() {
  dirty = true;
  message('Modifications en attente de validation.');
  $('publish').disabled = false;
  clearTimeout(timer);
  controller?.abort();
  const current = ++generation;
  timer = setTimeout(async () => {
    controller = new AbortController();
    try {
      const response = await api('/api/preview', model, controller.signal);
      const blob = await response.blob();
      if (current !== generation) return;
      if (previewUrl) URL.revokeObjectURL(previewUrl);
      previewUrl = URL.createObjectURL(blob); $('preview').src = previewUrl;
    } catch (e) {if (e.name !== 'AbortError' && current === generation) message(e.message);}
  }, 350);
}
function field(zone, key, title, type = 'text') {
  const label = document.createElement('label'); label.textContent = title;
  const input = document.createElement(key === 'text' ? 'textarea' : 'input');
  if (input.tagName === 'INPUT') input.type = type;
  input.value = zone[key];
  if (type === 'number') {input.min = key === 'size' ? 8 : ['width','height'].includes(key) ? 1 : 0; input.max = key === 'size' ? 160 : ['x','width'].includes(key) ? model.width : model.height;}
  if (key === 'text') input.maxLength = 500;
  if (key === 'label') input.maxLength = 60;
  input.addEventListener('input', () => {zone[key] = type === 'number' ? Number(input.value) : input.value; changed();});
  label.append(input); return label;
}
function drawEditor() {
  $('zones').replaceChildren(); $('empty').hidden = model.zones.length !== 0;
  $('add').disabled = model.zones.length >= 24;
  model.zones.forEach((zone, index) => {
    const block = document.createElement('article'); block.className = 'zone';
    const head = document.createElement('div'); head.className = 'zonehead'; head.append(field(zone, 'label', 'Nom de la zone'));
    const remove = document.createElement('button'); remove.textContent = 'Supprimer'; remove.className = 'danger';
    remove.onclick = () => {model.zones.splice(index,1); drawEditor(); changed();}; head.append(remove); block.append(head, field(zone,'text','Texte affiché'));
    const grid = document.createElement('div'); grid.className = 'grid';
    for (const [key,label] of [['x','Position X'],['y','Position Y'],['size','Taille du texte'],['width','Largeur'],['height','Hauteur']]) grid.append(field(zone,key,label,'number'));
    block.append(grid,field(zone,'color','Texte · #RRGGBBAA'),field(zone,'background','Fond · #RRGGBBAA (00 = transparent)'));
    $('zones').append(block);
  });
}
function newZone(label, text, x, y, width, height, size) {
  return {label,text,x,y,width: Math.min(width,model.width-x),height: Math.min(height,model.height-y),size,color:'#FFFFFFFF',background:'#10151BE6'};
}
$('add').onclick = () => {model.zones.push(newZone('Nouvelle zone','Votre texte',0,0,500,100,36));drawEditor();changed();};
$('preset').onclick = () => {
  const w = model.width, h = model.height, scale = Math.min(w/1920,h/1080);
  const z = (label,text,x,y,width,height,size) => newZone(label,text,Math.floor(x*scale),Math.floor(y*scale),Math.max(1,Math.floor(width*scale)),Math.max(1,Math.floor(height*scale)),Math.max(8,Math.floor(size*scale)));
  model.zones.push(z('Équipe domicile','DOMICILE   0',50,40,600,90,42),z('Équipe visiteuse','0   VISITEURS',650,40,600,90,42),z('Événement','Nom de l’événement · Quart-temps 1',50,140,1200,65,28));
  drawEditor();changed();
};
$('publish').onclick = async () => {
  $('publish').disabled = true;
  // Freeze this version while the request is in flight; preserve later edits.
  const version = generation;
  try {
    const state = await (await api('/api/overlay', model)).json();
    model.revision = state.revision;
    $('lastUpdate').textContent = 'Dernière validation : ' + new Date(state.updated_at*1000).toLocaleTimeString('fr-FR');
    if (version === generation) {dirty = false;message('Overlay validé. Prise en compte par le relais en quelques secondes.');}
    else message('Version validée. De nouvelles modifications restent à diffuser.');
  } catch(e) {message(e.message);} finally {$('publish').disabled = !dirty;}
};
$('logout').onclick = async () => {try {await api('/logout',{});location.assign('/login');} catch(e) {message(e.message);}};
async function status() {
  try {
    const s = await (await api('/api/status')).json();
    $('connection').textContent = s.stale ? 'Statut indisponible' : '● Relais connecté';
    $('state').textContent = s.stale ? 'Inconnue' : s.state === 'live' ? 'Caméra en direct' : 'Image d’attente';
    $('output').textContent = s.stale ? 'Inconnue' : s.output_healthy ? 'Encodage actif' : 'Reconnexion…';
    $('format').textContent = s.stale ? '—' : `${s.width} × ${s.height} · ${s.fps} ips`;
    $('bitrate').textContent = s.stale ? '—' : s.video_bitrate;
  } catch(e) {$('connection').textContent = 'Statut indisponible'; for (const id of ['state','output','format','bitrate']) $(id).textContent = '—';}
}
(async () => {
  try {model = await (await api('/api/overlay')).json(); $('dimensions').textContent = `${model.width} × ${model.height} · ALPHA`; $('preview').src = '/api/overlay.png';drawEditor();$('publish').disabled = true;message('Version diffusée · ajoutez ou modifiez une zone pour préparer la suite.');if(model.updated_at) $('lastUpdate').textContent = 'Dernière validation : ' + new Date(model.updated_at*1000).toLocaleTimeString('fr-FR');}
  catch(e) {message(e.message);$('add').disabled = true;$('preset').disabled = true;$('publish').disabled = true;}
  await status();setInterval(status,3000);
})();
window.addEventListener('beforeunload', e => {if(dirty) {e.preventDefault();e.returnValue = '';}});
